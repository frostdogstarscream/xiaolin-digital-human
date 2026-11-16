"""Reconstruct native-size cache directly from frozen source videos, with reference checks."""
import hashlib,json,subprocess,time
from pathlib import Path
import cv2,numpy as np
cv2.setNumThreads(4)
ROOT=Path(__file__).resolve().parents[2]
profile=json.loads((ROOT/'assets/presenter-v2-1080/profile.json').read_text())
expected=json.loads((ROOT.parent/'expected-frame-hashes.json').read_text());records=[]
for item in [profile['idle'],*profile['actions']]:
    started=time.monotonic();directory=ROOT/item['avatar_dir'];target=directory/'frames.npy'
    source=ROOT/'assets/presenter-v2-1080'/('incoming-'+item['source_id'])/'source.mp4'
    assert hashlib.file_digest(source.open('rb'),'sha256').hexdigest()==item['source_sha256']
    for sub in ('full_imgs','face_imgs'):(directory/sub).mkdir(exist_ok=True)
    coords=json.loads((directory/'coords.json').read_text())
    matrix=np.array(item['constant_transform'],np.float64)
    samples={i:cv2.imdecode(np.frombuffer((directory/'full_imgs'/f'{i:08d}.png').read_bytes(),np.uint8),cv2.IMREAD_COLOR)
             for i in (0,item['frames']//2,item['frames']-1)}
    array=np.lib.format.open_memmap(target.with_suffix('.tmp.npy'),mode='w+',dtype=np.uint8,shape=(item['frames'],1920,1080,3))
    command=['ffmpeg','-hide_banner','-v','error','-nostdin','-threads','2','-i',str(source),'-vf',
        'fps=25,scale=1080:1920:flags=lanczos','-t',str(item['seconds']),'-an','-f','rawvideo','-pix_fmt','bgr24','-']
    process=subprocess.Popen(command,stdout=subprocess.PIPE);count=0;identical=0;reference=[]
    while True:
        data=process.stdout.read(1080*1920*3)
        if not data:break
        assert len(data)==1080*1920*3 and count<item['frames']
        frame=np.frombuffer(data,np.uint8).reshape(1920,1080,3)
        frame=cv2.warpAffine(frame,matrix,(1080,1920),flags=cv2.INTER_LANCZOS4,borderValue=0)
        array[count]=frame;identical+=hashlib.sha256(frame).hexdigest()==expected[item['id']][count]
        if count in samples:
            original=samples[count];psnr=float(cv2.PSNR(original,frame));maximum=int(np.abs(original.astype(np.int16)-frame.astype(np.int16)).max())
            y1,y2,x1,x2=coords[count]
            face_psnr=float(cv2.PSNR(original[y1:y2,x1:x2],frame[y1:y2,x1:x2]))
            reference.append(dict(frame=count,psnr=psnr,face_psnr=face_psnr,max_pixel_difference=maximum))
            assert psnr>=50 and face_psnr>=45,(item['id'],count,psnr,face_psnr)
        y1,y2,x1,x2=coords[count];face=cv2.resize(frame[y1:y2,x1:x2],(256,256))
        ok,encoded=cv2.imencode('.png',face);assert ok;(directory/'face_imgs'/f'{count:08d}.png').write_bytes(encoded.tobytes())
        if count in samples:
            ok,encoded=cv2.imencode('.png',frame);assert ok;(directory/'full_imgs'/f'{count:08d}.png').write_bytes(encoded.tobytes())
        count+=1
    process.stdout.close();code=process.wait();assert code==0 and count==item['frames']
    array.flush();array._mmap.close();del array;target.with_suffix('.tmp.npy').replace(target)
    row=dict(id=item['id'],frames=count,pixel_exact_frames=identical,references=reference,seconds=time.monotonic()-started)
    records.append(row);print(json.dumps(row),flush=True)
report=dict(status='PASSED',method='reconstructed from SHA256-frozen original videos without additional lossy encoding',
    notes='Per-frame hashes and three full-frame references compare Windows and Linux decode/scale implementations.',clips=records)
(ROOT/'outputs/presenter-v2-1080').mkdir(parents=True,exist_ok=True)
(ROOT/'outputs/presenter-v2-1080/t4-reconstruction.json').write_text(json.dumps(report,indent=2))
