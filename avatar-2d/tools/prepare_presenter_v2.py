"""Prepare a separate native-1080p five-clip profile, preserving all v1 assets."""
from windows_runtime import prepare_runtime
prepare_runtime()
import hashlib,json,subprocess,sys,time
from pathlib import Path
import cv2,numpy as np,torch
ROOT=Path(__file__).resolve().parents[1];ASSET=ROOT/'assets/presenter-v2-1080'
CACHE=ROOT/'runtime/presenter-v2-1080/avatars'
FFMPEG=ROOT.parent/'fay-ue4/runtime/fay-local/app/test/ovr_lipsync/ffmpeg/bin/ffmpeg.exe'
SOURCE=Path(json.loads((ROOT/'source-manifest.json').read_text(encoding='utf-8'))['source_directory']);sys.path.insert(0,str(SOURCE))
from avatars.wav2lip.face_detection.detection.sfd import FaceDetector
SPECS=[('idle','自然待机','7299',30),('welcome-wave','迎宾挥手','1528',7),
       ('goodbye-wave','告别挥手','7502',7),('explain-open-palms','右手伸手讲解','3912',7),
       ('acknowledge-nod','轻微点头','1769',4)]
def write(path,image):
    ok,data=cv2.imencode('.png',image,[cv2.IMWRITE_PNG_COMPRESSION,2]);assert ok;path.write_bytes(data.tobytes())
def read(path):return cv2.imdecode(np.frombuffer(path.read_bytes(),np.uint8),cv2.IMREAD_COLOR)
def foreground(frame):
    mask=(frame.max(axis=2)>18).astype(np.uint8);n,labels,stats,_=cv2.connectedComponentsWithStats(mask)
    accepted=[i for i in range(1,n) if stats[i,cv2.CC_STAT_AREA]>1000]
    return cv2.boundingRect(np.isin(labels,accepted).astype(np.uint8))
