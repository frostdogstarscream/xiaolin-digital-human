"""Restore verified RGB transport to mmap and face crops inside an isolated eval root."""
import json,hashlib,sys
from pathlib import Path
import cv2,numpy as np
ROOT=Path(__file__).resolve().parents[2];TRANSPORT=ROOT.parent/'transport'
profile=json.loads((ROOT/'assets/presenter-v2-1080/profile.json').read_text());manifest=json.loads((TRANSPORT/'manifest.json').read_text())
for item in [profile['idle'],*profile['actions']]:
    record=next(r for r in manifest if r['id']==item['id']);source=TRANSPORT/record['file']
    assert hashlib.sha256(source.read_bytes()).hexdigest()==record['sha256']
    directory=ROOT/item['avatar_dir'];target=directory/'frames.npy'
    if target.exists():
        data=np.load(target,mmap_mode='r');assert data.shape==(item['frames'],1920,1080,3);data._mmap.close();continue
    for name in ['full_imgs','face_imgs']:(directory/name).mkdir(exist_ok=True)
    coords=json.loads((directory/'coords.json').read_text());array=np.lib.format.open_memmap(target.with_suffix('.tmp.npy'),mode='w+',dtype=np.uint8,shape=(item['frames'],1920,1080,3))
    cap=cv2.VideoCapture(str(source));count=0
    while True:
        ok,frame=cap.read()
        if not ok:break
        assert count<item['frames'];array[count]=frame;y1,y2,x1,x2=coords[count]
        face=cv2.resize(frame[y1:y2,x1:x2],(256,256));ok,data=cv2.imencode('.png',face);assert ok;(directory/'face_imgs'/f'{count:08d}.png').write_bytes(data.tobytes())
        if count in (0,item['frames']-1):
            ok,data=cv2.imencode('.png',frame);assert ok;(directory/'full_imgs'/f'{count:08d}.png').write_bytes(data.tobytes())
        count+=1
    cap.release();assert count==item['frames'];array.flush();array._mmap.close();del array;target.with_suffix('.tmp.npy').replace(target)
    print('Restored',item['id'],count,flush=True)
