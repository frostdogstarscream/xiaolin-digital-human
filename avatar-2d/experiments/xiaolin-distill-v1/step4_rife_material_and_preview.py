"""Step 4 (Body Stitching + End-to-End 50fps Integration & Preview):
1. Rebuilds 50fps clean idle & action clips using full-res RIFE v4 neural interpolation + Lab/luminance matching,
   plus clean closed-mouth harmonization on welcome-wave/goodbye-wave teeth-grin frames using Xiaolin-Ultralight.
2. Builds dense kinematic velocity-matched entry & return bridges using RIFE v4 recursive occlusion-aware
   bisection + cubic Hermite ease-in-out curve (replacing DISOpticalFlow linear addWeighted).
3. Runs 50fps real-time simulation on unseen speech (val_unseen_16k.wav, 1,148 frames @ 50fps = 22.96s)
   triggering all 4 gestures (welcome-wave, explain-open-palms, acknowledge-nod, goodbye-wave),
   comparing Old 50fps (DIS + Wav2Lip256 hard switch) vs New 50fps (RIFE + Xiaolin-Ultralight).
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


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", type=Path, default=Path("F:/xiaolin/app"))
    ap.add_argument("--distill-dir", type=Path, default=Path("F:/xiaolin/distill-v1"))
    return ap.parse_args()


ARGS = parse_args()
WORKSPACE = ARGS.workspace.resolve()
DISTILL_DIR = ARGS.distill_dir.resolve()
DATASET_DIR = DISTILL_DIR / "dataset"
CKPT_DIR = DISTILL_DIR / "checkpoints"
OUT_DIR = DISTILL_DIR / "outputs"
CACHE50_DIR = DISTILL_DIR / "material-cache-rife50"

AVATAR_ROOT = WORKSPACE / "avatar-2d"
MUSE_ROOT = WORKSPACE / "musetalk-eval"
VENDOR_ROOT = AVATAR_ROOT / "vendor" / "LiveTalking-c7269433a2b6ecebcd9342445d2ecc882c98b0da"
FFMPEG = WORKSPACE / "fay-ue4/runtime/fay-local/app/test/ovr_lipsync/ffmpeg/bin/ffmpeg.exe"

sys.path.insert(0, str(AVATAR_ROOT / "tools"))
from windows_runtime import prepare_runtime
prepare_runtime()

os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
sys.path.insert(0, str(VENDOR_ROOT))
sys.path.insert(0, str(DISTILL_DIR))

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from grade_presenter_v2 import cheek_color, grade
from xiaolin_ultralight_model import (
    XiaolinUltralightUNet,
    build_mouth_hide_mask_192,
    build_compose_alpha_192,
)


def imwrite_unicode(path: Path, img: np.ndarray, ext: str = ".jpg", params=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(ext, img, params or [])
    if not ok:
        raise RuntimeError(f"Failed to encode image for {path}")
    buf.tofile(str(path))


# --- 1. PSNR-Verified RIFE v4 Neural Frame Interpolator ---
def _conv(in_planes, out_planes, kernel_size=3, stride=1, padding=1):
    return nn.Sequential(
        nn.Conv2d(in_planes, out_planes, kernel_size, stride, padding, bias=True),
        nn.PReLU(out_planes),
    )


class _IFBlock(nn.Module):
    def __init__(self, in_planes, c=90):
        super().__init__()
        self.conv0 = nn.Sequential(_conv(in_planes, c // 2, 3, 2, 1), _conv(c // 2, c, 3, 2, 1))
        self.convblock0 = nn.Sequential(_conv(c, c), _conv(c, c))
        self.convblock1 = nn.Sequential(_conv(c, c), _conv(c, c))
        self.convblock2 = nn.Sequential(_conv(c, c), _conv(c, c))
        self.convblock3 = nn.Sequential(_conv(c, c), _conv(c, c))
        self.conv1 = nn.Sequential(
            nn.ConvTranspose2d(c, c // 2, 4, 2, 1),
            nn.PReLU(c // 2),
            nn.ConvTranspose2d(c // 2, 4, 4, 2, 1),
        )
        self.conv2 = nn.Sequential(
            nn.ConvTranspose2d(c, c // 2, 4, 2, 1),
            nn.PReLU(c // 2),
            nn.ConvTranspose2d(c // 2, 1, 4, 2, 1),
        )

    def forward(self, x, flow, scale=1):
        if scale != 1:
            x = F.interpolate(x, scale_factor=1.0 / scale, mode="bilinear", align_corners=False)
            flow = F.interpolate(flow, scale_factor=1.0 / scale, mode="bilinear", align_corners=False) * (1.0 / scale)
        feat = self.conv0(torch.cat((x, flow), 1))
        feat = self.convblock0(feat) + feat
        feat = self.convblock1(feat) + feat
        feat = self.convblock2(feat) + feat
        feat = self.convblock3(feat) + feat
        dflow = self.conv1(feat)
        dmask = self.conv2(feat)
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
        """I0, I1: (B, 3, H, W) RGB float32 in [0, 1], H & W divisible by 32."""
        B, _, H, W = I0.shape
        flow = torch.zeros(B, 4, H, W, device=I0.device, dtype=I0.dtype)
        mask = torch.zeros(B, 1, H, W, device=I0.device, dtype=I0.dtype)
        w0, w1 = I0, I1
        for blk, sc in ((self.net.block0, 4), (self.net.block1, 2), (self.net.block2, 1)):
            df, dm = blk(torch.cat([w0, w1, mask], dim=1), flow, scale=sc)
            flow = flow + df
            mask = mask + dm
            w0 = self._warp(I0, flow[:, :2])
            w1 = self._warp(I1, flow[:, 2:4])
        m = torch.sigmoid(mask)
        return (w0 * m + w1 * (1.0 - m)).clamp(0.0, 1.0)

    def _bgr_to_padded_rgb_t(self, frame_bgr: np.ndarray) -> torch.Tensor:
        # 1080x1920 -> pad width by 8px on right to 1088x1920 (divisible by 64!)
        t = torch.from_numpy(frame_bgr[:, :, ::-1].copy()).permute(2, 0, 1).unsqueeze(0).to(self.device).float() / 255.0
        return F.pad(t, (0, 8, 0, 0), mode="replicate")

    def _padded_rgb_t_to_bgr(self, t: torch.Tensor) -> np.ndarray:
        rgb = (t[0, :, :1920, :1080].clamp(0, 1) * 255.0).byte().permute(1, 2, 0).cpu().numpy()
        return rgb[:, :, ::-1].copy()

    @torch.inference_mode()
    def midpoint_bgr(self, a_bgr: np.ndarray, b_bgr: np.ndarray) -> np.ndarray:
        I0 = self._bgr_to_padded_rgb_t(a_bgr)
        I1 = self._bgr_to_padded_rgb_t(b_bgr)
        mid = self.midpoint_tensor(I0, I1)
        return self._padded_rgb_t_to_bgr(mid)

    @torch.inference_mode()
    def bridge_hermite(self, first_bgr: np.ndarray, last_bgr: np.ndarray, n_bridge: int = 20) -> list[tuple[float, np.ndarray]]:
        """Recursive RIFE v4 occlusion-aware bisection (depth=4 -> 17 dense sub-frames)
        sampled along a C1-velocity-continuous cubic Hermite ease-in-out curve!
        Zero DISOpticalFlow ghosting and zero linear start/stop jerk.
        """
        nodes = [self._bgr_to_padded_rgb_t(first_bgr), self._bgr_to_padded_rgb_t(last_bgr)]
        for _ in range(4):  # 2 -> 3 -> 5 -> 9 -> 17 occlusion-free RIFE nodes
            nxt = [nodes[0]]
            # Batch all midpoints at current recursion depth together on GPU!
            lefts = torch.cat(nodes[:-1], dim=0)
            rights = torch.cat(nodes[1:], dim=0)
            mids = self.midpoint_tensor(lefts, rights)
            for k in range(len(nodes) - 1):
                nxt.append(mids[k : k + 1])
                nxt.append(nodes[k + 1])
            nodes = nxt

        N_sub = len(nodes) - 1  # 16 intervals
        out = []
        for idx in range(n_bridge):
            tau = (idx + 1.0) / (n_bridge + 1.0)
            # C1 smoothstep curve (zero abrupt velocity step at anchor entry/exit)
            s = tau * tau * (3.0 - 2.0 * tau)
            pos = s * N_sub
            k0 = min(N_sub - 1, int(math.floor(pos)))
            rem = pos - k0
            frame_t = nodes[k0] * (1.0 - rem) + nodes[k0 + 1] * rem
            out.append((s, self._padded_rgb_t_to_bgr(frame_t)))
        return out


class FFmpegVideoWriter:
    def __init__(self, out_path: Path, width: int, height: int, fps: int, audio_path: Path):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            str(FFMPEG), "-v", "error", "-nostdin", "-y",
            "-f", "rawvideo", "-pix_fmt", "bgr24",
            "-s", f"{width}x{height}", "-r", str(fps), "-i", "pipe:0",
            "-i", str(audio_path),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-preset", "fast", "-crf", "16",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            str(out_path),
        ]
        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.out_path = out_path

    def write(self, frame_bgr: np.ndarray):
        self.proc.stdin.write(frame_bgr.tobytes())

    def close(self):
        self.proc.stdin.close()
        err = self.proc.stderr.read()
        rc = self.proc.wait(timeout=60)
        if rc != 0:
            raise RuntimeError(f"FFmpeg failed for {self.out_path}: {err.decode(errors='replace')[:400]}")


def get_student_ubox(coord_y1y2x1x2, frame_shape=(1920, 1080)):
    H, W = frame_shape[:2]
    y1, y2, x1, x2 = coord_y1y2x1x2
    return [max(0, x1 - 8), max(0, y1), min(W, x2 + 8), min(H, y2 + 16)]


def pose_descriptor(frame_bgr: np.ndarray) -> np.ndarray:
    feats = []
    for y1, y2, x1, x2 in [(100, 430, 400, 700), (350, 850, 300, 800), (650, 1150, 250, 850)]:
        gray = cv2.cvtColor(cv2.resize(frame_bgr[y1:y2, x1:x2], (40, 40)), cv2.COLOR_BGR2GRAY).astype(np.float32)
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0) * 0.15
        feats.append(np.concatenate([gray.ravel(), gx.ravel()]))
    return np.concatenate(feats)


def load_25fps_clip(clip_id: str):
    vid = AVATAR_ROOT / "assets/presenter-v2-1080/prepared" / f"{clip_id}.mp4"
    crd = json.loads((AVATAR_ROOT / "runtime/presenter-v2-1080/avatars" / clip_id / "coords.json").read_text(encoding="utf-8"))
    cap = cv2.VideoCapture(str(vid))
    frames = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    cap.release()
    assert len(frames) == len(crd), (clip_id, len(frames), len(crd))
    return frames, crd


def upsample_25_to_50_rife(frames_25: list[np.ndarray], coords_25: list[list[int]], rife: RIFEInterpolator):
    n = len(frames_25)
    mids = []
    pairs = n - 1
    for b0 in range(0, pairs, 6):
        b1 = min(pairs, b0 + 6)
        I0 = torch.cat([rife._bgr_to_padded_rgb_t(frames_25[k]) for k in range(b0, b1)], dim=0)
        I1 = torch.cat([rife._bgr_to_padded_rgb_t(frames_25[k + 1]) for k in range(b0, b1)], dim=0)
        mid_t = rife.midpoint_tensor(I0, I1)
        for k_loc in range(b1 - b0):
            mids.append(rife._padded_rgb_t_to_bgr(mid_t[k_loc : k_loc + 1]))

    frames_50 = []
    coords_50 = []
    for i in range(n):
        frames_50.append(frames_25[i])
        coords_50.append(coords_25[i])
        if i + 1 < n:
            mid_c = np.rint(0.5 * (np.array(coords_25[i]) + np.array(coords_25[i + 1]))).astype(int).tolist()
            frames_50.append(mids[i])
            coords_50.append(mid_c)
        else:
            frames_50.append(frames_25[i].copy())
            coords_50.append(coords_25[i])
    return frames_50, coords_50


def dis_bridge_15(first_bgr: np.ndarray, last_bgr: np.ndarray):
    """Exact reproduction of old build-material-cache.py DISOpticalFlow linear 15-frame bridge for comparison."""
    flow = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    small = lambda im: cv2.cvtColor(cv2.resize(im, (540, 960)), cv2.COLOR_BGR2GRAY)
    fwd = cv2.resize(flow.calc(small(first_bgr), small(last_bgr), None), (1080, 1920)) * 2.0
    bwd = cv2.resize(flow.calc(small(last_bgr), small(first_bgr), None), (1080, 1920)) * 2.0
    yy, xx = np.mgrid[:1920, :1080].astype(np.float32)
    out = []
    for idx in range(15):
        frac = (idx + 1.0) / 16.0
        a = cv2.remap(first_bgr, xx - fwd[:, :, 0] * frac, yy - fwd[:, :, 1] * frac, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        b = cv2.remap(last_bgr, xx - bwd[:, :, 0] * (1.0 - frac), yy - bwd[:, :, 1] * (1.0 - frac), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        out.append((frac, cv2.addWeighted(a, 1.0 - frac, b, frac, 0)))
    return out


def extract_whisper_50hz(audio_processor, audio_16k: np.ndarray, n_frames_50fps: int) -> np.ndarray:
    """Native 50Hz (20ms) Whisper encoder feature slicing — 1:1 with 50fps video frames!"""
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
        c = 10 + i  # 1 Whisper frame = 20ms = 1 video frame @ 50fps!
        windows[i] = whisper_all[c - 4 : c + 6].astype(np.float16)
    return windows


def compute_50fps_envelope(audio_16k: np.ndarray, n_frames_50fps: int) -> np.ndarray:
    """50fps active speech envelope that keeps alpha=1.0 across the ENTIRE opening & geometric
    lip-closure trajectory [onset-8, offset+22] (so open/closing mouths NEVER opacity-crossfade!),
    and only ramps 0<->1 while both student and base are 100% closed-mouth!
    """
    rms = np.array([
        math.sqrt(float(np.mean(audio_16k[i * 320 : (i + 1) * 320] ** 2)) + 1e-12)
        for i in range(n_frames_50fps)
    ])
    voiced = np.zeros(n_frames_50fps, dtype=np.int32)
    st = 0
    for i, r in enumerate(rms):
        if st == 0 and r >= 0.010:
            st = 1
        elif st == 1 and r < 0.0042:
            st = 0
        voiced[i] = st
    # Bridge intra-sentence pauses (< 34 frames @ 50fps = 0.68s) so Ultralight handles breaths natively
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

    # Expand solid=1.0 zone by [hold_pre=8, hold_post=22] so all mouth opening/closing happens at alpha=1.0!
    solid = np.zeros(n_frames_50fps, dtype=np.int32)
    for idx in range(n_frames_50fps):
        if voiced[idx] == 1:
            lo = max(0, idx - 8)
            hi = min(n_frames_50fps, idx + 23)
            solid[lo:hi] = 1

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


def build_showcase_33s_audio(val_pcm: np.ndarray, out_wav: Path, target_frames_50fps: int = 1650) -> np.ndarray:
    """Split strictly unseen val_unseen_16k.wav at natural silent valleys into utterance groups
    and insert natural 1.2s-1.5s live-stream silent pauses so all 4 full gestures + 8 bridges
    and multiple closed-mouth <-> speaking transitions are clearly demonstrated across 33.00s!
    """
    sr = 16000
    target_samples = target_frames_50fps * 320  # 528,000 samples = 33.00s
    win = 320
    n_w = len(val_pcm) // win
    rms = np.array([math.sqrt(float(np.mean(val_pcm[i * win : (i + 1) * win] ** 2)) + 1e-12) for i in range(n_w)])
    # Find silent runs >= 14 frames (0.28s)
    sil_runs = []
    i = 0
    while i < n_w:
        if rms[i] < 0.0025:
            j = i
            while j < n_w and rms[j] < 0.0025:
                j += 1
            if (j - i) >= 14 and i > 20 and j < n_w - 20:
                sil_runs.append(((i + j) // 2) * win)
            i = j
        else:
            i += 1

    # Pick up to 4 well-spaced split points across val_pcm
    splits = [0]
    for sp in sil_runs:
        if sp - splits[-1] >= int(3.8 * sr) and len(splits) < 5:
            splits.append(sp)
    splits.append(len(val_pcm))
    segs = [val_pcm[splits[k] : splits[k + 1]] for k in range(len(splits) - 1)]

    extra_needed = max(0, target_samples - len(val_pcm))
    # Distribute extra silence across: intro (0.9s), between segments, and outro
    n_gaps = len(segs) + 1
    intro_sil = min(int(0.95 * sr), extra_needed // 4)
    outro_sil = min(int(1.25 * sr), extra_needed // 4)
    rem_sil = max(0, extra_needed - intro_sil - outro_sil)
    per_mid = rem_sil // max(1, len(segs) - 1) if len(segs) > 1 else 0

    parts = [np.zeros(intro_sil, dtype=np.float32)]
    for idx, sg in enumerate(segs):
        parts.append(sg)
        if idx + 1 < len(segs):
            parts.append(np.zeros(per_mid, dtype=np.float32))
    parts.append(np.zeros(outro_sil, dtype=np.float32))
    full = np.concatenate(parts)
    if len(full) < target_samples:
        full = np.pad(full, (0, target_samples - len(full)))
    else:
        full = full[:target_samples]

    out_wav.parent.mkdir(parents=True, exist_ok=True)
    pcm16 = np.clip(full * 32767.0, -32768, 32767).astype("<i2")
    with wave.open(str(out_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm16.tobytes())
    return full


def make_banner(img: np.ndarray, title: str, sub: str, col=(80, 220, 115)) -> np.ndarray:
    out = img.copy()
    ov = out.copy()
    cv2.rectangle(ov, (0, 0), (out.shape[1], 72), (18, 18, 22), -1)
    cv2.addWeighted(ov, 0.74, out, 0.26, 0, out)
    cv2.rectangle(out, (0, 0), (6, 72), col, -1)
    cv2.putText(out, title, (16, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.72, col, 2, cv2.LINE_AA)
    cv2.putText(out, sub, (16, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (230, 230, 235), 1, cv2.LINE_AA)
    return out


def main():
    t_all = time.perf_counter()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CACHE50_DIR.mkdir(parents=True, exist_ok=True)
    torch.backends.cudnn.benchmark = False
    torch.cuda.set_per_process_memory_fraction(0.42)
    device = "cuda"

    print("[1/5] Loading RIFE v4, Xiaolin-Ultralight student checkpoint, and Whisper-tiny...", flush=True)
    rife = RIFEInterpolator(DISTILL_DIR / "rife_flownet.pkl", device=device)

    ckpt = torch.load(CKPT_DIR / "xiaolin_ultralight_best.pth", map_location="cpu", weights_only=False)
    student = XiaolinUltralightUNet(in_channels=6).cuda().half().eval()
    student.load_state_dict({k: v.cuda().half() for k, v in ckpt["model_fp16"].items()})
    canonical_ref_192 = ckpt["canonical_ref_192"]
    ref_t = (torch.from_numpy(canonical_ref_192.transpose(2, 0, 1)).float() / 255.0).unsqueeze(0).cuda().half()
    hide_mask_np = build_mouth_hide_mask_192()
    hide_mask_t = torch.from_numpy(hide_mask_np.transpose(2, 0, 1)).unsqueeze(0).cuda().half()
    compose_alpha_192 = build_compose_alpha_192()  # (192, 192, 1)

    prev_cwd = Path.cwd()
    os.chdir(MUSE_ROOT)
    try:
        from avatars.musetalk.whisper.audio2feature import Audio2Feature
        audio_processor = Audio2Feature(model_path=str(MUSE_ROOT / "models/whisper"))
    finally:
        os.chdir(prev_cwd)

    # Extract authentic silent Whisper window for harmonizing teeth-baring frames on wave clips
    sil_whisp = extract_whisper_50hz(audio_processor, np.zeros(16000, np.float32), 4)[0:1]
    sil_whisp_t = torch.from_numpy(sil_whisp).cuda().half()

    print("[2/5] Building RIFE 50fps Clean Idle Loop & Lab-Matched Action Clips...", flush=True)
    idle25_f, idle25_c = load_25fps_clip("idle")
    ref_lab = np.median([cheek_color(idle25_f[int(k)], idle25_c[int(k)]) for k in np.linspace(104, 304, 11).astype(int)], axis=0)

    # Clean bright-eyed closed-mouth idle: 25fps[104..304] -> RIFE 50fps (401 frames) -> seamless apex ping-pong (800 frames = 16.00s)
    clean_idle25_f = idle25_f[104:305]
    clean_idle25_c = idle25_c[104:305]
    idle50_fwd_f, idle50_fwd_c = upsample_25_to_50_rife(clean_idle25_f, clean_idle25_c, rife)
    # Remove duplicate trailing frame from upsample_25_to_50_rife and mirror smoothly
    idle50_fwd_f = idle50_fwd_f[:-1]  # 401 frames
    idle50_fwd_c = idle50_fwd_c[:-1]
    idle50_f = idle50_fwd_f + idle50_fwd_f[-2:0:-1]  # 800 frames = 16.00s exact zero-jump loop!
    idle50_c = idle50_fwd_c + idle50_fwd_c[-2:0:-1]

    # Also keep raw 50fps idle (0..320) for Old Baseline comparison (o_ptr resets to 0 after each gesture)
    old_idle50_f, old_idle50_c = upsample_25_to_50_rife(idle25_f[:160], idle25_c[:160], rife)
    del idle25_f, idle25_c

    action_names = ["welcome-wave", "explain-open-palms", "acknowledge-nod", "goodbye-wave"]
    actions50_f, actions50_c = {}, {}
    old_actions50_f, old_actions50_c = {}, {}

    def harmonize_silent_mouth_batch(frames_bgr: list[np.ndarray], coords_list: list[list[int]]) -> list[np.ndarray]:
        out_frames = []
        N = len(frames_bgr)
        for b0 in range(0, N, 32):
            b1 = min(N, b0 + 32)
            B = b1 - b0
            crops, boxes = [], []
            for k in range(b0, b1):
                ux1, uy1, ux2, uy2 = get_student_ubox(coords_list[k], frames_bgr[k].shape)
                boxes.append((ux1, uy1, ux2, uy2))
                crops.append(cv2.resize(frames_bgr[k][uy1:uy2, ux1:ux2], (192, 192), interpolation=cv2.INTER_LANCZOS4))
            s_t = (torch.from_numpy(np.asarray(crops).transpose(0, 3, 1, 2)).cuda().half() / 255.0)
            inp = torch.cat([s_t * (1.0 - hide_mask_t), ref_t.expand(B, -1, -1, -1)], dim=1)
            with torch.inference_mode():
                preds = (student(inp, sil_whisp_t.expand(B, -1, -1, -1)).float().clamp(0, 1) * 255.0).byte().permute(0, 2, 3, 1).cpu().numpy()
            for idx_local, k in enumerate(range(b0, b1)):
                ux1, uy1, ux2, uy2 = boxes[idx_local]
                alpha = cv2.resize(compose_alpha_192, (ux2 - ux1, uy2 - uy1), interpolation=cv2.INTER_LINEAR)[..., None]
                patch = cv2.resize(preds[idx_local], (ux2 - ux1, uy2 - uy1), interpolation=cv2.INTER_LANCZOS4)
                fr = frames_bgr[k].copy()
                fr[uy1:uy2, ux1:ux2] = (patch * alpha + fr[uy1:uy2, ux1:ux2] * (1.0 - alpha)).astype(np.uint8)
                out_frames.append(fr)
        return out_frames

    for act in action_names:
        f25, c25 = load_25fps_clip(act)
        # Old baseline uses ungraded raw 50fps frames
        of50, oc50 = upsample_25_to_50_rife(f25, c25, rife)
        old_actions50_f[act], old_actions50_c[act] = of50, oc50

        # Lab skin-tone match on 25fps before RIFE 50fps upsampling
        samp = np.linspace(0, len(f25) - 1, 11).astype(int)
        act_lab = np.median([cheek_color(f25[int(k)], c25[int(k)]) for k in samp], axis=0)
        corr = (ref_lab - act_lab).astype(np.float32)
        f25_graded = [grade(fr, corr) for fr in f25]

        # On welcome-wave & goodbye-wave, harmonize static teeth-baring grin into Xiaolin's serene
        # closed-mouth smile so silent/speaking transitions mid-wave never snap back to bared teeth!
        if act in ("welcome-wave", "goodbye-wave"):
            f25_graded = harmonize_silent_mouth_batch(f25_graded, c25)

        nf50, nc50 = upsample_25_to_50_rife(f25_graded, c25, rife)
        actions50_f[act], actions50_c[act] = nf50, nc50
        del f25, f25_graded
        print(f"  Prepared 50fps {act}: {len(nf50)} frames", flush=True)

    print("[3/5] Computing Dense Kinematic Anchor Matching (Open-Eye Guarded) + RIFE Hermite Bridges...", flush=True)
    idle_descs = [pose_descriptor(fr) for fr in idle50_f]
    n_idle = len(idle50_f)

    # Detect dark pupil/iris ratio on Clean Idle so bridge anchors NEVER land on a mid-blink frame!
    eye_dark = []
    for fr, cr in zip(idle50_f, idle50_c):
        y1, y2, x1, x2 = cr
        roi = fr[y1 + int(0.24 * (y2 - y1)) : y1 + int(0.42 * (y2 - y1)), x1 + int(0.18 * (x2 - x1)) : x1 + int(0.82 * (x2 - x1))]
        eye_dark.append(float((cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) < 75).mean()))
    med_eye = float(np.median(eye_dark))
    eye_open_ok = [
        all(eye_dark[(k + d) % n_idle] >= 0.80 * med_eye for d in range(-6, 7))
        for k in range(n_idle)
    ]

    def idle_vel(idx: int) -> np.ndarray:
        return idle_descs[(idx + 4) % n_idle] - idle_descs[idx]

    # Build optimal kinematic returns for each action across all open-eyed Clean Idle frames
    optimal_returns = {}
    valid_ret_indices = [r for r in range(0, n_idle, 2) if eye_open_ok[r]]
    for act in action_names:
        end_desc = pose_descriptor(actions50_f[act][-1])
        end_vel = end_desc - pose_descriptor(actions50_f[act][-5])
        best_r = min(
            valid_ret_indices,
            key=lambda r: float(np.mean(np.abs(end_desc - idle_descs[r])) + 0.6 * np.mean(np.abs(end_vel - idle_vel(r)))),
        )
        optimal_returns[act] = best_r

    # Plan a realistic 33.00s (1,650 frames @ 50fps) live-stream timeline covering all 4 full actions + 8 bridges!
    val_wav_path = DATASET_DIR / "val_unseen_16k.wav"
    with wave.open(str(val_wav_path), "rb") as wf:
        raw_val_pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    showcase_wav_path = OUT_DIR / "showcase_unseen_33s_16k.wav"
    val_pcm = build_showcase_33s_audio(raw_val_pcm, showcase_wav_path, target_frames_50fps=1650)
    n_total = len(val_pcm) // 320  # 1,650 frames @ 50fps (33.00s)

    # Schedule all 4 full gestures spaced naturally across the 33.00s timeline (zero truncation!):
    gesture_triggers = {
        30: "welcome-wave",
        475: "explain-open-palms",
        920: "acknowledge-nod",
        1210: "goodbye-wave",
    }

    # Generate New 50fps Timeline (Clean Idle + Dense Kinematic Anchor + 20-frame RIFE Hermite Bridge)
    new_body_frames = []
    new_body_coords = []
    new_phase_labels = []
    rife_bridge_mids = {}
    idle_ptr = 0
    t_cur = 0
    bridge_len = 20

    while t_cur < n_total:
        trig_act = None
        for tf, aname in list(gesture_triggers.items()):
            if t_cur <= tf <= t_cur + 12:
                trig_act = aname
                del gesture_triggers[tf]
                break

        if trig_act is not None:
            # Look ahead up to 22 frames (0.44s, dense step=2) for best open-eyed kinematic entry anchor on Clean Idle
            act_start_d = pose_descriptor(actions50_f[trig_act][0])
            act_start_v = pose_descriptor(actions50_f[trig_act][4]) - act_start_d
            cand_offsets = [off for off in range(0, 23, 2) if eye_open_ok[(idle_ptr + off) % n_idle]] or [0]
            best_off = min(
                cand_offsets,
                key=lambda off: float(
                    np.mean(np.abs(idle_descs[(idle_ptr + off) % n_idle] - act_start_d))
                    + 0.6 * np.mean(np.abs(idle_vel((idle_ptr + off) % n_idle) - act_start_v))
                ),
            )
            for _ in range(best_off):
                if t_cur >= n_total:
                    break
                new_body_frames.append(idle50_f[idle_ptr])
                new_body_coords.append(idle50_c[idle_ptr])
                new_phase_labels.append("idle")
                idle_ptr = (idle_ptr + 1) % n_idle
                t_cur += 1
            if t_cur >= n_total:
                break

            # RIFE v4 Hermite Entry Bridge (idle -> action[0])
            b_in = rife.bridge_hermite(idle50_f[idle_ptr], actions50_f[trig_act][0], n_bridge=bridge_len)
            rife_bridge_mids[f"enter:{trig_act}"] = b_in[len(b_in) // 2][1][120:1080, 260:820].copy()
            c_a = np.array(idle50_c[idle_ptr], dtype=np.float32)
            c_b = np.array(actions50_c[trig_act][0], dtype=np.float32)
            for s_val, bf in b_in:
                if t_cur >= n_total:
                    break
                new_body_frames.append(bf)
                new_body_coords.append(np.rint(c_a * (1.0 - s_val) + c_b * s_val).astype(int).tolist())
                new_phase_labels.append(f"RIFE-enter:{trig_act}")
                t_cur += 1

            # Full Action Playback
            for ai in range(len(actions50_f[trig_act])):
                if t_cur >= n_total:
                    break
                new_body_frames.append(actions50_f[trig_act][ai])
                new_body_coords.append(actions50_c[trig_act][ai])
                new_phase_labels.append(f"action:{trig_act}")
                t_cur += 1

            # RIFE v4 Hermite Return Bridge (action[-1] -> optimal_return on Clean Idle)
            ret_idx = optimal_returns[trig_act]
            b_out = rife.bridge_hermite(actions50_f[trig_act][-1], idle50_f[ret_idx], n_bridge=bridge_len)
            rife_bridge_mids[f"return:{trig_act}"] = b_out[len(b_out) // 2][1][120:1080, 260:820].copy()
            c_a = np.array(actions50_c[trig_act][-1], dtype=np.float32)
            c_b = np.array(idle50_c[ret_idx], dtype=np.float32)
            for s_val, bf in b_out:
                if t_cur >= n_total:
                    break
                new_body_frames.append(bf)
                new_body_coords.append(np.rint(c_a * (1.0 - s_val) + c_b * s_val).astype(int).tolist())
                new_phase_labels.append(f"RIFE-return:{trig_act}")
                t_cur += 1
            idle_ptr = ret_idx
        else:
            new_body_frames.append(idle50_f[idle_ptr])
            new_body_coords.append(idle50_c[idle_ptr])
            new_phase_labels.append("idle")
            idle_ptr = (idle_ptr + 1) % n_idle
            t_cur += 1

    # Also build Old 50fps Baseline Body Timeline (raw idle + DISOpticalFlow 15-frame linear bridges + single fixed return=0)
    old_triggers = {30: "welcome-wave", 475: "explain-open-palms", 920: "acknowledge-nod", 1210: "goodbye-wave"}
    old_body_frames, old_body_coords = [], []
    dis_bridge_mids = {}
    o_ptr, o_cur = 0, 0
    while o_cur < n_total:
        if o_cur in old_triggers:
            act = old_triggers[o_cur]
            db_in = dis_bridge_15(old_idle50_f[o_ptr % len(old_idle50_f)], old_actions50_f[act][0])
            dis_bridge_mids[f"enter:{act}"] = db_in[len(db_in) // 2][1][120:1080, 260:820].copy()
            for frac, bf in db_in:
                if o_cur >= n_total: break
                ca, cb = np.array(old_idle50_c[o_ptr % len(old_idle50_f)]), np.array(old_actions50_c[act][0])
                old_body_frames.append(bf)
                old_body_coords.append(np.rint(ca * (1 - frac) + cb * frac).astype(int).tolist())
                o_cur += 1
            for ai in range(len(old_actions50_f[act])):
                if o_cur >= n_total: break
                old_body_frames.append(old_actions50_f[act][ai])
                old_body_coords.append(old_actions50_c[act][ai])
                o_cur += 1
            db_out = dis_bridge_15(old_actions50_f[act][-1], old_idle50_f[0])
            dis_bridge_mids[f"return:{act}"] = db_out[len(db_out) // 2][1][120:1080, 260:820].copy()
            for frac, bf in db_out:
                if o_cur >= n_total: break
                ca, cb = np.array(old_actions50_c[act][-1]), np.array(old_idle50_c[0])
                old_body_frames.append(bf)
                old_body_coords.append(np.rint(ca * (1 - frac) + cb * frac).astype(int).tolist())
                o_cur += 1
            o_ptr = 0
        else:
            old_body_frames.append(old_idle50_f[o_ptr % len(old_idle50_f)])
            old_body_coords.append(old_idle50_c[o_ptr % len(old_idle50_f)])
            o_ptr += 1
            o_cur += 1

    # Save DISOpticalFlow vs RIFE v4 Hermite transition midpoint comparison sheet!
    b_cols = []
    for key in ["enter:welcome-wave", "return:welcome-wave", "enter:explain-open-palms", "return:explain-open-palms", "enter:acknowledge-nod", "enter:goodbye-wave"]:
        if key in dis_bridge_mids and key in rife_bridge_mids:
            d_im = cv2.resize(dis_bridge_mids[key], (280, 480), interpolation=cv2.INTER_AREA)
            r_im = cv2.resize(rife_bridge_mids[key], (280, 480), interpolation=cv2.INTER_AREA)
            cv2.putText(d_im, f"Old DIS: {key}", (8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (75, 115, 250), 1, cv2.LINE_AA)
            cv2.putText(r_im, f"New RIFE: {key}", (8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (80, 230, 115), 1, cv2.LINE_AA)
            b_cols.append(np.vstack([d_im, r_im]))
    if b_cols:
        imwrite_unicode(OUT_DIR / "rife-vs-dis-bridge-strip.jpg", np.hstack(b_cols), ".jpg", [cv2.IMWRITE_JPEG_QUALITY, 95])

    # Free source clip lists now that new_body_frames and old_body_frames hold exact frame pointers
    del idle50_f, idle50_c, old_idle50_f, old_idle50_c, actions50_f, actions50_c, old_actions50_f, old_actions50_c

    print("[4/5] Running 50fps Xiaolin-Ultralight vs Old Wav2Lip256 on unseen 33.00s timeline...", flush=True)
    whisp50 = extract_whisper_50hz(audio_processor, val_pcm, n_total)
    env50 = compute_50fps_envelope(val_pcm, n_total)

    # Old Wav2Lip256 50fps baseline
    from avatars.wav2lip_avatar import Wav2Lip
    from avatars.wav2lip import audio as wav2lip_audio

    w2l = Wav2Lip()
    w2l_ckpt = torch.load(DISTILL_DIR / "wav2lip256.pth", map_location="cpu", weights_only=True)
    w2l.load_state_dict({k.removeprefix("module."): v for k, v in w2l_ckpt["state_dict"].items()})
    w2l = w2l.cuda().half().eval()
    mel = wav2lip_audio.melspectrogram(np.pad(val_pcm, (0, 6400)))
    rms_20ms = [math.sqrt(float(np.mean(val_pcm[i * 320 : (i + 1) * 320] ** 2)) + 1e-12) for i in range(n_total)]

    preview_full_path = OUT_DIR / "preview-50fps-xiaolin-v2-full.mp4"
    preview_comp_path = OUT_DIR / "preview-50fps-old-vs-new-comparison.mp4"
    w_full = FFmpegVideoWriter(preview_full_path, 1080, 1920, 50, showcase_wav_path)
    w_comp = FFmpegVideoWriter(preview_comp_path, 1440, 1080, 50, showcase_wav_path)

    student_infer_sec = 0.0
    student_infer_frames = 0
    showcase_frames = {}
    showcase_targets = {12, 160, 260, 445, 620, 895, 1020, 1380}

    # Find first post-speech offset drop to sample an 8-frame 50fps speech->silence lip-closure strip
    drop_idx = next((idx for idx in range(100, n_total - 15) if env50[idx - 1] == 1.0 and env50[idx] < 1.0), 300)
    trans_targets = [max(0, drop_idx + d) for d in (-24, -20, -16, -12, -8, -4, 0, 6)]
    trans_frames = {}

    for b0 in range(0, n_total, 4):
        b1 = min(n_total, b0 + 4)
        B = b1 - b0

        # --- New 50fps Xiaolin-Ultralight batch=4 inference ---
        crops192 = []
        uboxes = []
        for i in range(b0, b1):
            ux1, uy1, ux2, uy2 = get_student_ubox(new_body_coords[i], new_body_frames[i].shape)
            uboxes.append((ux1, uy1, ux2, uy2))
            crops192.append(cv2.resize(new_body_frames[i][uy1:uy2, ux1:ux2], (192, 192), interpolation=cv2.INTER_LANCZOS4))

        if any(env50[i] > 1e-3 for i in range(b0, b1)):
            s_t = (torch.from_numpy(np.asarray(crops192).transpose(0, 3, 1, 2)).cuda().half() / 255.0)
            w_t = torch.from_numpy(whisp50[b0:b1]).cuda().half()
            inp_t = torch.cat([s_t * (1.0 - hide_mask_t), ref_t.expand(B, -1, -1, -1)], dim=1)
            torch.cuda.synchronize()
            t_inf = time.perf_counter()
            with torch.inference_mode():
                preds_u = student(inp_t, w_t)
            torch.cuda.synchronize()
            student_infer_sec += time.perf_counter() - t_inf
            student_infer_frames += B
            preds_u_np = (preds_u.float().clamp(0, 1) * 255.0).byte().permute(0, 2, 3, 1).cpu().numpy()
        else:
            preds_u_np = None

        # --- Old 50fps Wav2Lip256 inference ---
        old_crops = [cv2.resize(old_body_frames[i][old_body_coords[i][0]:old_body_coords[i][1], old_body_coords[i][2]:old_body_coords[i][3]], (256, 256)) for i in range(b0, b1)]
        old_faces = np.asarray(old_crops)
        old_masked = old_faces.copy()
        old_masked[:, 128:] = 0
        ox = torch.from_numpy((np.concatenate([old_masked, old_faces], axis=3).astype(np.float32) / 255.0).transpose(0, 3, 1, 2).copy()).cuda().half()
        m_chunks = [mel[:, min(int(i * 80.0 / 50.0), mel.shape[1] - 16) : min(int(i * 80.0 / 50.0), mel.shape[1] - 16) + 16] for i in range(b0, b1)]
        oa = torch.from_numpy(np.asarray(m_chunks, np.float32)[:, None].copy()).cuda().half()
        with torch.inference_mode():
            opreds = (w2l(oa, ox).float().clamp(0, 1) * 255.0).byte().permute(0, 2, 3, 1).cpu().numpy()

        for k, i in enumerate(range(b0, b1)):
            # Compose New 50fps Frame
            f_new = new_body_frames[i].copy()
            if preds_u_np is not None and env50[i] > 1e-3:
                ux1, uy1, ux2, uy2 = uboxes[k]
                uw, uh = ux2 - ux1, uy2 - uy1
                alpha = cv2.resize(compose_alpha_192 * float(env50[i]), (uw, uh), interpolation=cv2.INTER_LINEAR)[..., None]
                patch = cv2.resize(preds_u_np[k], (uw, uh), interpolation=cv2.INTER_LANCZOS4)
                f_new[uy1:uy2, ux1:ux2] = (patch * alpha + f_new[uy1:uy2, ux1:ux2] * (1.0 - alpha)).astype(np.uint8)

            # Compose Old 50fps Frame (hard audio switch rms > 0.004 just like render50.py)
            f_old = old_body_frames[i].copy()
            if rms_20ms[i] > 0.004:
                oy1, oy2, ox1, ox2 = old_body_coords[i]
                oh, ow = oy2 - oy1, ox2 - ox1
                opatch = cv2.resize(opreds[k], (ow, oh))
                yy, xx = np.mgrid[0:oh, 0:ow]
                edge = np.minimum(np.minimum(xx, ow - 1 - xx), np.minimum(yy, oh - 1 - yy))
                oalpha = (np.clip((yy / oh - 0.42) / 0.18, 0, 1) * np.clip(edge / 6.0, 0, 1))[..., None]
                f_old[oy1:oy2, ox1:ox2] = (opatch * oalpha + f_old[oy1:oy2, ox1:ox2] * (1.0 - oalpha)).astype(np.uint8)

            w_full.write(f_new)
            p_old = make_banner(
                f_old[20:1100, 180:900],
                "Old 50fps (DIS + Wav2Lip256)",
                f"t={i/50:.2f}s | Hard speech switch",
                col=(75, 115, 245),
            )
            p_new = make_banner(
                f_new[20:1100, 180:900],
                "New 50fps (RIFE + Xiaolin-Ultralight)",
                f"t={i/50:.2f}s | {new_phase_labels[i]}",
                col=(80, 220, 115),
            )
            w_comp.write(np.hstack([p_old, p_new]))

            if i in showcase_targets:
                showcase_frames[i] = (f_old[120:420, 400:700].copy(), f_new[120:420, 400:700].copy(), new_phase_labels[i])
            if i in trans_targets:
                trans_frames[i] = (f_old[150:400, 420:680].copy(), f_new[150:400, 420:680].copy(), float(rms_20ms[i]))

    w_full.close()
    w_comp.close()

    # Build visual verification sheet of the 50fps preview
    tiles = []
    for idx in sorted(showcase_frames):
        co, cn, lbl = showcase_frames[idx]
        co = cv2.resize(co, (260, 260), interpolation=cv2.INTER_CUBIC)
        cn = cv2.resize(cn, (260, 260), interpolation=cv2.INTER_CUBIC)
        cv2.putText(co, f"Old f={idx} ({idx/50:.2f}s)", (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (80, 120, 250), 1, cv2.LINE_AA)
        cv2.putText(cn, f"New: {lbl}", (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (80, 230, 115), 1, cv2.LINE_AA)
        tiles.append(np.vstack([co, cn]))
    imwrite_unicode(OUT_DIR / "preview-50fps-showcase-sheet.jpg", np.hstack(tiles), ".jpg", [cv2.IMWRITE_JPEG_QUALITY, 95])

    t_tiles = []
    for idx in sorted(trans_frames):
        co, cn, rv = trans_frames[idx]
        co = cv2.resize(co, (240, 240), interpolation=cv2.INTER_CUBIC)
        cn = cv2.resize(cn, (240, 240), interpolation=cv2.INTER_CUBIC)
        cv2.putText(co, f"Old f={idx} rms={rv:.3f}", (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (80, 120, 250), 1, cv2.LINE_AA)
        cv2.putText(cn, f"New f={idx} ({idx/50:.2f}s)", (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (80, 230, 115), 1, cv2.LINE_AA)
        t_tiles.append(np.vstack([co, cn]))
    if t_tiles:
        imwrite_unicode(OUT_DIR / "preview-50fps-mouth-transition-strip.jpg", np.hstack(t_tiles), ".jpg", [cv2.IMWRITE_JPEG_QUALITY, 95])

    eff_fps = student_infer_frames / max(1e-6, student_infer_sec)
    rep = {
        "preview_frames_50fps": n_total,
        "preview_seconds": round(n_total / 50.0, 2),
        "student_effective_gpu_fps": round(eff_fps, 1),
        "optimal_idle_returns": optimal_returns,
        "outputs": {
            "preview_full_50fps": str(preview_full_path),
            "preview_comparison_50fps": str(preview_comp_path),
            "showcase_sheet": str(OUT_DIR / "preview-50fps-showcase-sheet.jpg"),
        },
        "total_wall_seconds": round(time.perf_counter() - t_all, 2),
    }
    (OUT_DIR / "step4-preview-report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print("STEP4_PREVIEW_COMPLETE", json.dumps(rep, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
