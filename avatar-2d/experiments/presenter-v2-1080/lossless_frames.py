"""Optional pixel-exact, independently compressed frames for memory-limited hosts."""
import hashlib,json,mmap,sys,threading
from pathlib import Path
import numpy as np

def zstd_module():
    vendor=Path(__file__).parent/'_vendor'
    if vendor.exists():sys.path.insert(0,str(vendor))
    import zstandard
    return zstandard

class LosslessFrames:
    def __init__(self,directory,count):
        self.index=json.loads((directory/'frames.zstd.json').read_text(encoding='utf-8'))
        if self.index['schema']!=1 or self.index['shape']!=[count,1920,1080,3] or len(self.index['frames'])!=count:
            raise ValueError('Invalid lossless cache index')
        path=directory/'frames.zstd'
        if path.stat().st_size!=self.index['bytes']:raise ValueError('Lossless cache length mismatch')
        with path.open('rb') as source:
            if hashlib.file_digest(source,'sha256').hexdigest()!=self.index['sha256']:raise ValueError('Lossless cache checksum mismatch')
        self.file=path.open('rb');self.data=mmap.mmap(self.file.fileno(),0,access=mmap.ACCESS_READ)
        self.decoder=zstd_module().ZstdDecompressor();self.lock=threading.Lock()
    def __getitem__(self,index):
        offset,size=self.index['frames'][index]
        with self.lock:raw=self.decoder.decompress(self.data[offset:offset+size],max_output_size=1920*1080*3)
        if len(raw)!=1920*1080*3:raise ValueError('Invalid lossless frame')
        return np.frombuffer(raw,np.uint8).reshape(1920,1080,3)
