"""Step 3: Train 256x256 Dual-Reference GAN Student (XiaolinStudent256UNet + PatchGAN)
on Sonic DiT Teacher Dataset + Render 50fps 16s Multi-Action 3-Way Closed-Loop Preview.

Outputs in F:/xiaolin/dit-distill-v2/outputs/:
  1. preview_50fps_dit_v2_fullbody.mp4      (1080x1920 @ 50fps standalone full-body digital human)
  2. preview_50fps_3way_comparison.mp4      (Wav2Lip256 vs Distill-v1 192px L1 vs New DiT-v2 256px GAN + 2x Teeth/Cheek Zoom)
  3. preview_50fps_dit_v2_showcase_sheet.jpg (High-res visual verification strip across gestures & phonemes)
  4. val_256_teacher_vs_student_gan.jpg     (Direct 256x256 Base vs Sonic Teacher vs Student GAN audit sheet)
"""
import argparse
import json
import math
import os
import subprocess
import sys
import time
import wave
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision import models


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", type=Path, default=Path(r"F:\xiaolin\app"))
    ap.add_argument("--distill-v1-dir", type=Path, default=Path(r"F:\xiaolin\distill-v1"))
    ap.add_argument("--dit-dir", type=Path, default=Path(r"F:\xiaolin\dit-distill-v2"))
    ap.add_argument("--epochs", type=int, default=80)
    ap.add_argument("--gan-start-epoch", type=int, default=18)
    ap.add_argument("--batch-pairs", type=int, default=16)
    ap.add_argument("--lr-g", type=float, default=1.0e-3)
    ap.add_argument("--lr-d", type=float, default=4.0e-4)
    return ap.parse_args()


def imwrite_unicode(path: Path, img: np.ndarray, ext: str = ".jpg", params=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(ext, img, params or [])
    if not ok:
        raise RuntimeError(f"Failed to encode image for {path}")
    buf.tofile(str(path))


class OfflineVGGPerceptual256(nn.Module):
    """Multi-scale VGG16 perceptual loss focused on the entire 160x208 lower-half face
    [84:244, 24:232] (apple muscles + nasolabial folds + lips + individual teeth + chin).
    """
    def __init__(self):
        super().__init__()
        vgg_ckpt = Path.home() / ".cache/torch/hub/checkpoints/vgg16-397923af.pth"
        vgg = models.vgg16(weights=None)
        if not vgg_ckpt.exists():
            raise RuntimeError(f"Expected cached VGG16 weights at {vgg_ckpt}")
        vgg.load_state_dict(torch.load(vgg_ckpt, map_location="cpu", weights_only=True))
        feats = vgg.features
        self.s1 = nn.Sequential(*[feats[i] for i in range(4)]).eval()
        self.s2 = nn.Sequential(*[feats[i] for i in range(4, 9)]).eval()
        self.s3 = nn.Sequential(*[feats[i] for i in range(9, 16)]).eval()
        for p in self.parameters():
            p.requires_grad_(False)
        self.register_buffer("mean", torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1))
        self.register_buffer("std", torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1))

    def forward(self, pred_bgr: torch.Tensor, tgt_bgr: torch.Tensor) -> torch.Tensor:
        p_rgb = pred_bgr[:, [2, 1, 0], 84:244, 24:232]
        t_rgb = tgt_bgr[:, [2, 1, 0], 84:244, 24:232]
        p = (p_rgb - self.mean) / self.std
        t = (t_rgb - self.mean) / self.std
        f1_p, f1_t = self.s1(p), self.s1(t)
        f2_p, f2_t = self.s2(f1_p), self.s2(f1_t)
        f3_p, f3_t = self.s3(f2_p), self.s3(f2_t)
        return F.l1_loss(f1_p, f1_t) + F.l1_loss(f2_p, f2_t) + 0.85 * F.l1_loss(f3_p, f3_t)


def sobel_edges(img: torch.Tensor) -> torch.Tensor:
    kx = torch.tensor([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], dtype=img.dtype, device=img.device).view(1, 1, 3, 3).repeat(3, 1, 1, 1)
    ky = torch.tensor([[-1, -2, -1], [0, 0, 0], [1, 2, 1]], dtype=img.dtype, device=img.device).view(1, 1, 3, 3).repeat(3, 1, 1, 1)
    return torch.cat([F.conv2d(img, kx, padding=1, groups=3), F.conv2d(img, ky, padding=1, groups=3)], dim=1)


# --- RIFE v4 50fps Interpolator & Video Helpers ---
def _conv(in_planes, out_planes, kernel_size=3, stride=1, padding=1):
    return nn.Sequential(nn.Conv2d(in_planes, out_planes, kernel_size, stride, padding, bias=True), nn.PReLU(out_planes))


