"""Render exact pose/audio pairs through the native pipeline, with bounded frame IO."""
import argparse
import hashlib
import math
import queue
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'service'))
from bootstrap import ROOT,FFMPEG,read_json,write_json
from engine import load_assets,make_presenter
import cv2
import numpy as np
import torch


class VideoWriter:
    def __init__(self,path,width,height,audio):
        path.parent.mkdir(parents=True,exist_ok=True)
        self.process=subprocess.Popen([str(FFMPEG),'-v','error','-nostdin','-y','-f','rawvideo','-pix_fmt','bgr24',
            '-s',f'{width}x{height}','-r','25','-i','pipe:0','-i',str(audio),'-c:v','libx264','-threads','2',
            '-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-af','apad','-shortest',str(path)],
            stdin=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    def write(self,frame):self.process.stdin.write(frame.tobytes())
    def close(self):
        self.process.stdin.close();error=self.process.stderr.read();status=self.process.wait(timeout=30)
        if status:raise RuntimeError('Video encoding failed: '+error.decode(errors='replace')[:200])


def render(assets,backend,fixture,action):
    path=ROOT/fixture['file']
    with wave.open(str(path)) as stream:audio=np.frombuffer(stream.readframes(stream.getnframes()),'<i2').astype(np.float32)/32768
    audio=np.pad(audio,(0,(-len(audio))%320))
    count=max(math.ceil(len(audio)/640),len(assets.clips[action][1])+13 if action!='idle' else 1)
    prefix=ROOT/'outputs'/backend/(action+'-'+fixture['id'])
    full=VideoWriter(prefix.with_name(prefix.name+'-full.mp4'),720,1280,path)
    mouth=VideoWriter(prefix.with_name(prefix.name+'-mouth.mp4'),384,384,path)
    end=threading.Event();events=[];p=make_presenter(assets,lambda info:events.append(info))
    poses=[];outside_equal=True;started=None;frames=0
    class Output:
        _player=SimpleNamespace(audio=SimpleNamespace(_queue=queue.Queue()),video=SimpleNamespace(_queue=queue.Queue()))
        def start(self):pass
        def stop(self):pass
        def get_buffer_size(self):return 0
        def push_video_frame(self,frame):
            nonlocal started,frames,outside_equal
            if started is None:
                if not p.speaking:return
                started=time.perf_counter()
            if frames>=count:return
            name,index=p._emitting_pose;poses.append([name,index])
            y1,y2,x1,x2=assets.clips[name][1][index]
            original=assets.frame(name,index)
            outside_equal=outside_equal and np.array_equal(frame[min(y2+24,1280):],original[min(y2+24,1280):])
            full.write(frame)
            crop=frame[max(0,y1-12):min(1280,y2+12),max(0,x1-12):min(720,x2+12)]
            mouth.write(cv2.resize(crop,(384,384),interpolation=cv2.INTER_CUBIC))
            frames+=1
            if frames==count:end.set()
        def push_audio_frame(self,frame,eventpoint=None):p.notify(eventpoint)
    p.output=Output()
    before=p.snapshot()
    p.enqueue(audio,{'job_id':'offline','action':action})
    begin=time.perf_counter();worker=threading.Thread(target=p.render,args=(end,));worker.start();worker.join(timeout=180)
    if worker.is_alive():end.set();worker.join(timeout=5);raise RuntimeError('Offline render timed out')
    try:
        if p.error or frames!=count:raise RuntimeError(f'Render failed: {p.error}, {frames}/{count}')
    finally:full.close();mouth.close()
    elapsed=time.perf_counter()-begin;stats=p.snapshot()
    report={'backend':backend,'action':action,'fixture':fixture['id'],'fixture_sha256':fixture['sha256'],
        'frames':frames,'fps':25,'seconds':frames/25,'render_wall_seconds':elapsed,'wall_render_fps':frames/elapsed,
        'inference_seconds':stats['inference_seconds'],'feature_seconds':stats['feature_seconds'],
        'body_below_face_unchanged':outside_equal,'pose_sha256':hashlib.sha256(str(poses).encode()).hexdigest(),
        'first_pose':poses[0],'last_pose':poses[-1],
        'source_motion_frames':len(assets.clips[action][1]) if action!='idle' else 0,
        'full':str(prefix.relative_to(ROOT))+'-full.mp4','mouth':str(prefix.relative_to(ROOT))+'-mouth.mp4',
        'gpu_peak_mb':torch.cuda.max_memory_allocated()/1024**2 if torch.cuda.is_available() else 0}
    write_json(prefix.with_suffix('.json'),report)
    print('RENDERED',backend,action,fixture['id'],frames,round(report['wall_render_fps'],2),flush=True)
    return report


def main():
    args=argparse.ArgumentParser();args.add_argument('--backend',required=True,choices=['wav2lip','musetalk']);args=args.parse_args()
    assets=load_assets(args.backend);torch.cuda.reset_peak_memory_stats()
    fixtures=read_json(ROOT/'fixtures/manifest.json')['fixtures'];results=[]
    for fixture in fixtures:
        for action in ['idle',*assets.clips]:results.append(render(assets,args.backend,fixture,action))
    write_json(ROOT/'outputs'/(args.backend+'-offline.json'),{'model_load_seconds':assets.ready_seconds,'cases':results})
    print('OFFLINE_COMPLETE',args.backend,flush=True)


if __name__=='__main__':main()
