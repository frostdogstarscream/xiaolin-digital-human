"""Dedicated 50 fps Xiaolin-DiT-v2 (256x256 Dual-Ref PatchGAN Student + RIFE v4 Cache)
live WebRTC gateway launcher on the RTX 4090 workstation (port 18775, isolated from 18774).
"""
import importlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(r"F:\xiaolin")
APP = ROOT / "app"
DIT_DIR = ROOT / "dit-distill-v2"
STATE_DIR = DIT_DIR / "state50"
STATE_DIR.mkdir(parents=True, exist_ok=True)

# Copy initial settings from F:/xiaolin/state/settings.json if first run, switching lipsync_backend='wav2lip' (50fps DiT-v2)
settings_file = STATE_DIR / "settings.json"
if not settings_file.exists():
    src_settings = ROOT / "state/settings.json"
    cfg = json.loads(src_settings.read_text(encoding="utf-8")) if src_settings.exists() else {}
    cfg["lipsync_backend"] = "wav2lip"
    cfg["revision"] = int(cfg.get("revision", 1)) + 1
    settings_file.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

os.environ.update(
    QWEN_DEMO_PORT="18775",
    QWEN_DEMO_ORIGIN="http://127.0.0.1:18775",
    QWEN_STATE_DIR=str(STATE_DIR),
    FAY_SYSTEM_CONF=str(ROOT / "config/system.conf"),
    MUSE_ROOT=str(APP / "musetalk-eval"),
    XIAOLIN_VIDEO_ENCODER="h264_nvenc",
    XIAOLIN_50_PRECISION="fp16",
    XIAOLIN_DIT_V2_DIR=str(DIT_DIR),
    XIAOLIN_DIT_V2_CKPT=str(DIT_DIR / "checkpoints/xiaolin_dit_student256_full_best.pth"),
    XIAOLIN_MATERIAL_CACHE=str(DIT_DIR / "material-cache-dit-v2"),
    OMP_NUM_THREADS="2",
    OPENBLAS_NUM_THREADS="1",
    MKL_NUM_THREADS="1",
    HF_HUB_OFFLINE="1",
    TRANSFORMERS_OFFLINE="1",
    TOKENIZERS_PARALLELISM="false",
)

sys.path.insert(0, str(APP / "avatar-2d/tools"))
from windows_runtime import prepare_runtime
prepare_runtime()

import psutil
psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)

import torch
if not torch.cuda.is_available():
    raise RuntimeError("CUDA unavailable")
free, _ = torch.cuda.mem_get_info()
if free < 4 * 1024**3:
    raise RuntimeError("Less than 4 GiB GPU memory free; retry when resources are available")
torch.cuda.set_per_process_memory_fraction(0.25)
torch.set_num_threads(2)

sys.path.insert(0, str(ROOT))
from xiaolin_lan_rtc import configure as configure_lan_rtc
configure_lan_rtc()

gw_dir = APP / "avatar-2d/experiments/qwen-realtime-v2"
exp50_dir = APP / "avatar-2d/experiments/presenter-50fps"
exp25_dir = APP / "avatar-2d/experiments/presenter-v2-1080"
live_dir = DIT_DIR / "live50"

sys.path[:0] = [str(live_dir), str(DIT_DIR), str(exp50_dir), str(exp25_dir), str(gw_dir)]
os.chdir(APP / "avatar-2d")

from idle_scheduler import IdleScheduler
if not hasattr(IdleScheduler, "seek"):
    def _seek(self, index):
        for current, segment in enumerate(self.segments):
            if segment["start"] <= index < segment["end"]:
                self.current = current
                self.index = index
                return
        raise ValueError("Idle entry outside the available segments")
    IdleScheduler.seek = _seek

import gateway
from server import webrtc
from encoder50 import configure as configure_enc50


def _lipsync_engine_dit_v2(backend):
    if backend == "musetalk":
        from video_encoder import configure as configure_enc25
        webrtc.VIDEO_PTIME = 0.04
        configure_enc25()
        return importlib.import_module("musetalk_engine")
    webrtc.VIDEO_PTIME = 0.02
    configure_enc50()
    return importlib.import_module("engine50_dit_v2")


gateway.Gateway.lipsync_engine = staticmethod(_lipsync_engine_dit_v2)

if __name__ == "__main__":
    import asyncio
    import logging
    logging.getLogger("aioice").setLevel(logging.WARNING)
    asyncio.run(gateway.main())
