"""Step 2 (Mouth Track): Generate 4.53-minute (6,800 frames) multi-pose high-precision
Teacher v2 training dataset + 22.96s (574 frames) unseen validation dataset on RTX 4090.
Covers frontal idle (2 clean ranges), explain-open-palms (hand gestures + head tilt),
and acknowledge-nod (head pitch/nod), all Lab skin-tone matched and geometrically closed on pauses.
"""
import argparse
import json
import math
import os
import sys
import time
import wave
from pathlib import Path


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", type=Path, default=Path("F:/xiaolin/app"))
    ap.add_argument("--distill-dir", type=Path, default=Path("F:/xiaolin/distill-v1"))
    ap.add_argument("--batch-size", type=int, default=24)
    return ap.parse_args()


ARGS = parse_args()
WORKSPACE = ARGS.workspace.resolve()
DISTILL_DIR = ARGS.distill_dir.resolve()
DATASET_DIR = DISTILL_DIR / "dataset"
AVATAR_ROOT = WORKSPACE / "avatar-2d"
MUSE_ROOT = WORKSPACE / "musetalk-eval"
VENDOR_ROOT = AVATAR_ROOT / "vendor" / "LiveTalking-c7269433a2b6ecebcd9342445d2ecc882c98b0da"

sys.path.insert(0, str(AVATAR_ROOT / "tools"))
from windows_runtime import prepare_runtime
prepare_runtime()

os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
sys.path.insert(0, str(VENDOR_ROOT))
sys.path.insert(0, str(DISTILL_DIR))

import cv2
import numpy as np
import torch
from PIL import Image
from grade_presenter_v2 import cheek_color, grade
from make_teacher_sample_v2 import (
    load_wav_16k,
    compute_speech_rhythm_curves,
    parse_full_batch,
    blend_dynamic_jaw_v2,
    imwrite_unicode,
)


def get_student_ubox(coord_y1y2x1x2, frame_shape=(1920, 1080)):
    """Canonical crop box for Xiaolin-Ultralight 192x192 input/output.
    Includes full face width (+8px margin) and downward jaw allowance (+16px).
    """
    H, W = frame_shape[:2]
    y1, y2, x1, x2 = coord_y1y2x1x2
    return [max(0, x1 - 8), max(0, y1), min(W, x2 + 8), min(H, y2 + 16)]


def extract_whisper_long(audio_processor, audio_16k: np.ndarray, n_frames_25fps: int) -> np.ndarray:
    """Chunked 20s + 2s-margin Whisper encoder feature extraction with zero 30s truncation."""
    total_w = n_frames_25fps * 2 + 20  # includes 10 frames (200ms) left & right margin
    ext_audio = np.pad(audio_16k, (3200 + 32000, 3200 + 32000))
    pieces = []
    for w0 in range(0, total_w, 1000):
        w1 = min(total_w, w0 + 1000)
        pcm_win = ext_audio[w0 * 320 : (w1 + 200) * 320]
        feat = audio_processor.audio2feat(pcm_win)  # (1500, 5, 384)
        pieces.append(feat[100 : 100 + (w1 - w0)])
    whisper_all = np.concatenate(pieces, axis=0)
    assert whisper_all.shape[0] == total_w, (whisper_all.shape, total_w)

    windows = np.empty((n_frames_25fps, 10, 5, 384), dtype=np.float16)
    for i in range(n_frames_25fps):
        c = 10 + i * 2
        windows[i] = whisper_all[c - 4 : c + 6].astype(np.float16)
    return windows


def load_clip_subset(clip_id: str, indices_needed: set[int], lab_correction: np.ndarray | None):
    video_path = AVATAR_ROOT / "assets/presenter-v2-1080/prepared" / f"{clip_id}.mp4"
    coords_path = AVATAR_ROOT / "runtime/presenter-v2-1080/avatars" / clip_id / "coords.json"
    coords = json.loads(coords_path.read_text(encoding="utf-8"))
    max_idx = max(indices_needed)
    cap = cv2.VideoCapture(str(video_path))
    frames_dict = {}
    idx = 0
    while idx <= max_idx:
        ok, frame = cap.read()
        if not ok:
            break
        if idx in indices_needed:
            if lab_correction is not None:
                frame = grade(frame, lab_correction)
            frames_dict[idx] = frame
        idx += 1
    cap.release()
    if len(frames_dict) != len(indices_needed):
        raise RuntimeError(f"Missing frames in {clip_id}: got {len(frames_dict)}/{len(indices_needed)}")
    return frames_dict, coords


