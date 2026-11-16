"""Run one frozen case and save measured provenance alongside the video."""
import argparse
import json
import time
from pathlib import Path
from types import SimpleNamespace
import torch
from omegaconf import OmegaConf
from scripts.inference import main

parser=argparse.ArgumentParser()
parser.add_argument('--fixture',choices=['short','long'],default='short')
parser.add_argument('--action',choices=['idle','explain-open-palms'],default='idle')
args=parser.parse_args()
assert torch.cuda.device_count()==1
assert 'T4' in torch.cuda.get_device_name(0)
prefix=Path('outputs')/f'{args.action}-{args.fixture}'
prefix.parent.mkdir(exist_ok=True)
parameters=SimpleNamespace(video_path=f'inputs/{args.action}-{args.fixture}.mp4',
    audio_path=f'inputs/{args.fixture}.wav',video_out_path=str(prefix)+'.mp4',
    inference_ckpt_path='checkpoints/latentsync_unet.pt',inference_steps=20,
    guidance_scale=1.5,temp_dir=str(prefix)+'-temp',seed=1247,enable_deepcache=False)
report={'model':'LatentSync 1.5','gpu':torch.cuda.get_device_name(0),'precision':'float16',
        'source':json.loads(Path('source-manifest.json').read_text()),'parameters':vars(parameters),
        'visual_acceptance':'USER_REVIEW_REQUIRED','cloud_calls':0}
torch.cuda.reset_peak_memory_stats()
started=time.perf_counter()
try:
    main(OmegaConf.load('configs/unet/stage2.yaml'),parameters)
    torch.cuda.synchronize()
    report['status']='GENERATED'
except Exception as error:
    report.update(status='FAILED',error_type=type(error).__name__,error=str(error))
    raise
finally:
    report['wall_seconds']=time.perf_counter()-started
    report['peak_allocated_mb']=torch.cuda.max_memory_allocated()/1024**2
    prefix.with_suffix('.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({k:report[k] for k in ['status','wall_seconds','peak_allocated_mb']}),flush=True)
