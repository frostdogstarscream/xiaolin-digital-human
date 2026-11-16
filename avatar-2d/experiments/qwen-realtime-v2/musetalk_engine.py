"""MuseTalk 1.5 for the existing 1080p realtime presenter."""
import hashlib,json,os,time
from pathlib import Path
import cv2
import numpy as np
import torch
import live_engine_v2 as existing

base=existing.base
ROOT=existing.ROOT
MUSE=Path(os.environ.get('MUSE_ROOT','/muse'))
CACHE=ROOT/'runtime/musetalk-v2-1080'

class Assets(existing.Assets):
    def __init__(self):
        os.chdir(MUSE)
        self.profile=json.loads((ROOT/'assets/presenter-v2-1080/profile.json').read_text())
        self.device='cuda' if torch.cuda.is_available() else 'cpu'
        self.dtype=torch.float16 if self.device=='cuda' else torch.float32
        torch.set_num_threads(4)
        torch.backends.cudnn.benchmark=True
        from avatars.musetalk.utils.utils import load_all_model
        from avatars.musetalk.whisper.audio2feature import Audio2Feature
        self.vae,self.unet,self.pe=load_all_model(device=torch.device(self.device))
        self.vae.vae.to(device=self.device,dtype=self.dtype)
        self.unet.model.to(device=self.device,dtype=self.dtype).eval()
        self.pe.to(device=self.device,dtype=self.dtype)
        self.model=self.unet.model
        self.audio_processor=Audio2Feature(model_path=str(MUSE/'models/whisper'))
        self.timesteps=torch.tensor([0],device=self.device)
        self.clips={};self.full_frames={};self.muse={}
        items=[self.profile['idle'],*self.profile['actions']]
        for item in items:
            directory=ROOT/item['avatar_dir']
            coords=json.loads((directory/'coords.json').read_text())
            assert len(coords)==item['frames']
            self.clips[item['id']]=(directory,coords)
            if (directory/'frames.npy').exists():self.full_frames[item['id']]=np.load(directory/'frames.npy',mmap_mode='r')
        parser=None
        model_digest=hashlib.sha256((MUSE/'models/manifest.json').read_bytes()).hexdigest()
        for name,(directory,coords) in self.clips.items():
            stamp=hashlib.sha256(((directory/'coords.json').read_text()+model_digest+'jaw-margin10-v1').encode()).hexdigest()[:16]
            cache=CACHE/name/stamp;cache.mkdir(parents=True,exist_ok=True)
            metadata=cache/'metadata.json'
            if not metadata.exists():
                if parser is None:
                    from avatars.musetalk.utils.face_parsing import FaceParsing
                    parser=FaceParsing(left_cheek_width=90,right_cheek_width=90)
                from avatars.musetalk.utils.blending import get_image_prepare_material
                latents=[];boxes=[];mask_boxes=[]
                with torch.inference_mode():
                    for i,(y1,y2,x1,x2) in enumerate(coords):
                        frame=self.frame(name,i)
                        box=[x1,y1,x2,min(y2+10,frame.shape[0])]
                        crop=cv2.resize(frame[box[1]:box[3],box[0]:box[2]],(256,256),interpolation=cv2.INTER_LANCZOS4)
                        latents.append(self.vae.get_latents_for_unet(crop).cpu())
                        mask,mask_box=get_image_prepare_material(frame,box,fp=parser,mode='jaw')
                        assert np.any(mask),(name,i)
                        cv2.imencode('.png',mask)[1].tofile(cache/f'mask-{i:08d}.png')
                        boxes.append(box);mask_boxes.append(list(mask_box))
                        if i%50==0:print('MUSE_PREPARE',name,i+1,len(coords),flush=True)
                torch.save(torch.cat(latents),cache/'latents.pt')
                metadata.write_text(json.dumps({'boxes':boxes,'mask_boxes':mask_boxes,'frames':len(coords),'stamp':stamp}))
            data=json.loads(metadata.read_text());assert data['frames']==len(coords)
            self.muse[name]=(torch.load(cache/'latents.pt',map_location='cpu',weights_only=True),data['boxes'],cache,data['mask_boxes'])
        del parser
        self.frame.cache_clear()
        with torch.inference_mode():self.predict([('idle',0)]*4,np.ones((4,50,384),np.float32))
        torch.cuda.empty_cache()
        print('MUSE_1080_ASSETS_READY',flush=True)

    def predict(self,tokens,features):
        latent=torch.stack([self.muse[name][0][i] for name,i in tokens]).to(self.device,self.dtype)
        audio=self.pe(torch.as_tensor(np.asarray(features),device=self.device,dtype=self.dtype))
        prediction=self.unet.model(latent,self.timesteps,encoder_hidden_states=audio).sample
        return self.vae.decode_latents(prediction)

class Presenter(existing.Presenter):
    def __init__(self,opt,assets,callback):
        super().__init__(opt,assets,callback)
        from avatars.audio_features.whisper import WhisperASR
        self.asr=WhisperASR(opt,self,assets.audio_processor)
        self.asr.warm_up()
        self.stats.update(lipsync_backend='musetalk-1.5',decoder='original')

    def _infer(self,tokens,features):
        started=time.perf_counter()
        with torch.inference_mode():prediction=self.assets.predict(tokens,features)
        self.stats['inference_seconds']+=time.perf_counter()-started
        self.stats['inference_frames']+=len(tokens)
        return prediction

    def _compose(self,token,prediction):
        if prediction is None:return self.assets.frame(*token).copy()
        from avatars.musetalk.myutil import get_image_blending
        name,index=token
        _,boxes,cache,mask_boxes=self.assets.muse[name]
        box=boxes[index];x1,y1,x2,y2=box
        face=cv2.resize(prediction,(x2-x1,y2-y1))
        mask=cv2.imdecode(np.fromfile(cache/f'mask-{index:08d}.png',np.uint8),cv2.IMREAD_COLOR)
        return get_image_blending(self.assets.frame(name,index).copy(),face,box,mask,mask_boxes[index])

options=existing.options

