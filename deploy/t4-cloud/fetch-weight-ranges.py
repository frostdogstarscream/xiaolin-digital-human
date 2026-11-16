"""Bounded parallel downloads of frozen weights with final full-file hashes."""
import concurrent.futures
import hashlib
import json
import subprocess
import time
from pathlib import Path

ROOT = Path('/opt/xiaolin/evaluations/infinitetalk-t4-20261111')
CHUNK = 64 * 1024 * 1024


def valid(path, item):
    if not path.exists() or path.stat().st_size != item['bytes']:
        return False
    if item['sha256']:
        with path.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest() == item['sha256']
    data = path.read_bytes()
    return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest() == item['git_blob_sha1']


def fetch(item):
    path = ROOT/'weights'/item['destination']
    path.parent.mkdir(parents=True, exist_ok=True)
    if valid(path, item):
        print('REUSED',item['destination'],flush=True)
        return
    size = item['bytes']
    url = item['url'].replace('https://huggingface.co/', 'https://hf-mirror.com/')+'?download=true'
    temporary = path.with_suffix(path.suffix+'.ranged')
    if size < CHUNK:
        subprocess.run(['curl','-fLs','--retry','3','--connect-timeout','20','--max-time','600',
                        '--max-filesize',str(size),'-o',str(temporary),url], check=True)
    else:
        parts = path.parent/(path.name+'.parts')
        parts.mkdir(exist_ok=True)
        prefix = path.with_suffix(path.suffix+'.partial')
        if prefix.exists():
            with prefix.open('rb') as stream:
                for start in range(0,min(prefix.stat().st_size,size)//CHUNK*CHUNK,CHUNK):
                    part=parts/str(start)
                    data=stream.read(CHUNK)
                    if not part.exists():part.write_bytes(data)

        def part_download(start):
            end=min(start+CHUNK,size)-1
            part=parts/str(start)
            if part.exists() and part.stat().st_size == end-start+1:return part
            partial=part.with_suffix('.tmp')
            subprocess.run(['curl','-fLs','--retry','3','--connect-timeout','20','--max-time','600',
                            '--max-filesize',str(end-start+1),'--range',f'{start}-{end}',
                            '-o',str(partial),url],check=True)
            assert partial.stat().st_size == end-start+1, item['destination']
            partial.replace(part)
            print('PART',item['destination'],start,flush=True)
            return part

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            files=list(pool.map(part_download,range(0,size,CHUNK)))
        with temporary.open('wb') as output:
            for part in files:
                with part.open('rb') as stream:
                    while data:=stream.read(8*1024*1024):output.write(data)
    if not valid(temporary,item):raise RuntimeError('Full artifact hash mismatch: '+item['destination'])
    temporary.replace(path)
    print('VERIFIED',item['destination'],flush=True)


started=time.time()
items=json.loads((ROOT/'weights/manifest.json').read_text())['files']
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    list(pool.map(fetch,items))
(ROOT/'docs/download-result.json').write_text(json.dumps({'status':'ALL_HASHES_VERIFIED',
    'seconds':time.time()-started,'files':len(items),'bytes':sum(x['bytes'] for x in items)},indent=2))
print('ALL_HASHES_VERIFIED',flush=True)