class _IFBlock(nn.Module):
    def __init__(self, in_planes, c=90):
        super().__init__()
        self.conv0 = nn.Sequential(_conv(in_planes, c // 2, 3, 2, 1), _conv(c // 2, c, 3, 2, 1))
        self.convblock0 = nn.Sequential(_conv(c, c), _conv(c, c))
        self.convblock1 = nn.Sequential(_conv(c, c), _conv(c, c))
        self.convblock2 = nn.Sequential(_conv(c, c), _conv(c, c))
        self.convblock3 = nn.Sequential(_conv(c, c), _conv(c, c))
        self.conv1 = nn.Sequential(nn.ConvTranspose2d(c, c // 2, 4, 2, 1), nn.PReLU(c // 2), nn.ConvTranspose2d(c // 2, 4, 4, 2, 1))
        self.conv2 = nn.Sequential(nn.ConvTranspose2d(c, c // 2, 4, 2, 1), nn.PReLU(c // 2), nn.ConvTranspose2d(c // 2, 1, 4, 2, 1))

    def forward(self, x, flow, scale=1):
        if scale != 1:
            x = F.interpolate(x, scale_factor=1.0 / scale, mode="bilinear", align_corners=False)
            flow = F.interpolate(flow, scale_factor=1.0 / scale, mode="bilinear", align_corners=False) * (1.0 / scale)
        feat = self.conv0(torch.cat((x, flow), 1))
        feat = self.convblock0(feat) + feat
        feat = self.convblock1(feat) + feat
        feat = self.convblock2(feat) + feat
        feat = self.convblock3(feat) + feat
        dflow, dmask = self.conv1(feat), self.conv2(feat)
        if scale != 1:
            dflow = F.interpolate(dflow, scale_factor=scale, mode="bilinear", align_corners=False) * scale
            dmask = F.interpolate(dmask, scale_factor=scale, mode="bilinear", align_corners=False)
        return dflow, dmask


class RIFEInterpolator:
    def __init__(self, weight_path: Path, device: str = "cuda"):
        self.device = torch.device(device)
        self.net = nn.Module()
        self.net.block0 = _IFBlock(11, c=90)
        self.net.block1 = _IFBlock(11, c=90)
        self.net.block2 = _IFBlock(11, c=90)
        sd_raw = torch.load(weight_path, map_location="cpu", weights_only=False)
        sd = {k.replace("module.", ""): v for k, v in sd_raw.items() if "block_tea" not in k}
        self.net.load_state_dict(sd, strict=True)
        self.net.to(self.device).eval()
        self._grid_cache = {}

    def _warp(self, img: torch.Tensor, flow: torch.Tensor) -> torch.Tensor:
        B, C, H, W = img.shape
        key = (H, W, img.device)
        if key not in self._grid_cache:
            yy, xx = torch.meshgrid(
                torch.linspace(-1.0, 1.0, H, device=img.device),
                torch.linspace(-1.0, 1.0, W, device=img.device),
                indexing="ij",
            )
            self._grid_cache[key] = (xx, yy)
        xx, yy = self._grid_cache[key]
        gx = xx.unsqueeze(0) + flow[:, 0] / ((W - 1.0) / 2.0)
        gy = yy.unsqueeze(0) + flow[:, 1] / ((H - 1.0) / 2.0)
        return F.grid_sample(img, torch.stack([gx, gy], dim=-1), mode="bilinear", padding_mode="border", align_corners=True)

    @torch.inference_mode()
    def midpoint_tensor(self, I0: torch.Tensor, I1: torch.Tensor) -> torch.Tensor:
        B, _, H, W = I0.shape
        flow = torch.zeros(B, 4, H, W, device=I0.device, dtype=I0.dtype)
        mask = torch.zeros(B, 1, H, W, device=I0.device, dtype=I0.dtype)
        w0, w1 = I0, I1
        for blk, sc in ((self.net.block0, 4), (self.net.block1, 2), (self.net.block2, 1)):
            df, dm = blk(torch.cat([w0, w1, mask], dim=1), flow, scale=sc)
            flow, mask = flow + df, mask + dm
            w0 = self._warp(I0, flow[:, :2])
            w1 = self._warp(I1, flow[:, 2:4])
        m = torch.sigmoid(mask)
        return (w0 * m + w1 * (1.0 - m)).clamp(0.0, 1.0)

    def _bgr_to_padded_rgb_t(self, frame_bgr: np.ndarray) -> torch.Tensor:
        t = torch.from_numpy(frame_bgr[:, :, ::-1].copy()).permute(2, 0, 1).unsqueeze(0).to(self.device).float() / 255.0
        return F.pad(t, (0, 8, 0, 0), mode="replicate")

    def _padded_rgb_t_to_bgr(self, t: torch.Tensor) -> np.ndarray:
        rgb = (t[0, :, :1920, :1080].clamp(0, 1) * 255.0).byte().permute(1, 2, 0).cpu().numpy()
        return rgb[:, :, ::-1].copy()

    @torch.inference_mode()
    def bridge_hermite(self, first_bgr: np.ndarray, last_bgr: np.ndarray, n_bridge: int = 20) -> list[tuple[float, np.ndarray]]:
        nodes = [self._bgr_to_padded_rgb_t(first_bgr), self._bgr_to_padded_rgb_t(last_bgr)]
        for _ in range(4):
            nxt = [nodes[0]]
            mids = self.midpoint_tensor(torch.cat(nodes[:-1], dim=0), torch.cat(nodes[1:], dim=0))
            for k in range(len(nodes) - 1):
                nxt.append(mids[k : k + 1])
                nxt.append(nodes[k + 1])
            nodes = nxt
        N_sub = len(nodes) - 1
        out = []
        for idx in range(n_bridge):
            tau = (idx + 1.0) / (n_bridge + 1.0)
            s = tau * tau * (3.0 - 2.0 * tau)
            pos = s * N_sub
            k0 = min(N_sub - 1, int(math.floor(pos)))
            rem = pos - k0
            out.append((s, self._padded_rgb_t_to_bgr(nodes[k0] * (1.0 - rem) + nodes[k0 + 1] * rem)))
        return out


def upsample_25_to_50_rife(frames_25: list[np.ndarray], coords_25: list[list[int]], rife: RIFEInterpolator):
    n = len(frames_25)
    mids = []
    for b0 in range(0, n - 1, 6):
        b1 = min(n - 1, b0 + 6)
        I0 = torch.cat([rife._bgr_to_padded_rgb_t(frames_25[k]) for k in range(b0, b1)], dim=0)
        I1 = torch.cat([rife._bgr_to_padded_rgb_t(frames_25[k + 1]) for k in range(b0, b1)], dim=0)
        mid_t = rife.midpoint_tensor(I0, I1)
        for k_loc in range(b1 - b0):
            mids.append(rife._padded_rgb_t_to_bgr(mid_t[k_loc : k_loc + 1]))
    f50, c50 = [], []
    for i in range(n):
        f50.append(frames_25[i])
        c50.append(coords_25[i])
        if i + 1 < n:
            f50.append(mids[i])
            c50.append(np.rint(0.5 * (np.array(coords_25[i]) + np.array(coords_25[i + 1]))).astype(int).tolist())
        else:
            f50.append(frames_25[i].copy())
            c50.append(coords_25[i])
    return f50, c50


class FFmpegVideoWriter:
    def __init__(self, ffmpeg_exe: Path, out_path: Path, width: int, height: int, fps: int, audio_path: Path):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            str(ffmpeg_exe), "-v", "error", "-nostdin", "-y",
            "-f", "rawvideo", "-pix_fmt", "bgr24",
            "-s", f"{width}x{height}", "-r", str(fps), "-i", "pipe:0",
            "-i", str(audio_path),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-preset", "fast", "-crf", "15",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart",
            str(out_path),
        ]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        self.out_path = out_path

    def write(self, frame_bgr: np.ndarray):
        self.proc.stdin.write(frame_bgr.tobytes())

    def close(self):
        self.proc.stdin.close()
        err = self.proc.stderr.read()
        rc = self.proc.wait(timeout=60)
        if rc != 0:
            raise RuntimeError(f"FFmpeg failed for {self.out_path}: {err.decode(errors='replace')[:400]}")


def extract_whisper_50hz(audio_processor, audio_16k: np.ndarray, n_frames_50fps: int) -> np.ndarray:
    total_w = n_frames_50fps + 20
    ext_audio = np.pad(audio_16k, (3200 + 32000, 3200 + 32000))
    pieces = []
    for w0 in range(0, total_w, 1000):
        w1 = min(total_w, w0 + 1000)
        pcm_win = ext_audio[w0 * 320 : (w1 + 200) * 320]
        feat = audio_processor.audio2feat(pcm_win)
        pieces.append(feat[100 : 100 + (w1 - w0)])
    whisper_all = np.concatenate(pieces, axis=0)
    windows = np.empty((n_frames_50fps, 10, 5, 384), dtype=np.float16)
    for i in range(n_frames_50fps):
        c = 10 + i
        windows[i] = whisper_all[c - 4 : c + 6].astype(np.float16)
    return windows


def compute_50fps_envelope(audio_16k: np.ndarray, n_frames_50fps: int) -> np.ndarray:
    rms = np.array([math.sqrt(float(np.mean(audio_16k[i * 320 : (i + 1) * 320] ** 2)) + 1e-12) for i in range(n_frames_50fps)])
    voiced = np.zeros(n_frames_50fps, dtype=np.int32)
    st = 0
    for i, r in enumerate(rms):
        if st == 0 and r >= 0.009:
            st = 1
        elif st == 1 and r < 0.0040:
            st = 0
        voiced[i] = st
    i = 0
    while i < n_frames_50fps:
        if voiced[i] == 1:
            i += 1
            continue
        j = i
        while j < n_frames_50fps and voiced[j] == 0:
            j += 1
        if i > 0 and j < n_frames_50fps and (j - i) < 34:
            voiced[i:j] = 1
        i = j
    solid = np.zeros(n_frames_50fps, dtype=np.int32)
    for idx in range(n_frames_50fps):
        if voiced[idx] == 1:
            solid[max(0, idx - 8) : min(n_frames_50fps, idx + 23)] = 1
    env = np.zeros(n_frames_50fps, dtype=np.float32)
    ramp = 8
    for idx in range(n_frames_50fps):
        v = float(solid[idx])
        if v < 1.0:
            for k in range(1, ramp + 1):
                if idx + k < n_frames_50fps and solid[idx + k] == 1:
                    t = 1.0 - k / (ramp + 1.0)
                    v = max(v, t * t * (3.0 - 2.0 * t))
                if idx - k >= 0 and solid[idx - k] == 1:
                    t = 1.0 - k / (ramp + 1.0)
                    v = max(v, t * t * (3.0 - 2.0 * t))
        env[idx] = v
    return env


def make_panel_with_zoom(
    full_1080: np.ndarray,
    coord_y1y2x1x2: list[int],
    title: str,
    subtitle: str,
    accent_bgr: tuple[int, int, int],
) -> np.ndarray:
    """Creates a 540x1280 column:
      - Top 540x920: Half-body + hands + head view [y=30:1150, x=210:870]
      - Bottom 540x360: High-magnification 2.2x Apple-Muscle + Teeth + Jaw live zoom!
    """
    body_crop = cv2.resize(full_1080[30:1150, 210:870], (540, 920), interpolation=cv2.INTER_AREA)
    ov = body_crop.copy()
    cv2.rectangle(ov, (0, 0), (540, 68), (16, 16, 20), -1)
    cv2.addWeighted(ov, 0.76, body_crop, 0.24, 0, body_crop)
    cv2.rectangle(body_crop, (0, 0), (6, 68), accent_bgr, -1)
    cv2.putText(body_crop, title, (14, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.64, accent_bgr, 2, cv2.LINE_AA)
    cv2.putText(body_crop, subtitle, (14, 54), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (230, 230, 235), 1, cv2.LINE_AA)

    y1, y2, x1, x2 = coord_y1y2x1x2
    cx = int(0.5 * (x1 + x2))
    cy = int(0.5 * (y1 + y2)) + 16
    zx1, zy1 = max(0, cx - 135), max(0, cy - 90)
    zx2, zy2 = min(1080, zx1 + 270), min(1920, zy1 + 180)
    zoom = cv2.resize(full_1080[zy1:zy2, zx1:zx2], (540, 360), interpolation=cv2.INTER_CUBIC)
    cv2.line(zoom, (0, 0), (540, 0), accent_bgr, 2)
    cv2.putText(zoom, "2x Live Zoom: Cheeks + Teeth + Jaw", (12, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.52, accent_bgr, 1, cv2.LINE_AA)
    return np.vstack([body_crop, zoom])


def main():
    t_start = time.perf_counter()
    args = parse_args()
    WORKSPACE = args.workspace.resolve()
    DISTILL_V1 = args.distill_v1_dir.resolve()
    DIT_DIR = args.dit_dir.resolve()
    DATASET_DIR = DIT_DIR / "dataset256"
    CKPT_DIR = DIT_DIR / "checkpoints"
    OUT_DIR = DIT_DIR / "outputs"
    CKPT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    AVATAR_ROOT = WORKSPACE / "avatar-2d"
    MUSE_ROOT = WORKSPACE / "musetalk-eval"
    VENDOR_ROOT = AVATAR_ROOT / "vendor" / "LiveTalking-c7269433a2b6ecebcd9342445d2ecc882c98b0da"
    FFMPEG = WORKSPACE / "fay-ue4/runtime/fay-local/app/test/ovr_lipsync/ffmpeg/bin/ffmpeg.exe"

    sys.path.insert(0, str(AVATAR_ROOT / "tools"))
    from windows_runtime import prepare_runtime
    prepare_runtime()

    sys.path.insert(0, str(DIT_DIR))
    sys.path.insert(0, str(DISTILL_V1))
    sys.path.insert(0, str(VENDOR_ROOT))

    from grade_presenter_v2 import cheek_color, grade
    from xiaolin_student256_gan import (
        XiaolinStudent256UNet,
        LowerFacePatchGANDiscriminator,
        get_student_box256,
        build_lower_half_hide_mask_256,
        build_lower_half_compose_alpha_256,
    )
    from xiaolin_ultralight_model import (
        XiaolinUltralightUNet,
        build_mouth_hide_mask_192,
        build_compose_alpha_192,
    )

    torch.manual_seed(20261113)
    np.random.seed(20261113)
    torch.backends.cudnn.benchmark = False
    device = torch.device("cuda")

    # =========================================================================
    # PART 1: Train 256x256 Dual-Reference Student UNet + Lower-Face PatchGAN
    # =========================================================================
    print("[Part 1/2] Loading 256x256 Sonic Teacher dataset into RAM...", flush=True)
    train_src = np.load(DATASET_DIR / "train_src_256.npy")
    train_tgt = np.load(DATASET_DIR / "train_tgt_256.npy")
    train_whisp = np.load(DATASET_DIR / "train_whisper.npy")

    val_src = np.load(DATASET_DIR / "val_src_256.npy")
    val_tgt = np.load(DATASET_DIR / "val_tgt_256.npy")
    val_whisp = np.load(DATASET_DIR / "val_whisper.npy")

    closed_ref_256 = np.load(DATASET_DIR / "canonical_closed_ref_256.npy")
    teeth_ref_256 = np.load(DATASET_DIR / "canonical_teeth_ref_256.npy")

    n_train, n_val = len(train_src), len(val_src)
    silent_indices = [i for i in range(n_train) if np.max(np.abs(train_src[i].astype(int) - train_tgt[i].astype(int))) == 0]
    if not silent_indices:
        silent_indices = [0, 1, 2]
    silent_whisp_pool = torch.from_numpy(train_whisp[silent_indices[:64]].astype(np.float32)).to(device)

    hide_mask_np = build_lower_half_hide_mask_256()  # (256, 256, 1)
    hide_mask_t = torch.from_numpy(hide_mask_np.transpose(2, 0, 1)).unsqueeze(0).to(device)
    closed_ref_t = (torch.from_numpy(closed_ref_256.transpose(2, 0, 1)).float() / 255.0).unsqueeze(0).to(device)
    teeth_ref_t = (torch.from_numpy(teeth_ref_256.transpose(2, 0, 1)).float() / 255.0).unsqueeze(0).to(device)
    dual_refs_t = torch.cat([closed_ref_t, teeth_ref_t], dim=1)  # (1, 6, 256, 256)

    # Spatial loss weights across 256x256: apple muscles + nasolabial + jaw (5.5x) & mouth/teeth (15x)
    yy, xx = np.mgrid[0:256, 0:256].astype(np.float32)
    lower_roi = ((xx >= 24) & (xx <= 232) & (yy >= 96) & (yy <= 242)).astype(np.float32)
    teeth_roi = ((xx >= 58) & (xx <= 198) & (yy >= 136) & (yy <= 202)).astype(np.float32)
    lower_roi = cv2.GaussianBlur(lower_roi, (15, 15), 0)
    teeth_roi = cv2.GaussianBlur(teeth_roi, (11, 11), 0)
    pix_weight = torch.from_numpy(1.0 + 4.5 * lower_roi + 10.5 * teeth_roi).view(1, 1, 256, 256).to(device)
    edge_weight = torch.from_numpy(0.2 + 2.5 * lower_roi + 6.0 * teeth_roi).view(1, 1, 256, 256).to(device)

    netG = XiaolinStudent256UNet(in_channels=9).to(device)
    netD = LowerFacePatchGANDiscriminator(in_channels=6).to(device)
    vgg_fn = OfflineVGGPerceptual256().to(device)

    n_params_g = sum(p.numel() for p in netG.parameters())
    print(f"XiaolinStudent256UNet params: {n_params_g:,} (~{n_params_g*2/1024**2:.2f} MB FP16)", flush=True)

    optG = torch.optim.AdamW(netG.parameters(), lr=args.lr_g, betas=(0.5, 0.999), weight_decay=1e-4)
    optD = torch.optim.AdamW(netD.parameters(), lr=args.lr_d, betas=(0.5, 0.999), weight_decay=1e-4)
    schedG = torch.optim.lr_scheduler.CosineAnnealingLR(optG, T_max=args.epochs, eta_min=2e-5)
    schedD = torch.optim.lr_scheduler.CosineAnnealingLR(optD, T_max=args.epochs, eta_min=1e-5)
    scalerG = torch.amp.GradScaler("cuda")
    scalerD = torch.amp.GradScaler("cuda")

    valid_pairs = np.arange(0, n_train - 1)
    best_val_score = 999.0
    history = []

    def eval_val():
        netG.eval()
        tot_mse, tot_lower_l1, tot_mouth_l1 = 0.0, 0.0, 0.0
        preds_all = []
        with torch.inference_mode(), torch.amp.autocast("cuda", dtype=torch.float16):
            for b0 in range(0, n_val, 32):
                b1 = min(n_val, b0 + 32)
                B = b1 - b0
                s = torch.from_numpy(val_src[b0:b1].transpose(0, 3, 1, 2)).to(device).float() / 255.0
                t = torch.from_numpy(val_tgt[b0:b1].transpose(0, 3, 1, 2)).to(device).float() / 255.0
                w = torch.from_numpy(val_whisp[b0:b1]).to(device).float()
                inp = torch.cat([s * (1.0 - hide_mask_t), dual_refs_t.expand(B, -1, -1, -1)], dim=1)
                p = netG(inp, w).float()
                tot_mse += F.mse_loss(p, t, reduction="sum").item() / (3 * 256 * 256)
                tot_lower_l1 += torch.abs(p[:, :, 96:240, 28:228] - t[:, :, 96:240, 28:228]).mean(dim=(1, 2, 3)).sum().item()
                tot_mouth_l1 += torch.abs(p[:, :, 136:202, 58:198] - t[:, :, 136:202, 58:198]).mean(dim=(1, 2, 3)).sum().item()
                preds_all.append((p.clamp(0, 1) * 255.0).byte().cpu().numpy().transpose(0, 2, 3, 1))
        psnr = -10.0 * math.log10(max(1e-8, tot_mse / n_val))
        return psnr, tot_lower_l1 / n_val, tot_mouth_l1 / n_val, np.concatenate(preds_all, axis=0)

    for epoch in range(1, args.epochs + 1):
        netG.train()
        netD.train()
        t_ep = time.perf_counter()
        perm = np.random.permutation(valid_pairs)
        use_gan = epoch >= args.gan_start_epoch
        g_sum, d_sum, steps = 0.0, 0.0, 0

        for p0 in range(0, len(perm), args.batch_pairs):
            idx0 = perm[p0 : p0 + args.batch_pairs]
            if len(idx0) < 4:
                continue
            idx1 = idx0 + 1
            P = len(idx0)

            s0 = torch.from_numpy(train_src[idx0].transpose(0, 3, 1, 2)).to(device).float() / 255.0
            s1 = torch.from_numpy(train_src[idx1].transpose(0, 3, 1, 2)).to(device).float() / 255.0
            t0_gt = torch.from_numpy(train_tgt[idx0].transpose(0, 3, 1, 2)).to(device).float() / 255.0
            t1_gt = torch.from_numpy(train_tgt[idx1].transpose(0, 3, 1, 2)).to(device).float() / 255.0
            w0 = torch.from_numpy(train_whisp[idx0]).to(device).float()
            w1 = torch.from_numpy(train_whisp[idx1]).to(device).float()

            # 14% explicit multi-pose silent identity pairs
            n_sil = max(1, int(0.14 * P))
            sp = torch.randint(0, len(silent_whisp_pool), (n_sil,), device=device)
            w0[:n_sil] = silent_whisp_pool[sp]
            w1[:n_sil] = silent_whisp_pool[sp]
            t0_gt[:n_sil] = s0[:n_sil]
            t1_gt[:n_sil] = s1[:n_sil]

            if np.random.rand() < 0.5:
                gain = torch.empty((P, 1, 1, 1), device=device).uniform_(0.97, 1.03)
                s0, s1 = (s0 * gain).clamp(0, 1), (s1 * gain).clamp(0, 1)
                t0_gt, t1_gt = (t0_gt * gain).clamp(0, 1), (t1_gt * gain).clamp(0, 1)

            s_cat = torch.cat([s0, s1], dim=0)
            t_cat = torch.cat([t0_gt, t1_gt], dim=0)
            w_cat = torch.cat([w0, w1], dim=0)
            s_masked = s_cat * (1.0 - hide_mask_t)
            inp_cat = torch.cat([s_masked, dual_refs_t.expand(2 * P, -1, -1, -1)], dim=1)

            with torch.amp.autocast("cuda", dtype=torch.float16):
                pred_cat = netG(inp_cat, w_cat)

            # 1) Update PatchGAN Discriminator (Hinge loss on lower-half face)
            if use_gan:
                optD.zero_grad(set_to_none=True)
                with torch.amp.autocast("cuda", dtype=torch.float16):
                    d_real, _ = netD(t_cat, s_masked)
                    d_fake, _ = netD(pred_cat.detach(), s_masked)
                    loss_d = F.relu(1.0 - d_real.float()).mean() + F.relu(1.0 + d_fake.float()).mean()
                scalerD.scale(loss_d).backward()
                scalerD.step(optD)
                scalerD.update()
                d_sum += loss_d.item()

            # 2) Update Student UNet Generator
            optG.zero_grad(set_to_none=True)
            with torch.amp.autocast("cuda", dtype=torch.float16):
                l_vgg = vgg_fn(pred_cat, t_cat)
                pred_f = pred_cat.float()
                l_pix = (torch.abs(pred_f - t_cat) * pix_weight).mean()
                l_edge = (torch.abs(sobel_edges(pred_f) - sobel_edges(t_cat)) * edge_weight).mean()
                pred0, pred1 = pred_f[:P], pred_f[P:]
                l_temp = (torch.abs((pred1 - pred0) - (t1_gt - t0_gt)) * pix_weight).mean()
                loss_g = l_pix + 0.40 * l_edge + 0.14 * l_vgg.float() + 2.2 * l_temp

                if use_gan:
                    with torch.no_grad():
                        _, feats_real = netD(t_cat, s_masked)
                    d_fake_g, feats_fake = netD(pred_cat, s_masked)
                    l_adv = -d_fake_g.float().mean()
                    l_fm = sum(F.l1_loss(ff.float(), fr.float().detach()) for ff, fr in zip(feats_fake, feats_real))
                    loss_g = loss_g + 0.025 * l_adv + 0.25 * l_fm

            scalerG.scale(loss_g).backward()
            scalerG.unscale_(optG)
            torch.nn.utils.clip_grad_norm_(netG.parameters(), 2.0)
            scalerG.step(optG)
            scalerG.update()

            g_sum += loss_g.item()
            steps += 1

        schedG.step()
        schedD.step()

        if epoch in (1, 5, 17, 25) or epoch % 10 == 0 or epoch == args.epochs:
            psnr, low_l1, m_l1, v_preds = eval_val()
            rec = {
                "epoch": epoch,
                "gan": use_gan,
                "loss_g": round(g_sum / max(1, steps), 4),
                "loss_d": round(d_sum / max(1, steps), 4) if use_gan else 0.0,
                "val_psnr": round(psnr, 2),
                "val_lower_l1": round(low_l1, 5),
                "val_mouth_l1": round(m_l1, 5),
                "sec": round(time.perf_counter() - t_ep, 2),
            }
            history.append(rec)
            print("TRAIN256_EPOCH", json.dumps(rec), flush=True)

            # Save best checkpoint (after GAN turns on, prioritize GAN-sharpened epochs!)
            score_key = m_l1 + (0.015 if not use_gan else 0.0)
            if score_key < best_val_score:
                best_val_score = score_key
                torch.save(
                    {
                        "model_fp16": {k: v.half().cpu() for k, v in netG.state_dict().items()},
                        "canonical_closed_ref_256": closed_ref_256,
                        "canonical_teeth_ref_256": teeth_ref_256,
                        "epoch": epoch,
                        "val_psnr": psnr,
                        "val_mouth_l1": m_l1,
                    },
                    CKPT_DIR / "xiaolin_dit_student256_best.pth",
                )
                cols = []
                for pid in np.linspace(12, n_val - 16, 8).astype(int):
                    c = np.vstack([val_src[pid], val_tgt[pid], v_preds[pid]])
                    cv2.putText(c, f"Val#{pid}", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (80, 240, 120), 1, cv2.LINE_AA)
                    cols.append(c)
                imwrite_unicode(OUT_DIR / "val_256_teacher_vs_student_gan.jpg", np.hstack(cols), ".jpg", [cv2.IMWRITE_JPEG_QUALITY, 95])

    # Benchmark FP16 batch=4 inference speed!
    best_ckpt = torch.load(CKPT_DIR / "xiaolin_dit_student256_best.pth", map_location="cpu", weights_only=False)
    student256 = XiaolinStudent256UNet(in_channels=9).cuda().half().eval()
    student256.load_state_dict({k: v.cuda().half() for k, v in best_ckpt["model_fp16"].items()})

    dx = torch.randn(4, 9, 256, 256, device="cuda", dtype=torch.float16)
    dw = torch.randn(4, 10, 5, 384, device="cuda", dtype=torch.float16)
    with torch.inference_mode():
        for _ in range(30):
            _ = student256(dx, dw)
        torch.cuda.synchronize()
        tb = time.perf_counter()
        for _ in range(200):
            _ = student256(dx, dw)
        torch.cuda.synchronize()
        dt_bench = time.perf_counter() - tb
    fps_4090 = (200 * 4) / dt_bench
    print(f"[Benchmark] XiaolinStudent256UNet FP16 batch=4: {(dt_bench/200)*1000:.2f} ms/batch -> {fps_4090:.1f} FPS on 4090!", flush=True)

    # Free training tensors before 50fps full-body rendering
    del train_src, train_tgt, train_whisp, val_src, val_tgt, netG, netD, vgg_fn, optG, optD
    torch.cuda.empty_cache()

    # =========================================================================
    # PART 2: Render 50fps 16.0s Multi-Action 3-Way Comparison & Full-Body MP4
    # =========================================================================
    print("[Part 2/2] Building 50fps 16.0s Multi-Action Full-Body 3-Way Preview...", flush=True)
    rife = RIFEInterpolator(DISTILL_V1 / "rife_flownet.pkl", device="cuda")

    prev_cwd = Path.cwd()
    os.chdir(MUSE_ROOT)
    try:
        from avatars.musetalk.whisper.audio2feature import Audio2Feature
        audio_processor = Audio2Feature(model_path=str(MUSE_ROOT / "models/whisper"))
    finally:
        os.chdir(prev_cwd)

    val_wav = DIT_DIR / "teacher/val_16s_16k.wav"
    with wave.open(str(val_wav), "rb") as wf:
        val_pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    n_total_50 = len(val_pcm) // 320  # 800 frames = 16.00s @ 50fps!

    whisp50 = extract_whisper_50hz(audio_processor, val_pcm, n_total_50)
    env50 = compute_50fps_envelope(val_pcm, n_total_50)
    sil_whisp_t = torch.from_numpy(extract_whisper_50hz(audio_processor, np.zeros(16000, np.float32), 4)[0:1]).cuda().half()

    hide256_h = hide_mask_t.half()
    refs256_h = dual_refs_t.half()
    comp_alpha_256 = build_lower_half_compose_alpha_256()  # (256, 256, 1)

    # Load previous distill-v1 (192x192 L1) student read-only for 3-way comparison
    v1_ckpt = torch.load(DISTILL_V1 / "checkpoints/xiaolin_ultralight_best.pth", map_location="cpu", weights_only=False)
    student192 = XiaolinUltralightUNet(in_channels=6).cuda().half().eval()
    student192.load_state_dict({k: v.cuda().half() for k, v in v1_ckpt["model_fp16"].items()})
    ref192_h = (torch.from_numpy(v1_ckpt["canonical_ref_192"].transpose(2, 0, 1)).float() / 255.0).unsqueeze(0).cuda().half()
    hide192_h = torch.from_numpy(build_mouth_hide_mask_192().transpose(2, 0, 1)).unsqueeze(0).cuda().half()
    comp_alpha_192 = build_compose_alpha_192()

    def load_25fps_clip(cid: str):
        vp = AVATAR_ROOT / "assets/presenter-v2-1080/prepared" / f"{cid}.mp4"
        cp = json.loads((AVATAR_ROOT / "runtime/presenter-v2-1080/avatars" / cid / "coords.json").read_text(encoding="utf-8"))
        cap = cv2.VideoCapture(str(vp))
        fs = []
        while True:
            ok, fr = cap.read()
            if not ok:
                break
            fs.append(fr)
        cap.release()
        return fs, cp

    idle25_f, idle25_c = load_25fps_clip("idle")
    ref_lab = np.median([cheek_color(idle25_f[int(k)], idle25_c[int(k)]) for k in np.linspace(104, 304, 11).astype(int)], axis=0)
    idle50_f, idle50_c = upsample_25_to_50_rife(idle25_f[104:265], idle25_c[104:265], rife)
    old_idle50_f, old_idle50_c = upsample_25_to_50_rife(idle25_f[:160], idle25_c[:160], rife)
    del idle25_f, idle25_c

    def harmonize_wave_256(frames_bgr: list[np.ndarray], coords_list: list[list[int]]) -> list[np.ndarray]:
        """Harmonizes bared-teeth resting frames on welcome-wave across the ENTIRE lower half of the face
        using XiaolinStudent256UNet + silent Whisper so cheeks, nasolabial folds, and resting lips match 100%!
        """
        out = []
        for b0 in range(0, len(frames_bgr), 24):
            b1 = min(len(frames_bgr), b0 + 24)
            B = b1 - b0
            crops, boxes = [], []
            for k in range(b0, b1):
                bx1, by1, bx2, by2 = get_student_box256(coords_list[k], frames_bgr[k].shape)
                boxes.append((bx1, by1, bx2, by2))
                crops.append(cv2.resize(frames_bgr[k][by1:by2, bx1:bx2], (256, 256), interpolation=cv2.INTER_LANCZOS4))
            s_t = torch.from_numpy(np.asarray(crops).transpose(0, 3, 1, 2)).cuda().half() / 255.0
            inp = torch.cat([s_t * (1.0 - hide256_h), refs256_h.expand(B, -1, -1, -1)], dim=1)
            with torch.inference_mode():
                preds = (student256(inp, sil_whisp_t.expand(B, -1, -1, -1)).float().clamp(0, 1) * 255.0).byte().permute(0, 2, 3, 1).cpu().numpy()
            for idx_l, k in enumerate(range(b0, b1)):
                bx1, by1, bx2, by2 = boxes[idx_l]
                al = cv2.resize(comp_alpha_256, (bx2 - bx1, by2 - by1), interpolation=cv2.INTER_LINEAR)[..., None]
                pt = cv2.resize(preds[idx_l], (bx2 - bx1, by2 - by1), interpolation=cv2.INTER_LANCZOS4)
                fr = frames_bgr[k].copy()
                fr[by1:by2, bx1:bx2] = (pt * al + fr[by1:by2, bx1:bx2] * (1.0 - al)).astype(np.uint8)
                out.append(fr)
        return out

    def harmonize_wave_192_v1(frames_bgr: list[np.ndarray], coords_list: list[list[int]]) -> list[np.ndarray]:
        out = []
        for b0 in range(0, len(frames_bgr), 24):
            b1 = min(len(frames_bgr), b0 + 24)
            B = b1 - b0
            crops, boxes = [], []
            for k in range(b0, b1):
                H, W = frames_bgr[k].shape[:2]
                y1, y2, x1, x2 = coords_list[k]
                ux1, uy1, ux2, uy2 = max(0, x1 - 8), max(0, y1), min(W, x2 + 8), min(H, y2 + 16)
                boxes.append((ux1, uy1, ux2, uy2))
                crops.append(cv2.resize(frames_bgr[k][uy1:uy2, ux1:ux2], (192, 192), interpolation=cv2.INTER_LANCZOS4))
            s_t = torch.from_numpy(np.asarray(crops).transpose(0, 3, 1, 2)).cuda().half() / 255.0
            inp = torch.cat([s_t * (1.0 - hide192_h), ref192_h.expand(B, -1, -1, -1)], dim=1)
            with torch.inference_mode():
                preds = (student192(inp, sil_whisp_t.expand(B, -1, -1, -1)).float().clamp(0, 1) * 255.0).byte().permute(0, 2, 3, 1).cpu().numpy()
            for idx_l, k in enumerate(range(b0, b1)):
                ux1, uy1, ux2, uy2 = boxes[idx_l]
                al = cv2.resize(comp_alpha_192, (ux2 - ux1, uy2 - uy1), interpolation=cv2.INTER_LINEAR)[..., None]
                pt = cv2.resize(preds[idx_l], (ux2 - ux1, uy2 - uy1), interpolation=cv2.INTER_LANCZOS4)
                fr = frames_bgr[k].copy()
                fr[uy1:uy2, ux1:ux2] = (pt * al + fr[uy1:uy2, ux1:ux2] * (1.0 - al)).astype(np.uint8)
                out.append(fr)
        return out

    act_v2_50, act_v1_50, act_old_50, act_c50 = {}, {}, {}, {}
    for act in ["welcome-wave", "explain-open-palms"]:
        f25, c25 = load_25fps_clip(act)
        act_old_50[act], _ = upsample_25_to_50_rife(f25, c25, rife)
        samp = np.linspace(0, len(f25) - 1, 11).astype(int)
        corr = (ref_lab - np.median([cheek_color(f25[int(k)], c25[int(k)]) for k in samp], axis=0)).astype(np.float32)
        f25_g = [grade(fr, corr) for fr in f25]
        if act == "welcome-wave":
            f25_v2 = harmonize_wave_256(f25_g, c25)
            f25_v1 = harmonize_wave_192_v1(f25_g, c25)
        else:
            f25_v2 = f25_g
            f25_v1 = f25_g
        act_v2_50[act], act_c50[act] = upsample_25_to_50_rife(f25_v2, c25, rife)
        act_v1_50[act], _ = upsample_25_to_50_rife(f25_v1, c25, rife)

    # Assemble 800-frame (16.00s @ 50fps) multi-action body timelines:
    # idle -> RIFE bridge -> welcome-wave (full!) -> RIFE bridge -> idle -> RIFE bridge -> explain-open-palms
    def build_16s_timeline(idle_f, idle_c, act_map, c_map):
        bf, bc, bl = [], [], []
        # 1) Intro idle (36f)
        for i in range(36):
            bf.append(idle_f[i]); bc.append(idle_c[i]); bl.append("idle")
        # 2) Enter welcome-wave (18f)
        for s_v, fr in rife.bridge_hermite(idle_f[35], act_map["welcome-wave"][0], 18):
            bf.append(fr)
            bc.append(np.rint(np.array(idle_c[35]) * (1 - s_v) + np.array(c_map["welcome-wave"][0]) * s_v).astype(int).tolist())
            bl.append("bridge->welcome-wave")
        # 3) Full welcome-wave (350f)
        w_len = len(act_map["welcome-wave"])
        for i in range(w_len):
            bf.append(act_map["welcome-wave"][i]); bc.append(c_map["welcome-wave"][i]); bl.append("welcome-wave")
        # 4) Return to idle (18f)
        for s_v, fr in rife.bridge_hermite(act_map["welcome-wave"][-1], idle_f[60], 18):
            bf.append(fr)
            bc.append(np.rint(np.array(c_map["welcome-wave"][-1]) * (1 - s_v) + np.array(idle_c[60]) * s_v).astype(int).tolist())
            bl.append("bridge->idle")
        # 5) Mid idle (30f)
        for i in range(60, 90):
            bf.append(idle_f[i]); bc.append(idle_c[i]); bl.append("idle")
        # 6) Enter explain-open-palms (18f)
        for s_v, fr in rife.bridge_hermite(idle_f[89], act_map["explain-open-palms"][0], 18):
            bf.append(fr)
            bc.append(np.rint(np.array(idle_c[89]) * (1 - s_v) + np.array(c_map["explain-open-palms"][0]) * s_v).astype(int).tolist())
            bl.append("bridge->explain-palms")
        # 7) Explain-open-palms until 800f
        e_len = len(act_map["explain-open-palms"])
        k = 0
        while len(bf) < n_total_50:
            idx_e = min(k, e_len - 1)
            bf.append(act_map["explain-open-palms"][idx_e])
            bc.append(c_map["explain-open-palms"][idx_e])
            bl.append("explain-open-palms")
            k += 1
        return bf[:n_total_50], bc[:n_total_50], bl[:n_total_50]

    body_v2_f, body_c, phase_lbls = build_16s_timeline(idle50_f, idle50_c, act_v2_50, act_c50)
    body_v1_f, _, _ = build_16s_timeline(idle50_f, idle50_c, act_v1_50, act_c50)
    body_old_f, body_old_c, _ = build_16s_timeline(old_idle50_f, old_idle50_c, act_old_50, act_c50)

    # Load Old Wav2Lip256 for baseline column
    from avatars.wav2lip_avatar import Wav2Lip
    from avatars.wav2lip import audio as wav2lip_audio

    w2l = Wav2Lip()
    w2l_ckpt = torch.load(DISTILL_V1 / "wav2lip256.pth", map_location="cpu", weights_only=True)
    w2l.load_state_dict({k.removeprefix("module."): v for k, v in w2l_ckpt["state_dict"].items()})
    w2l = w2l.cuda().half().eval()
    mel = wav2lip_audio.melspectrogram(np.pad(val_pcm, (0, 6400)))
    rms_20ms = [math.sqrt(float(np.mean(val_pcm[i * 320 : (i + 1) * 320] ** 2)) + 1e-12) for i in range(n_total_50)]

    full_mp4 = OUT_DIR / "preview_50fps_dit_v2_fullbody.mp4"
    comp_mp4 = OUT_DIR / "preview_50fps_3way_comparison.mp4"
    w_full = FFmpegVideoWriter(FFMPEG, full_mp4, 1080, 1920, 50, val_wav)
    w_comp = FFmpegVideoWriter(FFMPEG, comp_mp4, 1620, 1280, 50, val_wav)

    audit_indices = [80, 145, 215, 290, 365, 515, 610, 715]
    audit_tiles = []

    for b0 in range(0, n_total_50, 4):
        b1 = min(n_total_50, b0 + 4)
        B = b1 - b0

        # 1) New DiT-v2 256x256 Dual-Ref GAN Student
        crops256, boxes256 = [], []
        for i in range(b0, b1):
            bx1, by1, bx2, by2 = get_student_box256(body_c[i], body_v2_f[i].shape)
            boxes256.append((bx1, by1, bx2, by2))
            crops256.append(cv2.resize(body_v2_f[i][by1:by2, bx1:bx2], (256, 256), interpolation=cv2.INTER_LANCZOS4))
        w_t = torch.from_numpy(whisp50[b0:b1]).cuda().half()
        s256_t = torch.from_numpy(np.asarray(crops256).transpose(0, 3, 1, 2)).cuda().half() / 255.0
        inp256 = torch.cat([s256_t * (1.0 - hide256_h), refs256_h.expand(B, -1, -1, -1)], dim=1)
        with torch.inference_mode():
            p256 = (student256(inp256, w_t).float().clamp(0, 1) * 255.0).byte().permute(0, 2, 3, 1).cpu().numpy()

        # 2) Prev Distill-v1 192x192 L1 Student
        crops192, boxes192 = [], []
        for i in range(b0, b1):
            H, W = body_v1_f[i].shape[:2]
            y1, y2, x1, x2 = body_c[i]
            ux1, uy1, ux2, uy2 = max(0, x1 - 8), max(0, y1), min(W, x2 + 8), min(H, y2 + 16)
            boxes192.append((ux1, uy1, ux2, uy2))
            crops192.append(cv2.resize(body_v1_f[i][uy1:uy2, ux1:ux2], (192, 192), interpolation=cv2.INTER_LANCZOS4))
        s192_t = torch.from_numpy(np.asarray(crops192).transpose(0, 3, 1, 2)).cuda().half() / 255.0
        inp192 = torch.cat([s192_t * (1.0 - hide192_h), ref192_h.expand(B, -1, -1, -1)], dim=1)
        with torch.inference_mode():
            p192 = (student192(inp192, w_t).float().clamp(0, 1) * 255.0).byte().permute(0, 2, 3, 1).cpu().numpy()

        # 3) Old Wav2Lip256
        ocrops = [cv2.resize(body_old_f[i][body_old_c[i][0]:body_old_c[i][1], body_old_c[i][2]:body_old_c[i][3]], (256, 256)) for i in range(b0, b1)]
        ofaces = np.asarray(ocrops)
        omasked = ofaces.copy(); omasked[:, 128:] = 0
        ox = torch.from_numpy((np.concatenate([omasked, ofaces], axis=3).astype(np.float32) / 255.0).transpose(0, 3, 1, 2).copy()).cuda().half()
        m_ch = [mel[:, min(int(i * 80.0 / 50.0), mel.shape[1] - 16) : min(int(i * 80.0 / 50.0), mel.shape[1] - 16) + 16] for i in range(b0, b1)]
        oa = torch.from_numpy(np.asarray(m_ch, np.float32)[:, None].copy()).cuda().half()
        with torch.inference_mode():
            opreds = (w2l(oa, ox).float().clamp(0, 1) * 255.0).byte().permute(0, 2, 3, 1).cpu().numpy()

        for k, i in enumerate(range(b0, b1)):
            # Compose New DiT-v2
            f_v2 = body_v2_f[i].copy()
            if env50[i] > 1e-3:
                bx1, by1, bx2, by2 = boxes256[k]
                bw, bh = bx2 - bx1, by2 - by1
                al = cv2.resize(comp_alpha_256 * float(env50[i]), (bw, bh), interpolation=cv2.INTER_LINEAR)[..., None]
                pt = cv2.resize(p256[k], (bw, bh), interpolation=cv2.INTER_LANCZOS4)
                f_v2[by1:by2, bx1:bx2] = (pt * al + f_v2[by1:by2, bx1:bx2] * (1.0 - al)).astype(np.uint8)

            # Compose Prev v1
            f_v1 = body_v1_f[i].copy()
            if env50[i] > 1e-3:
                ux1, uy1, ux2, uy2 = boxes192[k]
                uw, uh = ux2 - ux1, uy2 - uy1
                al1 = cv2.resize(comp_alpha_192 * float(env50[i]), (uw, uh), interpolation=cv2.INTER_LINEAR)[..., None]
                pt1 = cv2.resize(p192[k], (uw, uh), interpolation=cv2.INTER_LANCZOS4)
                f_v1[uy1:uy2, ux1:ux2] = (pt1 * al1 + f_v1[uy1:uy2, ux1:ux2] * (1.0 - al1)).astype(np.uint8)

            # Compose Old Wav2Lip256
            f_old = body_old_f[i].copy()
            if rms_20ms[i] > 0.004:
                oy1, oy2, ox1, ox2 = body_old_c[i]
                oh, ow = oy2 - oy1, ox2 - ox1
                opatch = cv2.resize(opreds[k], (ow, oh))
                yy_o, xx_o = np.mgrid[0:oh, 0:ow]
                edge_o = np.minimum(np.minimum(xx_o, ow - 1 - xx_o), np.minimum(yy_o, oh - 1 - yy_o))
                oalpha = (np.clip((yy_o / oh - 0.42) / 0.18, 0, 1) * np.clip(edge_o / 6.0, 0, 1))[..., None]
                f_old[oy1:oy2, ox1:ox2] = (opatch * oalpha + f_old[oy1:oy2, ox1:ox2] * (1.0 - oalpha)).astype(np.uint8)

            w_full.write(f_v2)

            col_old = make_panel_with_zoom(f_old, body_old_c[i], "1. Old Formal (Wav2Lip256)", f"t={i/50:.2f}s | Mouth-only blur", (70, 110, 245))
            col_v1 = make_panel_with_zoom(f_v1, body_c[i], "2. Prev Distill-v1 (192px L1)", f"t={i/50:.2f}s | No GAN, tight mask", (70, 195, 245))
            col_v2 = make_panel_with_zoom(f_v2, body_c[i], "3. New DiT-v2 (Sonic->256px GAN)", f"t={i/50:.2f}s | {phase_lbls[i]}", (85, 235, 115))
            w_comp.write(np.hstack([col_old, col_v1, col_v2]))

            if i in audit_indices:
                y1, y2, x1, x2 = body_c[i]
                cx, cy = int(0.5 * (x1 + x2)), int(0.5 * (y1 + y2)) + 12
                rx1, ry1 = max(0, cx - 120), max(0, cy - 110)
                rx2, ry2 = min(1080, rx1 + 240), min(1920, ry1 + 230)
                z_old = cv2.resize(f_old[ry1:ry2, rx1:rx2], (260, 250), interpolation=cv2.INTER_CUBIC)
                z_v1 = cv2.resize(f_v1[ry1:ry2, rx1:rx2], (260, 250), interpolation=cv2.INTER_CUBIC)
                z_v2 = cv2.resize(f_v2[ry1:ry2, rx1:rx2], (260, 250), interpolation=cv2.INTER_CUBIC)
                cv2.putText(z_old, f"Wav2Lip f={i}", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (75, 115, 250), 1, cv2.LINE_AA)
                cv2.putText(z_v1, f"v1-192-L1 ({phase_lbls[i][:12]})", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (70, 200, 250), 1, cv2.LINE_AA)
                cv2.putText(z_v2, f"DiT-v2-256-GAN ({i/50:.2f}s)", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (85, 235, 115), 1, cv2.LINE_AA)
                audit_tiles.append(np.vstack([z_old, z_v1, z_v2]))

    w_full.close()
    w_comp.close()

    if audit_tiles:
        imwrite_unicode(OUT_DIR / "preview_50fps_dit_v2_showcase_sheet.jpg", np.hstack(audit_tiles), ".jpg", [cv2.IMWRITE_JPEG_QUALITY, 95])

    report = {
        "best_epoch": best_ckpt["epoch"],
        "best_val_psnr_db": round(float(best_ckpt["val_psnr"]), 2),
        "best_val_mouth_l1": round(float(best_ckpt["val_mouth_l1"]), 5),
        "student256_params": n_params_g,
        "student256_fp16_mb": round((CKPT_DIR / "xiaolin_dit_student256_best.pth").stat().st_size / 1024**2, 2),
        "batch4_fp16_fps_4090": round(fps_4090, 1),
        "estimated_t4_fp16_fps": round(fps_4090 * 0.28, 1),
        "preview_frames_50fps": n_total_50,
        "total_wall_seconds": round(time.perf_counter() - t_start, 2),
    }
    (OUT_DIR / "step3_dit_v2_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("STEP3_DIT_V2_COMPLETE", json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
