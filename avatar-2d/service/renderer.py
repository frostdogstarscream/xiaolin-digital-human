"""Persistent local Wav2Lip model. A gesture runs once, then holds its neutral end pose."""
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from windows_runtime import prepare_runtime
prepare_runtime()

import json
import math
import subprocess
import threading
import time
from functools import lru_cache

import cv2
import numpy as np
import soundfile as sf
import torch

from lipsync_preview import Wav2Lip,audio,prepare_avatar,read_image,write_image

FFMPEG=ROOT.parent/'fay-ue4/runtime/fay-local/app/test/ovr_lipsync/ffmpeg/bin/ffmpeg.exe'


class RenderCancelled(Exception):pass


class Renderer:
    def __init__(self):
        self.device='cuda' if torch.cuda.is_available() else 'cpu'
        self.dtype=torch.float16 if self.device=='cuda' and torch.cuda.get_device_capability(0)[0]>=8 else torch.float32
        torch.set_num_threads(4)
        if self.device=='cuda':torch.backends.cudnn.benchmark=True
        checkpoint=torch.load(ROOT/'models/wav2lip256.pth',map_location='cpu',weights_only=True)
        state=checkpoint.get('state_dict',checkpoint)
        self.model=Wav2Lip()
        self.model.load_state_dict({k.removeprefix('module.'):v for k,v in state.items()})
        self.model=self.model.to(device=self.device,dtype=self.dtype).eval()
        self.assets={}
        library=json.loads((ROOT/'assets/presenter-v1/motions-v1/action-library.json').read_text(encoding='utf-8'))
        for item in library['actions']:
            if not item.get('speech_candidate'):continue
            directory,report=prepare_avatar(self.device,ROOT/item['video'],'presenter_v1__'+item['id'])
            coords=json.loads((directory/'coords.json').read_text(encoding='utf-8'))
            self.assets[item['id']]=(directory,coords,report['frames'])
        with torch.inference_mode():
            self.model(torch.ones(4,1,80,16,device=self.device,dtype=self.dtype),
                       torch.ones(4,6,256,256,device=self.device,dtype=self.dtype))
        if self.device=='cuda':torch.cuda.synchronize()

    @lru_cache(maxsize=24)
    def frame(self,action,index):
        directory,_,_=self.assets[action]
        return read_image(directory/'full_imgs'/f'{index:08d}.png')

    @lru_cache(maxsize=256)
    def face(self,action,index):
        directory,_,_=self.assets[action]
        return read_image(directory/'face_imgs'/f'{index:08d}.png')

    def render(self,source,action,output,cancel:threading.Event):
        started=time.perf_counter()
        output.mkdir(parents=True,exist_ok=False)
        normalized=output/'voice.wav'
        subprocess.run([str(FFMPEG),'-hide_banner','-v','error','-nostdin','-n','-i',str(source),
                        '-ar','16000','-ac','1','-c:a','pcm_s16le',str(normalized)],check=True)
        wave,sr=sf.read(normalized,dtype='float32')
        if sr!=16000 or wave.ndim!=1 or len(wave)==0 or len(wave)>45*16000 or not np.isfinite(wave).all():
            raise ValueError('Audio must be nonempty and no longer than 45 seconds')
        # Mel extraction requires a minimum analysis window, without discarding short utterances.
        if len(wave)<4000:wave=np.pad(wave,(0,4000-len(wave)))
        voice_seconds=len(wave)/16000
        voice_frames=math.ceil(voice_seconds*25)
        asset=action if action in self.assets else 'welcome-wave'
        _,coords,asset_frames=self.assets[asset]
        gesture=action!='idle'
        count=max(voice_frames,asset_frames if gesture else 1)
        sf.write(output/'playback.wav',np.pad(wave,(0,count*640-len(wave))),16000,subtype='PCM_16')
        mel=audio.melspectrogram(wave)
        if not np.isfinite(mel).all():raise ValueError('Invalid mel features')
        writer=cv2.VideoWriter(str(output/'silent.mp4'),cv2.VideoWriter_fourcc(*'mp4v'),25,(720,1280))
        if not writer.isOpened():raise RuntimeError('Cannot open frame encoder')
        last_source=None
        try:
            for begin in range(0,count,4):
                if cancel.is_set():raise RenderCancelled()
                actual=list(range(begin,min(begin+4,count)))
                padded=actual+[actual[-1]]*(4-len(actual))
                indices=[min(i,asset_frames-1) if gesture else 0 for i in padded]
                faces=np.asarray([self.face(asset,i) for i in indices])
                masked=faces.copy();masked[:,128:]=0
                image=np.concatenate([masked,faces],axis=3).astype(np.float32)/255
                features=[mel[:,max(0,min(int(i*80/25),mel.shape[1]-16)):max(0,min(int(i*80/25),mel.shape[1]-16))+16] for i in padded]
                x=torch.from_numpy(image.transpose(0,3,1,2).copy()).to(device=self.device,dtype=self.dtype)
                a=torch.from_numpy(np.asarray(features,dtype=np.float32)[:,None].copy()).to(device=self.device,dtype=self.dtype)
                with torch.inference_mode():pred=self.model(a,x)
                if not torch.isfinite(pred).all():raise ValueError('Invalid model output')
                pred=(pred.float().cpu().numpy().transpose(0,2,3,1)*255).clip(0,255).astype(np.uint8)
                for slot,i in enumerate(actual):
                    index=indices[slot]
                    original=self.frame(asset,index)
                    last_source=original
                    frame=original.copy()
                    if i<voice_frames:
                        y1,y2,x1,x2=coords[index];h,w=y2-y1,x2-x1
                        p=cv2.resize(pred[slot],(w,h))
                        yy,xx=np.mgrid[0:h,0:w]
                        edge=np.minimum(np.minimum(xx,w-1-xx),np.minimum(yy,h-1-yy))
                        alpha=(np.clip((yy/h-.42)/.18,0,1)*np.clip(edge/6,0,1))[...,None]
                        frame[y1:y2,x1:x2]=(p*alpha+frame[y1:y2,x1:x2]*(1-alpha)).clip(0,255).astype(np.uint8)
                    writer.write(frame)
                    if i in [0,count//2,count-1]:write_image(output/f'frame-{i:04d}.png',frame)
        finally:writer.release()
        if cancel.is_set():raise RenderCancelled()
        write_image(output/'rest.png',last_source)
        target=output/'speaking.mp4'
        subprocess.run([str(FFMPEG),'-hide_banner','-v','error','-nostdin','-n','-i',str(output/'silent.mp4'),
                        '-i',str(output/'playback.wav'),'-map','0:v:0','-map','1:a:0','-c:v','libx264',
                        '-crf','18','-preset','fast','-c:a','aac','-movflags','+faststart','-metadata',
                        'comment=AI-generated presenter; local Fay integration',str(target)],check=True)
        if cancel.is_set():raise RenderCancelled()
        report=dict(frames=count,fps=25,seconds=count/25,voice_seconds=voice_seconds,action=action,
                    wall_seconds=time.perf_counter()-started,device=self.device,precision=str(self.dtype),
                    completion='Gesture completes once; long speech holds its last pose; short speech is padded with silence',
                    cloud_render_calls=0)
        (output/'render-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        return report
