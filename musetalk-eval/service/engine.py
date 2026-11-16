"""Read-only Xiaolin assets; native LiveTalking audio/pose loop, two face engines."""
import gc
import hashlib
import time
from pathlib import Path

from bootstrap import ROOT,AVATAR,SOURCE,read_json,write_json
import cv2
import numpy as np
import torch

from live_engine import Assets as WavAssets,Presenter as WavPresenter,options,clear_queue


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class MuseAssets(WavAssets):
    def __init__(self,progress=print):
        started=time.perf_counter();torch.set_num_threads(4)
        self.kind='musetalk';self.device='cuda' if torch.cuda.is_available() else 'cpu'
        self.dtype=torch.float16 if self.device=='cuda' else torch.float32
        torch.manual_seed(42)
        if self.device=='cuda':torch.backends.cudnn.benchmark=True
        from avatars.musetalk.utils.utils import load_all_model
        from avatars.musetalk.whisper.audio2feature import Audio2Feature
        self.vae,self.unet,self.pe=load_all_model(device=torch.device(self.device))
        self.vae.vae=self.vae.vae.to(device=self.device,dtype=self.dtype)
        self.unet.model=self.unet.model.to(device=self.device,dtype=self.dtype).eval()
        self.pe=self.pe.to(device=self.device,dtype=self.dtype)
        self.audio_processor=Audio2Feature(model_path=str(ROOT/'models/whisper'))
        self.timesteps=torch.tensor([0],device=self.device)
        self.model=self.unet.model
        self.model_load_seconds=time.perf_counter()-started
        self.clips={};self.muse={}
        library_path=AVATAR/'assets/presenter-v1/motions-v1/action-library.json'
        library=read_json(library_path)
        stamp=hashlib.sha256((digest(library_path)+digest(ROOT/'models/manifest.json')+'reuse-coords-jaw-margin10-v1').encode()).hexdigest()[:16]
        parser=None;preparation=time.perf_counter();clip_reports=[]
        for item in library['actions']:
            if not item.get('speech_candidate'):continue
            name=item['id'];directory=AVATAR/'runtime/avatars'/('presenter_v1__'+name)
            coords=read_json(directory/'coords.json');self.clips[name]=(directory,coords)
            cache=ROOT/'cache'/stamp/name;metadata=cache/'metadata.json'
            if not metadata.exists():
                if parser is None:
                    from avatars.musetalk.utils.face_parsing import FaceParsing
                    parser=FaceParsing(left_cheek_width=90,right_cheek_width=90)
                cache.mkdir(parents=True,exist_ok=True);latents=[];boxes=[];mask_boxes=[]
                from avatars.musetalk.utils.blending import get_image_prepare_material
                before=time.perf_counter()
                with torch.inference_mode():
                    for i,(y1,y2,x1,x2) in enumerate(coords):
                        frame=self.read(directory/'full_imgs'/f'{i:08d}.png')
                        box=[x1,y1,x2,min(y2+10,frame.shape[0])]
                        crop=cv2.resize(frame[box[1]:box[3],box[0]:box[2]],(256,256),interpolation=cv2.INTER_LANCZOS4)
                        latent=self.vae.get_latents_for_unet(crop).cpu()
                        mask,mask_box=get_image_prepare_material(frame,box,fp=parser,mode='jaw')
                        if not np.any(mask):raise ValueError(f'Empty face mask: {name}/{i}')
                        cv2.imencode('.png',mask)[1].tofile(cache/f'mask-{i:08d}.png')
                        latents.append(latent);boxes.append(box);mask_boxes.append(list(mask_box))
                        if i%50==0:progress(f'PREPARE {name} {i+1}/{len(coords)}',flush=True)
                torch.save(torch.cat(latents),cache/'latents.pt')
                write_json(metadata,{'action':name,'frames':len(coords),'source_coords_sha256':digest(directory/'coords.json'),
                    'boxes':boxes,'mask_boxes':mask_boxes,'preparation_seconds':time.perf_counter()-before,'cache_version':stamp})
            data=read_json(metadata)
            if data['source_coords_sha256']!=digest(directory/'coords.json') or data['frames']!=len(coords):raise ValueError('Stale candidate cache')
            tensors=torch.load(cache/'latents.pt',map_location='cpu',weights_only=True)
            masks=[self.read(cache/f'mask-{i:08d}.png') for i in range(len(coords))]
            self.muse[name]=(tensors,data['boxes'],masks,data['mask_boxes'])
            clip_reports.append({k:data[k] for k in ['action','frames','source_coords_sha256','preparation_seconds']})
        del parser;gc.collect()
        if self.device=='cuda':torch.cuda.empty_cache()
        self.cache_load_or_prepare_seconds=time.perf_counter()-preparation
        self.cache_stamp=stamp
        self.loaded_seconds=time.perf_counter()-started
        write_json(ROOT/'docs/preparation.json',{'model_load_seconds':self.model_load_seconds,
            'cache_load_or_prepare_seconds':self.cache_load_or_prepare_seconds,'cache_stamp':stamp,'actions':clip_reports})
        with torch.inference_mode():
            self.predict([('welcome-wave',0)]*4,np.ones((4,50,384),np.float32))
        progress('MUSE_ASSETS_READY',flush=True)

    def predict(self,tokens,features):
        latent=torch.stack([self.muse[name][0][i] for name,i in tokens]).to(device=self.device,dtype=self.dtype)
        a=torch.as_tensor(np.stack(features),device=self.device,dtype=self.dtype)
        a=self.pe(a)
        pred=self.unet.model(latent,self.timesteps,encoder_hidden_states=a).sample
        return self.vae.decode_latents(pred)


