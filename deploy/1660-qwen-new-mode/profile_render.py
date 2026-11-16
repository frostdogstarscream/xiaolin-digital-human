import json,os,sys,time,fractions
from pathlib import Path
os.environ['OMP_NUM_THREADS']='1';os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['MKL_NUM_THREADS']='1'
ROOT=Path('D:/XiaolinDigitalHuman');HERE=ROOT/'avatar-2d/experiments/presenter-v2-1080';sys.path.insert(0,str(HERE))
import live_engine_v2 as engine
import numpy as np,torch,av
from video_encoder import configure
configure()
from aiortc import codecs
began=time.monotonic();assets=engine.Assets();p=engine.Presenter(engine.options('profile'),assets,lambda e:None)
stages={name:[] for name in ['infer_batch4','fetch_frame','compose_frame','to_av_frame','encode_frame','mel_batch4']}
encoder=codecs.H264Encoder();encoder.target_bitrate=4000000
for batch in range(12):
    tokens=[('idle',batch*4+i) for i in range(4)]
    start=time.perf_counter();predictions=p._infer(tokens,np.ones((4,80,16),np.float32));stages['infer_batch4'].append(time.perf_counter()-start)
    for i,token in enumerate(tokens):
        start=time.perf_counter();assets.frame(*token);stages['fetch_frame'].append(time.perf_counter()-start)
        start=time.perf_counter();image=p._compose(token,predictions[i]);stages['compose_frame'].append(time.perf_counter()-start)
        start=time.perf_counter();frame=av.VideoFrame.from_ndarray(image,format='bgr24');frame.pts=(batch*4+i)*3600;frame.time_base=fractions.Fraction(1,90000);stages['to_av_frame'].append(time.perf_counter()-start)
        start=time.perf_counter();encoder.encode(frame);stages['encode_frame'].append(time.perf_counter()-start)
    for _ in range(8):p.asr.put_audio_frame(np.ones(320,np.float32)*.02,{})
    start=time.perf_counter();p.asr.run_step();stages['mel_batch4'].append(time.perf_counter()-start)
    while not p.asr.output_queue.empty():p.asr.output_queue.get_nowait()
    while not p.asr.feat_queue.empty():p.asr.feat_queue.get_nowait()
report=dict(status='PROFILE_COMPLETE',gpu=torch.cuda.get_device_name(),torch_threads=torch.get_num_threads(),seconds=time.monotonic()-began,
    stages={name:dict(median_ms=float(np.median(values))*1000,mean_ms=float(np.mean(values))*1000,max_ms=max(values)*1000) for name,values in stages.items()})
(ROOT/'deployment/qwen-new-mode-20261110/reports/render-profile.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report),flush=True)
