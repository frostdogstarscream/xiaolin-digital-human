"""Compile both original networks and measure complete face throughput."""
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, '/eval/service')
from engine import MuseAssets
import numpy as np
import torch

assets = MuseAssets()
results = []
with torch.inference_mode():
    reference = assets.predict([('welcome-wave',0)]*4,np.ones((4,50,384),np.float32)).astype(np.float32)
    assets.unet.model.forward = torch.compile(assets.unet.model.forward,mode='max-autotune-no-cudagraphs',fullgraph=True,dynamic=False)
    assets.vae.vae.decode = torch.compile(assets.vae.vae.decode,mode='max-autotune-no-cudagraphs',fullgraph=True,dynamic=False)
    for batch in (4, 8):
        tokens = [('welcome-wave',0)]*batch
        features = np.ones((batch,50,384),np.float32)
        start = time.perf_counter()
        output = assets.predict(tokens,features)
        torch.cuda.synchronize()
        preparation = time.perf_counter()-start
        timings = []
        for _ in range(12):
            torch.cuda.synchronize()
            start = time.perf_counter()
            output = assets.predict(tokens,features)
            torch.cuda.synchronize()
            timings.append(time.perf_counter()-start)
        result={'batch':batch,'preparation_seconds':preparation,'median_seconds':float(np.median(timings)),
                'face_fps':batch/float(np.median(timings)),
                'mae_uint8_vs_original':float(np.mean(np.abs(output[:4].astype(np.float32)-reference)))}
        results.append(result)
        Path('/eval/outputs/compiled-pipeline-profile.json').write_text(json.dumps(results,indent=2))
        print(json.dumps(result),flush=True)
