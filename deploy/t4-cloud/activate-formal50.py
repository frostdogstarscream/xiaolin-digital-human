"""Activate the validated formal 50 fps runtime."""
import json,shutil,subprocess,urllib.request
from pathlib import Path
base=Path('/opt/xiaolin');info=json.loads((base/'deployment/formal50-candidate.json').read_text());release=Path(info['release'])
assert json.loads((release/'validation.json').read_text())['status']=='PASSED'
def run(*args):return subprocess.check_output(args,text=True).strip()
# Carry forward the latest business switches while applying the approved lip-sync model.
settings=json.loads((base/'evaluations/presenter-v2-1080/avatar-2d/runtime/qwen-realtime-v2/settings.json').read_text())
settings.pop('revision');settings['lipsync_backend']='wav2lip'
request=urllib.request.Request('http://127.0.0.1:8773/api/settings',data=json.dumps(settings).encode(),headers={'Origin':'http://127.0.0.1:8773','Content-Type':'application/json'})
with urllib.request.urlopen(request,timeout=120) as response:assert response.status==200
p=base/'releases/20261110-ports/deployment/nginx.conf';original=p.read_text();assert original.count('proxy_pass http://127.0.0.1:8772;')==1
shutil.copy2(p,release/'nginx-before.conf')
p.write_text(original.replace('proxy_pass http://127.0.0.1:8772;','proxy_pass http://127.0.0.1:8773;'))
try:
 run('docker','exec','xiaolin-nginx-1','nginx','-t')
 run('docker','exec','xiaolin-nginx-1','nginx','-s','reload')
except Exception:
 p.write_text(original);run('docker','exec','xiaolin-nginx-1','nginx','-s','reload');raise
run('docker','update','--restart=unless-stopped','xiaolin-formal-50fps')
run('docker','update','--restart=no','xiaolin-qwen-musetalk-v2')
control=base/'deployment/control-current.sh';shutil.copy2(control,release/'control-before.sh');s=control.read_text();assert 'xiaolin-qwen-musetalk-v2' in s;control.write_text(s.replace('xiaolin-qwen-musetalk-v2','xiaolin-formal-50fps'))
run('docker','stop','-t','45','xiaolin-qwen-musetalk-v2')
p=base/'deployment/current-runtime.json';report=json.loads(p.read_text());shutil.copy2(p,release/'runtime-before.json')
report['retained']=['xiaolin-formal-50fps' if x=='xiaolin-qwen-musetalk-v2' else x for x in report['retained']]
report['retired']=list(dict.fromkeys([*report['retired'],'xiaolin-qwen-musetalk-v2']))
report.update(formal_fps=50,formal_lipsync='wav2lip',formal_precision='fp16',formal_release=str(release),baseline25=info['baseline'])
p.write_text(json.dumps(report,indent=2))
print(json.dumps({'activated':True,'url':'https://36.133.88.94:6444/','fps':50,'release':str(release),'baseline25':info['baseline']}))
