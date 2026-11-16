"""Export original/50fps random-idle previews and transition contact sheets."""
import json,sys,subprocess
from pathlib import Path
import cv2,numpy as np
from idle_scheduler import IdleScheduler
ROOT=Path(__file__).resolve().parents[2];CACHE=ROOT/'runtime/presenter-50fps';OUT=ROOT/'outputs/presenter-50fps/review'
OUT.mkdir(parents=True,exist_ok=True)
plan=json.loads((CACHE/'idle-plan.json').read_text());frames=np.load(CACHE/'idle/frames.npy',mmap_mode='r')
segments=plan['segments']
desc=lambda x:cv2.resize(x[80:1200,250:830],(58,112)).astype(np.float32)
starts={s['start']:desc(frames[s['start']]) for s in segments}
scheduler=IdleScheduler(segments,lambda prev,i:np.mean(np.abs(desc(frames[prev])-starts[i])),20261110)
sequence=[];previous=0
for _ in range(3000):previous=scheduler.next(previous);sequence.append(previous)
(OUT/'sequence.json').write_text(json.dumps(dict(plan=plan,history=scheduler.history,indices=sequence)))
def video(path,indices,fps):
    process=subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','rawvideo','-pix_fmt','bgr24','-s','1080x1920','-r',str(fps),'-i','-','-an','-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',str(path)],stdin=subprocess.PIPE)
    for i in indices:process.stdin.write(frames[i].tobytes())
    process.stdin.close();assert process.wait()==0
rows=[]
for i,a in enumerate(segments):
    for j,b in enumerate(segments):
        if i==j:continue
        tiles=[]
        for index,label in [(a['end']-1,f'{i+1} end'),(b['start'],f'{j+1} start')]:
            tile=cv2.resize(frames[index],(270,480));cv2.putText(tile,label,(8,25),cv2.FONT_HERSHEY_SIMPLEX,.6,(255,255,255),1);tiles.append(tile)
        rows.append(np.hstack(tiles))
cv2.imwrite(str(OUT/'all-six-transitions.jpg'),np.vstack(rows))
if '--sheets-only' not in sys.argv:
    video(OUT/'idle-random-50fps.mp4',sequence,50)
    video(OUT/'idle-random-25fps-comparison.mp4',sequence[::2],25)
print('REVIEW COMPLETE',flush=True)
