"""Step 4 (Full-Scale Production Pipeline on RTX 4090):
1. Stage A — Full 4.53-minute (272.0s = 6,800 frames) Sonic 512x512 DiT Teacher synthesis
   (reusing cached first 64.0s = 1,600 frames and generating remaining 208.0s = 5,200 frames in
   resumable ~32s chunks) + Full 22.96s (574 frames) unseen validation Sonic Teacher synthesis.
2. Stage B — Sub-pixel skull-locked 256x256 multi-pose alignment across ALL 5 full-body clips
   (idle, welcome-wave, explain-open-palms, acknowledge-nod, goodbye-wave) with post-blur 100%
   side-hair silhouette guard and whole-lower-face resting harmonization.
3. Stage C — Full 65-epoch (27,625-step) training of XiaolinStudent256UNet + LowerFacePatchGAN
   with online-calibrated FastWhisper50Hz silent conditioning compatibility.
4. Stage D — Build formal 50fps RIFE v4 + DiT-v2 Full-Body Material Cache (idle + 4 actions +
   open-eye kinematic Hermite bridges, 100% gateway50.py compatible) + render 33.00s (1,650 frames)
   50fps All-4-Actions Full-Body Showcase & Comparison Videos.
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
from omegaconf import OmegaConf
from PIL import Image
from torchvision import models
from transformers import AutoFeatureExtractor, WhisperModel


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", type=Path, default=Path(r"F:\xiaolin\app"))
    ap.add_argument("--distill-v1-dir", type=Path, default=Path(r"F:\xiaolin\distill-v1"))
    ap.add_argument("--dit-dir", type=Path, default=Path(r"F:\xiaolin\dit-distill-v2"))
    ap.add_argument("--epochs", type=int, default=65)
    ap.add_argument("--gan-start-epoch", type=int, default=15)
    ap.add_argument("--batch-pairs", type=int, default=16)
    return ap.parse_args()


def imwrite_unicode(path: Path, img: np.ndarray, ext: str = ".jpg", params=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(ext, img, params or [])
    if not ok:
        raise RuntimeError(f"Failed to encode image for {path}")
    buf.tofile(str(path))


def load_wav_16k(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wf:
        assert wf.getframerate() == 16000 and wf.getnchannels() == 1
        raw = wf.readframes(wf.getnframes())
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


def save_wav_16k(path: Path, pcm: np.ndarray):
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm16 = np.clip(pcm * 32767.0, -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(pcm16.tobytes())


def read_video_frames_512(mp4_path: Path) -> list[np.ndarray]:
    cap = cv2.VideoCapture(str(mp4_path))
    frames = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        if f.shape[:2] != (512, 512):
            f = cv2.resize(f, (512, 512), interpolation=cv2.INTER_LANCZOS4)
        frames.append(f)
    cap.release()
    return frames


def encode_mp4(ffmpeg_exe: Path, frames_bgr: list[np.ndarray], wav_path: Path, out_mp4: Path, fps: int = 25):
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    H, W = frames_bgr[0].shape[:2]
    cmd = [
        str(ffmpeg_exe), "-v", "error", "-nostdin", "-y",
        "-f", "rawvideo", "-pix_fmt", "bgr24",
        "-s", f"{W}x{H}", "-r", str(fps), "-i", "pipe:0",
        "-i", str(wav_path),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "fast", "-crf", "15",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-movflags", "+faststart",
        str(out_mp4),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    for fr in frames_bgr:
        proc.stdin.write(fr.tobytes())
    proc.stdin.close()
    err = proc.stderr.read()
    rc = proc.wait(timeout=120)
    if rc != 0:
        raise RuntimeError(f"FFmpeg encode failed for {out_mp4}: {err.decode(errors='replace')[:400]}")


def build_calibrated_silent_whisper_windows(whisper_dir: Path, device: str = "cuda") -> np.ndarray:
    """Produces silent Whisper 50Hz windows (N, 10, 5, 384) float16 matching online FastWhisper50Hz
    calibration (0.28 sin pulse at t=28.0s) so streaming silence never shifts mouth closure.
    """
    fe = AutoFeatureExtractor.from_pretrained(str(whisper_dir), local_files_only=True)
    whisp = WhisperModel.from_pretrained(str(whisper_dir), local_files_only=True).to(device=device, dtype=torch.float16).eval()
    cal_buf = np.zeros(480000, dtype=np.float32)
    t_cal = np.arange(640, dtype=np.float32) / 16000.0
    cal_buf[448000:448640] = 0.28 * np.sin(2.0 * np.pi * 440.0 * t_cal)
    mel = fe(cal_buf, return_tensors="pt", sampling_rate=16000).input_features.to(device=device, dtype=torch.float16)
    with torch.inference_mode():
        hs = whisp.encoder(mel, output_hidden_states=True).hidden_states
        stacked = torch.stack(hs, dim=2)[0].cpu().numpy().astype(np.float16)  # (1500, 5, 384)
    del whisp, fe
    torch.cuda.empty_cache()
    wins = [stacked[c - 4 : c + 6] for c in range(10, 50, 2)]
    return np.stack(wins, axis=0)


def compose_sonic_onto_pose_512_v2(
    pose_crop_512: np.ndarray,
    pose_seg_512: np.ndarray,
    sonic_aligned_to_pose_512: np.ndarray,
    sonic_seg_in_pose_512: np.ndarray,
    nose_bridge_y: float,
    gate: float,
) -> np.ndarray:
    """Upgraded v2 lower-face semantic compositor with POST-BLUR 100% side-hair silhouette guard:
    eliminates the 1-2px outer jawline halo against dark hair while allowing full downward jaw motion
    over neck skin (class 14).
    """
    if gate <= 1e-3:
        return pose_crop_512

    yy, xx = np.mgrid[0:512, 0:512]
    ref_zone = (
        np.isin(pose_seg_512, [1, 10])
        & np.isin(sonic_seg_in_pose_512, [1, 10])
        & (yy >= int(nose_bridge_y - 18))
        & (yy <= int(nose_bridge_y + 28))
    )
    sonic_adj = sonic_aligned_to_pose_512.copy()
    if int(ref_zone.sum()) > 200:
        lab_p = cv2.cvtColor(pose_crop_512, cv2.COLOR_BGR2LAB).astype(np.float32)
        lab_s = cv2.cvtColor(sonic_adj, cv2.COLOR_BGR2LAB).astype(np.float32)
        delta = np.clip(np.median(lab_p[ref_zone] - lab_s[ref_zone], axis=0), [-12.0, -6.0, -6.0], [12.0, 6.0, 6.0])
        teeth_soft = cv2.GaussianBlur((sonic_seg_in_pose_512 == 11).astype(np.float32), (9, 9), 0)[..., None]
        lab_shifted = np.clip(lab_s + delta.reshape(1, 1, 3), 0, 255)
        lab_final = lab_shifted * (1.0 - 0.88 * teeth_soft) + lab_s * (0.88 * teeth_soft)
        sonic_adj = cv2.cvtColor(lab_final.astype(np.uint8), cv2.COLOR_LAB2BGR)

    face_classes = [1, 10, 11, 12, 13]
    pose_face = np.isin(pose_seg_512, face_classes)
    sonic_face = np.isin(sonic_seg_in_pose_512, face_classes)
    # Allow Sonic to expand downward over pose neck (class 14), NEVER laterally over pose hair (class 17)
    union_face = (pose_face | (sonic_face & (pose_seg_512 != 17))).astype(np.float32)

    top_y = nose_bridge_y - 6.0
    top_ramp = np.clip((yy.astype(np.float32) - top_y) / 30.0, 0.0, 1.0)
    border = np.minimum(np.minimum(xx, 511 - xx), np.minimum(yy, 511 - yy)).astype(np.float32)
    edge_ramp = np.clip(border / 24.0, 0.0, 1.0)

    # Post-blur 100% side-hair guard so Gaussian feather never spills cheek skin onto dark hair!
    hair_dil = cv2.dilate((pose_seg_512 == 17).astype(np.uint8), np.ones((5, 5), np.uint8))
    hair_guard = cv2.GaussianBlur(hair_dil.astype(np.float32), (13, 13), 0)

    raw_mask = cv2.GaussianBlur(union_face, (23, 23), 6.5) * top_ramp * edge_ramp * (1.0 - hair_guard)
    alpha = (np.clip(raw_mask, 0.0, 1.0) * float(gate))[..., None]
    out = np.rint(sonic_adj.astype(np.float32) * alpha + pose_crop_512.astype(np.float32) * (1.0 - alpha))
    return np.clip(out, 0, 255).astype(np.uint8)


def stage_a_full_sonic_teacher(args):
    WORKSPACE = args.workspace.resolve()
    DISTILL_V1 = args.distill_v1_dir.resolve()
    DIT_DIR = args.dit_dir.resolve()
    SONIC_DIR = DIT_DIR / "vendor/Sonic"
    CKPT_DIR = SONIC_DIR / "checkpoints"
    TEACHER_DIR = DIT_DIR / "teacher"
    CHUNKS_DIR = TEACHER_DIR / "full_chunks"
    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    FFMPEG = WORKSPACE / "fay-ue4/runtime/fay-local/app/test/ovr_lipsync/ffmpeg/bin/ffmpeg.exe"

    full_train_mp4 = TEACHER_DIR / "sonic_train_full_272s_512.mp4"
    full_val_mp4 = TEACHER_DIR / "sonic_val_full_23s_512.mp4"
    full_train_wav = TEACHER_DIR / "train_full_272s_16k.wav"
    full_val_wav = TEACHER_DIR / "val_full_23s_16k.wav"

    raw_train = load_wav_16k(DISTILL_V1 / "dataset/train_master_16k.wav")
    raw_val = load_wav_16k(DISTILL_V1 / "dataset/val_unseen_16k.wav")

    n_train_25 = (len(raw_train) // 1280) * 2  # 6800 frames = 272.00s
    n_val_25 = (len(raw_val) // 1280) * 2      # 574 frames = 22.96s
    train_pcm = raw_train[: n_train_25 * 640]
    val_pcm = raw_val[: n_val_25 * 640]
    save_wav_16k(full_train_wav, train_pcm)
    save_wav_16k(full_val_wav, val_pcm)

    if full_train_mp4.exists() and full_val_mp4.exists():
        f_tr = read_video_frames_512(full_train_mp4)
        f_vl = read_video_frames_512(full_val_mp4)
        if len(f_tr) == n_train_25 and len(f_vl) == n_val_25:
            print(f"[Stage A] Full Sonic Teacher MP4s already cached ({len(f_tr)} train + {len(f_vl)} val frames).", flush=True)
            return

    from step1_build_hd_refs_and_sonic_teacher import (
        build_hd_canonical_portrait_512,
        find_silent_split_sample,
        run_sonic_segment_frames,
    )
    from diffusers import AutoencoderKLTemporalDecoder
    from diffusers.schedulers import EulerDiscreteScheduler
    from src.models.base.unet_spatio_temporal_condition import UNetSpatioTemporalConditionModel, add_ip_adapters
    from src.pipelines.pipeline_sonic import SonicPipeline
    from src.models.audio_adapter.audio_proj import AudioProjModel
    from src.models.audio_adapter.audio_to_bucket import Audio2bucketModel
    from src.utils.RIFE.RIFE_HDv3 import RIFEModel
    from src.dataset.face_align.align import AlignImage
    from transformers import CLIPVisionModelWithProjection

    canon_png = TEACHER_DIR / "canonical_portrait_512.png"
    if not canon_png.exists():
        build_hd_canonical_portrait_512(
            WORKSPACE / "avatar-2d/assets/presenter-v2-1080/prepared/idle.mp4",
            WORKSPACE / "avatar-2d/runtime/presenter-v2-1080/avatars/idle/coords.json",
            canon_png,
        )

    config = OmegaConf.load(str(SONIC_DIR / "config/inference/sonic.yaml"))
    config.num_inference_steps = 25
    config.motion_bucket_scale = 0.92
    config.decode_chunk_size = 4

    svd_dir = str(CKPT_DIR / "stable-video-diffusion-img2vid-xt")
    device = "cuda"
    weight_dtype = torch.float16

    print("[Stage A] Loading Sonic FP16 DiT Teacher for full 4.53-min corpus synthesis...", flush=True)
    unet_cfg = UNetSpatioTemporalConditionModel.load_config(svd_dir, subfolder="unet")
    unet = UNetSpatioTemporalConditionModel.from_config(unet_cfg)
    add_ip_adapters(unet, [32], [config.ip_audio_scale])
    unet.load_state_dict(torch.load(str(CKPT_DIR / "Sonic/unet.pth"), map_location="cpu", weights_only=True), strict=True)
    unet = unet.to(device=device, dtype=weight_dtype).eval()

    vae = AutoencoderKLTemporalDecoder.from_pretrained(svd_dir, subfolder="vae", variant="fp16", torch_dtype=weight_dtype).to(device).eval()
    image_encoder = CLIPVisionModelWithProjection.from_pretrained(svd_dir, subfolder="image_encoder", variant="fp16", torch_dtype=weight_dtype).to(device).eval()
    scheduler = EulerDiscreteScheduler.from_pretrained(svd_dir, subfolder="scheduler")

    whisper = WhisperModel.from_pretrained(str(CKPT_DIR / "whisper-tiny")).to(device).eval()
    whisper.requires_grad_(False)
    feature_extractor = AutoFeatureExtractor.from_pretrained(str(CKPT_DIR / "whisper-tiny"))

    audio2token = AudioProjModel(seq_len=10, blocks=5, channels=384, intermediate_dim=1024, output_dim=1024, context_tokens=32)
    audio2token.load_state_dict(torch.load(str(CKPT_DIR / "Sonic/audio2token.pth"), map_location="cpu", weights_only=True), strict=True)
    audio2token = audio2token.to(device).eval()

    audio2bucket = Audio2bucketModel(seq_len=50, blocks=1, channels=384, clip_channels=1024, intermediate_dim=1024, output_dim=1, context_tokens=2)
    audio2bucket.load_state_dict(torch.load(str(CKPT_DIR / "Sonic/audio2bucket.pth"), map_location="cpu", weights_only=True), strict=True)
    audio2bucket = audio2bucket.to(device).eval()

    face_det = AlignImage(device, det_path=str(CKPT_DIR / "yoloface_v5m.pt"))
    rife = RIFEModel(device=device)
    rife.load_model(str(CKPT_DIR / "RIFE"))
    pipe = SonicPipeline(unet=unet, image_encoder=image_encoder, vae=vae, scheduler=scheduler).to(device=device, dtype=weight_dtype)

    # 1) Full 22.96s (574 frames) unseen validation Sonic Teacher
    if not full_val_mp4.exists() or len(read_video_frames_512(full_val_mp4)) != n_val_25:
        t_v = time.perf_counter()
        print(f"[Stage A] Generating full unseen validation Sonic Teacher ({n_val_25} frames = {n_val_25/25:.2f}s)...", flush=True)
        vf = run_sonic_segment_frames(
            pipe, config, whisper, feature_extractor, face_det,
            audio2token, audio2bucket, image_encoder, rife, canon_png, full_val_wav, seed=72589,
        )
        encode_mp4(FFMPEG, vf, full_val_wav, full_val_mp4, fps=25)
        print(f"  -> Val full {n_val_25} frames done in {time.perf_counter() - t_v:.1f}s", flush=True)

    # 2) Full 272.0s (6,800 frames) balanced-phoneme training Sonic Teacher
    # Reuse exact first 1,600 frames (0 .. 1,024,000 samples = 64.0s) from sonic_train_64s_512.mp4!
    all_train_frames: list[np.ndarray] = []
    cached_64s_mp4 = TEACHER_DIR / "sonic_train_64s_512.mp4"
    start_sample = 0
    if cached_64s_mp4.exists():
        f_64 = read_video_frames_512(cached_64s_mp4)
        if len(f_64) == 1600:
            print("[Stage A] Reusing verified first 1,600 frames (64.00s) from sonic_train_64s_512.mp4!", flush=True)
            all_train_frames.extend(f_64)
            start_sample = 1600 * 640  # 1,024,000

    rem_samples = len(train_pcm) - start_sample
    if rem_samples > 0:
        n_parts = math.ceil(rem_samples / (32 * 16000))
        cuts = [start_sample]
        for k in range(1, n_parts):
            target_s = start_sample + (rem_samples * k) // n_parts
            cuts.append(find_silent_split_sample(train_pcm, target_s))
        cuts.append(len(train_pcm))

        for idx_c in range(len(cuts) - 1):
            s0, s1 = cuts[idx_c], cuts[idx_c + 1]
            expected_f = (s1 - s0) // 640
            chunk_mp4 = CHUNKS_DIR / f"train_chunk_{s0}_{s1}.mp4"
            chunk_wav = CHUNKS_DIR / f"train_chunk_{s0}_{s1}.wav"
            if chunk_mp4.exists():
                cf = read_video_frames_512(chunk_mp4)
                if len(cf) == expected_f:
                    print(f"  [Resume Chunk {idx_c+1}/{len(cuts)-1}] Loaded {expected_f} frames from {chunk_mp4.name}", flush=True)
                    all_train_frames.extend(cf)
                    continue

            t_c = time.perf_counter()
            save_wav_16k(chunk_wav, train_pcm[s0:s1])
            print(f"[Stage A] Generating Sonic train chunk {idx_c+1}/{len(cuts)-1}: samples {s0}..{s1} ({expected_f}f = {expected_f/25:.2f}s)...", flush=True)
            cf = run_sonic_segment_frames(
                pipe, config, whisper, feature_extractor, face_det,
                audio2token, audio2bucket, image_encoder, rife, canon_png, chunk_wav, seed=72600 + idx_c,
            )
            encode_mp4(FFMPEG, cf, chunk_wav, chunk_mp4, fps=25)
            chunk_wav.unlink(missing_ok=True)
            all_train_frames.extend(cf)
            print(f"  -> Chunk {idx_c+1}/{len(cuts)-1} done in {time.perf_counter() - t_c:.1f}s (total={len(all_train_frames)}/{n_train_25} frames)", flush=True)

    assert len(all_train_frames) == n_train_25, (len(all_train_frames), n_train_25)
    encode_mp4(FFMPEG, all_train_frames, full_train_wav, full_train_mp4, fps=25)
    print(f"[Stage A] Saved full 6,800-frame Sonic Teacher MP4 -> {full_train_mp4}", flush=True)

    del pipe, unet, vae, image_encoder, whisper, audio2token, audio2bucket, rife, face_det
    torch.cuda.empty_cache()


def stage_b_full_dataset256(args):
    WORKSPACE = args.workspace.resolve()
    DIT_DIR = args.dit_dir.resolve()
    SONIC_DIR = DIT_DIR / "vendor/Sonic"
    TEACHER_DIR = DIT_DIR / "teacher"
    DATASET_DIR = DIT_DIR / "dataset256_full"
    DATASET_DIR.mkdir(parents=True, exist_ok=True)

    if (DATASET_DIR / "dataset256_full_complete.json").exists():
        print("[Stage B] Full 6,800-frame 256x256 multi-pose dataset already built.", flush=True)
        return

    AVATAR_ROOT = WORKSPACE / "avatar-2d"
    MUSE_ROOT = WORKSPACE / "musetalk-eval"
    from grade_presenter_v2 import cheek_color, grade
    from xiaolin_student256_gan import get_student_box256
    from step2_align_and_build_dataset256 import (
        compute_speech_gate_25fps,
        extract_whisper_windows_25fps,
        parse_bisenet_512,
        build_upper_skull_anchor_points,
        align_to_canonical_512,
        invert_affine_2x3,
        get_sonic_square_crop_box,
        ping_pong,
    )
    from src.dataset.face_align.align import AlignImage

    prev_cwd = Path.cwd()
    os.chdir(MUSE_ROOT)
    try:
        from avatars.musetalk.whisper.audio2feature import Audio2Feature
        from avatars.musetalk.utils.face_parsing import FaceParsing
        audio_processor = Audio2Feature(model_path=str(MUSE_ROOT / "models/whisper"))
        parser = FaceParsing(left_cheek_width=90, right_cheek_width=90)
    finally:
        os.chdir(prev_cwd)

    face_det = AlignImage("cuda", det_path=str(SONIC_DIR / "checkpoints/yoloface_v5m.pt"))

    train_pcm = load_wav_16k(TEACHER_DIR / "train_full_272s_16k.wav")
    val_pcm = load_wav_16k(TEACHER_DIR / "val_full_23s_16k.wav")
    sonic_train = read_video_frames_512(TEACHER_DIR / "sonic_train_full_272s_512.mp4")
    sonic_val = read_video_frames_512(TEACHER_DIR / "sonic_val_full_23s_512.mp4")

    n_train = min(len(train_pcm) // 640, len(sonic_train))
    n_val = min(len(val_pcm) // 640, len(sonic_val))
    train_pcm, val_pcm = train_pcm[: n_train * 640], val_pcm[: n_val * 640]
    sonic_train, sonic_val = sonic_train[:n_train], sonic_val[:n_val]
    print(f"[Stage B] Building full multi-pose 256x256 dataset: train={n_train}f ({n_train/25:.2f}s), val={n_val}f ({n_val/25:.2f}s)", flush=True)

    train_gate = compute_speech_gate_25fps(train_pcm, n_train)
    val_gate = compute_speech_gate_25fps(val_pcm, n_val)
    train_whisper = extract_whisper_windows_25fps(audio_processor, train_pcm, n_train)
    val_whisper = extract_whisper_windows_25fps(audio_processor, val_pcm, n_val)
    np.save(DATASET_DIR / "train_whisper.npy", train_whisper)
    np.save(DATASET_DIR / "val_whisper.npy", val_whisper)

    # Load ALL frames of all 5 full-body clips & match skin tone to idle
    all_clips = ["idle", "welcome-wave", "explain-open-palms", "acknowledge-nod", "goodbye-wave"]

    def load_all_clip(cid: str):
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

    idle_f_all, idle_c = load_all_clip("idle")
    ref_lab = np.median([cheek_color(idle_f_all[int(k)], idle_c[int(k)]) for k in np.linspace(104, 304, 11).astype(int)], axis=0)
    clip_frames = {"idle": {i: idle_f_all[i] for i in set(range(104, 305)) | set(range(488, 660)) | {150}}}
    clip_coords = {"idle": idle_c}
    del idle_f_all

    for cid in all_clips[1:]:
        fs, cp = load_all_clip(cid)
        samp = np.linspace(0, len(fs) - 1, 11).astype(int)
        corr = (ref_lab - np.median([cheek_color(fs[int(k)], cp[int(k)]) for k in samp], axis=0)).astype(np.float32)
        clip_frames[cid] = {i: grade(fs[i], corr) for i in range(len(fs))}
        clip_coords[cid] = cp
        print(f"  Loaded & Lab-matched full {cid}: {len(fs)} frames", flush=True)

    # Build 6,800-frame multi-pose cycle covering 100% of every full-body gesture multiple times!
    blocks = [
        [("idle", i) for i in ping_pong(104, 304)],                                       # 400f
        [("welcome-wave", i) for i in ping_pong(0, len(clip_coords["welcome-wave"]) - 1)],     # 348f
        [("explain-open-palms", i) for i in ping_pong(0, len(clip_coords["explain-open-palms"]) - 1)], # 348f
        [("idle", i) for i in ping_pong(488, 650)],                                       # 324f
        [("acknowledge-nod", i) for i in ping_pong(0, len(clip_coords["acknowledge-nod"]) - 1)], # 198f
        [("goodbye-wave", i) for i in ping_pong(0, len(clip_coords["goodbye-wave"]) - 1)],     # 348f
    ]
    cycle = [t for blk in blocks for t in blk]
    train_sched = (cycle * ((n_train // len(cycle)) + 2))[:n_train]
    val_sched = (
        [("idle", 120 + i) for i in range(80)]
        + [("welcome-wave", min(len(clip_coords["welcome-wave"]) - 1, i)) for i in range(150)]
        + [("explain-open-palms", min(len(clip_coords["explain-open-palms"]) - 1, i)) for i in range(130)]
        + [("acknowledge-nod", min(len(clip_coords["acknowledge-nod"]) - 1, i)) for i in range(94)]
        + [("goodbye-wave", min(len(clip_coords["goodbye-wave"]) - 1, i)) for i in range(120)]
    )[:n_val]

    canon_sq_box = get_sonic_square_crop_box(clip_coords["idle"][150], clip_frames["idle"][150].shape)
    csx1, csy1, csx2, csy2 = canon_sq_box
    canon_512 = cv2.imread(str(TEACHER_DIR / "canonical_portrait_512.png"))
    canon_gray = cv2.cvtColor(canon_512, cv2.COLOR_BGR2GRAY)
    canon_seg = parse_bisenet_512(parser, canon_512)
    canon_kps5 = face_det(canon_512, maxface=True)[0][0].astype(np.float32)
    canon_anchors = build_upper_skull_anchor_points(canon_512, canon_seg, canon_kps5)
    canon_nb_y = float(0.60 * (canon_kps5[0, 1] + canon_kps5[1, 1]) * 0.5 + 0.40 * canon_kps5[2, 1])

    unique_tokens = sorted(set(train_sched + val_sched + [("idle", 150)]))
    print(f"[Stage B] Precomputing skull-lock & v2 whole-lower-face harmonization for {len(unique_tokens)} unique base frames...", flush=True)
    pose_meta = {}
    degrin_clips = {"welcome-wave", "goodbye-wave", "acknowledge-nod"}

    for tok in unique_tokens:
        cid, fidx = tok
        fr = clip_frames[cid][fidx]
        sq = get_sonic_square_crop_box(clip_coords[cid][fidx], fr.shape)
        sx1, sy1, sx2, sy2 = sq
        crop_512 = cv2.resize(fr[sy1:sy2, sx1:sx2], (512, 512), interpolation=cv2.INTER_LANCZOS4)
        seg_512 = parse_bisenet_512(parser, crop_512)
        kl, _, _ = face_det(crop_512, maxface=True)
        kp = kl[0].astype(np.float32) if len(kl) > 0 else None
        M_p2c = align_to_canonical_512(crop_512, kp, canon_gray, canon_kps5, canon_anchors)
        M_c2p = invert_affine_2x3(M_p2c)
        nb_y = float(0.60 * (kp[0, 1] + kp[1, 1]) * 0.5 + 0.40 * kp[2, 1]) if kp is not None else canon_nb_y

        if cid in degrin_clips:
            c_in_p = cv2.warpAffine(canon_512, M_c2p, (512, 512), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REPLICATE)
            cs_in_p = cv2.warpAffine(canon_seg, M_c2p, (512, 512), flags=cv2.INTER_NEAREST)
            harm_512 = compose_sonic_onto_pose_512_v2(crop_512, seg_512, c_in_p, cs_in_p, nb_y, gate=1.0)
            fr_h = fr.copy()
            fr_h[sy1:sy2, sx1:sx2] = cv2.resize(harm_512, (sx2 - sx1, sy2 - sy1), interpolation=cv2.INTER_LANCZOS4)
            clip_frames[cid][fidx] = fr_h
            crop_512 = harm_512
            seg_512 = parse_bisenet_512(parser, crop_512)

        pose_meta[tok] = (sq, crop_512, seg_512, M_p2c, M_c2p, nb_y)

    # Dual Canonical References (reuse verified closed & teeth refs or pick sharpest across all 6,800 frames!)
    b256_idle = get_student_box256(clip_coords["idle"][150], clip_frames["idle"][150].shape)
    closed_ref_256 = cv2.resize(
        clip_frames["idle"][150][b256_idle[1]:b256_idle[3], b256_idle[0]:b256_idle[2]],
        (256, 256), interpolation=cv2.INTER_LANCZOS4,
    )
    best_score, best_f1080 = -1.0, None
    for sf in sonic_train[::4]:
        s_seg = parse_bisenet_512(parser, sf)
        inner_px = int((s_seg == 11).sum())
        if inner_px < 500:
            continue
        kl, _, _ = face_det(sf, maxface=True)
        kp = kl[0].astype(np.float32) if len(kl) > 0 else None
        M_s2c = align_to_canonical_512(sf, kp, canon_gray, canon_kps5, canon_anchors)
        sf_c = cv2.warpAffine(sf, M_s2c, (512, 512), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REPLICATE)
        s_seg_c = cv2.warpAffine(s_seg, M_s2c, (512, 512), flags=cv2.INTER_NEAREST)
        m_roi = sf_c[s_seg_c == 11]
        if len(m_roi) < 60:
            continue
        sharp = float(cv2.Laplacian(cv2.cvtColor(sf_c, cv2.COLOR_BGR2GRAY), cv2.CV_32F)[s_seg_c == 11].var())
        bright = float(np.percentile(m_roi, 85))
        sc = sharp * (1.0 + bright / 128.0) * min(inner_px / 900.0, 1.5)
        if sc > best_score:
            best_score = sc
            c512 = compose_sonic_onto_pose_512_v2(canon_512, canon_seg, sf_c, s_seg_c, canon_nb_y, gate=1.0)
            f1080 = clip_frames["idle"][150].copy()
            f1080[csy1:csy2, csx1:csx2] = cv2.resize(c512, (csx2 - csx1, csy2 - csy1), interpolation=cv2.INTER_LANCZOS4)
            best_f1080 = f1080

    if best_f1080 is not None:
        teeth_ref_256 = cv2.resize(
            best_f1080[b256_idle[1]:b256_idle[3], b256_idle[0]:b256_idle[2]],
            (256, 256), interpolation=cv2.INTER_LANCZOS4,
        )
    else:
        teeth_ref_256 = np.load(DIT_DIR / "dataset256/canonical_teeth_ref_256.npy")
    np.save(DATASET_DIR / "canonical_closed_ref_256.npy", closed_ref_256)
    np.save(DATASET_DIR / "canonical_teeth_ref_256.npy", teeth_ref_256)
    imwrite_unicode(DATASET_DIR / "dual_refs_full_256.png", np.hstack([closed_ref_256, teeth_ref_256]), ".png")

    def build_split(split_name: str, s_frames: list[np.ndarray], sched: list[tuple[str, int]], g_arr: np.ndarray):
        n = len(sched)
        src_mm = np.lib.format.open_memmap(DATASET_DIR / f"{split_name}_src_256.npy", mode="w+", dtype=np.uint8, shape=(n, 256, 256, 3))
        tgt_mm = np.lib.format.open_memmap(DATASET_DIR / f"{split_name}_tgt_256.npy", mode="w+", dtype=np.uint8, shape=(n, 256, 256, 3))
        for i in range(n):
            tok = sched[i]
            cid, fidx = tok
            base_1080 = clip_frames[cid][fidx]
            bx1, by1, bx2, by2 = get_student_box256(clip_coords[cid][fidx], base_1080.shape)
            src_mm[i] = cv2.resize(base_1080[by1:by2, bx1:bx2], (256, 256), interpolation=cv2.INTER_LANCZOS4)
            g = float(g_arr[i])
            if g <= 1e-3:
                tgt_1080 = base_1080
            else:
                sf = s_frames[i]
                kl, _, _ = face_det(sf, maxface=True)
                kp = kl[0].astype(np.float32) if len(kl) > 0 else None
                M_s2c = align_to_canonical_512(sf, kp, canon_gray, canon_kps5, canon_anchors)
                sq, pose_512, pose_seg_512, _, M_c2p, nb_y = pose_meta[tok]
                M_s2p = (np.vstack([M_c2p, [0, 0, 1]]) @ np.vstack([M_s2c, [0, 0, 1]]))[:2].astype(np.float32)
                sf_p = cv2.warpAffine(sf, M_s2p, (512, 512), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REPLICATE)
                s_seg_p = parse_bisenet_512(parser, sf_p)
                comp_512 = compose_sonic_onto_pose_512_v2(pose_512, pose_seg_512, sf_p, s_seg_p, nb_y, gate=g)
                sx1, sy1, sx2, sy2 = sq
                tgt_1080 = base_1080.copy()
                tgt_1080[sy1:sy2, sx1:sx2] = cv2.resize(comp_512, (sx2 - sx1, sy2 - sy1), interpolation=cv2.INTER_LANCZOS4)
            tgt_mm[i] = cv2.resize(tgt_1080[by1:by2, bx1:bx2], (256, 256), interpolation=cv2.INTER_LANCZOS4)
            if (i + 1) % 800 == 0 or (i + 1) == n:
                print(f"  [Stage B {split_name}] {i+1}/{n} frames aligned & composed", flush=True)
        src_mm.flush()
        tgt_mm.flush()

    build_split("train", sonic_train, train_sched, train_gate)
    build_split("val", sonic_val, val_sched, val_gate)
    (DATASET_DIR / "dataset256_full_complete.json").write_text(
        json.dumps({"train_frames": n_train, "val_frames": n_val, "best_teeth_score": round(best_score, 2)}, indent=2),
        encoding="utf-8",
    )
    del parser, audio_processor, face_det, clip_frames, sonic_train, sonic_val
    torch.cuda.empty_cache()


def stage_c_full_train_gan256(args):
    WORKSPACE = args.workspace.resolve()
    DIT_DIR = args.dit_dir.resolve()
    DATASET_DIR = DIT_DIR / "dataset256_full"
    CKPT_DIR = DIT_DIR / "checkpoints"
    OUT_DIR = DIT_DIR / "outputs"
    CKPT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    best_path = CKPT_DIR / "xiaolin_dit_student256_full_best.pth"

    if best_path.exists() and (OUT_DIR / "stage_c_full_train_report.json").exists():
        print(f"[Stage C] Full 6,800-frame production checkpoint already trained -> {best_path}", flush=True)
        return

    from xiaolin_student256_gan import (
        XiaolinStudent256UNet,
        LowerFacePatchGANDiscriminator,
        build_lower_half_hide_mask_256,
    )
    from step3_train_gan256_and_preview15s import OfflineVGGPerceptual256, sobel_edges

    device = torch.device("cuda")
    torch.manual_seed(20261116)
    np.random.seed(20261116)

    print("[Stage C] Loading full 6,800-frame 256x256 dataset into RAM...", flush=True)
    train_src = np.load(DATASET_DIR / "train_src_256.npy")
    train_tgt = np.load(DATASET_DIR / "train_tgt_256.npy")
    train_whisp = np.load(DATASET_DIR / "train_whisper.npy")
    val_src = np.load(DATASET_DIR / "val_src_256.npy")
    val_tgt = np.load(DATASET_DIR / "val_tgt_256.npy")
    val_whisp = np.load(DATASET_DIR / "val_whisper.npy")
    closed_ref_256 = np.load(DATASET_DIR / "canonical_closed_ref_256.npy")
    teeth_ref_256 = np.load(DATASET_DIR / "canonical_teeth_ref_256.npy")

    n_train, n_val = len(train_src), len(val_src)
    # Pool BOTH natural room-tone silence AND online FastWhisper50Hz calibrated silence!
    nat_sil_idx = [i for i in range(n_train) if np.max(np.abs(train_src[i].astype(int) - train_tgt[i].astype(int))) == 0][:40]
    if not nat_sil_idx:
        nat_sil_idx = [0, 1]
    cal_sil_wins = build_calibrated_silent_whisper_windows(WORKSPACE / "musetalk-eval/models/whisper", device="cuda")
    sil_pool_np = np.concatenate([train_whisp[nat_sil_idx], cal_sil_wins], axis=0).astype(np.float32)
    silent_whisp_pool = torch.from_numpy(sil_pool_np).to(device)

    hide_mask_t = torch.from_numpy(build_lower_half_hide_mask_256().transpose(2, 0, 1)).unsqueeze(0).to(device)
    closed_ref_t = (torch.from_numpy(closed_ref_256.transpose(2, 0, 1)).float() / 255.0).unsqueeze(0).to(device)
    teeth_ref_t = (torch.from_numpy(teeth_ref_256.transpose(2, 0, 1)).float() / 255.0).unsqueeze(0).to(device)
    dual_refs_t = torch.cat([closed_ref_t, teeth_ref_t], dim=1)

    yy, xx = np.mgrid[0:256, 0:256].astype(np.float32)
    lower_roi = cv2.GaussianBlur(((xx >= 24) & (xx <= 232) & (yy >= 96) & (yy <= 242)).astype(np.float32), (15, 15), 0)
    teeth_roi = cv2.GaussianBlur(((xx >= 58) & (xx <= 198) & (yy >= 136) & (yy <= 202)).astype(np.float32), (11, 11), 0)
    pix_weight = torch.from_numpy(1.0 + 4.5 * lower_roi + 11.0 * teeth_roi).view(1, 1, 256, 256).to(device)
    edge_weight = torch.from_numpy(0.2 + 2.5 * lower_roi + 6.5 * teeth_roi).view(1, 1, 256, 256).to(device)

    netG = XiaolinStudent256UNet(in_channels=9).to(device)
    netD = LowerFacePatchGANDiscriminator(in_channels=6).to(device)
    vgg_fn = OfflineVGGPerceptual256().to(device)

    optG = torch.optim.AdamW(netG.parameters(), lr=1.0e-3, betas=(0.5, 0.999), weight_decay=1e-4)
    optD = torch.optim.AdamW(netD.parameters(), lr=4.0e-4, betas=(0.5, 0.999), weight_decay=1e-4)
    schedG = torch.optim.lr_scheduler.CosineAnnealingLR(optG, T_max=args.epochs, eta_min=2e-5)
    schedD = torch.optim.lr_scheduler.CosineAnnealingLR(optD, T_max=args.epochs, eta_min=1e-5)
    scalerG = torch.amp.GradScaler("cuda")
    scalerD = torch.amp.GradScaler("cuda")

    valid_pairs = np.arange(0, n_train - 1)
    best_score = 999.0
    history = []

    def eval_val():
        netG.eval()
        tot_mse, tot_low_l1, tot_m_l1 = 0.0, 0.0, 0.0
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
                tot_low_l1 += torch.abs(p[:, :, 96:240, 28:228] - t[:, :, 96:240, 28:228]).mean(dim=(1, 2, 3)).sum().item()
                tot_m_l1 += torch.abs(p[:, :, 136:202, 58:198] - t[:, :, 136:202, 58:198]).mean(dim=(1, 2, 3)).sum().item()
                preds_all.append((p.clamp(0, 1) * 255.0).byte().cpu().numpy().transpose(0, 2, 3, 1))
        return -10.0 * math.log10(max(1e-8, tot_mse / n_val)), tot_low_l1 / n_val, tot_m_l1 / n_val, np.concatenate(preds_all, axis=0)

    t_tr0 = time.perf_counter()
    for epoch in range(1, args.epochs + 1):
        netG.train(); netD.train()
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

            optG.zero_grad(set_to_none=True)
            with torch.amp.autocast("cuda", dtype=torch.float16):
                l_vgg = vgg_fn(pred_cat, t_cat)
                pred_f = pred_cat.float()
                l_pix = (torch.abs(pred_f - t_cat) * pix_weight).mean()
                l_edge = (torch.abs(sobel_edges(pred_f) - sobel_edges(t_cat)) * edge_weight).mean()
                l_temp = (torch.abs((pred_f[P:] - pred_f[:P]) - (t1_gt - t0_gt)) * pix_weight).mean()
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
        if use_gan:
            schedD.step()

        if epoch in (1, 5, 14, 20) or epoch % 5 == 0 or epoch == args.epochs:
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
            print("FULL_TRAIN256_EPOCH", json.dumps(rec), flush=True)

            score_key = m_l1 + (0.015 if not use_gan else 0.0)
            if score_key < best_score:
                best_score = score_key
                torch.save(
                    {
                        "model_fp16": {k: v.half().cpu() for k, v in netG.state_dict().items()},
                        "canonical_closed_ref_256": closed_ref_256,
                        "canonical_teeth_ref_256": teeth_ref_256,
                        "epoch": epoch,
                        "val_psnr": psnr,
                        "val_lower_l1": low_l1,
                        "val_mouth_l1": m_l1,
                    },
                    best_path,
                )
                cols = []
                for pid in np.linspace(15, n_val - 20, 10).astype(int):
                    c = np.vstack([val_src[pid], val_tgt[pid], v_preds[pid]])
                    cv2.putText(c, f"Val#{pid}", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (80, 240, 120), 1, cv2.LINE_AA)
                    cols.append(c)
                imwrite_unicode(OUT_DIR / "val_full_teacher_vs_student_gan.jpg", np.hstack(cols), ".jpg", [cv2.IMWRITE_JPEG_QUALITY, 95])

    (OUT_DIR / "stage_c_full_train_report.json").write_text(
        json.dumps({"best_score": round(best_score, 5), "wall_seconds": round(time.perf_counter() - t_tr0, 2), "history": history}, indent=2),
        encoding="utf-8",
    )
    del train_src, train_tgt, train_whisp, val_src, val_tgt, netG, netD, vgg_fn
    torch.cuda.empty_cache()


def stage_d_full_material_cache_and_showcase(args):
    WORKSPACE = args.workspace.resolve()
    DISTILL_V1 = args.distill_v1_dir.resolve()
    DIT_DIR = args.dit_dir.resolve()
    CKPT_DIR = DIT_DIR / "checkpoints"
    OUT_DIR = DIT_DIR / "outputs"
    CACHE_DIR = DIT_DIR / "material-cache-dit-v2"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    AVATAR_ROOT = WORKSPACE / "avatar-2d"
    MUSE_ROOT = WORKSPACE / "musetalk-eval"
    FFMPEG = WORKSPACE / "fay-ue4/runtime/fay-local/app/test/ovr_lipsync/ffmpeg/bin/ffmpeg.exe"

    from grade_presenter_v2 import cheek_color, grade
    from xiaolin_student256_gan import (
        XiaolinStudent256UNet,
        get_student_box256,
        build_lower_half_hide_mask_256,
        build_lower_half_compose_alpha_256,
        build_degrin_mask_256,
    )
    from step3_train_gan256_and_preview15s import (
        RIFEInterpolator,
        upsample_25_to_50_rife,
        FFmpegVideoWriter,
        compute_50fps_envelope,
        make_panel_with_zoom,
    )

    rife = RIFEInterpolator(DISTILL_V1 / "rife_flownet.pkl", device="cuda")
    ckpt = torch.load(CKPT_DIR / "xiaolin_dit_student256_full_best.pth", map_location="cpu", weights_only=False)
    student256 = XiaolinStudent256UNet(in_channels=9).cuda().half().eval()
    student256.load_state_dict({k: v.cuda().half() for k, v in ckpt["model_fp16"].items()})

    closed_t = (torch.from_numpy(ckpt["canonical_closed_ref_256"].transpose(2, 0, 1)).float() / 255.0).unsqueeze(0).cuda().half()
    teeth_t = (torch.from_numpy(ckpt["canonical_teeth_ref_256"].transpose(2, 0, 1)).float() / 255.0).unsqueeze(0).cuda().half()
    refs256_t = torch.cat([closed_t, teeth_t], dim=1)
    hide256_t = torch.from_numpy(build_lower_half_hide_mask_256().transpose(2, 0, 1)).unsqueeze(0).cuda().half()
    degrin256_t = torch.from_numpy(build_degrin_mask_256().transpose(2, 0, 1)).unsqueeze(0).cuda().half()
    comp_alpha_256 = build_lower_half_compose_alpha_256()

    sil_wins = build_calibrated_silent_whisper_windows(MUSE_ROOT / "models/whisper", device="cuda")
    sil_whisp_t = torch.from_numpy(sil_wins[0:1]).cuda().half()

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

    def descriptor(frame: np.ndarray) -> np.ndarray:
        feats = []
        for y1, y2, x1, x2 in [(100, 430, 400, 700), (350, 850, 300, 800), (650, 1150, 250, 850)]:
            gray = cv2.cvtColor(cv2.resize(frame[y1:y2, x1:x2], (40, 40)), cv2.COLOR_BGR2GRAY).astype(np.float32)
            feats.append(np.concatenate([gray.ravel(), (cv2.Sobel(gray, cv2.CV_32F, 1, 0) * 0.15).ravel()]))
        return np.concatenate(feats)

    def harmonize_closed_smile_256(frames_bgr: list[np.ndarray], coords_list: list[list[int]]) -> list[np.ndarray]:
        out_f = []
        for b0 in range(0, len(frames_bgr), 24):
            b1 = min(len(frames_bgr), b0 + 24)
            B = b1 - b0
            crops, boxes = [], []
            for k in range(b0, b1):
                bx1, by1, bx2, by2 = get_student_box256(coords_list[k], frames_bgr[k].shape)
                boxes.append((bx1, by1, bx2, by2))
                crops.append(cv2.resize(frames_bgr[k][by1:by2, bx1:bx2], (256, 256), interpolation=cv2.INTER_LANCZOS4))
            s_t = torch.from_numpy(np.asarray(crops).transpose(0, 3, 1, 2)).cuda().half() / 255.0
            s_clean = s_t * (1.0 - degrin256_t) + closed_t.expand(B, -1, -1, -1) * degrin256_t
            inp = torch.cat([s_clean * (1.0 - hide256_t), refs256_t.expand(B, -1, -1, -1)], dim=1)
            with torch.inference_mode():
                preds = (student256(inp, sil_whisp_t.expand(B, -1, -1, -1)).float().clamp(0, 1) * 255.0).byte().permute(0, 2, 3, 1).cpu().numpy()
            for idx_l, k in enumerate(range(b0, b1)):
                bx1, by1, bx2, by2 = boxes[idx_l]
                al = cv2.resize(comp_alpha_256, (bx2 - bx1, by2 - by1), interpolation=cv2.INTER_LINEAR)[..., None]
                pt = cv2.resize(preds[idx_l], (bx2 - bx1, by2 - by1), interpolation=cv2.INTER_LANCZOS4)
                fr = frames_bgr[k].copy()
                fr[by1:by2, bx1:bx2] = (pt * al + fr[by1:by2, bx1:bx2] * (1.0 - al)).astype(np.uint8)
                out_f.append(fr)
        return out_f

    # 1) Build 50fps Full-Body Material Cache (100% compatible with gateway50.py / MotionTransitions!)
    idle_dir = CACHE_DIR / "idle"
    idle_dir.mkdir(exist_ok=True)
    idle_plan = {
        "fps": 50,
        "total_frames": 800,
        "segments": [
            {"id": "clean_fwd", "start": 0, "end": 400},
            {"id": "clean_bwd", "start": 400, "end": 800},
        ],
    }
    (CACHE_DIR / "idle-plan.json").write_text(json.dumps(idle_plan, indent=2), encoding="utf-8")

    idle25_f, idle25_c = load_25fps_clip("idle")
    ref_lab = np.median([cheek_color(idle25_f[int(k)], idle25_c[int(k)]) for k in np.linspace(104, 304, 11).astype(int)], axis=0)

    if not (idle_dir / "complete.json").exists():
        print("[Stage D] Building RIFE 50fps 800-frame Clean Idle Cache...", flush=True)
        fwd50_f, fwd50_c = upsample_25_to_50_rife(idle25_f[104:305], idle25_c[104:305], rife)
        fwd50_f, fwd50_c = fwd50_f[:-1], fwd50_c[:-1]
        idle50_f = fwd50_f + fwd50_f[-2:0:-1]
        idle50_c = fwd50_c + fwd50_c[-2:0:-1]
        mm_idle = np.lib.format.open_memmap(idle_dir / "frames.npy", mode="w+", dtype=np.uint8, shape=(800, 1920, 1080, 3))
        for idx, fr in enumerate(idle50_f):
            mm_idle[idx] = fr
        mm_idle.flush()
        del mm_idle, idle50_f, fwd50_f
        (idle_dir / "coords.json").write_text(json.dumps(idle50_c), encoding="utf-8")
        (idle_dir / "complete.json").write_text(json.dumps({"frames": 800}), encoding="utf-8")
    del idle25_f

    arrays = {"idle": np.load(idle_dir / "frames.npy", mmap_mode="r")}
    coords = {"idle": json.loads((idle_dir / "coords.json").read_text(encoding="utf-8"))}

    action_names = ["welcome-wave", "goodbye-wave", "explain-open-palms", "acknowledge-nod"]
    degrin_actions = {"welcome-wave", "goodbye-wave", "acknowledge-nod"}
    for name in action_names:
        dest = CACHE_DIR / name
        dest.mkdir(exist_ok=True)
        if not (dest / "complete.json").exists():
            print(f"[Stage D] Building RIFE 50fps + DiT-v2 harmonized action cache: {name}...", flush=True)
            f25, c25 = load_25fps_clip(name)
            samp = np.linspace(0, len(f25) - 1, 11).astype(int)
            corr = (ref_lab - np.median([cheek_color(f25[int(k)], c25[int(k)]) for k in samp], axis=0)).astype(np.float32)
            f25_g = [grade(fr, corr) for fr in f25]
            if name in degrin_actions:
                f25_g = harmonize_closed_smile_256(f25_g, c25)
            f50, c50 = upsample_25_to_50_rife(f25_g, c25, rife)
            mm_act = np.lib.format.open_memmap(dest / "frames.npy", mode="w+", dtype=np.uint8, shape=(len(f50), 1920, 1080, 3))
            for idx, fr in enumerate(f50):
                mm_act[idx] = fr
            mm_act.flush()
            del mm_act, f25, f25_g, f50
            (dest / "coords.json").write_text(json.dumps(c50), encoding="utf-8")
            (dest / "complete.json").write_text(json.dumps({"frames": len(c50), "degrin": name in degrin_actions}), encoding="utf-8")
        arrays[name] = np.load(dest / "frames.npy", mmap_mode="r")
        coords[name] = json.loads((dest / "coords.json").read_text(encoding="utf-8"))

    if not (CACHE_DIR / "complete.json").exists():
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

        for name in action_names:
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

        trans_dir = CACHE_DIR / "transitions"
        trans_dir.mkdir(exist_ok=True)
        total_trans_frames = len(jobs) * bridge_len
        print(f"[Stage D] Building {len(jobs)} RIFE v4 Hermite bridges ({total_trans_frames} frames)...", flush=True)
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
            if (number + 1) % 30 == 0 or (number + 1) == len(jobs):
                print(f"  [Bridges] {number + 1}/{len(jobs)} completed", flush=True)
        full_mm.flush()
        del full_mm
        (trans_dir / "coords.json").write_text(json.dumps(boxes), encoding="utf-8")
        (CACHE_DIR / "transition-plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
        (CACHE_DIR / "complete.json").write_text(
            json.dumps({"version": "rife-dit-v2", "bridge_count": len(jobs), "transition_frames": total_trans_frames}, indent=2),
            encoding="utf-8",
        )

    arrays["transitions"] = np.load(CACHE_DIR / "transitions/frames.npy", mmap_mode="r")
    coords["transitions"] = json.loads((CACHE_DIR / "transitions/coords.json").read_text(encoding="utf-8"))
    trans_plan = json.loads((CACHE_DIR / "transition-plan.json").read_text(encoding="utf-8"))

    # 2) Render 33.00s (1,650 frames @ 50fps) All-4-Actions Full-Body Showcase using MotionTransitions + FastWhisper50Hz!
    print("[Stage D] Rendering 33.00s (1,650 frames @ 50fps) All-4-Actions Full-Body Showcase...", flush=True)
    sys.path.insert(0, str(AVATAR_ROOT / "experiments/presenter-50fps"))
    from idle_scheduler import IdleScheduler
    from motion_transitions import MotionTransitions

    if not hasattr(IdleScheduler, "seek"):
        def _seek(self, index):
            for current, segment in enumerate(self.segments):
                if segment["start"] <= index < segment["end"]:
                    self.current = current
                    self.index = index
                    return
            raise ValueError("Idle entry outside segments")
        IdleScheduler.seek = _seek

    # Use unseen 33s audio from distill-v1 (or build from val_unseen_16k.wav)
    showcase_wav = DISTILL_V1 / "outputs/showcase_unseen_33s_16k.wav"
    if not showcase_wav.exists():
        from step4_rife_material_and_preview import build_showcase_33s_audio
        showcase_wav = OUT_DIR / "showcase_unseen_33s_16k.wav"
        build_showcase_33s_audio(load_wav_16k(DISTILL_V1 / "dataset/val_unseen_16k.wav"), showcase_wav, 1650)

    val33_pcm = load_wav_16k(showcase_wav)
    n_total = len(val33_pcm) // 320  # 1650 frames = 33.00s @ 50fps!

    # Extract 50Hz Whisper using online-identical calibrated extractor!
    fe = AutoFeatureExtractor.from_pretrained(str(MUSE_ROOT / "models/whisper"), local_files_only=True)
    mel_fb = np.asarray(fe.mel_filters, dtype=np.float32)
    if mel_fb.shape == (201, 80):
        mel_fb = mel_fb.T.copy()
    mel_fb_t = torch.from_numpy(mel_fb).cuda()
    hann_t = torch.hann_window(400, device="cuda", dtype=torch.float32)
    whisp_m = WhisperModel.from_pretrained(str(MUSE_ROOT / "models/whisper"), local_files_only=True).to(device="cuda", dtype=torch.float16).eval()

    cal_pcm = np.zeros(1600, dtype=np.float32)
    cal_pcm[480:1120] = 0.28 * np.sin(2.0 * np.pi * 440.0 * (np.arange(640, dtype=np.float32) / 16000.0))
    cal_stft = torch.stft(torch.from_numpy(cal_pcm).cuda(), 400, 160, 400, hann_t, center=True, pad_mode="reflect", return_complex=True)
    cal_cols = (mel_fb_t @ cal_stft.abs()[:, :-1].pow(2)).clamp(min=1e-10).log10()
    cal_peak = float(cal_cols.max().item())

    padded_pcm = np.pad(val33_pcm, (30 * 320, 20 * 320))
    whisp50 = np.empty((n_total, 10, 5, 384), dtype=np.float16)
    with torch.inference_mode():
        for b0 in range(0, n_total, 4):
            b1 = min(n_total, b0 + 4)
            B = b1 - b0
            seg = padded_pcm[b0 * 320 : (b0 + 30 + 10 + B) * 320]
            stft = torch.stft(torch.from_numpy(seg).cuda(), 400, 160, 400, hann_t, center=True, pad_mode="reflect", return_complex=True)
            ls = (mel_fb_t @ stft.abs()[:, :-1].pow(2)).clamp(min=1e-10).log10()
            gmax = torch.clamp(ls.max(), min=cal_peak)
            fmin = gmax - 8.0
            fnorm = (fmin + 4.0) / 4.0
            full_mel = torch.full((1, 80, 3000), float(fnorm.item()), device="cuda", dtype=torch.float16)
            nc = min(2790, ls.shape[1])
            full_mel[0, :, :nc] = ((torch.maximum(ls[:, :nc], fmin) + 4.0) / 4.0).half()
            full_mel[0, :, 2800 : 2800 + cal_cols.shape[1]] = ((torch.maximum(cal_cols, fmin) + 4.0) / 4.0).half()
            hs = whisp_m.encoder(full_mel, output_hidden_states=True).hidden_states
            stk = torch.stack(hs, dim=2)[0]
            for k in range(B):
                whisp50[b0 + k] = stk[30 + k - 4 : 30 + k + 6].cpu().numpy()
    del whisp_m

    env50 = compute_50fps_envelope(val33_pcm, n_total)

    sched = IdleScheduler(idle_plan["segments"], lambda tok, idx: 0.0, seed=42)
    mt = MotionTransitions(trans_plan, sched, {k: len(v) for k, v in coords.items()})
    triggers = {30: "welcome-wave", 475: "explain-open-palms", 920: "acknowledge-nod", 1210: "goodbye-wave"}
    tokens = []
    pose = ("idle", 0)
    for t_idx in range(n_total):
        if t_idx in triggers:
            mt.request(triggers[t_idx])
        pose = mt.next(pose)
        tokens.append(pose)

    full_mp4 = OUT_DIR / "showcase_50fps_dit_v2_all4actions_fullbody.mp4"
    w_full = FFmpegVideoWriter(FFMPEG, full_mp4, 1080, 1920, 50, showcase_wav)

    # Also compare against v1 33s video if present!
    v1_mp4 = DISTILL_V1 / "outputs/preview-50fps-xiaolin-v2-full.mp4"
    cap_v1 = cv2.VideoCapture(str(v1_mp4)) if v1_mp4.exists() else None
    comp_mp4 = OUT_DIR / "showcase_50fps_dit_v2_vs_v1_all4actions.mp4"
    w_comp = FFmpegVideoWriter(FFMPEG, comp_mp4, 1080, 1280, 50, showcase_wav) if cap_v1 is not None else None

    sheet_targets = [160, 290, 560, 680, 990, 1060, 1340, 1440]
    sheet_cols = []
    infer_sec, infer_frames = 0.0, 0

    for b0 in range(0, n_total, 4):
        b1 = min(n_total, b0 + 4)
        B = b1 - b0
        if any(env50[i] > 1e-3 for i in range(b0, b1)):
            crops, boxes = [], []
            for i in range(b0, b1):
                nm, idx = tokens[i]
                fr = arrays[nm][idx]
                bx1, by1, bx2, by2 = get_student_box256(coords[nm][idx], fr.shape)
                boxes.append((bx1, by1, bx2, by2))
                crops.append(cv2.resize(fr[by1:by2, bx1:bx2], (256, 256), interpolation=cv2.INTER_LINEAR))
            s_t = torch.from_numpy(np.asarray(crops).transpose(0, 3, 1, 2)).cuda().half() / 255.0
            w_t = torch.from_numpy(whisp50[b0:b1]).cuda().half()
            inp = torch.cat([s_t * (1.0 - hide256_t), refs256_t.expand(B, -1, -1, -1)], dim=1)
            torch.cuda.synchronize()
            t_i = time.perf_counter()
            with torch.inference_mode():
                pr = student256(inp, w_t)
            torch.cuda.synchronize()
            infer_sec += time.perf_counter() - t_i
            infer_frames += B
            preds_np = (pr.float().clamp(0, 1) * 255.0).byte().permute(0, 2, 3, 1).cpu().numpy()
        else:
            preds_np, boxes = None, None

        for k, i in enumerate(range(b0, b1)):
            nm, idx = tokens[i]
            f_v2 = arrays[nm][idx].copy()
            crd = coords[nm][idx]
            if preds_np is not None and env50[i] > 1e-3:
                bx1, by1, bx2, by2 = boxes[k]
                bw, bh = bx2 - bx1, by2 - by1
                al = cv2.resize(comp_alpha_256 * float(env50[i]), (bw, bh), interpolation=cv2.INTER_LINEAR)[..., None]
                pt = cv2.resize(preds_np[k], (bw, bh), interpolation=cv2.INTER_LINEAR)
                f_v2[by1:by2, bx1:bx2] = (pt * al + f_v2[by1:by2, bx1:bx2] * (1.0 - al)).astype(np.uint8)

            w_full.write(f_v2)

            f_v1 = None
            if cap_v1 is not None:
                ok1, fv1 = cap_v1.read()
                if ok1:
                    f_v1 = fv1
            if w_comp is not None and f_v1 is not None:
                p_left = make_panel_with_zoom(f_v1, crd, "Prev v1 (192px L1, Mouth-Only)", f"t={i/50:.2f}s | {nm}", (70, 195, 245))
                p_right = make_panel_with_zoom(f_v2, crd, "Prod DiT-v2 (6800f Sonic->256px GAN)", f"t={i/50:.2f}s | {nm}", (85, 235, 115))
                w_comp.write(np.hstack([p_left, p_right]))

            if i in sheet_targets:
                y1, y2, x1, x2 = crd
                cx, cy = int(0.5 * (x1 + x2)), int(0.5 * (y1 + y2)) + 12
                rx1, ry1 = max(0, cx - 120), max(0, cy - 110)
                rx2, ry2 = min(1080, rx1 + 240), min(1920, ry1 + 230)
                z2 = cv2.resize(f_v2[ry1:ry2, rx1:rx2], (260, 250), interpolation=cv2.INTER_CUBIC)
                cv2.putText(z2, f"DiT-v2 {nm[:12]} ({i/50:.1f}s)", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (85, 235, 115), 1, cv2.LINE_AA)
                if f_v1 is not None:
                    z1 = cv2.resize(f_v1[ry1:ry2, rx1:rx2], (260, 250), interpolation=cv2.INTER_CUBIC)
                    cv2.putText(z1, f"Prev v1 f={i}", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (70, 195, 245), 1, cv2.LINE_AA)
                    sheet_cols.append(np.vstack([z1, z2]))
                else:
                    sheet_cols.append(z2)

    w_full.close()
    if w_comp is not None:
        w_comp.close()
    if cap_v1 is not None:
        cap_v1.release()
    if sheet_cols:
        imwrite_unicode(OUT_DIR / "showcase_50fps_dit_v2_all4actions_sheet.jpg", np.hstack(sheet_cols), ".jpg", [cv2.IMWRITE_JPEG_QUALITY, 95])

    eff_fps = infer_frames / max(1e-6, infer_sec)
    summary = {
        "material_cache_dir": str(CACHE_DIR),
        "material_version": "rife-dit-v2",
        "checkpoint": str(CKPT_DIR / "xiaolin_dit_student256_full_best.pth"),
        "best_epoch": ckpt["epoch"],
        "val_psnr_db": round(float(ckpt["val_psnr"]), 2),
        "val_lower_l1": round(float(ckpt["val_lower_l1"]), 5),
        "val_mouth_l1": round(float(ckpt["val_mouth_l1"]), 5),
        "effective_gpu_fps_4090": round(eff_fps, 1),
        "showcase_frames_50fps": n_total,
        "actions_verified": action_names,
    }
    (OUT_DIR / "step4_full_production_report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("STEP4_FULL_PRODUCTION_COMPLETE", json.dumps(summary, ensure_ascii=False), flush=True)


def main():
    t0 = time.perf_counter()
    args = parse_args()
    WORKSPACE = args.workspace.resolve()
    DIT_DIR = args.dit_dir.resolve()
    SONIC_DIR = DIT_DIR / "vendor/Sonic"

    sys.path.insert(0, str(WORKSPACE / "avatar-2d/tools"))
    from windows_runtime import prepare_runtime
    prepare_runtime()

    sys.path.insert(0, str(DIT_DIR / "pylibs"))
    sys.path.insert(0, str(DIT_DIR))
    sys.path.insert(0, str(SONIC_DIR))
    sys.path.insert(0, str(args.distill_v1_dir.resolve()))
    sys.path.insert(0, str(WORKSPACE / "avatar-2d/vendor/LiveTalking-c7269433a2b6ecebcd9342445d2ecc882c98b0da"))

    torch.backends.cudnn.benchmark = False

    stage_a_full_sonic_teacher(args)
    stage_b_full_dataset256(args)
    stage_c_full_train_gan256(args)
    stage_d_full_material_cache_and_showcase(args)
    print(f"ALL_FULL_BODY_PRODUCTION_STAGES_COMPLETE in {(time.perf_counter() - t0)/60.0:.2f} min!", flush=True)


if __name__ == "__main__":
    main()
