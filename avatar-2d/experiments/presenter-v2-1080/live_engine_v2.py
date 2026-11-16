"""Independent 1080p profile and forward idle playback; existing v1 engine stays intact."""
import sys,os,json,threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
from windows_runtime import prepare_runtime
prepare_runtime()
import engine_baseline as base
import torch
import numpy as np
from functools import lru_cache

class Assets(base.Assets):
    def __init__(self):
        self.profile=json.loads((ROOT/'assets/presenter-v2-1080/profile.json').read_text(encoding='utf-8'))
        self.device='cuda' if torch.cuda.is_available() else 'cpu'
        half=self.device=='cuda' and torch.cuda.get_device_capability()[0]>=8 and os.environ.get('XIAOLIN_PRECISION')!='fp32'
        self.dtype=torch.float16 if half else torch.float32
        torch.set_num_threads(4);torch.backends.cudnn.benchmark=False
        self.model=base.Wav2Lip()
        checkpoint=torch.load(ROOT/'models/wav2lip256.pth',map_location='cpu',weights_only=True)
        self.model.load_state_dict({k.removeprefix('module.'):v for k,v in checkpoint['state_dict'].items()})
        self.model=self.model.to(device=self.device,dtype=self.dtype).eval()
        self.clips={}
        for item in [self.profile['idle'],*self.profile['actions']]:
            directory=ROOT/item['avatar_dir'];coords=json.loads((directory/'coords.json').read_text(encoding='utf-8'))
            if len(coords)!=item['frames']:raise ValueError('Incomplete v2 cache: '+item['id'])
            for index in (0,len(coords)-1):
                if self.read(directory/'full_imgs'/f'{index:08d}.png').shape[:2]!=(1920,1080):raise ValueError('Unexpected resolution')
            self.clips[item['id']]=(directory,coords)
        self.full_frames={}
        for name,(directory,coords) in self.clips.items():
            if (directory/'frames.zstd.json').exists():
                from lossless_frames import LosslessFrames
                self.full_frames[name]=LosslessFrames(directory,len(coords))
            elif (directory/'frames.npy').exists():self.full_frames[name]=np.load(directory/'frames.npy',mmap_mode='r')
        self.faces={name:[self.read(directory/'face_imgs'/f'{i:08d}.png') for i in range(len(coords))]
                    for name,(directory,coords) in self.clips.items()}
        with torch.inference_mode():self.model(torch.ones(4,1,80,16,device=self.device,dtype=self.dtype),torch.ones(4,6,256,256,device=self.device,dtype=self.dtype))
        if self.device=='cuda':torch.cuda.synchronize()

    @lru_cache(maxsize=32)
    def frame(self,name,index):
        if name in self.full_frames:return self.full_frames[name][index]
        return self.read(self.clips[name][0]/'full_imgs'/f'{index:08d}.png')

class Presenter(base.Presenter):
    def __init__(self,opt,assets,callback):
        super().__init__(opt,assets,callback)
        self.pose=('idle',0);self.idle_index=0
        self.stats.update(idle_frames=0,idle_loops=0)

    def flush_talk(self,preserve_motion=False):
        with self.lock:
            self.generation+=1;self.reset_requested.set();self.preserve_motion_on_reset=preserve_motion
            self.motion_requested=None;self.pending_audio.clear();base.clear_queue(self.asr.queue)
            if not preserve_motion:
                self.motion=None
                if self.pose[0]!='idle':self.pose=('idle',0);self.idle_index=0
            player=getattr(self.output,'_player',None)
            if player is not None:base.clear_queue(player.audio._queue);base.clear_queue(player.video._queue)

    def request_motion(self,action):
        if action=='idle' or action not in self.assets.clips:raise ValueError('Unknown non-idle gesture')
        with self.lock:self.motion_requested=action

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
            if self.motion_index==len(self.assets.clips[self.motion][1]):self.motion=None;self.idle_index=0
        else:
            length=len(self.assets.clips['idle'][1]);self.pose=('idle',self.idle_index)
            self.idle_index=(self.idle_index+1)%length;self.stats['idle_frames']+=1
            if self.idle_index==0:self.stats['idle_loops']+=1
        return self.pose

options=base.options
RTCManager=base.RTCManager
session_manager=base.session_manager
