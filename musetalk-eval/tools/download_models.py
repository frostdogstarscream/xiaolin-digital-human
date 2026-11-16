"""Download only official inference dependencies, pinned to hub revisions/LFS hashes."""
import concurrent.futures
import hashlib
import json
import time
from pathlib import Path

import requests

ROOT=Path(__file__).resolve().parents[1]
SOURCES={
    'TMElyralab/MuseTalk':{'musetalkV15/musetalk.json':'musetalkV15/musetalk.json','musetalkV15/unet.pth':'musetalkV15/unet.pth'},
    'stabilityai/sd-vae-ft-mse':{'config.json':'sd-vae/config.json','diffusion_pytorch_model.bin':'sd-vae/diffusion_pytorch_model.bin'},
    'openai/whisper-tiny':{x:'whisper/'+x for x in ['config.json','pytorch_model.bin','preprocessor_config.json']},
    'ManyOtherFunctions/face-parse-bisent':{x:'face-parse-bisent/'+x for x in ['79999_iter.pth','resnet18-5c106cde.pth']},
}


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda:stream.read(4*1024*1024),b''):h.update(part)
    return h.hexdigest()


def download(item):
    destination=ROOT/'models'/item['destination'];destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists() and destination.stat().st_size==item['bytes']:
        digest=sha(destination)
        if not item.get('lfs_sha256') or digest==item['lfs_sha256']:return {**item,'sha256':digest,'verified':True}
    partial=destination.with_suffix(destination.suffix+'.part')
    for attempt in range(5):
        try:
            offset=partial.stat().st_size if partial.exists() else 0
            with requests.get(item['url'],headers={'Range':f'bytes={offset}-'} if offset else {},stream=True,timeout=(20,90)) as response:
                response.raise_for_status()
                if response.status_code!=206:offset=0
                with partial.open('ab' if offset else 'wb') as output:
                    for chunk in response.iter_content(1024*1024):output.write(chunk)
            if partial.stat().st_size!=item['bytes']:raise RuntimeError('Incomplete model download')
            digest=sha(partial)
            if item.get('lfs_sha256') and digest!=item['lfs_sha256']:raise RuntimeError('Model digest mismatch')
            partial.replace(destination)
            print('VERIFIED',item['destination'],item['bytes'],flush=True)
            return {**item,'sha256':digest,'verified':True}
        except Exception as error:
            print('RETRY',item['destination'],attempt+1,type(error).__name__,flush=True)
            if attempt==4:raise
            time.sleep(min(2**attempt,8))


def main():
    manifest_path=ROOT/'models/manifest.json'
    if manifest_path.exists():
        manifest=json.loads(manifest_path.read_text(encoding='utf-8'));items=manifest['files']
    else:
        items=[];revisions={}
        for repository,files in SOURCES.items():
            r=requests.get('https://huggingface.co/api/models/'+repository,params={'blobs':'true'},timeout=30);r.raise_for_status()
            data=r.json();revision=data['sha'];revisions[repository]=revision
            available={x['rfilename']:x for x in data['siblings']}
            for remote,dest in files.items():
                info=available[remote];lfs=info.get('lfs') or {}
                items.append({'repository':repository,'revision':revision,'file':remote,'destination':dest,
                    'bytes':info.get('size') or lfs['size'],'lfs_sha256':lfs.get('sha256'),
                    'url':f'https://huggingface.co/{repository}/resolve/{revision}/{remote}'})
        manifest={'revisions':revisions,'files':items}
        manifest_path.parent.mkdir(exist_ok=True);manifest_path.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('MODEL_BYTES',sum(x['bytes'] for x in items),flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(download,items))
    manifest['files']=results;manifest['status']='ALL_OFFICIAL_FILES_HASH_VERIFIED'
    manifest_path.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(manifest['status'],flush=True)


if __name__=='__main__':main()
