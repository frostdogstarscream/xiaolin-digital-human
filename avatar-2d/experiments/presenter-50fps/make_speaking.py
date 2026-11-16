"""Real 50fps Wav2Lip + frozen audio export for human visual review."""
import json,subprocess,hashlib
import engine50 as engine
from avatars.wav2lip import audio
import numpy as np,soundfile as sf,cv2
OUT=engine.ROOT/'outputs/presenter-50fps/review';OUT.mkdir(parents=True,exist_ok=True)
assets=engine.Assets();p=engine.Presenter(engine.options('offline-preview'),assets,lambda e:None)
fixture=engine.ROOT/'assets/calibration-speech-16k-v1.wav';wave,rate=sf.read(fixture,dtype='float32');assert rate==16000
for name in ['welcome-wave','goodbye-wave','explain-open-palms','acknowledge-nod']:
    count=len(assets.clips[name][1]);driving=wave[np.arange(count*320)%len(wave)]
    wav=OUT/(name+'.wav');sf.write(wav,driving,rate,subtype='PCM_16');mel=audio.melspectrogram(driving)
    process=subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','rawvideo','-pix_fmt','bgr24','-s','1080x1920','-r','50','-i','-',
        '-i',str(wav),'-c:v','libx264','-preset','veryfast','-threads','4','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-shortest','-movflags','+faststart',str(OUT/(name+'-speaking-50fps.mp4'))],stdin=subprocess.PIPE)
    tiles=[]
    for begin in range(0,count,4):
        indices=list(range(begin,min(count,begin+4)));tokens=[(name,i) for i in indices]
        features=[mel[:,min(int(i*80/50),mel.shape[1]-16):min(int(i*80/50),mel.shape[1]-16)+16] for i in indices]
        preds=p._infer(tokens,features)
        for i,token,pred in zip(indices,tokens,preds):
            frame=p._compose(token,pred);process.stdin.write(frame.tobytes())
            if i in (0,count//2,count-1):
                y1,y2,x1,x2=assets.clips[name][1][i]
                tiles.append(cv2.resize(frame[y1:y2,x1:x2],(256,320)))
    process.stdin.close();assert process.wait()==0
    cv2.imwrite(str(OUT/(name+'-mouth.jpg')),np.hstack(tiles))
    print(name,'COMPLETE',flush=True)
(OUT/'speaking-metadata.json').write_text(json.dumps(dict(fps=50,precision=str(assets.dtype),fixture_sha256=hashlib.sha256(fixture.read_bytes()).hexdigest(),cloud_calls=0,human_visual_review_required=True)))
