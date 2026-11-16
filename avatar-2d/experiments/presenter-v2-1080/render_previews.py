"""Render real Wav2Lip previews from frozen audio at native 1080x1920."""
from pathlib import Path
import sys,time,json,hashlib,subprocess
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
from windows_runtime import prepare_runtime
prepare_runtime()
import cv2,numpy as np,soundfile as sf,torch
import live_engine_v2 as engine
from avatars.wav2lip import audio
OUT=ROOT/'outputs/presenter-v2-1080';OUT.mkdir(exist_ok=True)
FFMPEG=ROOT.parent/'fay-ue4/runtime/fay-local/app/test/ovr_lipsync/ffmpeg/bin/ffmpeg.exe'
def main():
    assets=engine.Assets();p=object.__new__(engine.Presenter);p.assets=assets
    fixture=ROOT/'assets/calibration-speech-16k-v1.wav';wave,rate=sf.read(fixture,dtype='float32');assert rate==16000 and wave.ndim==1
    reports=[]
    for name in ['idle','welcome-wave','goodbye-wave','explain-open-palms','acknowledge-nod']:
        folder=OUT/name;folder.mkdir(exist_ok=True);marker=folder/'report.json'
        if marker.exists():reports.append(json.loads(marker.read_text(encoding='utf-8')));continue
        seconds=10 if name=='idle' else len(assets.clips[name][1])/25;count=round(seconds*25)
        driving=wave[:round(seconds*rate)];sf.write(folder/'driving.wav',driving,rate,subtype='PCM_16');mel=audio.melspectrogram(driving)
        target=folder/'speaking-1080p.mp4'
        errors=(folder/'encode.log').open('wb')
        process=subprocess.Popen([str(FFMPEG),'-hide_banner','-v','error','-nostdin','-y','-f','rawvideo','-pix_fmt','bgr24','-s','1080x1920','-r','25','-i','-',
            '-i',str(folder/'driving.wav'),'-map','0:v:0','-map','1:a:0','-c:v','libx264','-crf','16','-preset','fast','-threads','4',
            '-c:a','aac','-b:a','128k','-shortest','-movflags','+faststart',str(target)],stdin=subprocess.PIPE,stderr=errors)
        started=time.perf_counter();network=0.;faces=[]
        try:
            for begin in range(0,count,4):
                indices=list(range(begin,min(count,begin+4)));tokens=[(name,i) for i in indices]
                crops=np.asarray([assets.faces[name][i] for i in indices]);masked=crops.copy();masked[:,128:]=0
                image=np.concatenate([masked,crops],axis=3).astype(np.float32)/255
                features=np.asarray([mel[:,min(int(i*80/25),mel.shape[1]-16):min(int(i*80/25),mel.shape[1]-16)+16] for i in indices],np.float32)[:,None]
                x=torch.from_numpy(image.transpose(0,3,1,2).copy()).to(device=assets.device,dtype=assets.dtype)
                a=torch.from_numpy(features.copy()).to(device=assets.device,dtype=assets.dtype)
                if assets.device=='cuda':torch.cuda.synchronize()
                tick=time.perf_counter()
                with torch.inference_mode():prediction=assets.model(a,x)
                if assets.device=='cuda':torch.cuda.synchronize()
                network+=time.perf_counter()-tick
                if not torch.isfinite(prediction).all():raise RuntimeError('Nonfinite lip inference')
                prediction=(prediction.float().cpu().numpy().transpose(0,2,3,1)*255).clip(0,255).astype(np.uint8)
                for index,token,pred in zip(indices,tokens,prediction):
                    frame=p._compose(token,pred);process.stdin.write(frame.tobytes())
                    if index in [0,count//2,count-1]:
                        y1,y2,x1,x2=assets.clips[name][1][index];before=assets.frame(name,index)[y1:y2,x1:x2];after=frame[y1:y2,x1:x2]
                        pair=np.hstack([cv2.resize(before,(256,320)),cv2.resize(after,(256,320))]);faces.append(pair)
                        ok,data=cv2.imencode('.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,95]);assert ok;(folder/f'frame-{index:05d}.jpg').write_bytes(data.tobytes())
                if begin%100==0:print(f'{name}: inferred {min(count,begin+4)}/{count}',flush=True)
        finally:process.stdin.close();code=process.wait();errors.close()
        assert code==0
        cap=cv2.VideoCapture(str(target));assert (cap.get(3),cap.get(4))==(1080,1920);decoded=0
        while cap.read()[0]:decoded+=1
        cap.release();assert decoded==count,(name,decoded,count)
        ok,data=cv2.imencode('.jpg',np.vstack(faces),[cv2.IMWRITE_JPEG_QUALITY,95]);assert ok;(folder/'face-before-after.jpg').write_bytes(data.tobytes())
        report=dict(status='REAL_WAV2LIP_RENDERED_VISUAL_REVIEW_REQUIRED',motion=name,width=1080,height=1920,frames=count,fps=25,
            device=assets.device,precision=str(assets.dtype),model='Wav2Lip256',batch_size=4,wall_seconds=round(time.perf_counter()-started,3),
            inference_seconds=round(network,3),fixture_sha256=hashlib.sha256(fixture.read_bytes()).hexdigest(),cloud_calls=0,
            video=str(target.relative_to(ROOT)),sha256=hashlib.sha256(target.read_bytes()).hexdigest(),human_lipsync_accepted=False)
        marker.write_text(json.dumps(report,indent=2),encoding='utf-8');reports.append(report);print(json.dumps(report),flush=True)
    (OUT/'render-report.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
if __name__=='__main__':main()
