"""Test decoder precision and cuDNN choices before changing the service."""
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, '/eval/service')
from engine import MuseAssets
import numpy as np
import torch

assets = MuseAssets()
result = []
with torch.inference_mode():
    latent = assets.muse['welcome-wave'][0][:4].to('cuda', torch.float16)
    audio = assets.pe(torch.ones(4, 50, 384, device='cuda', dtype=torch.float16))
    predicted = assets.unet.model(latent, assets.timesteps, encoder_hidden_states=audio).sample
    reference = assets.vae.decode_latents(predicted).astype(np.float32)
    for dtype, benchmark, enabled in [(torch.float16, False, True), (torch.float32, False, True),
                                      (torch.float32, True, True), (torch.float16, False, False)]:
        torch.backends.cudnn.enabled = enabled
        torch.backends.cudnn.benchmark = benchmark
        assets.vae.vae.to(dtype=dtype, memory_format=torch.contiguous_format)
        assets.vae.decode_latents(predicted)
        timings = []
        for _ in range(8):
            torch.cuda.synchronize()
            start = time.perf_counter()
            output = assets.vae.decode_latents(predicted)
            torch.cuda.synchronize()
            timings.append(time.perf_counter()-start)
        row = {'dtype':str(dtype), 'cudnn_enabled':enabled, 'cudnn_benchmark':benchmark,
               'median_seconds':float(np.median(timings)), 'p95_seconds':float(np.percentile(timings,95)),
               'mae_uint8_vs_original':float(np.mean(np.abs(output.astype(np.float32)-reference))),
               'finite':bool(np.isfinite(output).all())}
        result.append(row)
        Path('/eval/outputs/vae-profile.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(row),flush=True)