def load_assets(backend):
    started=time.perf_counter()
    if backend=='musetalk':assets=MuseAssets()
    elif backend=='wav2lip':
        assets=WavAssets();assets.kind='wav2lip';assets.loaded_seconds=time.perf_counter()-started
    else:raise ValueError('Unknown backend')
    if torch.cuda.is_available():torch.cuda.synchronize()
    assets.ready_seconds=time.perf_counter()-started
    return assets


class EvalPresenter(WavPresenter):
    def __init__(self,opt,assets,callback):
        super().__init__(opt,assets,callback)
        self.video_callback=None;self.audio_callback=None
        self._batch_tokens=[];self._token_index=0
        self.stats.update(inference_batches=0,feature_seconds=0.,feature_steps=0,pose_trace=[])
        if assets.kind=='musetalk':
            from avatars.audio_features.whisper import WhisperASR
            self.asr=WhisperASR(opt,self,assets.audio_processor);self.asr.warm_up()
        step=self.asr.run_step
        def timed_step():
            begin=time.perf_counter();step()
            self.stats['feature_seconds']+=time.perf_counter()-begin;self.stats['feature_steps']+=1
        self.asr.run_step=timed_step
        push_video=self.output.push_video_frame
        def video(frame):
            if self.video_callback:self.video_callback(frame,self._emitting_pose,self.speaking)
            push_video(frame)
        self.output.push_video_frame=video

    def _advance(self,packets):
        token=super()._advance(packets)
        return token

    def _infer(self,tokens,features):
        if self.assets.kind=='wav2lip':return super()._infer(tokens,features)
        before=time.perf_counter()
        with torch.inference_mode():pred=self.assets.predict(tokens,features)
        self.stats['inference_seconds']+=time.perf_counter()-before
        self.stats['inference_frames']+=len(tokens);self.stats['inference_batches']+=1
        return pred

    def _compose(self,token,prediction):
        # Carry the exact pose associated with this emitted frame, not the last batch pose.
        self._emitting_pose=token
        if prediction is None or self.assets.kind=='wav2lip':return super()._compose(token,prediction)
        from avatars.musetalk.myutil import get_image_blending
        name,index=token;_,boxes,masks,mask_boxes=self.assets.muse[name]
        x1,y1,x2,y2=boxes[index]
        face=cv2.resize(prediction,(x2-x1,y2-y1))
        return get_image_blending(self.assets.frame(name,index).copy(),face,boxes[index],masks[index],mask_boxes[index])

    def snapshot(self):
        return {k:v for k,v in self.stats.items() if k!='pose_trace'}


def make_presenter(assets,callback,sessionid='eval'):
    opt=options(sessionid)
    return EvalPresenter(opt,assets,callback)
