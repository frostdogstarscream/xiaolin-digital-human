"""Step 0: Isolated setup & high-speed ModelScope domestic CDN checkpoint downloader on RTX 4090 (F:/xiaolin/dit-distill-v2).
- Downloads SVD-XT FP16 & Sonic checkpoints directly from ModelScope Aliyun OSS domestic CDN
  (ai-modelscope/stable-video-diffusion-img2vid-xt & ApacheOne/ComfyUI-Sonic-models) at full domestic bandwidth,
  avoiding HuggingFace / hf-mirror US AWS Xet-bridge throttling.
- Verifies Sonic FP16 pipeline initialization within <12 GB VRAM budget.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(r"F:\xiaolin\dit-distill-v2")
PYLIBS = ROOT / "pylibs"
SONIC_DIR = ROOT / "vendor" / "Sonic"
CKPT_DIR = SONIC_DIR / "checkpoints"


def ensure_pylibs():
    PYLIBS.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(PYLIBS))
    try:
        import imageio  # noqa: F401
        print("[pylibs] imageio already available.", flush=True)
    except ImportError:
        subprocess.check_call([
            sys.executable, "-m", "pip", "install",
            "--target", str(PYLIBS), "--no-deps",
            "-i", "https://pypi.tuna.tsinghua.edu.cn/simple",
            "imageio", "imageio-ffmpeg"
        ])


def copy_local_reusable_models():
    src_whisp = Path(r"F:\xiaolin\app\musetalk-eval\models\whisper")
    dst_whisp = CKPT_DIR / "whisper-tiny"
    dst_whisp.mkdir(parents=True, exist_ok=True)
    for fn in ["config.json", "preprocessor_config.json", "pytorch_model.bin"]:
        s = src_whisp / fn
        d = dst_whisp / fn
        if s.exists() and not d.exists():
            shutil.copy2(s, d)

    src_rife = Path(r"F:\xiaolin\distill-v1\rife_flownet.pkl")
    dst_rife = CKPT_DIR / "RIFE" / "flownet.pkl"
    dst_rife.parent.mkdir(parents=True, exist_ok=True)
    if src_rife.exists() and not dst_rife.exists():
        shutil.copy2(src_rife, dst_rife)


def ms_download(ms_repo: str, ms_rel: str, dest: Path, min_bytes: int = 10):
    if dest.exists() and dest.stat().st_size >= min_bytes:
        print(f"[skip] {dest.relative_to(CKPT_DIR)} ({dest.stat().st_size / 1024**2:.1f} MB)", flush=True)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    url = f"https://www.modelscope.cn/models/{ms_repo}/resolve/master/{ms_rel}"

    for attempt in range(1, 5):
        t0 = time.perf_counter()
        cur_mb = part.stat().st_size / (1024 ** 2) if part.exists() else 0.0
        print(f"[ModelScope dl #{attempt}] {ms_repo}/{ms_rel} (resume={cur_mb:.1f} MB) ...", flush=True)
        cmd = [
            "curl.exe", "-L", "--fail", "-s", "-S",
            "-C", "-",
            "--connect-timeout", "15",
            "--speed-time", "30",
            "--speed-limit", "51200",
            "--retry", "3",
            "-o", str(part),
            url,
        ]
        rc = subprocess.call(cmd)
        if rc == 0 and part.exists() and part.stat().st_size >= min_bytes:
            if dest.exists():
                dest.unlink()
            part.rename(dest)
            tot_mb = dest.stat().st_size / (1024 ** 2)
            dl_mb = max(0.01, tot_mb - cur_mb)
            dt = max(1e-3, time.perf_counter() - t0)
            print(f"  -> OK {tot_mb:.2f} MB (+{dl_mb:.1f} MB in {dt:.1f}s = {dl_mb/dt:.1f} MB/s)", flush=True)
            return
        print(f"  -> curl exited {rc}, retrying...", flush=True)
    raise RuntimeError(f"Failed to download {ms_repo}/{ms_rel}")


def download_all():
    svd_dir = CKPT_DIR / "stable-video-diffusion-img2vid-xt"
    svd_specs = [
        ("model_index.json", 50),
        ("scheduler/scheduler_config.json", 50),
        ("feature_extractor/preprocessor_config.json", 50),
        ("vae/config.json", 50),
        ("vae/diffusion_pytorch_model.fp16.safetensors", 180_000_000),
        ("image_encoder/config.json", 50),
        ("image_encoder/model.fp16.safetensors", 1_150_000_000),
        ("unet/config.json", 50),
    ]
    for rel, min_b in svd_specs:
        ms_download("ai-modelscope/stable-video-diffusion-img2vid-xt", rel, svd_dir / rel, min_b)

    sonic_specs = [
        ("sonic/yoloface_v5m.pt", CKPT_DIR / "yoloface_v5m.pt", 75_000_000),
        ("sonic/audio2bucket.pth", CKPT_DIR / "Sonic/audio2bucket.pth", 80_000_000),
        ("sonic/audio2token.pth", CKPT_DIR / "Sonic/audio2token.pth", 200_000_000),
        ("sonic/unet.pth", CKPT_DIR / "Sonic/unet.pth", 6_000_000_000),
    ]
    for ms_rel, dst, min_b in sonic_specs:
        ms_download("ApacheOne/ComfyUI-Sonic-models", ms_rel, dst, min_b)


def verify_sonic_from_config():
    sys.path.insert(0, str(PYLIBS))
    sys.path.insert(0, str(SONIC_DIR))
    import torch
    from diffusers import AutoencoderKLTemporalDecoder
    from diffusers.schedulers import EulerDiscreteScheduler
    from transformers import WhisperModel, CLIPVisionModelWithProjection, AutoFeatureExtractor
    from src.models.base.unet_spatio_temporal_condition import UNetSpatioTemporalConditionModel, add_ip_adapters
    from src.models.audio_adapter.audio_proj import AudioProjModel
    from src.models.audio_adapter.audio_to_bucket import Audio2bucketModel

    svd_dir = str(CKPT_DIR / "stable-video-diffusion-img2vid-xt")
    print("[verify] Loading Sonic UNet from config + Sonic/unet.pth...", flush=True)
    unet_cfg = UNetSpatioTemporalConditionModel.load_config(svd_dir, subfolder="unet")
    unet = UNetSpatioTemporalConditionModel.from_config(unet_cfg)
    add_ip_adapters(unet, [32], [1.0])
    sd = torch.load(str(CKPT_DIR / "Sonic" / "unet.pth"), map_location="cpu", weights_only=True)
    unet.load_state_dict(sd, strict=True)
    del sd
    unet = unet.to(device="cuda", dtype=torch.float16).eval()

    vae = AutoencoderKLTemporalDecoder.from_pretrained(svd_dir, subfolder="vae", variant="fp16", torch_dtype=torch.float16).to("cuda").eval()
    img_enc = CLIPVisionModelWithProjection.from_pretrained(svd_dir, subfolder="image_encoder", variant="fp16", torch_dtype=torch.float16).to("cuda").eval()
    _ = EulerDiscreteScheduler.from_pretrained(svd_dir, subfolder="scheduler")
    whisper = WhisperModel.from_pretrained(str(CKPT_DIR / "whisper-tiny")).to("cuda").eval()
    _ = AutoFeatureExtractor.from_pretrained(str(CKPT_DIR / "whisper-tiny"))

    a2t = AudioProjModel(seq_len=10, blocks=5, channels=384, intermediate_dim=1024, output_dim=1024, context_tokens=32)
    a2t.load_state_dict(torch.load(str(CKPT_DIR / "Sonic" / "audio2token.pth"), map_location="cpu", weights_only=True), strict=True)
    a2t = a2t.to("cuda").eval()

    a2b = Audio2bucketModel(seq_len=50, blocks=1, channels=384, clip_channels=1024, intermediate_dim=1024, output_dim=1, context_tokens=2)
    a2b.load_state_dict(torch.load(str(CKPT_DIR / "Sonic" / "audio2bucket.pth"), map_location="cpu", weights_only=True), strict=True)
    a2b = a2b.to("cuda").eval()

    torch.cuda.synchronize()
    alloc_mb = torch.cuda.memory_allocated() / (1024 ** 2)
    res_mb = torch.cuda.memory_reserved() / (1024 ** 2)
    print("SONIC_INIT_SUCCESS", json.dumps({"allocated_mb": round(alloc_mb, 1), "reserved_mb": round(res_mb, 1)}), flush=True)


if __name__ == "__main__":
    t_start = time.perf_counter()
    ensure_pylibs()
    copy_local_reusable_models()
    download_all()
    verify_sonic_from_config()
    print(f"STEP0_COMPLETE in {time.perf_counter() - t_start:.1f}s", flush=True)
