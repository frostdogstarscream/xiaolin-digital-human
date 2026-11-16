import json,subprocess
from pathlib import Path

def run(*args):return subprocess.check_output(args,text=True).strip()
folder=Path('/opt/xiaolin/evaluations/presenter-v2-1080/avatar-2d/experiments/qwen-realtime-v2')
s=(folder/'gateway.py').read_text()
assert 'import live_engine_v2 as engine' in s
s=s.replace('import live_engine_v2 as engine','import musetalk_engine as engine')
s=s.replace("profile='presenter-v2-1080',","profile='presenter-v2-1080',lipsync_backend='musetalk-1.5',lipsync_decoder='original',")
(folder/'gateway_musetalk.py').write_text(s)
info=json.loads(run('docker','inspect','xiaolin-qwen-realtime-v2'))[0]
args=['docker','run','-d','--name','xiaolin-qwen-musetalk-v2','--restart','unless-stopped','--network','host','--device','nvidia.com/gpu=GPU-d83c041f-3543-6c67-faf0-23f3d1910f44','--shm-size','2g']
for val in info['Config']['Env']:
 if val.startswith('QWEN_DEMO_PORT='):val='QWEN_DEMO_PORT=8772'
 args+=['-e',val]
args+=['-e','MUSE_ROOT=/muse']
for m in info['Mounts']:args+=['-v',m['Source']+':'+m['Destination']+('' if m['RW'] else ':ro')]
args+=['-v','/opt/xiaolin/evaluations/musetalk-t4-20261111/musetalk-eval:/muse:ro','-w',info['Config']['WorkingDir'],info['Config']['Image'],'python','/eval/avatar-2d/experiments/qwen-realtime-v2/gateway_musetalk.py']
print(run(*args))
