"""Render matched original/approximate MuseTalk and Wav2Lip samples."""
import gc
import os
import sys
from pathlib import Path
sys.path.insert(0,'/eval/tools')
from render_comparisons import render
from engine import load_assets
from bootstrap import ROOT,read_json,write_json
import torch

reports=[]
for backend,variant,label in [('wav2lip','original','wav2lip-t4'),
                              ('musetalk','original','musetalk-original-t4'),
                              ('musetalk','taesd','musetalk-taesd-t4')]:
    os.environ['MUSE_DECODER_VARIANT']=variant
    assets=load_assets(backend)
    torch.cuda.reset_peak_memory_stats()
    for fixture in read_json(ROOT/'fixtures/manifest.json')['fixtures']:
        report=render(assets,label,fixture,'idle')
        report['decoder_variant']=variant
        report['visual_acceptance']='USER_REVIEW_REQUIRED'
        reports.append(report)
        write_json(ROOT/'outputs/t4-offline-comparisons.json',reports)
    assets.frame.cache_clear()
    del assets
    gc.collect();torch.cuda.empty_cache()
print('MATCHED_RENDER_COMPLETE',flush=True)
