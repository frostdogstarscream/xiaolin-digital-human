"""Use original compressed sources plus deterministic reconstruction instead of huge RGB transport."""
import hashlib,json,zipfile
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2];ASSET=ROOT/'assets/presenter-v2-1080';OUT=ROOT/'outputs/presenter-v2-1080'
profile=json.loads((ASSET/'profile.json').read_text(encoding='utf-8'))
target=OUT/'presenter-v2-1080-source-delivery.zip';hashes={}
with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=1) as archive:
    def put(path):archive.write(path,'avatar-2d/'+path.relative_to(ROOT).as_posix())
    put(ASSET/'profile.json');put(ROOT/'assets/calibration-speech-16k-v1.wav');put(ROOT/'tools/windows_runtime.py')
    for path in Path(__file__).parent.glob('*.py'):put(path)
    for item in [profile['idle'],*profile['actions']]:
        source=ASSET/('incoming-'+item['source_id'])/'source.mp4';put(source)
        directory=ROOT/item['avatar_dir'];put(directory/'coords.json');put(directory/'prepared.json')
        frames=np.load(directory/'frames.npy',mmap_mode='r')
        hashes[item['id']]=[hashlib.sha256(frame).hexdigest() for frame in frames]
        for i in (0,len(frames)//2,len(frames)-1):put(directory/'full_imgs'/f'{i:08d}.png')
        frames._mmap.close()
    archive.writestr('expected-frame-hashes.json',json.dumps(hashes))
digest=hashlib.file_digest(target.open('rb'),'sha256').hexdigest()
record=dict(file=target.name,bytes=target.stat().st_size,sha256=digest,method='original video + fixed reconstruction + all-frame hashes + reference PNGs')
(OUT/'source-delivery.json').write_text(json.dumps(record,indent=2))
print(json.dumps(record),flush=True)
