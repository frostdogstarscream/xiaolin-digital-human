python3 - <<'PY'
from pathlib import Path
import json,subprocess,datetime,shutil
p=Path('/opt/xiaolin/releases/20261110-ports/deployment/nginx.conf')
s=p.read_text();backup=p.with_name(p.name+'.before-50fps-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));shutil.copy2(p,backup)
route='''  location ^~ /experiments/50fps/ {
   proxy_pass http://127.0.0.1:8788/;
   proxy_set_header Host $http_host;
   proxy_set_header Origin $http_origin;
   proxy_set_header X-Xiaolin-User preview;
   proxy_read_timeout 3600s;
   proxy_buffering off;
  }
'''
assert '/experiments/50fps/' not in s
s=s.replace('  location / {',route+'  location / {');p.write_text(s)
try:subprocess.run(['docker','exec','xiaolin-nginx-1','nginx','-t'],check=True)
except Exception:shutil.copyfile(backup,p);raise
subprocess.run(['docker','start','xiaolin-50fps-preview'],check=True)
subprocess.run(['docker','exec','xiaolin-nginx-1','nginx','-s','reload'],check=True)
r=Path('/opt/xiaolin/deployment/current-runtime.json');d=json.loads(r.read_text());d['retired']=[n for n in d['retired'] if n!='xiaolin-50fps-preview'];d['manual_previews']=['xiaolin-50fps-preview'];r.write_text(json.dumps(d,indent=2))
print('50FPS_PREVIEW_STARTED')
PY
