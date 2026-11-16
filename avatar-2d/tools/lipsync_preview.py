"""Real Wav2Lip256 local inference using retained official LiveTalking modules."""
from windows_runtime import prepare_runtime
prepare_runtime()

import argparse
import hashlib
import json
import math
import pickle
import subprocess
import sys
import time
from pathlib import Path

import torch
import cv2
import numpy as np
import soundfile as sf

ROOT=Path(__file__).resolve().parents[1]
SOURCE=Path(json.loads((ROOT/'source-manifest.json').read_text(encoding='utf-8'))['source_directory'])
sys.path.insert(0,str(SOURCE))
from avatars.wav2lip.models import Wav2Lip
from avatars.wav2lip import audio
from avatars.wav2lip.face_detection.detection.sfd import FaceDetector


def write_image(path,frame):
    ok,data=cv2.imencode('.png',frame)
    if not ok:raise RuntimeError('PNG encoding failed')
    path.write_bytes(data.tobytes())


def read_image(path):
    frame=cv2.imdecode(np.frombuffer(path.read_bytes(),np.uint8),cv2.IMREAD_COLOR)
    if frame is None:raise RuntimeError('Invalid frame '+str(path))
    return frame


def prepare_avatar(device, video=None, avatar_id='presenter_v1'):
    directory=ROOT/'runtime/avatars'/avatar_id
    marker=directory/'prepared.json'
    video=video or ROOT/'assets/presenter-v1/idle-fullbody-20s-25fps-v1.mp4'
    digest=hashlib.sha256(video.read_bytes()).hexdigest()
    if marker.exists():
        report=json.loads(marker.read_text(encoding='utf-8'))
        if report['source_sha256']!=digest:raise ValueError('Existing avatar belongs to another video')
        return directory,report
    directory.mkdir(parents=True,exist_ok=True)
    for name in ['full_imgs','face_imgs']:(directory/name).mkdir(exist_ok=True)
    detector=FaceDetector(device=device,path_to_detector=str(ROOT/'models/s3fd-619a316812.pth'))
    capture=cv2.VideoCapture(str(video));boxes=[];count=0;batch=[];started=time.perf_counter()
    expected=int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if not capture.isOpened() or expected<1:raise ValueError('Cannot open avatar video')
    if (int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))!=(720,1280):
        raise ValueError('Avatar video must be normalized to 720x1280')

    def detect(frames):
        reduced=np.stack([cv2.resize(f,(360,640)) for f in frames])
        with torch.inference_mode():predictions=detector.detect_from_batch(reduced[...,::-1].copy())
        for frame,pred in zip(frames,predictions):
            candidates=[p for p in pred if p[1]<256]
            if not candidates:raise ValueError('No frontal face at frame '+str(len(boxes)))
            box=max(candidates,key=lambda r:(r[2]-r[0])*(r[3]-r[1]))
            x1,y1,x2,y2=[int(round(float(v)*2)) for v in box[:4]]
            boxes.append([max(0,x1),max(0,y1),min(720,x2),min(1280,y2+10)])

    while True:
        ok,frame=capture.read()
        if not ok:break
        write_image(directory/'full_imgs'/('{:08d}.png'.format(count)),frame)
        count+=1;batch.append(frame)
        if len(batch)==4:detect(batch);batch=[]
    if batch:detect(batch)
    capture.release()
    if count!=expected or len(boxes)!=count:raise ValueError('Incomplete avatar frame extraction')
    raw=np.asarray(boxes,dtype=np.float64)
    smooth=np.stack([raw[max(0,i-2):min(count,i+3)].mean(axis=0) for i in range(count)]).round().astype(int)
    coords=[]
    for i,(x1,y1,x2,y2) in enumerate(smooth):
        frame=read_image(directory/'full_imgs'/('{:08d}.png'.format(i)))
        crop=frame[y1:y2,x1:x2]
        if crop.size==0:raise ValueError('Empty face crop')
        write_image(directory/'face_imgs'/('{:08d}.png'.format(i)),cv2.resize(crop,(256,256)))
        coords.append((int(y1),int(y2),int(x1),int(x2)))
    # This pickle is produced locally from plain coordinates, never downloaded.
    with (directory/'coords.pkl').open('wb') as out:pickle.dump(coords,out)
    (directory/'coords.json').write_text(json.dumps(coords),encoding='utf-8')
    report=dict(frames=count,width=720,height=1280,face_size=256,detector='official S3FD',device=device,
                preprocessing_seconds=time.perf_counter()-started,source_sha256=digest,
                bbox_range=dict(min=smooth.min(axis=0).tolist(),max=smooth.max(axis=0).tolist()))
    marker.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Avatar prepared:',json.dumps(report),flush=True)
    del detector
    if device=='cuda':torch.cuda.empty_cache()
    return directory,report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default='preview-v1')
    parser.add_argument('--device',default='cuda',choices=['cuda','cpu'])
    parser.add_argument('--batch-size',type=int,default=8)
    parser.add_argument('--seconds',type=float,default=0)
    parser.add_argument('--precision',default='auto',choices=['auto','fp32','fp16'])
    parser.add_argument('--motion',default='idle',choices=['idle','welcome-wave','goodbye-wave','explain-open-palms','acknowledge-nod'])
    args=parser.parse_args()
    if args.device=='cuda' and not torch.cuda.is_available():raise RuntimeError('CUDA not available')
    torch.set_num_threads(4)
    half=args.precision=='fp16' or (args.precision=='auto' and args.device=='cuda' and torch.cuda.get_device_capability(0)[0]>=8)
    dtype=torch.float16 if half else torch.float32
    if args.device=='cuda':torch.backends.cudnn.benchmark=True
    motion=None
    avatar_id='presenter_v1'
    if args.motion!='idle':
        library=json.loads((ROOT/'assets/presenter-v1/motions-v1/action-library.json').read_text(encoding='utf-8'))
        motion=next(item for item in library['actions'] if item['id']==args.motion)
        if not motion['speech_candidate']:raise ValueError('This motion is not eligible for speech inference')
        avatar_id+='__'+args.motion
    directory,avatar_report=prepare_avatar(args.device,ROOT/motion['video'] if motion else None,avatar_id)
    avatar_frames=avatar_report['frames']
    output=ROOT/'outputs'/args.output
    output.mkdir(parents=True,exist_ok=False)
    weight=ROOT/'models/wav2lip256.pth'
    checkpoint=torch.load(weight,map_location='cpu',weights_only=True)
    state=checkpoint['state_dict'] if 'state_dict' in checkpoint else checkpoint
    state={k.removeprefix('module.'):v for k,v in state.items()}
    model=Wav2Lip();model.load_state_dict(state,strict=True);model=model.to(device=args.device,dtype=dtype).eval()
    waveform,sample_rate=sf.read(ROOT/'assets/calibration-speech-16k-v1.wav',dtype='float32')
    if sample_rate!=16000 or waveform.ndim!=1:raise ValueError('Expected PCM mono 16 kHz')
    if args.seconds>0:waveform=waveform[:round(args.seconds*sample_rate)]
    # Gesture clips play once. Longer speech returns to idle in a future live controller,
    # rather than looping a greeting or an explanation gesture in this offline test.
    if motion:waveform=waveform[:round(avatar_frames/25*sample_rate)]
    sf.write(output/'driving-audio.wav',waveform,16000,subtype='PCM_16')
    mel=audio.melspectrogram(waveform)
    if not np.isfinite(mel).all():raise ValueError('Invalid audio features')
    count=math.ceil(len(waveform)/16000*25)
    coords=json.loads((directory/'coords.json').read_text(encoding='utf-8'))
    with torch.inference_mode():
        model(torch.ones(args.batch_size,1,80,16,device=args.device,dtype=dtype),torch.ones(args.batch_size,6,256,256,device=args.device,dtype=dtype))
    if args.device=='cuda':torch.cuda.synchronize();torch.cuda.reset_peak_memory_stats()
    writer=cv2.VideoWriter(str(output/'silent.mp4'),cv2.VideoWriter_fourcc(*'mp4v'),25,(720,1280))
    if not writer.isOpened():raise RuntimeError('Video encoder did not open')
    model_seconds=0;started=time.perf_counter();samples=[];difference=[]
    for begin in range(0,count,args.batch_size):
        indices=list(range(begin,min(count,begin+args.batch_size)))
        frames=[read_image(directory/'full_imgs'/('{:08d}.png'.format(i%avatar_frames))) for i in indices]
        faces=[read_image(directory/'face_imgs'/('{:08d}.png'.format(i%avatar_frames))) for i in indices]
        images=np.asarray(faces);masked=images.copy();masked[:,128:]=0
        inputs=np.concatenate([masked,images],axis=3).astype(np.float32)/255
        features=[]
        for i in indices:
            start=min(int(i*80/25),mel.shape[1]-16);features.append(mel[:,start:start+16])
        x=torch.from_numpy(inputs.transpose(0,3,1,2)).to(device=args.device,dtype=dtype)
        a=torch.from_numpy(np.asarray(features,dtype=np.float32)[:,None]).to(device=args.device,dtype=dtype)
        if args.device=='cuda':torch.cuda.synchronize()
        tick=time.perf_counter()
        with torch.inference_mode():pred=model(a,x)
        if args.device=='cuda':torch.cuda.synchronize()
        model_seconds+=time.perf_counter()-tick
        if not torch.isfinite(pred).all():raise RuntimeError('Non-finite model output')
        pred=(pred.float().cpu().numpy().transpose(0,2,3,1)*255).clip(0,255).astype(np.uint8)
        for i,frame,prediction in zip(indices,frames,pred):
            y1,y2,x1,x2=coords[i%avatar_frames];height,width=y2-y1,x2-x1
            prediction=cv2.resize(prediction,(width,height))
            before=frame[y1:y2,x1:x2].copy()
            # Feather lower-face changes into the source, preserving eyes and hair.
            yy,xx=np.mgrid[0:height,0:width]
            vertical=np.clip((yy/height-.42)/.18,0,1)
            edge=np.minimum(np.minimum(xx,width-1-xx),np.minimum(yy,height-1-yy))
            alpha=(vertical*np.clip(edge/6,0,1))[...,None]
            blended=(prediction*alpha+before*(1-alpha)).clip(0,255).astype(np.uint8)
            frame[y1:y2,x1:x2]=blended
            difference.append(float(np.abs(blended.astype(float)-before).mean()))
            writer.write(frame)
            if i in [0,25,50,100,200,300,count-1]:
                write_image(output/('frame-{:04d}.png'.format(i)),frame)
                write_image(output/('face-{:04d}.png'.format(i)),blended)
                samples.append(i)
        print('Inferred {}/{} frames'.format(min(count,begin+args.batch_size),count),flush=True)
    writer.release()
    elapsed=time.perf_counter()-started
    ffmpeg=ROOT.parent/'fay-ue4/runtime/fay-local/app/test/ovr_lipsync/ffmpeg/bin/ffmpeg.exe'
    target=output/'presenter-speaking.mp4'
    subprocess.run([str(ffmpeg),'-hide_banner','-loglevel','error','-nostdin','-n','-i',str(output/'silent.mp4'),
                    '-i',str(output/'driving-audio.wav'),'-map','0:v:0','-map','1:a:0','-c:v','libx264','-crf','18',
                    '-preset','medium','-c:a','aac','-b:a','128k','-movflags','+faststart',
                    '-metadata','comment=AI-generated presenter; local Wav2Lip technical preview',str(target)],check=True)
    report=dict(status='LOCAL_LIPSYNC_RENDERED_REVIEW_REQUIRED',framework_commit=json.loads((ROOT/'source-manifest.json').read_text(encoding='utf-8'))['commit'],
                model_sha256=hashlib.sha256(weight.read_bytes()).hexdigest(),torch=torch.__version__,device=args.device,precision=str(dtype),batch_size=args.batch_size,
                gpu=torch.cuda.get_device_name(0) if args.device=='cuda' else None,frames=count,video_fps=25,
                audio_seconds=len(waveform)/16000,wall_seconds=elapsed,network_inference_seconds=model_seconds,
                network_fps=count/model_seconds,pipeline_fps=count/elapsed,
                peak_allocated_gpu_mb=torch.cuda.max_memory_allocated()/2**20 if args.device=='cuda' else None,
                mean_face_pixel_change=float(np.mean(difference)),saved_frames=samples,avatar=avatar_report,
                target_hardware_verified=False,streaming_verified=False,cloud_calls=0,
                timing_scope='Measured inference loop with frame reads, compositing and intermediate encoding; excludes avatar preparation, warmup and final H264/AAC encoding.',
                motion=args.motion,avatar_id=avatar_id,
                output=str(target),acceptance='Visual and human audio/phoneme review still required; local test only')
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