def main():
    assert torch.cuda.is_available(),'CUDA required for isolated preprocessing'
    torch.set_num_threads(4);torch.backends.cudnn.benchmark=False
    detector=FaceDetector(device='cuda',path_to_detector=str(ROOT/'models/s3fd-619a316812.pth'))
    cap=cv2.VideoCapture(str(ASSET/'incoming-7299/source.mp4'));ok,reference=cap.read();cap.release();assert ok
    reference=cv2.resize(reference,(1080,1920),interpolation=cv2.INTER_LANCZOS4)
    write(ASSET/'reference-frame.png',reference);rx,ry,rw,rh=foreground(reference)
    prepared=ASSET/'prepared';prepared.mkdir(exist_ok=True);items=[]
    for name,label,key,seconds in SPECS:
        video=ASSET/f'incoming-{key}/source.mp4';digest=hashlib.sha256(video.read_bytes()).hexdigest()
        directory=CACHE/name;directory.mkdir(parents=True,exist_ok=True)
        marker=directory/'prepared.json'
        if marker.exists():
            item=json.loads(marker.read_text(encoding='utf-8'));assert item['source_sha256']==digest
            items.append(item);print('Reused '+name,flush=True);continue
        for sub in ('full_imgs','face_imgs'):(directory/sub).mkdir(exist_ok=True)
        cap=cv2.VideoCapture(str(video));ok,first=cap.read();cap.release();assert ok
        first=cv2.resize(first,(1080,1920),interpolation=cv2.INTER_LANCZOS4)
        sx,sy,sw,sh=foreground(first);scale=rh/sh
        matrix=np.array([[scale,0,rx+rw/2-scale*(sx+sw/2)],[0,scale,ry+rh-scale*(sy+sh)]],np.float64)
        boxes=[];batch=[];count=0;started=time.perf_counter()
        def detect(frames):
            reduced=np.stack([cv2.resize(f,(360,640)) for f in frames])
            with torch.inference_mode():predictions=detector.detect_from_batch(reduced[...,::-1].copy())
            for prediction in predictions:
                candidates=[p for p in prediction if p[1]<256]
                if not candidates:raise RuntimeError(f'No face: {name}/{len(boxes)}')
                box=max(candidates,key=lambda p:(p[2]-p[0])*(p[3]-p[1]))
                x1,y1,x2,y2=[round(float(v)*3) for v in box[:4]]
                boxes.append([max(0,x1),max(0,y1),min(1080,x2),min(1920,y2+15)])
        with (prepared/f'{name}-decode.log').open('wb') as errors:
            process=subprocess.Popen([str(FFMPEG),'-hide_banner','-v','error','-nostdin','-threads','2','-i',str(video),
                '-vf','fps=25,scale=1080:1920:flags=lanczos','-t',str(seconds),'-an','-f','rawvideo','-pix_fmt','bgr24','-'],stdout=subprocess.PIPE,stderr=errors)
            while True:
                data=process.stdout.read(1080*1920*3)
                if not data:break
                if len(data)!=1080*1920*3:raise RuntimeError('Truncated raw frame')
                frame=np.frombuffer(data,np.uint8).reshape(1920,1080,3)
                aligned=cv2.warpAffine(frame,matrix,(1080,1920),flags=cv2.INTER_LANCZOS4,borderValue=0)
                write(directory/'full_imgs'/f'{count:08d}.png',aligned);batch.append(aligned);count+=1
                if len(batch)==4:detect(batch);batch=[]
                if count%100==0:print(f'{name}: extracted/detected {count}/{seconds*25}',flush=True)
            process.stdout.close();code=process.wait()
        if batch:detect(batch)
        assert code==0 and count==seconds*25 and len(boxes)==count,(name,code,count)
        raw=np.asarray(boxes,float);smooth=np.array([raw[max(0,i-2):min(count,i+3)].mean(axis=0) for i in range(count)]).round().astype(int)
        coords=[]
        for i,(x1,y1,x2,y2) in enumerate(smooth):
            frame=read(directory/'full_imgs'/f'{i:08d}.png');crop=frame[y1:y2,x1:x2];assert crop.size
            write(directory/'face_imgs'/f'{i:08d}.png',cv2.resize(crop,(256,256)))
            coords.append([int(y1),int(y2),int(x1),int(x2)])
        (directory/'coords.json').write_text(json.dumps(coords),encoding='utf-8')
        target=prepared/(name+'.mp4')
        subprocess.run([str(FFMPEG),'-hide_banner','-loglevel','error','-nostdin','-y','-framerate','25','-i',str(directory/'full_imgs/%08d.png'),
            '-an','-c:v','libx264','-crf','15','-preset','fast','-threads','4','-movflags','+faststart',str(target)],check=True)
        item=dict(id=name,label=label,source_id=key,source_sha256=digest,frames=count,seconds=seconds,fps=25,width=1080,height=1920,
            avatar_dir=directory.relative_to(ROOT).as_posix(),video=target.relative_to(ROOT).as_posix(),
            video_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),constant_transform=matrix.tolist(),
            source_foreground_box=[sx,sy,sw,sh],reference_foreground_box=[rx,ry,rw,rh],
            original_audio_removed=True,speech_candidate=True,loop=name=='idle',loop_mode='forward',
            preprocessing_seconds=round(time.perf_counter()-started,3),face_size=256,face_detector='official S3FD')
        marker.write_text(json.dumps(item,ensure_ascii=False,indent=2),encoding='utf-8');items.append(item)
        print('PREPARED '+json.dumps({k:item[k] for k in ('id','frames','width','height','preprocessing_seconds')}),flush=True)
    profile=dict(schema_version=2,name='presenter-v2-1080',width=1080,height=1920,fps=25,idle=next(i for i in items if i['id']=='idle'),
        actions=[i for i in items if i['id']!='idle'],status='PREPARED_VISUAL_AND_LIPSYNC_REVIEW_REQUIRED')
    (ASSET/'profile.json').write_text(json.dumps(profile,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PROFILE_READY',flush=True)
if __name__=='__main__':main()
