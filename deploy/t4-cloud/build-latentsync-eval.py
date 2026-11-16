"""Package the pinned 1.5 source and explicit T4/offline adaptations."""
import hashlib
import json
import shutil
import tarfile
from pathlib import Path

workspace = Path(__file__).resolve().parents[2]
root = workspace/'runtime/musetalk-t4-20261111'
source = root/'LatentSync-source'
stage = root/'latentsync-stage'
stage.mkdir(exist_ok=True)
for name in ['latentsync', 'configs', 'scripts']:
    shutil.copytree(source/name, stage/name, dirs_exist_ok=True)
for name in ['LICENSE', 'requirements.txt', 'README.md']:
    shutil.copy2(source/name, stage/name)
path = stage/'scripts/inference.py'
text = path.read_text(encoding='utf-8')
assert 'torch.cuda.get_device_capability()[0] > 7' in text
text = text.replace('torch.cuda.get_device_capability()[0] > 7', 'torch.cuda.get_device_capability()[0] >= 7')
text = text.replace('"stabilityai/sd-vae-ft-mse", torch_dtype=dtype', '"/muse-models/sd-vae", torch_dtype=dtype')
text = text.replace('def main(config, args):', 'def main(config, args):\n    torch.set_num_threads(4)')
path.write_text(text, encoding='utf-8')
info = json.loads((root/'latentsync15-model-info.json').read_text(encoding='utf-8-sig'))
manifest = {'repository':info['id'], 'revision':info['sha'], 'files':[]}
for item in info['siblings']:
    if item['rfilename'] in ['latentsync_unet.pt', 'whisper/tiny.pt']:
        manifest['files'].append({'destination':item['rfilename'], 'bytes':item['size'],
            'sha256':item['lfs']['sha256'],
            'url':f"https://huggingface.co/{info['id']}/resolve/{info['sha']}/{item['rfilename']}"})
(stage/'checkpoints').mkdir(exist_ok=True)
(stage/'checkpoints/manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
(stage/'docs').mkdir(exist_ok=True)
(stage/'outputs').mkdir(exist_ok=True)
(stage/'source-manifest.json').write_text(json.dumps({
    'repository':'https://github.com/bytedance/LatentSync',
    'commit':'7b380d6adde7aa23cba4a53bb15cd5cfb3c168e7',
    'model':'LatentSync 1.5',
    'adaptations':['Enable float16 on Turing T4 (SM 7.5)', 'Use verified local SD VAE', 'Limit CPU threads to four'],
    'inference_sha256':hashlib.sha256(path.read_bytes()).hexdigest()},indent=2),encoding='utf-8')
fetcher = (workspace/'deploy/t4-cloud/fetch-eval-models.py').read_text()
fetcher = fetcher.replace('/opt/xiaolin/evaluations/musetalk-t4-20261111/musetalk-eval', '/opt/xiaolin/evaluations/latentsync-t4-20261111')
fetcher = fetcher.replace("'models'", "'checkpoints'").replace("models/manifest.json", "checkpoints/manifest.json")
(stage/'fetch-models.py').write_text(fetcher,encoding='utf-8')
(stage/'Dockerfile').write_text('''FROM xiaolin-presenter:20261110-ports
RUN pip install --no-cache-dir --index-url https://mirrors.aliyun.com/pypi/simple cython==3.0.12
RUN pip install --no-cache-dir --index-url https://mirrors.aliyun.com/pypi/simple diffusers==0.32.2 transformers==4.48.0 decord==0.6.0 omegaconf==2.3.0 kornia==0.8.0 insightface==0.7.3 onnxruntime-gpu==1.21.0 DeepCache==0.1.1 tiktoken==0.9.0
WORKDIR /eval
RUN pip install --no-cache-dir --index-url https://mirrors.aliyun.com/pypi/simple ffmpeg-python==0.2.0
''',encoding='utf-8')
with tarfile.open(root/'latentsync-code.tar','w') as archive:
    for path in stage.iterdir():
        archive.add(path,arcname=path.name)
print(root/'latentsync-code.tar')
