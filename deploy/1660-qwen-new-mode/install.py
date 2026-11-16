"""Verify immutable source delivery and install only new-mode code/assets."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT=Path('D:/XiaolinDigitalHuman')
STAGE=ROOT/'deployment/qwen-new-mode-20261110'
SOURCE_SHA='ef9a2eb56b56893556ee7c8e4c9ff7102a9346bb984667e6e4b9c5f5d4030bce'
def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
archive=STAGE/'source-delivery.zip'
assert digest(archive)==SOURCE_SHA,'Source archive hash mismatch'
assert digest(ROOT/'avatar-2d/models/wav2lip256.pth')=='b22d7ac86295df667644b17254dc71250c2600b89e20403e90e58812450bc173'
selected=[]
with zipfile.ZipFile(archive) as source:
    for name in source.namelist():
        allowed=name.startswith(('avatar-2d/assets/presenter-v2-1080/','avatar-2d/runtime/presenter-v2-1080/')) or name in {
            'expected-frame-hashes.json', 'avatar-2d/assets/calibration-speech-16k-v1.wav'}
        if not allowed:continue
        path=(ROOT/name).resolve();assert path.is_relative_to(ROOT)
        data=source.read(name)
        if path.exists() and path.read_bytes()!=data:raise RuntimeError('Existing asset differs: '+name)
        path.parent.mkdir(parents=True,exist_ok=True)
        if not path.exists():path.write_bytes(data)
        selected.append(dict(path=name,sha256=hashlib.sha256(data).hexdigest(),bytes=len(data)))
with zipfile.ZipFile(STAGE/'new-mode-code.zip') as source:
    expected=json.loads(source.read('manifest.json'))
    for name,sha in expected.items():
        data=source.read(name);assert hashlib.sha256(data).hexdigest()==sha
        path=(ROOT/name).resolve();assert path.is_relative_to(ROOT)
        if path.exists() and path.read_bytes()!=data:
            backup=STAGE/'before-install'/name;backup.parent.mkdir(parents=True,exist_ok=True)
            if not backup.exists():shutil.copy2(path,backup)
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        selected.append(dict(path=name,sha256=sha,bytes=len(data)))
# Existing native Fay remains the source of credentials; log configuration presence only.
import configparser
cfg=configparser.ConfigParser(interpolation=None);cfg.read(ROOT/'fay-ue4/runtime/fay-local/app/system.conf',encoding='utf-8-sig')
presence={name:bool(cfg.get('key',name,fallback='').strip()) for name in ['bailian_tts_api_key','embedding_api_key','rerank_api_key']}
assert all(presence.values()),'Required existing service configuration is missing'
record=dict(source_archive_sha256=SOURCE_SHA,files=selected,existing_configuration_present=presence,
    embedding=cfg.get('key','embedding_api_model',fallback=''),rerank=cfg.get('key','rerank_api_model',fallback=''),
    history_migrated=False,memory_migrated=False)
(STAGE/'installed-manifest.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
ffmpeg=ROOT/'fay-ue4/runtime/fay-local/app/test/ovr_lipsync/ffmpeg/bin/ffmpeg.exe'
assert ffmpeg.exists();os.environ['PATH']=str(ffmpeg.parent)+os.pathsep+os.environ['PATH']
os.environ['OMP_NUM_THREADS']='1';os.environ['OPENBLAS_NUM_THREADS']='1'
profile=json.loads((ROOT/'avatar-2d/assets/presenter-v2-1080/profile.json').read_text(encoding='utf-8'))
if not all((ROOT/'avatar-2d'/item['avatar_dir']/'frames.npy').exists() for item in [profile['idle'],*profile['actions']]):
    subprocess.run([sys.executable,'-X','utf8',str(ROOT/'avatar-2d/experiments/presenter-v2-1080/restore_sources.py')],check=True)
print(json.dumps(dict(status='INSTALLED',configuration=presence,files=len(selected))),flush=True)
