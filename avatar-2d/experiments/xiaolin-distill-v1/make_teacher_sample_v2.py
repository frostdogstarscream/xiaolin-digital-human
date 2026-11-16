"""Step 1 v2 (~16.28s, 407 frames @ 25fps) Offline Teacher with:
  1) Geometric Lip-Closure & Mouth-Corner Warp (cv2.remap driven by BiSeNet lip/teeth geometry,
     eliminating semi-transparent ghost teeth and mouth-corner jumps during open<->close transitions)
  2) Zero-lag hysteresis speech rhythm:
     - Intra-word stops (<=3f / 120ms): g = 1.0 (native consonant articulation)
     - Short clause breaths (4..13f / 160..520ms): g smoothly closes to 0.12 (lips gently closed,
       teeth covered, without snapping mouth corners out to studio smile for just 2 frames)
     - Full sentence pauses (>=14f / >=560ms & turn start/end): g smoothly closes 1.0 -> 0.0
       right from the end of phonation into Clean Base resting smile.
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
    ap.add_argument("--workspace", type=Path, default=Path(r"d:\Code\3D数字人"))
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--wav2lip-ckpt", type=Path, default=None)
    ap.add_argument("--batch-size", type=int, default=16)
    args, _ = ap.parse_known_args()
    return args


ARGS = parse_args()
WORKSPACE = ARGS.workspace.resolve()
AVATAR_ROOT = WORKSPACE / "avatar-2d"
MUSE_ROOT = WORKSPACE / "musetalk-eval"
VENDOR_ROOT = AVATAR_ROOT / "vendor" / "LiveTalking-c7269433a2b6ecebcd9342445d2ecc882c98b0da"
FFMPEG = WORKSPACE / "fay-ue4/runtime/fay-local/app/test/ovr_lipsync/ffmpeg/bin/ffmpeg.exe"
OUT_DIR = (ARGS.out_dir or (AVATAR_ROOT / "outputs" / "xiaolin-distill-v1")).resolve()
WAV2LIP_CKPT = (ARGS.wav2lip_ckpt or (AVATAR_ROOT / "models" / "wav2lip256.pth")).resolve()

sys.path.insert(0, str(AVATAR_ROOT / "tools"))
from windows_runtime import prepare_runtime
prepare_runtime()

os.environ.update(
    HF_HUB_OFFLINE="1",
    TRANSFORMERS_OFFLINE="1",
    HF_HUB_DISABLE_TELEMETRY="1",
)
sys.path.insert(0, str(VENDOR_ROOT))

import cv2
import numpy as np
import torch
from PIL import Image


def imwrite_unicode(path: Path, img: np.ndarray, ext: str = ".jpg", params=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(ext, img, params or [])
    if not ok:
        raise RuntimeError(f"Failed to encode image for {path}")
    buf.tofile(str(path))


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
            cmd,
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
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


def load_idle_frames(max_frame_needed: int):
    video_path = AVATAR_ROOT / "assets/presenter-v2-1080/prepared/idle.mp4"
    coords_path = AVATAR_ROOT / "runtime/presenter-v2-1080/avatars/idle/coords.json"
    coords = json.loads(coords_path.read_text(encoding="utf-8"))

    cap = cv2.VideoCapture(str(video_path))
    frames = []
    idx = 0
    while idx <= max_frame_needed:
        ok, frame = cap.read()
        if not ok:
            break
        frames.append(frame)
        idx += 1
    cap.release()
    if len(frames) <= max_frame_needed:
        raise RuntimeError(f"Expected >={max_frame_needed+1} frames from {video_path}, got {len(frames)}")
    return frames, coords


def load_wav_16k(audio_path: Path) -> np.ndarray:
    with wave.open(str(audio_path), "rb") as wf:
        sr = wf.getframerate()
        ch = wf.getnchannels()
        sw = wf.getsampwidth()
        raw = wf.readframes(wf.getnframes())
    if sr != 16000 or ch != 1 or sw != 2:
        raise RuntimeError(f"Expected 16kHz mono s16le wav, got sr={sr}, ch={ch}, sw={sw}")
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


def smoothstep(edge0: float, edge1: float, x: float) -> float:
    t = max(0.0, min(1.0, (x - edge0) / max(1e-6, edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)


def compute_speech_rhythm_curves(audio_padded: np.ndarray, n_frames: int, fps: int = 25):
    """Returns:
      open_curve[i] in [0, 1]: physical jaw/lip openness (1=speaking, 0=lips closed)
      smile_curve[i] in [0, 1]: resting-smile corner & texture handoff (1=speaking poise, 0=resting smile)
      rms[i]: per-frame RMS
    Distinguishes:
      - Intra-word consonant stops (<=3 silent frames): open=1, smile=1
      - Short clause breath pauses (4..13 silent frames): open closes smoothly to 0.08 (hiding idle teeth)
        while smile stays >=0.75 so mouth corners do NOT snap wide and back in 0.4s!
      - Long sentence pauses (>=14 silent frames & leading/trailing silence): both open and smile
        close smoothly to 0.0 right as phonation ends (zero post-speech hang!).
    """
    spf = 16000 // fps
    rms = [
        float(np.sqrt(np.mean(audio_padded[i * spf : (i + 1) * spf] ** 2) + 1e-12))
        for i in range(n_frames)
    ]
    # Hysteresis voiced/fricative activity (eliminates breath noise blips)
    voiced = np.zeros(n_frames, dtype=np.int32)
    state = 0
    for i, r in enumerate(rms):
        if state == 0 and r >= 0.012:
            state = 1
        elif state == 1 and r < 0.005:
            state = 0
        voiced[i] = state

    # Remove isolated 1-frame noise blips
    for i in range(1, n_frames - 1):
        if voiced[i] == 1 and voiced[i - 1] == 0 and voiced[i + 1] == 0:
            voiced[i] = 0

    # Classify silent runs
    open_target = voiced.astype(np.float32).copy()
    smile_target = voiced.astype(np.float32).copy()

    i = 0
    while i < n_frames:
        if voiced[i] == 1:
            i += 1
            continue
        j = i
        while j < n_frames and voiced[j] == 0:
            j += 1
        run_len = j - i
        is_boundary = (i == 0) or (j == n_frames)
        if not is_boundary and run_len <= 3:
            # Intra-word stop consonant: keep full speaking state
            open_target[i:j] = 1.0
            smile_target[i:j] = 1.0
        elif not is_boundary and run_len <= 13:
            # Short breath pause between clauses: gently close lips (hide static teeth),
            # but keep speaking mouth-corner poise so there is no rapid smile ping-pong!
            open_target[i:j] = 0.06
            smile_target[i:j] = 0.80
        else:
            # True sentence pause (>=0.56s) or leading/trailing silence: full return to Clean Base
            open_target[i:j] = 0.0
            smile_target[i:j] = 0.0
        i = j

    # Zero-lag asymmetric ramp:
    # - Before speech starts: pre-open 3 frames (120ms) ahead like natural pre-phonation breath
    # - After speech ends: start closing IMMEDIATELY on frame 0 of silence over 5 frames (200ms)
    def shape_envelope(target: np.ndarray, pre_frames: int, release_frames: int) -> np.ndarray:
        out = np.zeros_like(target)
        for idx in range(n_frames):
            val = target[idx]
            # Look ahead up to pre_frames for upcoming speech onset
            for k in range(1, pre_frames + 1):
                if idx + k < n_frames and target[idx + k] > val:
                    frac = 1.0 - (k / (pre_frames + 1.0))
                    val = max(val, target[idx] + (target[idx + k] - target[idx]) * smoothstep(0.0, 1.0, frac))
            # Look back up to release_frames for smooth decay after speech offset
            for k in range(1, release_frames + 1):
                if idx - k >= 0 and target[idx - k] > val:
                    frac = 1.0 - (k / (release_frames + 1.0))
                    val = max(val, target[idx] + (target[idx - k] - target[idx]) * smoothstep(0.0, 1.0, frac))
            out[idx] = val
        return out

    open_curve = shape_envelope(open_target, pre_frames=3, release_frames=5)
    smile_curve = shape_envelope(smile_target, pre_frames=3, release_frames=6)
    return open_curve, smile_curve, rms


def parse_full_batch(pil_images: list[Image.Image], parser):
    """Batched GPU BiSeNet returning (jaw_masks, mouth_masks, raw_parsings_resized)."""
    orig_sizes = [im.size for im in pil_images]
    tensors = [parser.preprocess(im.resize((512, 512), Image.BILINEAR)) for im in pil_images]
    batch = torch.stack(tensors, dim=0).cuda()
    with torch.inference_mode():
        outs = parser.net(batch)[0]
        parsings = outs.argmax(1).cpu().numpy().astype(np.uint8)
    jaw_results, mouth_results, seg_results = [], [], []
    for k, parsing in enumerate(parsings):
        face_region = (parsing == 1).astype(np.uint8) * 255
        original_dilated = cv2.dilate(face_region, parser.kernel, iterations=1)
        eroded = cv2.erode(original_dilated, parser.cheek_kernel, iterations=2)
        face_region = cv2.bitwise_and(eroded, parser.cheek_mask)
        face_region = cv2.bitwise_or(face_region, cv2.bitwise_and(original_dilated, ~parser.cheek_mask))
        mask512 = np.zeros((512, 512), dtype=np.uint8)
        mask512[(face_region == 255) & (parsing != 10)] = 255
        mask512[np.isin(parsing, [11, 12, 13])] = 255

        mouth512 = (np.isin(parsing, [11, 12, 13]).astype(np.uint8)) * 255
        w_o, h_o = orig_sizes[k]
        jaw_results.append(cv2.resize(mask512, (w_o, h_o), interpolation=cv2.INTER_LINEAR))
        mouth_results.append(cv2.resize(mouth512, (w_o, h_o), interpolation=cv2.INTER_LINEAR))
        seg_results.append(cv2.resize(parsing, (w_o, h_o), interpolation=cv2.INTER_NEAREST))
    return jaw_results, mouth_results, seg_results


def warp_speaking_mouth_geometry(
    pred_rgb_np: np.ndarray,
    src_rgb_np: np.ndarray,
    seg_pred: np.ndarray,
    seg_src: np.ndarray,
    open_g: float,
    smile_g: float,
) -> np.ndarray:
    """Physically closes the speaking lower lip & jaw upward over the teeth as open_g -> 0,
    and smoothly aligns mouth width/corners toward the resting smile as smile_g -> 0.
    Eliminates semi-transparent ghost teeth and double-lip dissolve artifacts.
    """
    if open_g >= 0.995 and smile_g >= 0.995:
        return pred_rgb_np

    h, w = pred_rgb_np.shape[:2]
    m_src = np.isin(seg_src, [11, 12, 13])
    m_pred = np.isin(seg_pred, [11, 12, 13])
    if not m_src.any() or not m_pred.any():
        return pred_rgb_np

    ys_s, xs_s = np.where(m_src)
    ys_p, xs_p = np.where(m_pred)

    xL_s, xR_s = np.percentile(xs_s, [3, 97])
    cx_s = 0.5 * (xL_s + xR_s)
    w_s = max(20.0, float(xR_s - xL_s))
    ym_s = float(np.median(ys_s))
    # Corner heights in resting smile vs speaking
    y_corner_s = float(np.median(ys_s[(xs_s <= xL_s + 6) | (xs_s >= xR_s - 6)])) if np.any((xs_s <= xL_s + 6) | (xs_s >= xR_s - 6)) else ym_s

    xL_p, xR_p = np.percentile(xs_p, [3, 97])
    cx_p = 0.5 * (xL_p + xR_p)
    w_p = max(20.0, float(xR_p - xL_p))
    ym_p = float(np.median(ys_p))
    y_corner_p = float(np.median(ys_p[(xs_p <= xL_p + 6) | (xs_p >= xR_p - 6)])) if np.any((xs_p <= xL_p + 6) | (xs_p >= xR_p - 6)) else ym_p

    # Measure inner oral/teeth vertical gap in pred (class 11 = inner mouth/teeth)
    inner = (seg_pred == 11) & (np.abs(np.arange(w)[None, :] - cx_p) <= 0.32 * w_p)
    if inner.sum() >= 6:
        yi, _ = np.where(inner)
        y_top_inner = float(np.percentile(yi, 8))
        y_bot_inner = float(np.percentile(yi, 92))
        gap_h = max(0.0, y_bot_inner - y_top_inner)
    else:
        # Even if class 11 wasn't explicitly labeled, measure upper-vs-lower lip separation
        u12 = seg_pred == 12
        l13 = seg_pred == 13
        if u12.any() and l13.any():
            y_top_inner = float(np.percentile(np.where(u12)[0], 85))
            y_bot_inner = float(np.percentile(np.where(l13)[0], 15))
            gap_h = max(0.0, y_bot_inner - y_top_inner)
        else:
            y_top_inner = ym_p
            gap_h = 0.0

    close_frac = 1.0 - float(open_g)      # 0 = fully open, 1 = fully closed
    align_frac = 1.0 - float(smile_g)     # 0 = speaking corners, 1 = resting smile corners

    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    map_x = xx.copy()
    map_y = yy.copy()

    # 1) Upward lower-lip & chin closure over the teeth gap (positive map_y shift samples lower lip upward)
    if close_frac > 1e-3 and gap_h > 0.5:
        # Horizontal falloff centered on mouth (includes full mouth + jaw width)
        wx = np.exp(-0.5 * ((xx - cx_p) / (0.68 * max(w_p, w_s))) ** 2)
        # Vertical step starting cleanly at y_top_inner (upper lip stays fixed; lower lip rises by close_frac*gap_h)
        # Smooth ramp over 2.5px at lip seam, then smooth decay down across chin/jaw (sigma=48px) so neck stays fixed
        seam_ramp = np.clip((yy - (y_top_inner - 1.0)) / 3.0, 0.0, 1.0)
        jaw_decay = np.exp(-0.5 * (np.maximum(0.0, yy - (y_top_inner + gap_h + 14.0)) / 42.0) ** 2)
        # Also pull upper lip down subtly (15%) while lower lip + jaw rise up (85%) like real human orbicularis oris!
        upper_pull = -0.15 * close_frac * gap_h * np.exp(-0.5 * ((yy - (y_top_inner - 3.0)) / 6.0) ** 2) * wx
        lower_lift = 0.92 * close_frac * gap_h * seam_ramp * jaw_decay * wx
        map_y = map_y + upper_pull + lower_lift

    # 2) Smooth mouth-width & corner-lift alignment toward resting smile as align_frac -> 1
    if align_frac > 1e-3:
        w_cur = w_p + align_frac * (w_s - w_p)
        cx_cur = cx_p + align_frac * (cx_s - cx_p)
        ym_cur = ym_p + align_frac * (ym_s - ym_p)
        env = np.exp(-0.5 * (((xx - cx_cur) / (0.72 * w_s)) ** 2 + ((yy - ym_cur) / (0.55 * w_s)) ** 2))
        scale_x = w_p / max(16.0, w_cur)
        dx = ((xx - cx_cur) * scale_x + cx_p - xx) * env
        # Corner vertical lift (strongest near |x - cx| ~ 0.5*w_cur)
        corner_weight = np.clip(np.abs(xx - cx_cur) / (0.45 * w_cur), 0.0, 1.2) * env
        dy_corner = align_frac * ((y_corner_p - ym_p) - (y_corner_s - ym_s))
        dy_center = align_frac * (ym_p - ym_s) * env
        map_x = map_x + dx
        map_y = map_y + dy_center + dy_corner * corner_weight

    warped_pred = cv2.remap(pred_rgb_np, map_x, map_y, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

    # 3) Appearance handoff ONLY when mouth is already mostly closed & corners aligned (align_frac > 0.55 & open_g < 0.35)
    # Zero pixel cross-fade while teeth are open -> zero ghost teeth!
    if smile_g < 0.45 and open_g < 0.35:
        tex_w = smoothstep(0.0, 0.40, max(open_g, smile_g * 0.85))
        warped_pred = (warped_pred.astype(np.float32) * tex_w + src_rgb_np.astype(np.float32) * (1.0 - tex_w)).clip(0, 255).astype(np.uint8)

    return warped_pred


def blend_dynamic_jaw_v2(
    body_bgr: np.ndarray,
    face_large_pred: Image.Image,
    face_large_src: Image.Image,
    mask_src: np.ndarray,
    mask_pred: np.ndarray,
    mouth_mask_pred: np.ndarray,
    seg_src: np.ndarray,
    seg_pred: np.ndarray,
    face_box: list[int],
    crop_box: list[int],
    open_g: float,
    smile_g: float,
    upper_boundary_ratio: float = 0.50,
) -> np.ndarray:
    if open_g <= 1e-3 and smile_g <= 1e-3:
        return body_bgr.copy()

    body_rgb = Image.fromarray(body_bgr[:, :, ::-1])
    x, y, x1, y1 = face_box
    x_s, y_s, x_e, y_e = crop_box
    ori_w, ori_h = x_e - x_s, y_e - y_s

    # Subtle clarity unsharp mask strictly inside mouth/teeth interior
    pred_np = np.array(face_large_pred, dtype=np.float32)
    blurred_pred = cv2.GaussianBlur(pred_np, (0, 0), 1.0)
    sharpened = np.clip(pred_np + 0.28 * (pred_np - blurred_pred), 0, 255)
    m_alpha = (cv2.GaussianBlur(mouth_mask_pred, (7, 7), 0).astype(np.float32) / 255.0)[..., None]
    pred_sharp = (sharpened * m_alpha + pred_np * (1.0 - m_alpha)).astype(np.uint8)

    src_np = np.array(face_large_src, dtype=np.uint8)
    warped_np = warp_speaking_mouth_geometry(pred_sharp, src_np, seg_pred, seg_src, open_g=open_g, smile_g=smile_g)

    mask_union = Image.fromarray(np.maximum(mask_src, mask_pred))
    mask_small = mask_union.crop((x - x_s, y - y_s, x1 - x_s, y1 - y_s))
    mask_full = Image.new("L", (ori_w, ori_h), 0)
    mask_full.paste(mask_small, (x - x_s, y - y_s, x1 - x_s, y1 - y_s))

    top_boundary = int(ori_h * upper_boundary_ratio)
    modified_mask = Image.new("L", (ori_w, ori_h), 0)
    modified_mask.paste(mask_full.crop((0, top_boundary, ori_w, ori_h)), (0, top_boundary))

    blur_k = int(0.08 * ori_w // 2 * 2) + 1
    mask_arr = cv2.GaussianBlur(np.array(modified_mask), (blur_k, blur_k), 0)

    box_mask = np.zeros((ori_h, ori_w), dtype=np.float32)
    bx0, by0 = max(0, x - x_s), max(0, y - y_s)
    bx1, by1 = min(ori_w, x1 - x_s), min(ori_h, y1 - y_s)
    bh, bw = by1 - by0, bx1 - bx0
    yy, xx = np.mgrid[0:bh, 0:bw]
    edge = np.minimum(np.minimum(xx, bw - 1 - xx), np.minimum(yy, bh - 1 - yy))
    box_mask[by0:by1, bx0:bx1] = np.clip(edge / 10.0, 0.0, 1.0)

    # Note: mask_arr stays at 1.0 during geometric closure (no ghost alpha dissolve!),
    # and only tapers to 0 in the final closed tail (<0.20) when warped_np already matches src_np!
    paste_gate = smoothstep(0.0, 0.18, max(open_g, smile_g))
    mask_arr = (mask_arr.astype(np.float32) * box_mask * paste_gate).clip(0, 255).astype(np.uint8)

    body_rgb.paste(Image.fromarray(warped_np), crop_box[:2], Image.fromarray(mask_arr))
    return np.array(body_rgb)[:, :, ::-1]


def make_label_banner(img: np.ndarray, title: str, subtitle: str, accent_bgr=(80, 220, 120)) -> np.ndarray:
    out = img.copy()
    overlay = out.copy()
    cv2.rectangle(overlay, (0, 0), (out.shape[1], 74), (18, 18, 22), -1)
    cv2.addWeighted(overlay, 0.72, out, 0.28, 0, out)
    cv2.rectangle(out, (0, 0), (6, 74), accent_bgr, -1)
    cv2.putText(out, title, (18, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.78, accent_bgr, 2, cv2.LINE_AA)
    cv2.putText(out, subtitle, (18, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (230, 230, 235), 1, cv2.LINE_AA)
    return out


def verify_mp4(path: Path, expected_frames: int):
    cap = cv2.VideoCapture(str(path))
    cnt = 0
    while True:
        ok, _ = cap.read()
        if not ok:
            break
        cnt += 1
    cap.release()
    if cnt != expected_frames:
        raise RuntimeError(f"Decoded frame count mismatch for {path}: got {cnt}, expected {expected_frames}")
    return cnt


def main():
    t_start = time.perf_counter()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    audio_path = MUSE_ROOT / "fixtures/long.wav"
    audio_16k = load_wav_16k(audio_path)
    fps = 25
    n_frames = math.ceil(len(audio_16k) / (16000 // fps))
    audio_padded = np.pad(audio_16k, (0, n_frames * 640 - len(audio_16k)))
    open_curve, smile_curve, rms_per_frame = compute_speech_rhythm_curves(audio_padded, n_frames, fps=fps)

    fwd = list(range(104, 305))
    rev_len = n_frames - len(fwd)
    seq_indices = fwd + list(range(303, 303 - rev_len, -1))
    assert len(seq_indices) == n_frames

    max_needed = max(max(seq_indices), n_frames - 1)
    frames_src, coords = load_idle_frames(max_needed)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32
    batch_size = ARGS.batch_size
    print(f"GPU={torch.cuda.get_device_name(0) if device=='cuda' else 'cpu'}, frames={n_frames}", flush=True)

    # --- 1. Wav2Lip256 Baseline ---
    from avatars.wav2lip_avatar import Wav2Lip
    from avatars.wav2lip import audio as wav2lip_audio

    w2l = Wav2Lip()
    ckpt = torch.load(WAV2LIP_CKPT, map_location="cpu", weights_only=True)
    w2l.load_state_dict({k.removeprefix("module."): v for k, v in ckpt["state_dict"].items()})
    w2l = w2l.to(device=device, dtype=dtype).eval()

    mel = wav2lip_audio.melspectrogram(np.pad(audio_padded, (0, 6400)))
    mel_chunks = [mel[:, min(int(i * 80.0 / 25.0), mel.shape[1] - 16) : min(int(i * 80.0 / 25.0), mel.shape[1] - 16) + 16] for i in range(n_frames)]

    w2l_preds_256 = []
    with torch.inference_mode():
        for b0 in range(0, n_frames, batch_size):
            b1 = min(n_frames, b0 + batch_size)
            crops = [cv2.resize(frames_src[i][coords[i][0]:coords[i][1], coords[i][2]:coords[i][3]], (256, 256)) for i in range(b0, b1)]
            faces = np.asarray(crops)
            masked = faces.copy()
            masked[:, 128:] = 0
            inp = np.concatenate([masked, faces], axis=3).astype(np.float32) / 255.0
            x = torch.from_numpy(inp.transpose(0, 3, 1, 2).copy()).to(device=device, dtype=dtype)
            a = torch.from_numpy(np.asarray(mel_chunks[b0:b1], dtype=np.float32)[:, None].copy()).to(device=device, dtype=dtype)
            preds = (w2l(a, x).float().cpu().numpy().transpose(0, 2, 3, 1) * 255.0).clip(0, 255).astype(np.uint8)
            w2l_preds_256.extend(list(preds))
    del w2l
    torch.cuda.empty_cache()

    # --- 2. MuseTalk 1.5 Teacher + Geometric Lip Closure Warp ---
    teacher_full_path = OUT_DIR / "sample-teacher-v2-full.mp4"
    comp_path = OUT_DIR / "sample-comparison-wav2lip-vs-teacher-v2.mp4"

    w_teacher = FFmpegVideoWriter(teacher_full_path, 1080, 1920, fps, audio_path)
    w_comp = FFmpegVideoWriter(comp_path, 1080, 960, fps, audio_path)

    diag_indices = set(range(68, 88)) | set(range(123, 147))
    diag_saved = {}

    prev_cwd = Path.cwd()
    os.chdir(MUSE_ROOT)
    try:
        from avatars.musetalk.utils.utils import load_all_model
        from avatars.musetalk.whisper.audio2feature import Audio2Feature
        from avatars.musetalk.utils.face_parsing import FaceParsing
        from avatars.musetalk.utils.blending import get_crop_box

        vae, unet, pe = load_all_model(device=torch.device(device))
        vae.vae = vae.vae.to(device=device, dtype=dtype)
        unet.model = unet.model.to(device=device, dtype=dtype).eval()
        pe = pe.to(device=device, dtype=dtype)
        audio_processor = Audio2Feature(model_path=str(MUSE_ROOT / "models/whisper"))
        parser = FaceParsing(left_cheek_width=90, right_cheek_width=90)
        timesteps = torch.tensor([0], device=device)

        padded_audio = np.pad(audio_padded, (3200, 3200))
        whisper_feat = audio_processor.audio2feat(padded_audio)
        whisper_chunks = [whisper_feat[10 + i * 2 - 4 : 10 + i * 2 + 6].reshape(50, 384) for i in range(n_frames)]

        unique_indices = sorted(set(seq_indices))
        latent_map, box_map, crop_box_map, src_large_map, src_mask_map, src_seg_map = {}, {}, {}, {}, {}, {}

        with torch.inference_mode():
            for u0 in range(0, len(unique_indices), batch_size):
                u_slice = unique_indices[u0 : u0 + batch_size]
                pil_batch = []
                for src_idx in u_slice:
                    frame = frames_src[src_idx]
                    y1, y2, x1, x2 = coords[src_idx]
                    box = [x1, y1, x2, min(y2 + 15, frame.shape[0])]
                    cbox, _ = get_crop_box(box, 1.5)
                    crop256 = cv2.resize(frame[box[1]:box[3], box[0]:box[2]], (256, 256), interpolation=cv2.INTER_LANCZOS4)
                    latent_map[src_idx] = vae.get_latents_for_unet(crop256).squeeze(0).cpu()
                    box_map[src_idx] = box
                    crop_box_map[src_idx] = cbox
                    fl_src = Image.fromarray(frame[:, :, ::-1]).crop(cbox)
                    src_large_map[src_idx] = fl_src
                    pil_batch.append(fl_src)
                masks_b, _, segs_b = parse_full_batch(pil_batch, parser)
                for src_idx, m_src, s_src in zip(u_slice, masks_b, segs_b):
                    src_mask_map[src_idx] = m_src
                    src_seg_map[src_idx] = s_src

        with torch.inference_mode():
            for b0 in range(0, n_frames, batch_size):
                b1 = min(n_frames, b0 + batch_size)
                lat_batch = torch.stack([latent_map[seq_indices[i]] for i in range(b0, b1)]).to(device=device, dtype=dtype)
                aud_batch = pe(torch.as_tensor(np.stack(whisper_chunks[b0:b1]), device=device, dtype=dtype))
                pred_lat = unet.model(lat_batch, timesteps, encoder_hidden_states=aud_batch).sample
                decoded = vae.decode_latents(pred_lat)

                pred_large_pils = []
                for k, i in enumerate(range(b0, b1)):
                    src_idx = seq_indices[i]
                    x, y, x1, y1 = box_map[src_idx]
                    x_s, y_s, _, _ = crop_box_map[src_idx]
                    face_resized = cv2.resize(decoded[k], (x1 - x, y1 - y), interpolation=cv2.INTER_LANCZOS4)
                    fl_pred = src_large_map[src_idx].copy()
                    fl_pred.paste(Image.fromarray(face_resized[:, :, ::-1]), (x - x_s, y - y_s, x1 - x_s, y1 - y_s))
                    pred_large_pils.append(fl_pred)

                pred_jaw_masks, pred_mouth_masks, pred_segs = parse_full_batch(pred_large_pils, parser)

                for k, i in enumerate(range(b0, b1)):
                    fb = frames_src[i].copy()
                    by1, by2, bx1, bx2 = coords[i]
                    bh, bw = by2 - by1, bx2 - bx1
                    bpatch = cv2.resize(w2l_preds_256[i], (bw, bh), interpolation=cv2.INTER_LINEAR)
                    yy, xx = np.mgrid[0:bh, 0:bw]
                    edge = np.minimum(np.minimum(xx, bw - 1 - xx), np.minimum(yy, bh - 1 - yy))
                    alpha = (np.clip((yy / bh - 0.42) / 0.18, 0, 1) * np.clip(edge / 6.0, 0, 1))[..., None]
                    fb[by1:by2, bx1:bx2] = (bpatch * alpha + fb[by1:by2, bx1:bx2] * (1.0 - alpha)).astype(np.uint8)

                    src_idx = seq_indices[i]
                    ft = blend_dynamic_jaw_v2(
                        frames_src[src_idx],
                        pred_large_pils[k],
                        src_large_map[src_idx],
                        src_mask_map[src_idx],
                        pred_jaw_masks[k],
                        pred_mouth_masks[k],
                        src_seg_map[src_idx],
                        pred_segs[k],
                        box_map[src_idx],
                        crop_box_map[src_idx],
                        open_g=float(open_curve[i]),
                        smile_g=float(smile_curve[i]),
                        upper_boundary_ratio=0.50,
                    )

                    w_teacher.write(ft)
                    panel_b = make_label_banner(
                        fb[40:1000, 270:810],
                        "Current Online (Wav2Lip256)",
                        f"Original idle base | t={i/fps:.2f}s (f={i})",
                        accent_bgr=(70, 110, 245),
                    )
                    panel_t = make_label_banner(
                        ft[40:1000, 270:810],
                        "Scheme 1 Teacher v2 (Geo-Close)",
                        f"Geometric lip closure + breath rhythm | t={i/fps:.2f}s",
                        accent_bgr=(80, 215, 110),
                    )
                    w_comp.write(np.hstack([panel_b, panel_t]))

                    if i in diag_indices:
                        diag_saved[i] = ft[210:380, 465:635].copy()
    finally:
        os.chdir(prev_cwd)
        w_teacher.close()
        w_comp.close()

    c1 = verify_mp4(teacher_full_path, n_frames)
    c2 = verify_mp4(comp_path, n_frames)

    def make_strip(indices):
        tiles = []
        for idx in indices:
            c = cv2.resize(diag_saved[idx], (180, 180), interpolation=cv2.INTER_CUBIC)
            cv2.rectangle(c, (0, 0), (180, 28), (20, 20, 24), -1)
            cv2.putText(
                c,
                f"f={idx} o={open_curve[idx]:.2f} s={smile_curve[idx]:.2f}",
                (4, 19),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.38,
                (90, 230, 120),
                1,
                cv2.LINE_AA,
            )
            tiles.append(c)
        return np.hstack(tiles)

    diag_img = np.vstack([
        make_strip(range(70, 78)),
        make_strip(range(78, 86)),
        make_strip(range(123, 131)),
        make_strip(range(131, 139)),
        make_strip(range(139, 147)),
    ])
    diag_path = OUT_DIR / "transition-diagnosis-v2.jpg"
    imwrite_unicode(diag_path, diag_img, ".jpg", [cv2.IMWRITE_JPEG_QUALITY, 95])

    print(
        "STEP1_V2_COMPLETE",
        json.dumps(
            {
                "wall_seconds": round(time.perf_counter() - t_start, 2),
                "verified_frames": {"teacher_v2": c1, "comp_v2": c2},
                "diag": str(diag_path),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
