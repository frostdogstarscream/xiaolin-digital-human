"""Build the formal 50 fps RIFE v4 + Xiaolin-DiT-v2 (256x256 Dual-Ref GAN) material cache on Tesla T4 (GPU 0):
1. Clean bright-eyed closed-mouth Idle Loop: idle[104..304] -> RIFE 50fps -> 800-frame zero-jump ping-pong
   split into 2 contiguous 400-frame segments for 100% IdleScheduler compatibility.
2. All 4 Action Clips (welcome-wave, goodbye-wave, explain-open-palms, acknowledge-nod):
   Lab skin-tone matched + whole-lower-face resting harmonization via XiaolinStudent256UNet
   + RIFE v4 25->50fps neural upsampling.
3. Open-Eye Kinematic Velocity+Pose Anchors + 20-frame recursive RIFE v4 Hermite bridges.
"""
import json
import math
import os
import sys
import time
from pathlib import Path

os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
sys.path[:0] = ["/formal/dit-v2-assets", "/formal/avatar-2d/experiments/presenter-50fps", "/eval/avatar-2d/tools"]

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from transformers import AutoFeatureExtractor, WhisperModel
from grade_presenter_v2 import grade
from xiaolin_student256_gan import (
    XiaolinStudent256UNet,
    get_student_box256,
    build_lower_half_hide_mask_256,
    build_lower_half_compose_alpha_256,
    build_degrin_mask_256,
)

cv2.setNumThreads(4)

ASSETS_DIR = Path("/formal/dit-v2-assets")
EVAL_AVATAR = Path("/eval/avatar-2d")
MUSE_ROOT = Path("/muse")
OUTPUT = Path("/formal/material-cache")


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
            pairs = len(nodes) - 1
            mids_all = []
            for b0 in range(0, pairs, 4):
                b1 = min(pairs, b0 + 4)
                mids_all.append(self.midpoint_tensor(torch.cat(nodes[b0:b1], dim=0), torch.cat(nodes[b0 + 1 : b1 + 1], dim=0)))
            mids = torch.cat(mids_all, dim=0)
            for k in range(pairs):
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


def descriptor(frame: np.ndarray) -> np.ndarray:
    feats = []
    for y1, y2, x1, x2 in [(100, 430, 400, 700), (350, 850, 300, 800), (650, 1150, 250, 850)]:
        gray = cv2.cvtColor(cv2.resize(frame[y1:y2, x1:x2], (40, 40)), cv2.COLOR_BGR2GRAY).astype(np.float32)
        feats.append(np.concatenate([gray.ravel(), (cv2.Sobel(gray, cv2.CV_32F, 1, 0) * 0.15).ravel()]))
    return np.concatenate(feats)


def load_25fps_clip(clip_id: str):
    vid = EVAL_AVATAR / "assets/presenter-v2-1080/prepared" / f"{clip_id}.mp4"
    crd_path = EVAL_AVATAR / "runtime/presenter-v2-1080/avatars" / clip_id / "coords.json"
    coords_25 = json.loads(crd_path.read_text(encoding="utf-8"))
    cap = cv2.VideoCapture(str(vid))
    frames = []
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        frames.append(fr)
    cap.release()
    assert len(frames) == len(coords_25), (clip_id, len(frames), len(coords_25))
    return frames, coords_25


def upsample_25_to_50_rife(frames_25: list[np.ndarray], coords_25: list[list[int]], rife: RIFEInterpolator):
    n = len(frames_25)
    mids = []
    for b0 in range(0, n - 1, 4):
        b1 = min(n - 1, b0 + 4)
        I0 = torch.cat([rife._bgr_to_padded_rgb_t(frames_25[k]) for k in range(b0, b1)], dim=0)
        I1 = torch.cat([rife._bgr_to_padded_rgb_t(frames_25[k + 1]) for k in range(b0, b1)], dim=0)
        mid_t = rife.midpoint_tensor(I0, I1)
        for k_loc in range(b1 - b0):
            mids.append(rife._padded_rgb_t_to_bgr(mid_t[k_loc : k_loc + 1]))
    f50, c50 = [], []
    for i in range(n):
        f50.append(frames_25[i]); c50.append(coords_25[i])
        if i + 1 < n:
            f50.append(mids[i])
            c50.append(np.rint(0.5 * (np.array(coords_25[i]) + np.array(coords_25[i + 1]))).astype(int).tolist())
        else:
            f50.append(frames_25[i].copy()); c50.append(coords_25[i])
    return f50, c50


