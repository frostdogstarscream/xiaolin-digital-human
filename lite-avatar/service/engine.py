"""Official LiteAvatar inference, with process-local Windows compatibility."""
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
WORKSPACE=ROOT.parent
VENDOR=ROOT/'vendor/lite-avatar'
AVATAR_ID='20250612/P1VtV9PVTqDj7CiZx2CCme2A'
AVATAR_DIR=ROOT/'avatars'/AVATAR_ID/'P1VtV9PVTqDj7CiZx2CCme2A'
FFMPEG=WORKSPACE/'fay-ue4/runtime/fay-local/app/test/ovr_lipsync/ffmpeg/bin/ffmpeg.exe'
sys.path.insert(0,str(WORKSPACE/'avatar-2d/tools'))
from windows_runtime import prepare_runtime
prepare_runtime()
os.environ['PATH']=str(FFMPEG.parent)+os.pathsep+os.environ.get('PATH','')

import cv2
import numpy as np
import torch
import setuptools  # Supplies distutils for the pinned upstream code on Python 3.12.


class LiteEngine:
    fps=25
    def __init__(self):
        started=time.perf_counter()
        torch.set_num_threads(4)
        os.chdir(VENDOR)
        sys.path.insert(0,str(VENDOR))
        from lite_avatar import liteAvatar
        self.device='cuda' if torch.cuda.is_available() else 'cpu'
        with torch.inference_mode():
            self.avatar=liteAvatar(use_gpu=False,fps=self.fps)
            # Audio features stay on CPU. Only the small face renderer uses GPU.
            self.avatar.device=self.device
            self.avatar.load_dynamic_model(os.path.relpath(AVATAR_DIR,VENDOR))
            self.rest=self.frame(self.avatar.get_idle_param(),0)
        self.loaded_seconds=time.perf_counter()-started
        self.stats={'rendered_frames':0,'last_feature_seconds':0.,'last_render_fps':0.}

    def frame(self,param,index):
        count=self.avatar.bg_video_frame_count
        phase=index%(count*2)
        background=phase if phase<count else count*2-1-phase
        with torch.inference_mode():
            mouth=self.avatar.param2img(param,background)
            frame,_=self.avatar.merge_mouth_to_bg(mouth,background)
        return frame

    def parameters(self,pcm):
        started=time.perf_counter()
        with torch.inference_mode():params=self.avatar.audio2param(pcm,is_complete=False)
        self.stats['last_feature_seconds']=time.perf_counter()-started
        return params

    @staticmethod
    def decode(source):
        output=subprocess.run([str(FFMPEG),'-v','error','-nostdin','-i',str(source),'-t','60','-ar','16000','-ac','1','-f','s16le','pipe:1'],
            check=True,capture_output=True,timeout=20)
        return output.stdout

    def render(self,source,action,destination,cancel):
        destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
        pcm=self.decode(source);params=self.parameters(pcm)
        height,width=self.rest.shape[:2]
        command=[str(FFMPEG),'-v','error','-nostdin','-y','-f','rawvideo','-pix_fmt','bgr24','-s',f'{width}x{height}',
            '-r',str(self.fps),'-i','pipe:0','-i',str(source),'-vf','pad=ceil(iw/2)*2:ceil(ih/2)*2',
            '-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(destination/'speaking.mp4')]
        process=subprocess.Popen(command,stdin=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        started=time.perf_counter();last=self.rest
        try:
            for index,param in enumerate(params):
                if cancel.is_set():raise RuntimeError('Render cancelled')
                last=self.frame(param,index);process.stdin.write(last.tobytes());self.stats['rendered_frames']+=1
            process.stdin.close();error=process.stderr.read();status=process.wait(timeout=30)
            if status:raise RuntimeError('LiteAvatar video encoding failed')
        except BaseException:
            process.kill();process.wait();raise
        cv2.imencode('.png',last)[1].tofile(destination/'rest.png')
        seconds=time.perf_counter()-started;self.stats['last_render_fps']=len(params)/max(seconds,.001)
        return dict(backend='LiteAvatar',avatar_id=AVATAR_ID,frames=len(params),fps=self.fps,
            feature_seconds=self.stats['last_feature_seconds'],render_seconds=seconds,render_fps=self.stats['last_render_fps'],device=self.device)
