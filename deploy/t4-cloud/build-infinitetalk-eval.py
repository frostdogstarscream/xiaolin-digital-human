"""Build an isolated INT8 InfiniteTalk experiment for a single T4."""
import hashlib
import json
import re
import shutil
import tarfile
from pathlib import Path

workspace = Path(__file__).resolve().parents[2]
root = workspace/'runtime/musetalk-t4-20261111'
source = root/'InfiniteTalk-source'
stage = root/'infinitetalk-stage'
stage.mkdir(exist_ok=True)
for name in ['wan', 'src']:
    shutil.copytree(source/name, stage/name, dirs_exist_ok=True)
for name in ['generate_infinitetalk.py', 'LICENSE.txt', 'README.md', 'requirements.txt']:
    shutil.copy2(source/name, stage/name)
shutil.copy2(workspace/'deploy/t4-cloud/t4_attention.py', stage/'wan/modules/t4_attention.py')
single_gpu = '''def get_sequence_parallel_rank(): return 0
def get_sequence_parallel_world_size(): return 1
def get_sp_group(): raise RuntimeError('Distributed execution is disabled in this evaluation')
'''
(stage/'single_gpu.py').write_text(single_gpu)
for relative in ['wan/modules/attention.py', 'wan/utils/multitalk_utils.py']:
    path = stage/relative
    s = path.read_text(encoding='utf-8')
    s, count = re.subn(r'from xfuser.core.distributed import \([\s\S]*?\)',
                      'from single_gpu import get_sequence_parallel_rank, get_sequence_parallel_world_size, get_sp_group', s, count=1)
    assert count == 1
    if relative.endswith('/attention.py'):
        s += '\n# T4-only evaluation override; original implementation retained above.\nfrom .t4_attention import flash_attention\n'
    path.write_text(s,encoding='utf-8')
path = stage/'wan/configs/shared_config.py'
s = path.read_text(encoding='utf-8').replace('wan_shared_cfg.t5_dtype = torch.bfloat16', 'wan_shared_cfg.t5_dtype = torch.float32')
s = s.replace('wan_shared_cfg.param_dtype = torch.bfloat16', 'wan_shared_cfg.param_dtype = torch.float16')
path.write_text(s,encoding='utf-8')
path = stage/'wan/multitalk.py'
s = path.read_text(encoding='utf-8').replace('from inspect import ArgSpec\n', '')
s = s.replace('quant=quant,\n            quant_dir=os.path.dirname(quant_dir)', 'quant=None,\n            quant_dir=os.path.dirname(quant_dir)', 1)
path.write_text(s,encoding='utf-8')
path = stage/'generate_infinitetalk.py'
s = path.read_text(encoding='utf-8').replace('from kokoro import KPipeline', '# Local-file evaluation does not import or invoke TTS.')
s = s.replace('args = parser.parse_args()', "args = parser.parse_args()\n    assert args.audio_mode == 'localfile'\n    assert args.ulysses_size == 1 and args.ring_size == 1\n    torch.set_num_threads(8)")
path.write_text(s,encoding='utf-8')
manifest = {'files':[],'revisions':{}}
for slug, prefix in [('Wan-AI--Wan2.1-I2V-14B-480P','wan'), ('MeiGen-AI--InfiniteTalk','quant'),
                     ('TencentGameMate--chinese-wav2vec2-base','wav2vec')]:
    info = json.loads((root/(slug+'.json')).read_text(encoding='utf-8-sig'))
    manifest['revisions'][info['id']] = info['sha']
    for item in info['siblings']:
        name = item['rfilename']
        selected = ((prefix == 'wan' and (name in ['config.json','Wan2.1_VAE.pth','models_clip_open-clip-xlm-roberta-large-vit-huge-14.pth','models_t5_umt5-xxl-enc-bf16.pth'] or name.startswith(('google/', 'xlm-roberta-large/'))))
                    or (prefix == 'quant' and name in ['quant_models/infinitetalk_single_int8.safetensors','quant_models/infinitetalk_single_int8.json'])
                    or (prefix == 'wav2vec' and name in ['config.json','preprocessor_config.json','pytorch_model.bin']))
        if not selected: continue
        destination = prefix+'/'+(Path(name).name if prefix=='quant' else name)
        manifest['files'].append({'destination':destination,'bytes':item['size'],
            'sha256':item.get('lfs',{}).get('sha256'), 'git_blob_sha1':item['blobId'],
            'url':f"https://huggingface.co/{info['id']}/resolve/{info['sha']}/{name}"})
for name in ['weights','docs','outputs','inputs']:
    (stage/name).mkdir(exist_ok=True)
(stage/'weights/manifest.json').write_text(json.dumps(manifest,indent=2))
fetcher = (workspace/'deploy/t4-cloud/fetch-eval-models.py').read_text(encoding='utf-8')
fetcher = fetcher.replace('/opt/xiaolin/evaluations/musetalk-t4-20261111/musetalk-eval', '/opt/xiaolin/evaluations/infinitetalk-t4-20261111')
fetcher = fetcher.replace("'models'", "'weights'").replace('models/manifest.json','weights/manifest.json')
fetcher = fetcher.replace("if actual != item['sha256']:", "if item['sha256'] and actual != item['sha256']:")
fetcher = fetcher.replace('    temporary.replace(path)', "    if not item['sha256']:\n        data = temporary.read_bytes()\n        assert hashlib.sha1(b'blob '+str(len(data)).encode()+b'\\0'+data).hexdigest() == item['git_blob_sha1']\n    temporary.replace(path)")
fetcher = fetcher.replace("'1800'", "'3600'")
(stage/'fetch-models.py').write_text(fetcher)
(stage/'Dockerfile').write_text('''FROM xiaolin-presenter:20261110-ports
RUN pip install --no-cache-dir --index-url https://mirrors.aliyun.com/pypi/simple xformers==0.0.33.post2 optimum-quanto==0.2.6 easydict==1.13 ftfy==6.3.1 pyloudnorm==0.1.1 moviepy==1.0.3 decord==0.6.0 scenedetect==0.6.7.1 sentencepiece==0.2.0
WORKDIR /eval
RUN pip install --no-cache-dir --index-url https://mirrors.aliyun.com/pypi/simple scikit-image==0.26.0
RUN pip install --no-cache-dir --index-url https://mirrors.aliyun.com/pypi/simple loguru==0.7.3
''')
files = {str(p.relative_to(stage)):hashlib.sha256(p.read_bytes()).hexdigest() for p in stage.rglob('*.py')}
(stage/'source-manifest.json').write_text(json.dumps({'repository':'https://github.com/MeiGen-AI/InfiniteTalk',
    'commit':'50aa0a94184315407a991ae804d9b58d6d311ba8', 'model':'official single-person INT8',
    'adaptations':['single GPU only','FP16 DiT and FP32 CPU T5','xFormers attention with preserved sequence lengths',
                   'disable unused TTS imports','remove unused Python 3.10 ArgSpec import'], 'python_sha256':files},indent=2))
with tarfile.open(root/'infinitetalk-code.tar','w') as archive:
    for p in stage.iterdir(): archive.add(p,arcname=p.name)
print('Selected weight bytes:',sum(x['bytes'] for x in manifest['files']))