def build_calibrated_silent_whisper_window(device: str = "cuda") -> torch.Tensor:
    fe = AutoFeatureExtractor.from_pretrained(str(MUSE_ROOT / "models/whisper"), local_files_only=True)
    whisper = WhisperModel.from_pretrained(str(MUSE_ROOT / "models/whisper"), local_files_only=True).to(device=device, dtype=torch.float16).eval()
    cal_buf = np.zeros(460000, dtype=np.float32)
    t_cal = np.arange(640, dtype=np.float32) / 16000.0
    cal_buf[448000:448640] = 0.28 * np.sin(2.0 * np.pi * 440.0 * t_cal)
    mel = fe(cal_buf, return_tensors="pt", sampling_rate=16000).input_features.to(device=device, dtype=torch.float16)
    with torch.inference_mode():
        hs = whisper.encoder(mel, output_hidden_states=True).hidden_states
        win = torch.stack(hs, dim=2)[0, 20:30].unsqueeze(0).contiguous()
    del whisper, fe
    torch.cuda.empty_cache()
    return win


def main():
    t0 = time.perf_counter()
    assert torch.cuda.is_available(), "CUDA required for RIFE + DiT-v2 cache build"
    OUTPUT.mkdir(parents=True, exist_ok=True)
    config = json.loads((ASSETS_DIR / "material-input.json").read_text(encoding="utf-8"))

    print(json.dumps({"stage": "init_models", "gpu": torch.cuda.get_device_name(0)}), flush=True)
    rife = RIFEInterpolator(ASSETS_DIR / "rife_flownet.pkl", device="cuda")

    ckpt = torch.load(ASSETS_DIR / "xiaolin_dit_student256_full_best.pth", map_location="cpu", weights_only=False)
    student = XiaolinStudent256UNet(in_channels=9).cuda().half().eval()
    student.load_state_dict({k: v.cuda().half() for k, v in ckpt["model_fp16"].items()})

    closed_t = (torch.from_numpy(ckpt["canonical_closed_ref_256"].transpose(2, 0, 1)).float() / 255.0).unsqueeze(0).cuda().half()
    teeth_t = (torch.from_numpy(ckpt["canonical_teeth_ref_256"].transpose(2, 0, 1)).float() / 255.0).unsqueeze(0).cuda().half()
    dual_refs_t = torch.cat([closed_t, teeth_t], dim=1)
    hide_t = torch.from_numpy(build_lower_half_hide_mask_256().transpose(2, 0, 1)).unsqueeze(0).cuda().half()
    degrin_t = torch.from_numpy(build_degrin_mask_256().transpose(2, 0, 1)).unsqueeze(0).cuda().half()
    comp_alpha_256 = build_lower_half_compose_alpha_256()
    sil_whisp_t = build_calibrated_silent_whisper_window(device="cuda")

    def harmonize_closed_smile_batch(frames_bgr: list[np.ndarray], coords_list: list[list[int]]) -> list[np.ndarray]:
        out_frames = []
        for b0 in range(0, len(frames_bgr), 24):
            b1 = min(len(frames_bgr), b0 + 24)
            B = b1 - b0
            crops, boxes = [], []
            for k in range(b0, b1):
                bx1, by1, bx2, by2 = get_student_box256(coords_list[k], frames_bgr[k].shape)
                boxes.append((bx1, by1, bx2, by2))
                crops.append(cv2.resize(frames_bgr[k][by1:by2, bx1:bx2], (256, 256), interpolation=cv2.INTER_LANCZOS4))
            s_t = torch.from_numpy(np.asarray(crops).transpose(0, 3, 1, 2)).cuda().half() / 255.0
            s_clean = s_t * (1.0 - degrin_t) + closed_t.expand(B, -1, -1, -1) * degrin_t
            inp = torch.cat([s_clean * (1.0 - hide_t), dual_refs_t.expand(B, -1, -1, -1)], dim=1)
            with torch.inference_mode():
                preds = (student(inp, sil_whisp_t.expand(B, -1, -1, -1)).float().clamp(0, 1) * 255.0).byte().permute(0, 2, 3, 1).cpu().numpy()
            for idx_loc, k in enumerate(range(b0, b1)):
                bx1, by1, bx2, by2 = boxes[idx_loc]
                alpha = cv2.resize(comp_alpha_256, (bx2 - bx1, by2 - by1), interpolation=cv2.INTER_LINEAR)[..., None]
                patch = cv2.resize(preds[idx_loc], (bx2 - bx1, by2 - by1), interpolation=cv2.INTER_LANCZOS4)
                fr = frames_bgr[k].copy()
                fr[by1:by2, bx1:bx2] = (patch * alpha + fr[by1:by2, bx1:bx2] * (1.0 - alpha)).astype(np.uint8)
                out_frames.append(fr)
        return out_frames

    idle_dir = OUTPUT / "idle"
    idle_dir.mkdir(exist_ok=True)
    idle_plan = {
        "fps": 50,
        "total_frames": 800,
        "segments": [
            {"id": "clean_fwd", "start": 0, "end": 400},
            {"id": "clean_bwd", "start": 400, "end": 800},
        ],
    }
    (OUTPUT / "idle-plan.json").write_text(json.dumps(idle_plan, indent=2), encoding="utf-8")

    if not (idle_dir / "complete.json").exists():
        idle25_f, idle25_c = load_25fps_clip("idle")
        fwd50_f, fwd50_c = upsample_25_to_50_rife(idle25_f[104:305], idle25_c[104:305], rife)
        fwd50_f, fwd50_c = fwd50_f[:-1], fwd50_c[:-1]
        idle50_f = fwd50_f + fwd50_f[-2:0:-1]
        idle50_c = fwd50_c + fwd50_c[-2:0:-1]
        mm_idle = np.lib.format.open_memmap(idle_dir / "frames.npy", mode="w+", dtype=np.uint8, shape=(800, 1920, 1080, 3))
        for idx, fr in enumerate(idle50_f):
            mm_idle[idx] = fr
        mm_idle.flush()
        del mm_idle, idle50_f, idle25_f, fwd50_f
        (idle_dir / "coords.json").write_text(json.dumps(idle50_c), encoding="utf-8")
        (idle_dir / "complete.json").write_text(json.dumps({"frames": 800}), encoding="utf-8")

    arrays = {"idle": np.load(idle_dir / "frames.npy", mmap_mode="r")}
    coords = {"idle": json.loads((idle_dir / "coords.json").read_text(encoding="utf-8"))}

    degrin_actions = {"welcome-wave", "goodbye-wave", "acknowledge-nod"}
    for item in config["clips"]:
        name = item["id"]
        dest = OUTPUT / name
        dest.mkdir(exist_ok=True)
        if not (dest / "complete.json").exists():
            f25, c25 = load_25fps_clip(name)
            corr = np.array(item["correction_Lab"], dtype=np.float32)
            f25_graded = [grade(fr, corr) for fr in f25]
            if name in degrin_actions:
                f25_graded = harmonize_closed_smile_batch(f25_graded, c25)
            f50, c50 = upsample_25_to_50_rife(f25_graded, c25, rife)
            mm_act = np.lib.format.open_memmap(dest / "frames.npy", mode="w+", dtype=np.uint8, shape=(len(f50), 1920, 1080, 3))
            for idx, fr in enumerate(f50):
                mm_act[idx] = fr
            mm_act.flush()
            del mm_act, f25, f25_graded, f50
            (dest / "coords.json").write_text(json.dumps(c50), encoding="utf-8")
            (dest / "complete.json").write_text(json.dumps({"frames": len(c50), "degrin": name in degrin_actions}), encoding="utf-8")
        arrays[name] = np.load(dest / "frames.npy", mmap_mode="r")
        coords[name] = json.loads((dest / "coords.json").read_text(encoding="utf-8"))

    del student, sil_whisp_t
    torch.cuda.empty_cache()

    n_idle = len(arrays["idle"])
    idle_descs = [descriptor(arrays["idle"][k]) for k in range(n_idle)]
    eye_dark = []
    for k in range(n_idle):
        y1, y2, x1, x2 = coords["idle"][k]
        roi = arrays["idle"][k][
            y1 + int(0.24 * (y2 - y1)) : y1 + int(0.42 * (y2 - y1)),
            x1 + int(0.18 * (x2 - x1)) : x1 + int(0.82 * (x2 - x1)),
        ]
        eye_dark.append(float((cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) < 75).mean()))
    med_eye = float(np.median(eye_dark))
    eye_open_ok = [all(eye_dark[(k + d) % n_idle] >= 0.80 * med_eye for d in range(-6, 7)) for k in range(n_idle)]

    anchors_set = {seg["end"] - 1 for seg in idle_plan["segments"]}
    for seg in idle_plan["segments"]:
        pos = seg["start"]
        while pos < seg["end"] - 1:
            hi = min(pos + 18, seg["end"] - 1)
            cands = [c for c in range(max(seg["start"], hi - 8), hi + 1) if eye_open_ok[c]]
            chosen = cands[-1] if cands else hi
            anchors_set.add(chosen)
            pos = chosen + 1
    anchors = sorted(anchors_set)
    idle_vel = lambda idx: idle_descs[(idx + 4) % n_idle] - idle_descs[idx]
    valid_ret_indices = [r for r in range(0, n_idle, 2) if eye_open_ok[r]]
    bridge_len = 20
    jobs = []
    plan = dict(version="rife-dit-v2", fps=50, bridge_frames=bridge_len, entries={}, returns={}, idle_joins={})

    for item in config["clips"]:
        name = item["id"]
        start_d = descriptor(arrays[name][0])
        start_v = descriptor(arrays[name][4]) - start_d
        plan["entries"][name] = []
        for anchor in anchors:
            cost = float(np.mean(np.abs(idle_descs[anchor] - start_d)) + 0.6 * np.mean(np.abs(idle_vel(anchor) - start_v)))
            entry = dict(idle_index=anchor, cost=cost)
            plan["entries"][name].append(entry)
            jobs.append((("idle", anchor), (name, 0), entry))

        end_d = descriptor(arrays[name][-1])
        end_v = end_d - descriptor(arrays[name][-5])
        best_ret = min(valid_ret_indices, key=lambda r: float(np.mean(np.abs(end_d - idle_descs[r])) + 0.6 * np.mean(np.abs(end_v - idle_vel(r)))))
        ret_record = dict(idle_index=int(best_ret))
        plan["returns"][name] = ret_record
        jobs.append(((name, len(arrays[name]) - 1), ("idle", int(best_ret)), ret_record))

    trans_dir = OUTPUT / "transitions"
    trans_dir.mkdir(exist_ok=True)
    total_trans_frames = len(jobs) * bridge_len
    full_mm = np.lib.format.open_memmap(trans_dir / "frames.npy", mode="w+", dtype=np.uint8, shape=(total_trans_frames, 1920, 1080, 3))
    boxes = []
    for number, (src, dst, rec) in enumerate(jobs):
        rec["start"] = number * bridge_len
        rec["end"] = (number + 1) * bridge_len
        first_bgr = arrays[src[0]][src[1]]
        last_bgr = arrays[dst[0]][dst[1]]
        first_box = np.array(coords[src[0]][src[1]], dtype=np.float32)
        last_box = np.array(coords[dst[0]][dst[1]], dtype=np.float32)
        for offset, (s_val, bf) in enumerate(rife.bridge_hermite(first_bgr, last_bgr, n_bridge=bridge_len)):
            box = np.rint(first_box * (1.0 - s_val) + last_box * s_val).astype(int)
            full_mm[number * bridge_len + offset] = bf
            boxes.append(box.tolist())
    full_mm.flush()
    del full_mm
    (trans_dir / "coords.json").write_text(json.dumps(boxes), encoding="utf-8")
    (OUTPUT / "transition-plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")

    summary = dict(
        version="rife-dit-v2",
        idle_frames=n_idle,
        anchor_count=len(anchors),
        bridge_count=len(jobs),
        bridge_frames=bridge_len,
        transition_frames=total_trans_frames,
        optimal_returns={k: v["idle_index"] for k, v in plan["returns"].items()},
        actions=[item["id"] for item in config["clips"]],
        elapsed_seconds=round(time.perf_counter() - t0, 2),
    )
    (OUTPUT / "complete.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("RIFE_DIT_V2_CACHE_COMPLETE", json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
