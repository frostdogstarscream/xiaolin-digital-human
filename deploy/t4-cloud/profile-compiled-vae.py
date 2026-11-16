"""Evaluate compilation of the original decoder, retaining its weights."""
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, '/eval/service')
from engine import MuseAssets
import numpy as np
import torch

assets = MuseAssets()
torch.set_num_threads(4)
with torch.inference_mode():
    latent = assets.muse['welcome-wave'][0][:4].to('cuda', torch.float16)
    audio = assets.pe(torch.ones(4, 50, 384, device='cuda', dtype=torch.float16))
    predicted = assets.unet.model(latent, assets.timesteps, encoder_hidden_states=audio).sample
    reference = assets.vae.decode_latents(predicted).astype(np.float32)
    started = time.perf_counter()
    assets.vae.vae.decode = torch.compile(assets.vae.vae.decode, mode='max-autotune-no-cudagraphs', fullgraph=True, dynamic=False)
    output = assets.vae.decode_latents(predicted)
    torch.cuda.synchronize()
    compilation = time.perf_counter() - started
    timings = []
    for _ in range(20):
        torch.cuda.synchronize()
        started = time.perf_counter()
        output = assets.vae.decode_latents(predicted)
        torch.cuda.synchronize()
        timings.append(time.perf_counter()-started)
    result = {'original_weights':True,'batch':4,'compile_and_first_run_seconds':compilation,
              'median_seconds':float(np.median(timings)), 'p95_seconds':float(np.percentile(timings,95)),
              'mae_uint8_vs_original':float(np.mean(np.abs(output.astype(np.float32)-reference)))}
    Path('/eval/outputs/compiled-vae-profile.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result),flush=True)
