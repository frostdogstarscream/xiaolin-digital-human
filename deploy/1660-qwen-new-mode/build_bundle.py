"""Small code bundle; frozen compressed original-video delivery is transferred separately."""
import hashlib,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'runtime/deploy-1660/qwen-new-mode-20261110';OUT.mkdir(parents=True,exist_ok=True)
files={}
def put(name,data):files[name]=data
for name in ['gateway.py','provider.py','capabilities.py','demo.js','index.html']:
    path=ROOT/'avatar-2d/experiments/qwen-realtime-v2'/name;data=path.read_bytes()
    if name=='index.html':data=data.replace(b'https://36.133.88.94:6443/',b'http://127.0.0.1:8766/')
    put('avatar-2d/experiments/qwen-realtime-v2/'+name,data)
for name in ['engine_baseline.py','live_engine_v2.py','video_encoder.py','restore_sources.py','lossless_frames.py']:
    put('avatar-2d/experiments/presenter-v2-1080/'+name,(ROOT/'avatar-2d/experiments/presenter-v2-1080'/name).read_bytes())
benchmark=(ROOT/'avatar-2d/experiments/presenter-v2-1080/check_t4_sustained.py').read_text(encoding='utf-8')
benchmark=benchmark.replace("'T4 server-local native WebRTC; not external browser/network acceptance'","'GTX 1660 local native WebRTC; physical microphone/speaker not verified'")
benchmark=benchmark.replace("assert 'T4' in torch.cuda.get_device_name(0)","assert '1660' in torch.cuda.get_device_name(0)")
benchmark=benchmark.replace("'Only reserved T4 may be visible'","'Expected one GTX 1660'")
benchmark=benchmark.replace("'t4-sustained'","'1660-new-mode-sustained'")
put('avatar-2d/experiments/presenter-v2-1080/check_1660_sustained.py',benchmark.encode())
for name in ['run_windows.py','Control-Qwen.ps1','Register-Qwen.ps1']:
    path=Path(__file__).parent/name
    put('deployment/qwen-new-mode-20261110/'+name,path.read_text(encoding='utf-8').encode('utf-8-sig' if path.suffix=='.ps1' else 'utf-8'))
manifest={name:hashlib.sha256(data).hexdigest() for name,data in files.items()}
archive=OUT/'new-mode-code.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    for name,data in files.items():z.writestr(name,data)
    z.writestr('manifest.json',json.dumps(manifest,indent=2))
(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2))
print(json.dumps(dict(bundle=str(archive),bytes=archive.stat().st_size,sha256=hashlib.sha256(archive.read_bytes()).hexdigest())))
