"""Experimental 50 fps renderer, 20ms PCM unchanged, isolated from production."""
import sys,json,types,os,time
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'presenter-v2-1080'))
import live_engine_v2 as previous
import numpy as np
import cv2
import torch
cv2.setNumThreads(1)
from avatars.wav2lip import audio
from server import webrtc
from idle_scheduler import IdleScheduler
from render50 import render

ROOT=previous.ROOT;base=previous.base
webrtc.VIDEO_PTIME=.02

def features50(self):
    for _ in range(self.batch_size):
        packet=self.get_audio_frame();self.frames.append(packet.data);self.output_queue.put(packet)
    mel=audio.melspectrogram(np.concatenate(self.frames))
    chunks=[]
    for i in range(self.batch_size):
        start=min(int((self.stride_left_size+i)*80/50),mel.shape[1]-16)
        chunks.append(mel[:,start:start+16])
    self.feat_queue.put(chunks)
    self.frames=self.frames[-(self.stride_left_size+self.stride_right_size):]

def desc(frame):
    return cv2.resize(frame[80:1200,250:830],(58,112)).astype(np.float32)

class Assets(previous.Assets):
    def __init__(self):
        super().__init__()
        if os.environ.get('XIAOLIN_50_PRECISION')=='fp16':
            self.dtype=torch.float16;self.model=self.model.to(dtype=self.dtype)
            torch.backends.cudnn.benchmark=True;torch.backends.cudnn.benchmark_limit=4
            with torch.inference_mode():
                self.model(torch.ones(4,1,80,16,device=self.device,dtype=self.dtype),torch.ones(4,6,256,256,device=self.device,dtype=self.dtype))
            torch.cuda.synchronize()
        self.cache=ROOT/'runtime/presenter-50fps'
        self.idle_plan=json.loads((self.cache/'idle-plan.json').read_text())
        self.full_frames={};self.faces={};self.clips={}
        for item in [self.profile['idle'],*self.profile['actions']]:
            name=item['id'];directory=self.cache/name
            coords=json.loads((directory/'coords.json').read_text())
            self.clips[name]=(directory,coords)
            self.full_frames[name]=np.load(directory/'frames.npy',mmap_mode='r')
            self.faces[name]=np.load(directory/'faces.npy',mmap_mode='r')
        self.start_descriptors={s['start']:desc(self.full_frames['idle'][s['start']]) for s in self.idle_plan['segments']}

    def frame(self,name,index):return self.full_frames[name][index]

class Presenter(previous.Presenter):
    def __init__(self,opt,assets,callback):
        super().__init__(opt,assets,callback)
        # Keep BaseAvatar's PCM chunk=320 (20ms). Only mel/video cadence changes.
        assert self.chunk==320 and self.asr.chunk==320
        self.asr.fps=50;self.asr.run_step=types.MethodType(features50,self.asr)
        self.idle_scheduler=IdleScheduler(assets.idle_plan['segments'],self._distance)
        self.stats.update(idle_segment_switches=0,video_fps=50)
        # Avoid recomputing 1080p face blend geometry on every video frame.
        self._blend_masks={}
        def instrument(target,name,label):
            original=getattr(target,name)
            def measured(*args,**kwargs):
                began=time.perf_counter()
                try:return original(*args,**kwargs)
                finally:
                    self.stats[label+'_seconds']=self.stats.get(label+'_seconds',0)+time.perf_counter()-began
                    self.stats[label+'_calls']=self.stats.get(label+'_calls',0)+1
            setattr(target,name,measured)
        for target,name,label in [(self.asr,'run_step','mel'),(self,'_infer','infer'),(self,'_compose','compose'),(self.output,'push_video_frame','push')]:
            instrument(target,name,label)

    def _compose(self,token,prediction):
        name,index=token;frame=self.assets.frame(name,index).copy()
        if prediction is not None:
            y1,y2,x1,x2=self.assets.clips[name][1][index];h,w=y2-y1,x2-x1
            key=(h,w)
            if key not in self._blend_masks:
                yy,xx=np.mgrid[0:h,0:w]
                edge=np.minimum(np.minimum(xx,w-1-xx),np.minimum(yy,h-1-yy))
                self._blend_masks[key]=(np.clip((yy/h-.42)/.18,0,1)*np.clip(edge/6,0,1))[...,None]
            alpha=self._blend_masks[key];patch=cv2.resize(prediction,(w,h))
            frame[y1:y2,x1:x2]=(patch*alpha+frame[y1:y2,x1:x2]*(1-alpha)).astype(np.uint8)
        return frame

    def _distance(self,token,index):
        return np.mean(np.abs(desc(self.assets.frame(*token))-self.assets.start_descriptors[index]))

    def flush_talk(self,preserve_motion=False):
        with self.lock:
            self.generation+=1;self.reset_requested.set();self.preserve_motion_on_reset=preserve_motion
            self.motion_requested=None;self.pending_audio.clear();base.clear_queue(self.asr.queue)
            if not preserve_motion:self.motion=None
            player=getattr(self.output,'_player',None)
            if player is not None:base.clear_queue(player.audio._queue);base.clear_queue(player.video._queue)

    def _advance(self,packets):
        for packet in packets:
            info=packet.userdata
            if info.get('status')=='start' and info.get('action') in self.assets.clips and info['action']!='idle':
                self.motion=info['action'];self.motion_index=0;self.stats['last_motion']=self.motion;info['motion_start']=self.motion
        with self.lock:
            if self.motion_requested:
                self.motion=self.motion_requested;self.motion_index=0;self.stats['last_motion']=self.motion;self.motion_requested=None
        if self.motion:
            self.pose=(self.motion,self.motion_index);self.motion_index+=1;self.stats['motion_frames']+=1
            if self.motion_index==len(self.assets.clips[self.motion][1]):self.motion=None
        else:
            index=self.idle_scheduler.next(self.pose,from_action=self.pose[0]!='idle')
            self.pose=('idle',index);self.stats['idle_frames']+=1
            self.stats['idle_loops']=self.idle_scheduler.completed
            self.stats['idle_segment_switches']=len(self.idle_scheduler.history)
        return self.pose

    render=render

options=previous.options
RTCManager=previous.RTCManager
session_manager=previous.session_manager
