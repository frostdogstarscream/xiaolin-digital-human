"""Convert existing frame arrays without resizing, encoding loss, or deleting originals."""
import hashlib,json,os,sys,time
from pathlib import Path
os.environ['OPENBLAS_NUM_THREADS']='1'
import numpy as np
ROOT=Path('D:/XiaolinDigitalHuman');HERE=ROOT/'avatar-2d/experiments/presenter-v2-1080'
sys.path.insert(0,str(HERE))
from lossless_frames import zstd_module,LosslessFrames
zstd=zstd_module();profile=json.loads((ROOT/'avatar-2d/assets/presenter-v2-1080/profile.json').read_text(encoding='utf-8'))
expected=json.loads((ROOT/'expected-frame-hashes.json').read_text(encoding='utf-8'));records=[]
for item in [profile['idle'],*profile['actions']]:
    began=time.monotonic();directory=ROOT/'avatar-2d'/item['avatar_dir'];source=np.load(directory/'frames.npy',mmap_mode='r')
    encoder=zstd.ZstdCompressor(level=1);decoder=zstd.ZstdDecompressor();entries=[];total=0
    temporary=directory/'frames.zstd.tmp'
    with temporary.open('wb') as output:
        for i,frame in enumerate(source):
            raw=frame.tobytes();assert hashlib.sha256(raw).hexdigest()==expected[item['id']][i]
            compressed=encoder.compress(raw);assert decoder.decompress(compressed,max_output_size=len(raw))==raw
            output.write(compressed);entries.append([total,len(compressed)]);total+=len(compressed)
    temporary.replace(directory/'frames.zstd')
    with (directory/'frames.zstd').open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    index=dict(schema=1,shape=list(source.shape),bytes=total,sha256=digest,frames=entries)
    index_path=directory/'frames.zstd.json';index_path.with_suffix('.tmp').write_text(json.dumps(index),encoding='utf-8');index_path.with_suffix('.tmp').replace(index_path)
    restored=LosslessFrames(directory,len(source))
    for i in [0,len(source)//2,len(source)-1]:assert np.array_equal(restored[i],source[i])
    restored.data.close();restored.file.close();source._mmap.close()
    row=dict(id=item['id'],frames=item['frames'],all_frames_pixel_exact=True,raw_bytes=item['frames']*1920*1080*3,compressed_bytes=total,seconds=time.monotonic()-began)
    records.append(row);print(json.dumps(row),flush=True)
out=ROOT/'deployment/qwen-new-mode-20261110/reports/lossless-cache.json'
out.write_text(json.dumps(dict(status='PASSED',codec='zstandard 0.25.0 level 1, lossless',clips=records),indent=2),encoding='utf-8')
