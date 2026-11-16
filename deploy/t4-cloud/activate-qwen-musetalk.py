"""Switch only the 6444 upstream after the MuseTalk integration check passes."""
import datetime,json,subprocess,urllib.request
from pathlib import Path

def run(*args):return subprocess.check_output(args,text=True).strip()
health=json.load(urllib.request.urlopen('http://127.0.0.1:8772/api/health',timeout=10))
assert health.get('lipsync_backend')=='musetalk-1.5'
report=Path('/opt/xiaolin/evaluations/presenter-v2-1080/avatar-2d/outputs/qwen-realtime-v2/musetalk-integration-check.json')
assert json.loads(report.read_text())['status']=='PASSED'
info=json.loads(run('docker','inspect','xiaolin-nginx-1'))[0]
p=Path(next(x['Source'] for x in info['Mounts'] if x['Destination']=='/etc/nginx/nginx.conf'))
s=p.read_text();assert s.count('proxy_pass http://127.0.0.1:8771;')==1
backup=p.with_name(p.name+'.before-musetalk-6444-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.write_text(s)
p.write_text(s.replace('proxy_pass http://127.0.0.1:8771;','proxy_pass http://127.0.0.1:8772;'))
try:
 run('docker','exec','xiaolin-nginx-1','nginx','-t')
 run('docker','exec','xiaolin-nginx-1','nginx','-s','reload')
except Exception:
 p.write_text(s);run('docker','exec','xiaolin-nginx-1','nginx','-s','reload');raise
print(json.dumps({'switched':True,'port':6444,'upstream':8772,'backup':str(backup)}))
