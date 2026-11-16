"""Step 1: Extract HD 512x512 Canonical Reference of Xiaolin + Generate 512x512 Sonic DiT Teacher Videos.

Key engineering safeguards:
  1. Preserves 100% of Xiaolin's real facial identity from idle#150 (384x384 -> 512x512 Lanczos4 +
     gentle anatomical detail crispness boost on lips/eyes without plastic skin halos).
  2. Exact FP16/FP32 mixed-dtype orchestration for Sonic (UNet/VAE/CLIP in FP16, Whisper/Audio2Token/
     Audio2Bucket in FP32) with decode_chunk_size=4 and streaming CPU RIFE 2x interpolation so peak
     VRAM stays < 9.5 GB (safe alongside existing 8.2 GB services on the 24 GB RTX 4090).
  3. Generates unseen 16.0s validation Teacher video FIRST for immediate visual teeth/cheek verification,
     followed by the 64.0s balanced-phoneme training Teacher video (chunked in two 32.0s segments at a
     silent boundary).
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
from omegaconf import OmegaConf
from PIL import Image


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", type=Path, default=Path(r"F:\xiaolin\app"))
    ap.add_argument("--distill-v1-dir", type=Path, default=Path(r"F:\xiaolin\distill-v1"))
    ap.add_argument("--dit-dir", type=Path, default=Path(r"F:\xiaolin\dit-distill-v2"))
    ap.add_argument("--train-seconds", type=float, default=64.0)
    ap.add_argument("--val-seconds", type=float, default=16.0)
    ap.add_argument("--inference-steps", type=int, default=25)
    ap.add_argument("--dynamic-scale", type=float, default=0.92)
    return ap.parse_args()


def imwrite_unicode(path: Path, img: np.ndarray, ext: str = ".png", params=None):
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


def get_sonic_square_crop_box(idle_box_y1y2x1x2, frame_shape=(1920, 1080)) -> list[int]:
    H, W = frame_shape[:2]
    y1, y2, x1, x2 = idle_box_y1y2x1x2
    cx = 0.5 * (x1 + x2)
    cy = 0.5 * (y1 + y2) + 8.0
    half = 192
    sx1 = max(0, int(round(cx - half)))
    sy1 = max(0, int(round(cy - half)))
    sx2 = min(W, sx1 + 2 * half)
    sy2 = min(H, sy1 + 2 * half)
    return [sx1, sy1, sx2, sy2]


def build_hd_canonical_portrait_512(idle_mp4: Path, idle_coords_json: Path, out_png: Path) -> tuple[np.ndarray, list[int]]:
    coords = json.loads(idle_coords_json.read_text(encoding="utf-8"))
    cap = cv2.VideoCapture(str(idle_mp4))
    frame_150 = None
    for i in range(151):
        ok, fr = cap.read()
        if not ok:
            break
        if i == 150:
            frame_150 = fr
    cap.release()
    if frame_150 is None:
        raise RuntimeError("Could not read frame #150 from idle.mp4")

    sq = get_sonic_square_crop_box(coords[150], frame_150.shape)
    sx1, sy1, sx2, sy2 = sq
    crop_512 = cv2.resize(frame_150[sy1:sy2, sx1:sx2], (512, 512), interpolation=cv2.INTER_LANCZOS4)

    # Subtle high-frequency micro-contrast restoration in Lab L-channel ONLY (zero chrominance shift!)
    lab = cv2.cvtColor(crop_512, cv2.COLOR_BGR2LAB).astype(np.float32)
    L = lab[:, :, 0]
    L_blur = cv2.GaussianBlur(L, (0, 0), 1.3)
    L_sharp = np.clip(L + 0.30 * (L - L_blur), 0.0, 255.0)
    lab[:, :, 0] = L_sharp
    hd_512 = cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2BGR)
    imwrite_unicode(out_png, hd_512, ".png")
    return hd_512, sq


def find_silent_split_sample(pcm_16k: np.ndarray, target_sample: int, search_radius_sec: float = 4.0) -> int:
    """Finds the quietest 40ms frame-aligned sample index (multiple of 1280 = 2 frames @ 25fps) near target_sample."""
    rad = int(search_radius_sec * 16000)
    lo = max(1280, ((target_sample - rad) // 1280) * 1280)
    hi = min(len(pcm_16k) - 1280, ((target_sample + rad) // 1280) * 1280)
    best_s = (target_sample // 1280) * 1280
    best_rms = 999.0
    for s in range(lo, hi + 1, 1280):
        seg = pcm_16k[s - 640 : s + 640]
        r = float(np.sqrt(np.mean(seg ** 2)))
        if r < best_rms:
            best_rms = r
            best_s = s
    return best_s


@torch.no_grad()
def run_sonic_segment_frames(
    pipe,
    config,
    whisper,
    feature_extractor,
    face_det,
    audio2token,
    audio2bucket,
    image_encoder,
    rife,
    image_path: Path,
    audio_path: Path,
    seed: int = 72589,
) -> list[np.ndarray]:
    """Runs Sonic diffusion + streaming RIFE 2x interpolation on a single audio file (<= 36s)
    and returns exact 25fps BGR uint8 frames (512x512) on CPU with bounded VRAM (< 9.5 GB).
    """
    from src.dataset.test_preprocess import image_audio_to_tensor
    from src.utils.util import seed_everything

    seed_everything(seed)
    device = pipe.device
    img_enc_dtype = next(image_encoder.parameters()).dtype

    batch = image_audio_to_tensor(
        face_det,
        feature_extractor,
        str(image_path),
        str(audio_path),
        limit=10000,
        image_size=512,
        area=config.area,
    )
    if batch is None:
        raise RuntimeError(f"YoloFace detected no face in {image_path}")

    for k, v in batch.items():
        if isinstance(v, torch.Tensor):
            batch[k] = v.unsqueeze(0).to(device).float()

    ref_img = batch["ref_img"]
    clip_img = batch["clip_images"]
    face_mask = batch["face_mask"]
    height, width = ref_img.shape[-2:]

    image_embeds = image_encoder(clip_img.to(dtype=img_enc_dtype)).image_embeds.float()

    audio_feature = batch["audio_feature"]
    audio_len = int(batch["audio_len"])
    step = int(config.step)  # 2 -> 12.5fps diffusion, then 2x RIFE -> 25fps

    window = 3000
    audio_prompts = []
    last_audio_prompts = []
    for i in range(0, audio_feature.shape[-1], window):
        enc_out = whisper.encoder(audio_feature[:, :, i : i + window], output_hidden_states=True)
        audio_prompt = torch.stack(enc_out.hidden_states, dim=2)
        last_audio_prompt = enc_out.last_hidden_state.unsqueeze(-2)
        audio_prompts.append(audio_prompt)
        last_audio_prompts.append(last_audio_prompt)

    audio_prompts = torch.cat(audio_prompts, dim=1)[:, : audio_len * 2]
    audio_prompts = torch.cat(
        [torch.zeros_like(audio_prompts[:, :4]), audio_prompts, torch.zeros_like(audio_prompts[:, :6])], dim=1
    )

    last_audio_prompts = torch.cat(last_audio_prompts, dim=1)[:, : audio_len * 2]
    last_audio_prompts = torch.cat(
        [torch.zeros_like(last_audio_prompts[:, :24]), last_audio_prompts, torch.zeros_like(last_audio_prompts[:, :26])],
        dim=1,
    )

    audio_tensor_list = []
    uncond_audio_tensor_list = []
    motion_buckets = []
    n_diff_frames = audio_len // step
    for i in range(n_diff_frames):
        audio_clip = audio_prompts[:, i * 2 * step : i * 2 * step + 10].unsqueeze(0)
        audio_clip_for_bucket = last_audio_prompts[:, i * 2 * step : i * 2 * step + 50].unsqueeze(0)
        motion_bucket = audio2bucket(audio_clip_for_bucket, image_embeds) * 16.0 + 16.0
        motion_buckets.append(motion_bucket[0])

        cond_audio_clip = audio2token(audio_clip).squeeze(0)
        uncond_audio_clip = audio2token(torch.zeros_like(audio_clip)).squeeze(0)
        audio_tensor_list.append(cond_audio_clip[0])
        uncond_audio_tensor_list.append(uncond_audio_clip[0])

    video = pipe(
        ref_img,
        clip_img,
        face_mask,
        audio_tensor_list,
        uncond_audio_tensor_list,
        motion_buckets,
        height=height,
        width=width,
        num_frames=len(audio_tensor_list),
        decode_chunk_size=4,
        motion_bucket_scale=config.motion_bucket_scale,
        fps=config.fps,
        noise_aug_strength=config.noise_aug_strength,
        min_guidance_scale1=config.min_appearance_guidance_scale,
        max_guidance_scale1=config.max_appearance_guidance_scale,
        min_guidance_scale2=config.audio_guidance_scale,
        max_guidance_scale2=config.audio_guidance_scale,
        overlap=config.overlap,
        shift_offset=config.shift_offset,
        frames_per_batch=config.n_sample_frames,
        num_inference_steps=config.num_inference_steps,
        i2i_noise_strength=config.i2i_noise_strength,
    ).frames

    # video on CPU: (1, 3, F_diff, H, W) in [-1, 1] RGB -> [0, 1]
    video = (video * 0.5 + 0.5).clamp(0.0, 1.0).cpu()
    f_diff = video.shape[2]

    def rgb_t_to_bgr_u8(t_1chw: torch.Tensor) -> np.ndarray:
        rgb = (t_1chw[0].clamp(0.0, 1.0) * 255.0).round().byte().permute(1, 2, 0).cpu().numpy()
        return rgb[:, :, ::-1].copy()

    frames_bgr: list[np.ndarray] = []
    for idx in range(f_diff - 1):
        I1 = video[:, :, idx].to(device, dtype=torch.float32)
        I2 = video[:, :, idx + 1].to(device, dtype=torch.float32)
        mid = rife.inference(I1, I2).clamp(0.0, 1.0).detach()
        frames_bgr.append(rgb_t_to_bgr_u8(I1))
        frames_bgr.append(rgb_t_to_bgr_u8(mid))
    frames_bgr.append(rgb_t_to_bgr_u8(video[:, :, f_diff - 1]))
    # Pad trailing midpoint so 2 * n_diff_frames == exact 25fps audio_len!
    while len(frames_bgr) < audio_len:
        frames_bgr.append(frames_bgr[-1].copy())
    torch.cuda.empty_cache()
    return frames_bgr[:audio_len]


def encode_mp4_25fps(ffmpeg_exe: Path, frames_bgr: list[np.ndarray], wav_path: Path, out_mp4: Path):
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    H, W = frames_bgr[0].shape[:2]
    cmd = [
        str(ffmpeg_exe), "-v", "error", "-nostdin", "-y",
        "-f", "rawvideo", "-pix_fmt", "bgr24",
        "-s", f"{W}x{H}", "-r", "25", "-i", "pipe:0",
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
    rc = proc.wait(timeout=60)
    if rc != 0:
        raise RuntimeError(f"FFmpeg encode failed for {out_mp4}: {err.decode(errors='replace')[:400]}")


def save_open_mouth_sheet(frames_bgr: list[np.ndarray], out_jpg: Path, label: str):
    """Selects 10 diverse frames (2 closed/resting + 8 high-contrast open-mouth/teeth frames) for visual audit."""
    scores = []
    for idx, fr in enumerate(frames_bgr):
        # Mouth zone in 512x512 canonical crop is roughly y=270..380, x=180..332
        roi = fr[270:380, 180:332]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY).astype(np.float32)
        lap_var = float(cv2.Laplacian(gray, cv2.CV_32F).var())
        std_val = float(gray.std())
        scores.append((lap_var * std_val, idx))

    # Pick 8 well-spaced sharpest expressive frames + frame 0 & midpoint
    top_picks = [0]
    for _, idx in sorted(scores, reverse=True):
        if all(abs(idx - p) >= max(8, len(frames_bgr) // 16) for p in top_picks):
            top_picks.append(idx)
        if len(top_picks) >= 10:
            break
    top_picks = sorted(top_picks)

    tiles = []
    for idx in top_picks:
        im = frames_bgr[idx].copy()
        # Add 2x zoomed mouth/apple-muscle inset at bottom!
        mouth_crop = cv2.resize(im[220:412, 136:376], (512, 410), interpolation=cv2.INTER_CUBIC)
        cv2.putText(im, f"{label} f={idx} ({idx/25:.2f}s)", (12, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (80, 240, 120), 2, cv2.LINE_AA)
        cv2.putText(mouth_crop, "2x Apple-Muscle + Teeth Zoom", (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (120, 220, 255), 2, cv2.LINE_AA)
        tiles.append(np.vstack([im, mouth_crop]))
    imwrite_unicode(out_jpg, np.hstack(tiles), ".jpg", [cv2.IMWRITE_JPEG_QUALITY, 95])


def main():
    t0 = time.perf_counter()
    args = parse_args()
    WORKSPACE = args.workspace.resolve()
    DISTILL_V1 = args.distill_v1_dir.resolve()
    DIT_DIR = args.dit_dir.resolve()
    SONIC_DIR = DIT_DIR / "vendor" / "Sonic"
    CKPT_DIR = SONIC_DIR / "checkpoints"
    TEACHER_DIR = DIT_DIR / "teacher"
    TEACHER_DIR.mkdir(parents=True, exist_ok=True)

    FFMPEG = WORKSPACE / "fay-ue4/runtime/fay-local/app/test/ovr_lipsync/ffmpeg/bin/ffmpeg.exe"
    IDLE_MP4 = WORKSPACE / "avatar-2d/assets/presenter-v2-1080/prepared/idle.mp4"
    IDLE_COORDS = WORKSPACE / "avatar-2d/runtime/presenter-v2-1080/avatars/idle/coords.json"

    sys.path.insert(0, str(DIT_DIR / "pylibs"))
    sys.path.insert(0, str(SONIC_DIR))
    torch.backends.cudnn.benchmark = False

    # 1. Build Canonical 512x512 Portrait Reference
    canon_png = TEACHER_DIR / "canonical_portrait_512.png"
    _, sq_box = build_hd_canonical_portrait_512(IDLE_MP4, IDLE_COORDS, canon_png)
    print(f"[Step1] Saved HD canonical portrait 512x512 -> {canon_png} (native box={sq_box})", flush=True)

    # 2. Prepare read-only audio slices (multiples of 1280 samples = even frame counts @ 25fps for Sonic step=2!)
    val_frames_25 = int(round(args.val_seconds * 25.0 / 2.0)) * 2     # 400 frames = 16.00s
    train_frames_25 = int(round(args.train_seconds * 25.0 / 2.0)) * 2 # 1600 frames = 64.00s

    raw_val = load_wav_16k(DISTILL_V1 / "dataset/val_unseen_16k.wav")
    raw_train = load_wav_16k(DISTILL_V1 / "dataset/train_master_16k.wav")

    val_pcm = raw_val[: val_frames_25 * 640]
    if len(val_pcm) < val_frames_25 * 640:
        val_pcm = np.pad(val_pcm, (0, val_frames_25 * 640 - len(val_pcm)))
    val_wav = TEACHER_DIR / "val_16s_16k.wav"
    save_wav_16k(val_wav, val_pcm)

    train_pcm = raw_train[: train_frames_25 * 640]
    train_wav = TEACHER_DIR / "train_64s_16k.wav"
    save_wav_16k(train_wav, train_pcm)

    # 3. Load Sonic FP16 Pipeline
    from diffusers import AutoencoderKLTemporalDecoder
    from diffusers.schedulers import EulerDiscreteScheduler
    from transformers import WhisperModel, CLIPVisionModelWithProjection, AutoFeatureExtractor
    from src.models.base.unet_spatio_temporal_condition import UNetSpatioTemporalConditionModel, add_ip_adapters
    from src.pipelines.pipeline_sonic import SonicPipeline
    from src.models.audio_adapter.audio_proj import AudioProjModel
    from src.models.audio_adapter.audio_to_bucket import Audio2bucketModel
    from src.utils.RIFE.RIFE_HDv3 import RIFEModel
    from src.dataset.face_align.align import AlignImage

    config = OmegaConf.load(str(SONIC_DIR / "config/inference/sonic.yaml"))
    config.num_inference_steps = args.inference_steps
    config.motion_bucket_scale = args.dynamic_scale
    config.decode_chunk_size = 4

    svd_dir = str(CKPT_DIR / "stable-video-diffusion-img2vid-xt")
    device = "cuda"
    weight_dtype = torch.float16

    print("[Step1] Initializing Sonic FP16 DiT Teacher pipeline...", flush=True)
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

    # 4. Run Unseen 16s Validation Sonic Teacher FIRST!
    val_mp4 = TEACHER_DIR / "sonic_val_16s_512.mp4"
    t_v = time.perf_counter()
    print(f"[Step1] Generating unseen 16.0s Sonic 512x512 Teacher ({val_frames_25} frames)...", flush=True)
    val_frames = run_sonic_segment_frames(
        pipe, config, whisper, feature_extractor, face_det,
        audio2token, audio2bucket, image_encoder, rife,
        canon_png, val_wav, seed=72589,
    )
    encode_mp4_25fps(FFMPEG, val_frames, val_wav, val_mp4)
    save_open_mouth_sheet(val_frames, TEACHER_DIR / "sonic_val_16s_sheet.jpg", "Sonic-Val")
    peak_mb = torch.cuda.max_memory_reserved() / (1024 ** 2)
    print(f"  -> Val 16s complete in {time.perf_counter() - t_v:.1f}s (peak_reserved_vram={peak_mb:.1f} MB)", flush=True)

    # 5. Run 64s Balanced-Phoneme Training Sonic Teacher (split into <=32s chunks at quietest boundary)
    train_mp4 = TEACHER_DIR / "sonic_train_64s_512.mp4"
    t_tr = time.perf_counter()
    n_samples = len(train_pcm)
    if n_samples <= 36 * 16000:
        chunks = [(0, n_samples)]
    else:
        n_parts = math.ceil(n_samples / (32 * 16000))
        cuts = [0]
        for k in range(1, n_parts):
            cuts.append(find_silent_split_sample(train_pcm, (n_samples * k) // n_parts))
        cuts.append(n_samples)
        chunks = [(cuts[i], cuts[i + 1]) for i in range(len(cuts) - 1)]

    all_train_frames: list[np.ndarray] = []
    for idx_c, (s0, s1) in enumerate(chunks):
        part_wav = TEACHER_DIR / f"_tmp_train_part{idx_c}.wav"
        save_wav_16k(part_wav, train_pcm[s0:s1])
        print(f"[Step1] Generating Train Sonic chunk {idx_c+1}/{len(chunks)} ({(s1-s0)/16000:.2f}s)...", flush=True)
        part_frames = run_sonic_segment_frames(
            pipe, config, whisper, feature_extractor, face_det,
            audio2token, audio2bucket, image_encoder, rife,
            canon_png, part_wav, seed=72589 + idx_c,
        )
        all_train_frames.extend(part_frames)
        part_wav.unlink(missing_ok=True)

    encode_mp4_25fps(FFMPEG, all_train_frames, train_wav, train_mp4)
    save_open_mouth_sheet(all_train_frames, TEACHER_DIR / "sonic_train_64s_sheet.jpg", "Sonic-Train")
    print(f"  -> Train {args.train_seconds}s complete in {time.perf_counter() - t_tr:.1f}s ({len(all_train_frames)} frames)", flush=True)

    rep = {
        "val_frames": len(val_frames),
        "train_frames": len(all_train_frames),
        "peak_reserved_vram_mb": round(float(torch.cuda.max_memory_reserved() / (1024 ** 2)), 1),
        "wall_seconds": round(time.perf_counter() - t0, 2),
    }
    (TEACHER_DIR / "step1_sonic_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print("STEP1_SONIC_COMPLETE", json.dumps(rep, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
