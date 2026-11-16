"""Generate Step 1 (~16.28s, 407 frames @ 25fps) offline high-precision Teacher sample
vs current Wav2Lip256 baseline on Xiaolin's existing presenter-v2-1080 idle clip (Method A).
Includes:
  1) Lively open-eyed closed-mouth base selection (idle[104..304] ping-pong)
  2) Batched GPU BiSeNet dynamic jaw union mask (source U predicted jaw)
  3) Smooth inter-sentence speech-presence gate (200ms attack/release, preserves intra-word stops)
  4) Gentle mouth-interior-only clarity refinement to counteract SD-VAE 256px softening
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
    return ap.parse_args()


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


def compute_speech_gate(audio_padded: np.ndarray, n_frames: int, fps: int = 25) -> tuple[np.ndarray, list[float]]:
    """Compute smooth inter-sentence speech presence envelope in [0, 1].
    Keeps gate=1.0 across short intra-sentence consonant closures (<240ms) while
    smoothly returning to 0.0 (natural closed-mouth smile) during true pauses.
    """
    spf = 16000 // fps
    rms = [
        float(np.sqrt(np.mean(audio_padded[i * spf : (i + 1) * spf] ** 2) + 1e-12))
        for i in range(n_frames)
    ]
    active = np.array([1.0 if r > 0.0035 else 0.0 for r in rms], dtype=np.float32)
    # Dilate 3 frames left (120ms pre-open) and 4 frames right (160ms hold across stops)
    dilated = np.zeros_like(active)
    for i in range(n_frames):
        lo = max(0, i - 4)
        hi = min(n_frames, i + 4)
        dilated[i] = float(np.max(active[lo:hi]))
    # Smooth 5-frame Hann window (~200ms smooth ramp)
    win = np.hanning(7)[1:-1]
    win = win / win.sum()
    smoothed = np.convolve(np.pad(dilated, (2, 2), mode="edge"), win, mode="valid")
    return np.clip(smoothed, 0.0, 1.0), rms


def parse_jaw_and_mouth_masks_batch(pil_images: list[Image.Image], parser) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """Batched GPU BiSeNet parsing returning (jaw_masks, mouth_interior_masks)."""
    orig_sizes = [im.size for im in pil_images]
    tensors = [parser.preprocess(im.resize((512, 512), Image.BILINEAR)) for im in pil_images]
    batch = torch.stack(tensors, dim=0).cuda()
    with torch.inference_mode():
        outs = parser.net(batch)[0]
        parsings = outs.argmax(1).cpu().numpy()
    jaw_results = []
    mouth_results = []
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
    return jaw_results, mouth_results


def blend_dynamic_jaw_with_masks(
    body_bgr: np.ndarray,
    face_large_pred: Image.Image,
    mask_src: np.ndarray,
    mask_pred: np.ndarray,
    mouth_mask_pred: np.ndarray,
    face_box: list[int],
    crop_box: list[int],
    speech_gate: float = 1.0,
    upper_boundary_ratio: float = 0.50,
) -> np.ndarray:
    if speech_gate <= 1e-3:
        return body_bgr.copy()

    body_rgb = Image.fromarray(body_bgr[:, :, ::-1])
    x, y, x1, y1 = face_box
    x_s, y_s, x_e, y_e = crop_box
    ori_w, ori_h = x_e - x_s, y_e - y_s

    # Subtle clarity unsharp mask strictly inside mouth/teeth region (counteracts 256px VAE softness)
    pred_np = np.array(face_large_pred, dtype=np.float32)
    blurred_pred = cv2.GaussianBlur(pred_np, (0, 0), 1.0)
    sharpened = np.clip(pred_np + 0.28 * (pred_np - blurred_pred), 0, 255)
    m_alpha = (cv2.GaussianBlur(mouth_mask_pred, (7, 7), 0).astype(np.float32) / 255.0)[..., None]
    pred_refined = Image.fromarray((sharpened * m_alpha + pred_np * (1.0 - m_alpha)).astype(np.uint8))

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
    mask_arr = (mask_arr.astype(np.float32) * box_mask * float(speech_gate)).clip(0, 255).astype(np.uint8)

    body_rgb.paste(pred_refined, crop_box[:2], Image.fromarray(mask_arr))
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
    n_frames = math.ceil(len(audio_16k) / (16000 // fps))  # 407 frames = 16.28s
    audio_padded = np.pad(audio_16k, (0, n_frames * 640 - len(audio_16k)))
    speech_gates, rms_per_frame = compute_speech_gate(audio_padded, n_frames, fps=fps)

    # Lively bright open-eyed closed-mouth range: 104..304 (201f) + 303..98 (206f) = 407f
    fwd = list(range(104, 305))
    rev_len = n_frames - len(fwd)
    seq_indices = fwd + list(range(303, 303 - rev_len, -1))
    assert len(seq_indices) == n_frames, (len(seq_indices), n_frames)

    max_needed = max(max(seq_indices), n_frames - 1)
    frames_src, coords = load_idle_frames(max_needed)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32
    batch_size = ARGS.batch_size
    print(f"GPU={torch.cuda.get_device_name(0) if device=='cuda' else 'cpu'}, dtype={dtype}, frames={n_frames}", flush=True)

    # --- 1. Wav2Lip256 Baseline ---
    from avatars.wav2lip_avatar import Wav2Lip
    from avatars.wav2lip import audio as wav2lip_audio

    t0 = time.perf_counter()
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
    print(f"[1/3] Wav2Lip256 predictions done in {time.perf_counter() - t0:.2f}s", flush=True)

    # --- 2. MuseTalk 1.5 Teacher + Dynamic Jaw + Speech Gate ---
    teacher_full_path = OUT_DIR / "sample-teacher-v1-full.mp4"
    baseline_full_path = OUT_DIR / "sample-baseline-wav2lip-full.mp4"
    comp_path = OUT_DIR / "sample-comparison-wav2lip-vs-teacher.mp4"

    w_teacher = FFmpegVideoWriter(teacher_full_path, 1080, 1920, fps, audio_path)
    w_base = FFmpegVideoWriter(baseline_full_path, 1080, 1920, fps, audio_path)
    w_comp = FFmpegVideoWriter(comp_path, 1080, 960, fps, audio_path)

    probe_frames = {2, 18, 24, 42, 78, 128, 235, 315}
    probe_saved = {}

    t1 = time.perf_counter()
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
        latent_map = {}
        box_map = {}
        crop_box_map = {}
        src_large_map = {}
        src_mask_map = {}

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
                    body_rgb = Image.fromarray(frame[:, :, ::-1])
                    fl_src = body_rgb.crop(cbox)
                    src_large_map[src_idx] = fl_src
                    pil_batch.append(fl_src)
                masks_b, _ = parse_jaw_and_mouth_masks_batch(pil_batch, parser)
                for src_idx, m_src in zip(u_slice, masks_b):
                    src_mask_map[src_idx] = m_src

        print(f"[2/3] Prepared {len(unique_indices)} base latents + jaw masks in {time.perf_counter() - t1:.2f}s", flush=True)

        t2 = time.perf_counter()
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

                pred_jaw_masks, pred_mouth_masks = parse_jaw_and_mouth_masks_batch(pred_large_pils, parser)

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
                    ft = blend_dynamic_jaw_with_masks(
                        frames_src[src_idx],
                        pred_large_pils[k],
                        src_mask_map[src_idx],
                        pred_jaw_masks[k],
                        pred_mouth_masks[k],
                        box_map[src_idx],
                        crop_box_map[src_idx],
                        speech_gate=float(speech_gates[i]),
                        upper_boundary_ratio=0.50,
                    )

                    w_base.write(fb)
                    w_teacher.write(ft)

                    panel_b = make_label_banner(
                        fb[40:1000, 270:810],
                        "Current Online (Wav2Lip256)",
                        f"Original idle base | t={i/fps:.2f}s (f={i})",
                        accent_bgr=(70, 110, 245),
                    )
                    panel_t = make_label_banner(
                        ft[40:1000, 270:810],
                        "New Offline Teacher (Scheme 1)",
                        f"Clean base + Dynamic Jaw | t={i/fps:.2f}s",
                        accent_bgr=(80, 215, 110),
                    )
                    w_comp.write(np.hstack([panel_b, panel_t]))

                    if i in probe_frames:
                        y0, y1_c, x0, x1_c = 120, 410, 410, 700
                        probe_saved[i] = (
                            frames_src[src_idx][y0:y1_c, x0:x1_c].copy(),
                            fb[y0:y1_c, x0:x1_c].copy(),
                            ft[y0:y1_c, x0:x1_c].copy(),
                        )

        print(f"[3/3] Teacher inference + streaming MP4 encode done in {time.perf_counter() - t2:.2f}s", flush=True)
    finally:
        os.chdir(prev_cwd)
        w_teacher.close()
        w_base.close()
        w_comp.close()

    c1 = verify_mp4(teacher_full_path, n_frames)
    c2 = verify_mp4(baseline_full_path, n_frames)
    c3 = verify_mp4(comp_path, n_frames)

    ordered_probes = sorted(probe_frames)
    rows = []
    for idx in ordered_probes:
        src_idx = seq_indices[idx]
        c_src, c_wav, c_tch = probe_saved[idx]
        p_src = cv2.resize(c_src, (320, 320), interpolation=cv2.INTER_CUBIC)
        p_wav = cv2.resize(c_wav, (320, 320), interpolation=cv2.INTER_CUBIC)
        p_tch = cv2.resize(c_tch, (320, 320), interpolation=cv2.INTER_CUBIC)
        for tile, tag, col in [
            (p_src, f"Clean Base (idle#{src_idx})", (200, 200, 200)),
            (p_wav, f"Wav2Lip256 (f={idx}, {idx/fps:.2f}s)", (80, 120, 250)),
            (p_tch, f"Teacher (g={speech_gates[idx]:.2f}, r={rms_per_frame[idx]:.3f})", (80, 220, 110)),
        ]:
            cv2.rectangle(tile, (0, 0), (320, 34), (20, 20, 24), -1)
            cv2.putText(tile, tag, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.50, col, 1, cv2.LINE_AA)
        rows.append(np.hstack([p_src, p_wav, p_tch]))

    sheet = np.vstack([np.hstack([rows[2 * r], rows[2 * r + 1]]) for r in range(4)])
    sheet_path = OUT_DIR / "teacher-vs-wav2lip-contact-sheet.jpg"
    imwrite_unicode(sheet_path, sheet, ".jpg", [cv2.IMWRITE_JPEG_QUALITY, 95])

    report = {
        "gpu": torch.cuda.get_device_name(0) if device == "cuda" else "cpu",
        "total_wall_seconds": round(time.perf_counter() - t_start, 2),
        "duration_seconds": round(n_frames / fps, 2),
        "frames": n_frames,
        "clean_base_range": "idle[104..304] forward + idle[303..98] reverse",
        "verified_mp4_frames": {"teacher": c1, "baseline": c2, "comparison": c3},
        "outputs": {
            "teacher_full": str(teacher_full_path),
            "baseline_full": str(baseline_full_path),
            "comparison_side_by_side": str(comp_path),
            "contact_sheet": str(sheet_path),
        },
        "probe_frames": {
            str(i): {"rms": round(rms_per_frame[i], 4), "gate": round(float(speech_gates[i]), 3)}
            for i in ordered_probes
        },
    }
    (OUT_DIR / "step1-teacher-sample-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("STEP1_SAMPLE_COMPLETE", json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
