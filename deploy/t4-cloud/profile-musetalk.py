"""Component timings on the actual evaluation GPU; not WebRTC acceptance."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, '/eval/service')
from engine import MuseAssets
import numpy as np
import torch


def measure(fn, repeats=8):
    values = []
    for _ in range(repeats):
        torch.cuda.synchronize()
        before = time.perf_counter()
        fn()
        torch.cuda.synchronize()
        values.append(time.perf_counter() - before)
    return {'median_seconds': float(np.median(values)), 'p95_seconds': float(np.percentile(values, 95))}


assert torch.cuda.device_count() == 1
assert 'T4' in torch.cuda.get_device_name(0)
assets = MuseAssets()
result = {'gpu': torch.cuda.get_device_name(0), 'torch': torch.__version__,
          'scope': 'warm component timings; not end-to-end or external receiver acceptance',
          'batches': []}
with torch.inference_mode():
  for layout in ('contiguous', 'channels_last'):
    if layout == 'channels_last':
        assets.unet.model.to(memory_format=torch.channels_last)
        assets.vae.vae.to(memory_format=torch.channels_last)
    for batch in (1, 2, 4, 8):
        tokens = [('welcome-wave', 0)] * batch
        features = np.ones((batch, 50, 384), np.float32)
        assets.predict(tokens, features)
        latent = torch.stack([assets.muse[name][0][i] for name, i in tokens]).to(assets.device, assets.dtype)
        audio = assets.pe(torch.as_tensor(features, device=assets.device, dtype=assets.dtype))
        predicted = assets.unet.model(latent, assets.timesteps, encoder_hidden_states=audio).sample
        row = {'batch': batch, 'layout': layout,
               'unet': measure(lambda: assets.unet.model(latent, assets.timesteps, encoder_hidden_states=audio)),
               'vae_decode_and_copy': measure(lambda: assets.vae.decode_latents(predicted)),
               'face_pipeline': measure(lambda: assets.predict(tokens, features)),
               'whisper': measure(lambda: assets.audio_processor.audio2feat(np.zeros((20 + batch * 2) * 320, np.float32)))}
        row['face_only_fps'] = batch / row['face_pipeline']['median_seconds']
        result['batches'].append(row)
        Path('/eval/outputs/component-profile.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(row), flush=True)
