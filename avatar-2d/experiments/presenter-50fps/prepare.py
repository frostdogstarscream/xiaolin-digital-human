"""Offline 25->50 optical-flow cache; originals are read-only. No provider calls."""
import hashlib,json,time
from pathlib import Path
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'runtime/presenter-50fps'
cv2.setNumThreads(4)

def midpoint(a,b):
    # Bidirectional half-time warps at half-resolution, then full-resolution resampling.
    small=lambda x:cv2.cvtColor(cv2.resize(x,(540,960)),cv2.COLOR_BGR2GRAY)
    flow=cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    ab=flow.calc(small(a),small(b),None)
    ba=flow.calc(small(b),small(a),None)
    ab=cv2.resize(ab,(1080,1920))*2;ba=cv2.resize(ba,(1080,1920))*2
    yy,xx=np.mgrid[:1920,:1080].astype(np.float32)
    wa=cv2.remap(a,xx-ab[:,:,0]*.5,yy-ab[:,:,1]*.5,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
    wb=cv2.remap(b,xx-ba[:,:,0]*.5,yy-ba[:,:,1]*.5,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
    return cv2.addWeighted(wa,.5,wb,.5,0)

def descriptor(frame):
    # Include face, shoulders and hands, avoiding black-border dominance.
    return cv2.resize(frame[80:1200,250:830],(58,112)).astype(np.float32)

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    profile=json.loads((ROOT/'assets/presenter-v2-1080/profile.json').read_text())
    started=time.monotonic();records=[]
    for item in [profile['idle'],*profile['actions']]:
        name=item['id'];src=ROOT/item['avatar_dir'];dst=OUT/name;dst.mkdir(exist_ok=True)
        if (dst/'complete.json').exists():
            records.append(json.loads((dst/'complete.json').read_text()));continue
        frames=np.load(src/'frames.npy',mmap_mode='r');coords=json.loads((src/'coords.json').read_text())
        n=len(frames);target=np.lib.format.open_memmap(dst/'frames.npy',mode='w+',dtype=np.uint8,shape=(n*2,1920,1080,3))
        faces=np.lib.format.open_memmap(dst/'faces.npy',mode='w+',dtype=np.uint8,shape=(n*2,256,256,3))
        newcoords=[];began=time.monotonic()
        for i in range(n):
            j=min(i+1,n-1)
            for k,frame in enumerate((frames[i],midpoint(frames[i],frames[j]) if j!=i else frames[i])):
                index=i*2+k;target[index]=frame
                c=coords[i] if k==0 else np.rint((np.array(coords[i])+coords[j])/2).astype(int).tolist()
                newcoords.append(c);y1,y2,x1,x2=c
                faces[index]=cv2.resize(frame[y1:y2,x1:x2],(256,256))
            if i%100==0:print(json.dumps(dict(clip=name,source_frame=i,total=n)),flush=True)
        target.flush();faces.flush()
        (dst/'coords.json').write_text(json.dumps(newcoords))
        record=dict(id=name,frames=n*2,seconds=n/25,fps=50,preprocess_seconds=time.monotonic()-began,
                    source_video_sha256=item['video_sha256'],method='bidirectional DIS midpoint; final frame held 20ms')
        (dst/'complete.json').write_text(json.dumps(record));records.append(record)
    # Three contiguous ~10-second segments. Optimize both cuts for all directed joins.
    idle=np.load(OUT/'idle/frames.npy',mmap_mode='r');n=len(idle)
    # Visual review of this exact source found blinks around 9s and 18s.
    # Exclude both sides of these blinks: never cut an eyelid closure in half.
    candidates1=list(range(400,441,10))+list(range(480,601,10));candidates2=list(range(930,1101,10))
    needed=set([0,n-1]+candidates1+candidates2+[i-1 for i in candidates1+candidates2])
    desc={i:descriptor(idle[i]) for i in needed}
    score=lambda i,j:float(np.mean(np.abs(desc[i]-desc[j])))
    choices=[]
    for a in candidates1:
        for b in candidates2:
            starts=[0,a,b];ends=[a-1,b-1,n-1]
            costs=[score(ends[i],starts[j]) for i in range(3) for j in range(3) if i!=j]
            choices.append((max(costs)+np.mean(costs),(a,b),costs))
    cost,(a,b),costs=min(choices)
    segments=[dict(id=f'idle-{i+1}',start=s,end=e,seconds=(e-s)/50) for i,(s,e) in enumerate(zip([0,a,b],[a,b,n]))]
    plan=dict(fps=50,segments=segments,join_costs=costs,selection='weighted random by endpoint similarity; no consecutive repeat',
              visual_review_required=True)
    (OUT/'idle-plan.json').write_text(json.dumps(plan,indent=2))
    # Exact source-duration check and sampled unchanged original frames.
    for item in [profile['idle'],*profile['actions']]:
        src=np.load(ROOT/item['avatar_dir']/'frames.npy',mmap_mode='r');dst=np.load(OUT/item['id']/'frames.npy',mmap_mode='r')
        assert len(dst)==2*len(src)
        for i in [0,len(src)//2,len(src)-1]:assert np.array_equal(src[i],dst[i*2])
    (OUT/'manifest.json').write_text(json.dumps(dict(clips=records,idle=plan,total_seconds=time.monotonic()-started),indent=2))
    print('PREPROCESS COMPLETE',flush=True)

if __name__=='__main__':main()
