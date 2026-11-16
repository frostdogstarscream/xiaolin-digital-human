"""Benchmark and save visual evidence for the explicitly approximate decoder."""
import json
import os
import sys
import time
from pathlib import Path
sys.path.insert(0,'/eval/service')
from engine import MuseAssets
from decoder_variants import configure
import cv2
import numpy as np
import torch

assets=MuseAssets()
results=[]
with torch.inference_mode():
    tokens=[('welcome-wave',0)]*4
    features=np.ones((4,50,384),np.float32)
    reference=assets.predict(tokens,features)
    os.environ['MUSE_DECODER_VARIANT']='taesd'
    configure(assets,Path('/eval'))
    for batch in (2,4,8):
        tokens=[('welcome-wave',0)]*batch
        features=np.ones((batch,50,384),np.float32)
        assets.predict(tokens,features)
        timings=[]
        for _ in range(12):
            torch.cuda.synchronize();start=time.perf_counter()
            output=assets.predict(tokens,features)
            torch.cuda.synchronize();timings.append(time.perf_counter()-start)
        row={'variant':'MuseTalk 1.5 + TAESD approximate decoder','batch':batch,
             'median_seconds':float(np.median(timings)),'face_fps':batch/float(np.median(timings)),
             'visual_acceptance':'USER_REVIEW_REQUIRED'}
        results.append(row);print(json.dumps(row),flush=True)
        cv2.imwrite('/eval/outputs/decoder-original-vs-tiny.png',np.concatenate([reference[0],output[0]],axis=1))
        Path('/eval/outputs/tiny-decoder-profile.json').write_text(json.dumps(results,indent=2))
