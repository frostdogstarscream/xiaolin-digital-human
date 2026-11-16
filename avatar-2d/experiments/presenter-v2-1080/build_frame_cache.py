"""Decode PNG once into read-only memory-mapped RGB-equivalent BGR frame arrays."""
from pathlib import Path
import json,time
import numpy as np,cv2
ROOT=Path(__file__).resolve().parents[2]
profile=json.loads((ROOT/'assets/presenter-v2-1080/profile.json').read_text(encoding='utf-8'))
reports=[]
for item in [profile['idle'],*profile['actions']]:
    directory=ROOT/item['avatar_dir'];target=directory/'frames.npy';started=time.perf_counter()
    if not target.exists():
        temporary=directory/'frames.tmp.npy'
        array=np.lib.format.open_memmap(temporary,mode='w+',dtype=np.uint8,shape=(item['frames'],1920,1080,3))
        for i in range(item['frames']):
            frame=cv2.imdecode(np.frombuffer((directory/'full_imgs'/f'{i:08d}.png').read_bytes(),np.uint8),cv2.IMREAD_COLOR)
            array[i]=frame
            if i%200==0:print(item['id'],i,'/',item['frames'],flush=True)
        array.flush();array._mmap.close();del array;temporary.replace(target)
    array=np.load(target,mmap_mode='r');assert array.shape==(item['frames'],1920,1080,3) and array.dtype==np.uint8
    for i in [0,item['frames']//2,item['frames']-1]:
        original=cv2.imdecode(np.frombuffer((directory/'full_imgs'/f'{i:08d}.png').read_bytes(),np.uint8),cv2.IMREAD_COLOR)
        assert np.array_equal(array[i],original),'Frame cache must preserve all pixel values'
    array._mmap.close();del array
    report=dict(id=item['id'],bytes=target.stat().st_size,pixel_exact_sample_check=True,seconds=round(time.perf_counter()-started,3));reports.append(report);print(json.dumps(report),flush=True)
(ROOT/'outputs/presenter-v2-1080/frame-cache-report.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
