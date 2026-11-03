"""Download only the selected official avatar and the two inference weights."""
import concurrent.futures
import hashlib
import json
import sys
import zipfile
from pathlib import Path
from urllib.parse import urlencode

import requests

ROOT=Path(__file__).resolve().parents[1]
AVATAR='20250612/P1VtV9PVTqDj7CiZx2CCme2A'
VENDOR=ROOT/'vendor/lite-avatar'


def download(item):
    target=Path(item['destination']);target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()==item['sha256']:
        print('verified existing',target.name,flush=True);return
    temporary=target.with_suffix(target.suffix+'.part')
    url='https://modelscope.cn/api/v1/models/HumanAIGC-Engineering/LiteAvatarGallery/repo?'+urlencode({'Revision':item['revision'],'FilePath':item['path']})
    digest=hashlib.sha256();size=0
    with requests.get(url,stream=True,timeout=(15,45)) as response:
        response.raise_for_status()
        with temporary.open('wb') as output:
            for block in response.iter_content(1024*1024):
                output.write(block);digest.update(block);size+=len(block)
    if size!=item['size'] or digest.hexdigest()!=item['sha256']:
        raise RuntimeError('Official asset checksum mismatch: '+item['path'])
    temporary.replace(target);print('downloaded and verified',target.name,size,flush=True)


def main():
    weights=json.loads((ROOT/'research/weights-files.json').read_text(encoding='utf-8'))['Data']['Files']
    gallery=json.loads((ROOT/'research/gallery-files.json').read_text(encoding='utf-8'))['Data']['Files']
    wanted={
        'lite_avatar_weights/model.pb':VENDOR/'weights/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch/model.pb',
        'lite_avatar_weights/model_1.onnx':VENDOR/'weights/model_1.onnx',
        AVATAR+'.zip':ROOT/'models/selected-avatar.zip',
    }
    items=[]
    for file in weights+gallery:
        if file['Path'] in wanted:
            items.append(dict(path=file['Path'],revision=file['Revision'],sha256=file['Sha256'],size=file['Size'],destination=str(wanted[file['Path']])))
    assert len(items)==len(wanted)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:list(executor.map(download,items))
    destination=ROOT/'avatars'/AVATAR
    destination.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(ROOT/'models/selected-avatar.zip') as archive:
        for member in archive.infolist():
            relative=Path(member.filename)
            if relative.is_absolute() or '..' in relative.parts or ((member.external_attr>>16)&0o170000)==0o120000:
                raise RuntimeError('Unsafe avatar archive path')
        archive.extractall(destination)
    (ROOT/'models/download-manifest.json').write_text(json.dumps({'avatar':AVATAR,'files':items},ensure_ascii=False,indent=2),encoding='utf-8')
    print('Selected avatar ready:',destination,flush=True)


if __name__=='__main__':main()