def ping_pong(lo: int, hi: int) -> list[int]:
    return list(range(lo, hi + 1)) + list(range(hi - 1, lo, -1))


def build_pose_schedule(n_frames: int) -> list[tuple[str, int]]:
    """Multi-pose closed-mouth schedule cycling smoothly across frontal idle,
    hand-gesture explain-open-palms, alternate idle, and head-pitch acknowledge-nod.
    """
    blocks = [
        [("idle", i) for i in ping_pong(104, 304)],                # 400f
        [("explain-open-palms", i) for i in ping_pong(0, 174)],    # 348f
        [("idle", i) for i in ping_pong(488, 690)],                # 404f
        [("acknowledge-nod", i) for i in ping_pong(0, 98)],        # 196f
    ]
    cycle = [tok for blk in blocks for tok in blk]  # 1,348 frames per full multi-pose cycle
    out = []
    while len(out) < n_frames:
        out.extend(cycle)
    return out[:n_frames]


def main():
    t_begin = time.perf_counter()
    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    device = "cuda"
    dtype = torch.float16
    batch_size = ARGS.batch_size
    print(f"Step 2 Dataset Generation on {torch.cuda.get_device_name(0)} (batch={batch_size})", flush=True)

    train_audio = load_wav_16k(DATASET_DIR / "train_master_16k.wav")
    val_audio = load_wav_16k(DATASET_DIR / "val_unseen_16k.wav")
    n_train = len(train_audio) // 640
    n_val = len(val_audio) // 640
    print(f"Train frames={n_train} ({n_train/25:.2f}s), Val frames={n_val} ({n_val/25:.2f}s)", flush=True)

    train_open, train_smile, _ = compute_speech_rhythm_curves(train_audio, n_train, fps=25)
    val_open, val_smile, _ = compute_speech_rhythm_curves(val_audio, n_val, fps=25)

    train_sched = build_pose_schedule(n_train)
    # Offset val schedule so val also tests different pose combinations
    val_sched = build_pose_schedule(n_val + 300)[300 : 300 + n_val]

    needed_by_clip: dict[str, set[int]] = {}
    for clip_id, fidx in train_sched + val_sched + [("idle", 150)]:
        needed_by_clip.setdefault(clip_id, set()).add(fidx)
    # Also include 11 evenly-spaced frames for Lab color matching
    for k in np.linspace(0, 749, 11).astype(int):
        needed_by_clip["idle"].add(int(k))

    # Load idle first to compute Lab skin reference
    idle_frames, idle_coords = load_clip_subset("idle", needed_by_clip["idle"], lab_correction=None)
    ref_lab = np.median([cheek_color(idle_frames[int(k)], idle_coords[int(k)]) for k in np.linspace(0, 749, 11).astype(int)], axis=0)

    clip_frames = {"idle": idle_frames}
    clip_coords = {"idle": idle_coords}
    lab_corrections = {"idle": [0.0, 0.0, 0.0]}

    for action_id in ["explain-open-palms", "acknowledge-nod"]:
        ac_coords = json.loads((AVATAR_ROOT / "runtime/presenter-v2-1080/avatars" / action_id / "coords.json").read_text(encoding="utf-8"))
        sample_idx = set(int(k) for k in np.linspace(0, len(ac_coords) - 1, 11).astype(int))
        raw_samples, _ = load_clip_subset(action_id, sample_idx, lab_correction=None)
        before_lab = np.median([cheek_color(raw_samples[k], ac_coords[k]) for k in sorted(sample_idx)], axis=0)
        corr = (ref_lab - before_lab).astype(np.float32)
        lab_corrections[action_id] = corr.tolist()
        clip_frames[action_id], clip_coords[action_id] = load_clip_subset(action_id, needed_by_clip[action_id], lab_correction=corr)
        print(f"Loaded & Lab-matched {action_id}: {len(clip_frames[action_id])} unique frames (corr={np.round(corr, 2).tolist()})", flush=True)

    # Save canonical closed-mouth reference 192x192 from idle#150
    ref_ubox = get_student_ubox(clip_coords["idle"][150], clip_frames["idle"][150].shape)
    rx1, ry1, rx2, ry2 = ref_ubox
    canonical_ref_192 = cv2.resize(clip_frames["idle"][150][ry1:ry2, rx1:rx2], (192, 192), interpolation=cv2.INTER_LANCZOS4)
    np.save(DATASET_DIR / "canonical_ref_192.npy", canonical_ref_192)
    imwrite_unicode(DATASET_DIR / "canonical_ref_192.png", canonical_ref_192, ".png")

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

        print("Extracting chunked Whisper encoder features...", flush=True)
        train_whisper = extract_whisper_long(audio_processor, train_audio, n_train)
        val_whisper = extract_whisper_long(audio_processor, val_audio, n_val)
        np.save(DATASET_DIR / "train_whisper.npy", train_whisper)
        np.save(DATASET_DIR / "val_whisper.npy", val_whisper)

        # Precompute SD-VAE latents + BiSeNet source masks/segs for all unique tokens in train+val
        unique_tokens = sorted(set(train_sched + val_sched))
        print(f"Pre-encoding {len(unique_tokens)} unique multi-pose base frames...", flush=True)
        t_pre = time.perf_counter()
        latent_map, box_map, cbox_map, src_large_map, src_mask_map, src_seg_map = {}, {}, {}, {}, {}, {}

        with torch.inference_mode():
            for u0 in range(0, len(unique_tokens), batch_size):
                u_batch = unique_tokens[u0 : u0 + batch_size]
                pils = []
                for tok in u_batch:
                    cid, fidx = tok
                    frame = clip_frames[cid][fidx]
                    y1, y2, x1, x2 = clip_coords[cid][fidx]
                    box = [x1, y1, x2, min(y2 + 15, frame.shape[0])]
                    cbox, _ = get_crop_box(box, 1.5)
                    crop256 = cv2.resize(frame[box[1]:box[3], box[0]:box[2]], (256, 256), interpolation=cv2.INTER_LANCZOS4)
                    latent_map[tok] = vae.get_latents_for_unet(crop256).squeeze(0).cpu()
                    box_map[tok] = box
                    cbox_map[tok] = cbox
                    fl_src = Image.fromarray(frame[:, :, ::-1]).crop(cbox)
                    src_large_map[tok] = fl_src
                    pils.append(fl_src)
                masks_b, _, segs_b = parse_full_batch(pils, parser)
                for tok, m_s, s_s in zip(u_batch, masks_b, segs_b):
                    src_mask_map[tok] = m_s
                    src_seg_map[tok] = s_s
        print(f"Pre-encoding finished in {time.perf_counter() - t_pre:.2f}s", flush=True)

        def render_split(split_name: str, sched, whisper_arr, open_c, smile_c):
            n = len(sched)
            src_mm = np.lib.format.open_memmap(DATASET_DIR / f"{split_name}_src_192.npy", mode="w+", dtype=np.uint8, shape=(n, 192, 192, 3))
            tgt_mm = np.lib.format.open_memmap(DATASET_DIR / f"{split_name}_tgt_192.npy", mode="w+", dtype=np.uint8, shape=(n, 192, 192, 3))
            t_s = time.perf_counter()
            with torch.inference_mode():
                for b0 in range(0, n, batch_size):
                    b1 = min(n, b0 + batch_size)
                    # Skip heavy UNet+BiSeNet on pure silent batches where open_g==0 and smile_g==0!
                    need_gpu = [i for i in range(b0, b1) if (open_c[i] > 1e-3 or smile_c[i] > 1e-3)]
                    composed_map = {}
                    if need_gpu:
                        lat_b = torch.stack([latent_map[sched[i]] for i in need_gpu]).to(device=device, dtype=dtype)
                        aud_b = pe(torch.as_tensor(whisper_arr[need_gpu].reshape(len(need_gpu), 50, 384), device=device, dtype=dtype))
                        pred_lat = unet.model(lat_b, timesteps, encoder_hidden_states=aud_b).sample
                        decoded = vae.decode_latents(pred_lat)

                        pred_pils = []
                        for k, i in enumerate(need_gpu):
                            tok = sched[i]
                            x, y, x1, y1 = box_map[tok]
                            x_s, y_s, _, _ = cbox_map[tok]
                            face_res = cv2.resize(decoded[k], (x1 - x, y1 - y), interpolation=cv2.INTER_LANCZOS4)
                            fl_p = src_large_map[tok].copy()
                            fl_p.paste(Image.fromarray(face_res[:, :, ::-1]), (x - x_s, y - y_s, x1 - x_s, y1 - y_s))
                            pred_pils.append(fl_p)

                        p_jaws, p_mouths, p_segs = parse_full_batch(pred_pils, parser)
                        for k, i in enumerate(need_gpu):
                            tok = sched[i]
                            cid, fidx = tok
                            composed_map[i] = blend_dynamic_jaw_v2(
                                clip_frames[cid][fidx],
                                pred_pils[k],
                                src_large_map[tok],
                                src_mask_map[tok],
                                p_jaws[k],
                                p_mouths[k],
                                src_seg_map[tok],
                                p_segs[k],
                                box_map[tok],
                                cbox_map[tok],
                                open_g=float(open_c[i]),
                                smile_g=float(smile_c[i]),
                                upper_boundary_ratio=0.50,
                            )

                    for i in range(b0, b1):
                        cid, fidx = sched[i]
                        s_frame = clip_frames[cid][fidx]
                        t_frame = composed_map.get(i, s_frame)
                        ux1, uy1, ux2, uy2 = get_student_ubox(clip_coords[cid][fidx], s_frame.shape)
                        src_mm[i] = cv2.resize(s_frame[uy1:uy2, ux1:ux2], (192, 192), interpolation=cv2.INTER_LANCZOS4)
                        tgt_mm[i] = cv2.resize(t_frame[uy1:uy2, ux1:ux2], (192, 192), interpolation=cv2.INTER_LANCZOS4)

                    if b1 % 960 == 0 or b1 == n:
                        elapsed = time.perf_counter() - t_s
                        print(f"  [{split_name}] {b1}/{n} frames ({b1/max(1e-3, elapsed):.1f} fps)", flush=True)
            src_mm.flush()
            tgt_mm.flush()

        render_split("train", train_sched, train_whisper, train_open, train_smile)
        render_split("val", val_sched, val_whisper, val_open, val_smile)
    finally:
        os.chdir(prev_cwd)

    # Save visual sample grid of multi-pose training pairs
    val_src = np.load(DATASET_DIR / "val_src_192.npy", mmap_mode="r")
    val_tgt = np.load(DATASET_DIR / "val_tgt_192.npy", mmap_mode="r")
    sample_tiles = []
    for k in np.linspace(10, n_val - 20, 12).astype(int):
        pair = np.vstack([val_src[k], val_tgt[k]])
        sample_tiles.append(pair)
    imwrite_unicode(DATASET_DIR / "dataset_multipose_samples.jpg", np.hstack(sample_tiles), ".jpg", [cv2.IMWRITE_JPEG_QUALITY, 95])

    meta = {
        "train_frames": n_train,
        "val_frames": n_val,
        "unique_base_frames": len(unique_tokens),
        "lab_corrections": lab_corrections,
        "silent_frame_fraction_train": round(float(np.mean(train_open < 0.02)), 3),
        "wall_seconds": round(time.perf_counter() - t_begin, 2),
    }
    (DATASET_DIR / "dataset_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print("STEP2_DATASET_COMPLETE", json.dumps(meta, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
