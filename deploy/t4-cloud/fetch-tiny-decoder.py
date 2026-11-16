"""Download a separately labelled approximate decoder; preserve original weights."""
import hashlib
import json
import subprocess
import urllib.request
from pathlib import Path

root=Path('/opt/xiaolin/evaluations/musetalk-t4-20261111/musetalk-eval/models/taesd')
root.mkdir(exist_ok=True)
info=json.loads((root/'model-info.json').read_text(encoding='utf-8-sig'))
records=[]
for item in info['siblings']:
    name=item['rfilename']
    if name not in ['config.json','diffusion_pytorch_model.safetensors']:continue
    url=f"https://hf-mirror.com/{info['id']}/resolve/{info['sha']}/{name}"
    temporary=root/(name+'.partial')
    subprocess.run(['curl','-fLs','--retry','2','--max-time','180','-o',str(temporary),url],check=True)
    data=temporary.read_bytes()
    digest=hashlib.sha256(data).hexdigest()
    if item.get('lfs'):
        assert digest==item['lfs']['sha256']
    else:
        assert hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()==item['blobId']
    temporary.replace(root/name)
    records.append({'file':name,'sha256':digest})
(root/'verified.json').write_text(json.dumps({'repository':info['id'],'revision':info['sha'],
    'role':'approximate decoder candidate, not original MuseTalk VAE','files':records},indent=2))
print('TINY_DECODER_HASHES_VERIFIED',flush=True)
