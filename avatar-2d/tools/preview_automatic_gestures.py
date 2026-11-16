"""Pre-release actual Wav2Lip/Presenter geometry check using frozen local audio."""
import hashlib
import json
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'service'),str(ROOT/'tools')]
from live_app import LiveBridge
from live_engine import Assets,Presenter
from lipsync_preview import audio
import cv2
import numpy as np

def main():
    output=ROOT/'docs'/('automatic-gestures-preview-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    output.mkdir()
    candidates=list((ROOT.parent/'fay-ue4/runtime/fay-local/app/samples').glob('bailian-realtime-*.wav'))
    source=max((p for p in candidates if p.stat().st_size>24000),key=lambda p:p.stat().st_mtime)
    wave=LiveBridge.decode_audio(source)
    assets=Assets();p=Presenter.__new__(Presenter);p.assets=assets;p.model=assets.model
    p.lock=threading.Lock();p.motion_requested=None;p.motion=None;p.motion_index=0;p.pose=('welcome-wave',0)
    p.stats=dict(motion_frames=0,inference_seconds=0.,inference_frames=0)
    ffmpeg=ROOT.parent/'fay-ue4/runtime/fay-local/app/test/ovr_lipsync/ffmpeg/bin/ffmpeg.exe'
    report=dict(audio_file=str(source),audio_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),sample_rate=16000,
                backend='Wav2Lip256 / actual Presenter._advance + _infer + _compose',cases=[])
    tiles=[]
    for action in ('welcome-wave','goodbye-wave','explain-open-palms','acknowledge-nod'):
        n=len(assets.clips[action][1]);target=n+25;signal=np.tile(wave,int(np.ceil(target*640/len(wave))))[:target*640]
        mel=audio.melspectrogram(signal);avi=output/(action+'.avi');first=assets.frame(action,0)
        writer=cv2.VideoWriter(str(avi),cv2.VideoWriter_fourcc(*'MJPG'),25,(first.shape[1],first.shape[0]))
        started=time.perf_counter();sample_indices={0,n//4,n//2,3*n//4,n-1};snapshots=[];before=p.stats['motion_frames']
        for base in range(0,target,4):
            count=min(4,target-base);tokens=[];features=[]
            for i in range(base,base+count):
                packets=[SimpleNamespace(userdata={'status':'start','action':action,'plan_id':action})] if i==0 else []
                tokens.append(p._advance(packets))
                begin=min(int(i*80/25),mel.shape[1]-16);features.append(mel[:,begin:begin+16])
            predictions=p._infer(tokens,features)
            for offset,(token,prediction) in enumerate(zip(tokens,predictions)):
                frame=p._compose(token,prediction);writer.write(frame)
                if base+offset in sample_indices:
                    y1,y2,x1,x2=assets.clips[token[0]][1][token[1]]
                    assert 0<=x1<x2<=frame.shape[1] and 0<=y1<y2<=frame.shape[0]
                    full=cv2.resize(frame,(164,round(frame.shape[0]*164/frame.shape[1])))
                    face=cv2.resize(frame[y1:y2,x1:x2],(164,164))
                    image=np.vstack((full,face));cv2.putText(image,f'{action} {base+offset}',(3,16),cv2.FONT_HERSHEY_SIMPLEX,.35,(80,220,180),1)
                    snapshots.append(image)
        writer.release();assert p.stats['motion_frames']-before==n and p.pose==(action,n-1) and p.motion is None
        import soundfile as sf
        wav=output/(action+'.wav');sf.write(wav,signal,16000,subtype='PCM_16')
        mp4=output/(action+'.mp4')
        subprocess.run([str(ffmpeg),'-v','error','-nostdin','-n','-i',str(avi),'-i',str(wav),'-c:v','libx264','-crf','20',
                        '-pix_fmt','yuv420p','-c:a','aac','-movflags','+faststart',str(mp4)],check=True)
        tiles.append(np.hstack(snapshots))
        report['cases'].append(dict(action=action,motion_frames=n,held_frames=25,frames=target,video=str(mp4),
            generation_seconds=round(time.perf_counter()-started,3),geometry_bounds_valid=True,hold_last_frame=True))
        print(action+' preview complete',flush=True)
    sheet=output/'four-gestures-full-and-face.jpg';cv2.imencode('.jpg',np.vstack(tiles))[1].tofile(str(sheet))
    report['contact_sheet']=str(sheet);(output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'output':str(output),'contact_sheet':str(sheet)},ensure_ascii=True),flush=True)

if __name__=='__main__':main()
