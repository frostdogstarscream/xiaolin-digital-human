"""Retire superseded Xiaolin runtimes while keeping the current skirt presenter."""
import datetime,json,re,shutil,subprocess,urllib.request
from pathlib import Path
base=Path('/opt/xiaolin')
stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
backup=base/'deployment'/('retired-xiaolin-'+stamp);backup.mkdir()
retire=['xiaolin-presenter-1','xiaolin-qwen-realtime-v2','xiaolin-qwen-realtime-v1','xiaolin-50fps-preview','xiaolin-musetalk-original','xiaolin-musetalk-https','xiaolin-musetalk-taesd-eval-20261111','xiaolin-bootstrap-1']
keep=['xiaolin-qwen-musetalk-v2','xiaolin-nginx-1','xiaolin-turn-1','xiaolin-asr-1','xiaolin-fay-1','xiaolin-attendance-1']
def run(*args):return subprocess.check_output(args,text=True).strip()
existing=set(run('docker','ps','-a','--format','{{.Names}}').splitlines())
retire=[name for name in retire if name in existing]
(backup/'containers-before.json').write_text(run('docker','inspect',*retire,*keep));(backup/'containers-before.json').chmod(0o600)
nginx=base/'releases/20261110-ports/deployment/nginx.conf';shutil.copy2(nginx,backup/'nginx.conf')
page=base/'evaluations/presenter-v2-1080/avatar-2d/experiments/qwen-realtime-v2/index.html';shutil.copy2(page,backup/'index.html')
# A single public frontend points to the current configurable lip-sync gateway.
nginx.write_text('''events {}
http {
 map $http_upgrade $connection_upgrade { default upgrade; '' close; }
 server {
  listen 6444 ssl;
  server_name 36.133.88.94;
  ssl_certificate /certs/server.crt;
  ssl_certificate_key /certs/server.key;
  ssl_protocols TLSv1.2 TLSv1.3;
  client_max_body_size 1m;
  location / {
   proxy_pass http://127.0.0.1:8772;
   proxy_http_version 1.1;
   proxy_set_header Host $http_host;
   proxy_set_header Origin $http_origin;
   proxy_set_header X-Forwarded-Proto https;
   proxy_set_header Upgrade $http_upgrade;
   proxy_set_header Connection $connection_upgrade;
   proxy_read_timeout 3600s;
   proxy_send_timeout 3600s;
   proxy_buffering off;
  }
 }
}
''')
try:run('docker','exec','xiaolin-nginx-1','nginx','-t')
except Exception:shutil.copyfile(backup/'nginx.conf',nginx);raise
s=page.read_text();s=re.sub(r'<a\b[^>]*href="https://36\.133\.88\.94:6443/"[^>]*>.*?</a>','',s,flags=re.S)
s=re.sub(r'<span class="badge">独立版本.*?</span>','',s);page.write_text(s)
run('docker','exec','xiaolin-nginx-1','nginx','-s','reload')
# Persist the retirement before stopping each old instance.
for name in retire:run('docker','update','--restart=no',name)
for name in retire:
 if run('docker','inspect',name,'--format','{{.State.Running}}')=='true':run('docker','stop','-t','30',name)
# Save the legacy Fay speech core's memory and leave its MCP management server available.
request=urllib.request.Request('http://127.0.0.1:5000/api/stop-live',data=b'{}',headers={'Content-Type':'application/json'},method='POST')
with urllib.request.urlopen(request,timeout=120) as response:
 (backup/'fay-stop-live.json').write_bytes(response.read())
control=base/'deployment/control-current.sh'
control.write_text('''#!/bin/bash
set -euo pipefail
services=(xiaolin-turn-1 xiaolin-asr-1 xiaolin-fay-1 xiaolin-attendance-1 xiaolin-qwen-musetalk-v2 xiaolin-nginx-1)
case "${1:-status}" in
 start) for name in "${services[@]}"; do docker start "$name" >/dev/null; done ;;
 stop) docker stop -t 45 xiaolin-qwen-musetalk-v2 xiaolin-nginx-1 xiaolin-attendance-1 xiaolin-fay-1 xiaolin-asr-1 xiaolin-turn-1 ;;
 status) for name in "${services[@]}"; do docker inspect "$name" --format '{{.Name}} {{.State.Status}}'; done ;;
 logs) docker logs --tail 100 xiaolin-qwen-musetalk-v2 ;;
 *) echo 'Usage: control-current.sh {start|stop|status|logs}' >&2; exit 2 ;;
esac
''');control.chmod(0o755)
folder=Path('/etc/systemd/system/xiaolin.service.d');folder.mkdir(exist_ok=True)
unit=folder/'current-only.conf'
if unit.exists():shutil.copy2(unit,backup/'systemd-current-only.conf')
unit.write_text('[Service]\nExecStart=\nExecStart=/opt/xiaolin/deployment/control-current.sh start\nExecStop=\nExecStop=/opt/xiaolin/deployment/control-current.sh stop\n')
run('systemctl','daemon-reload')
report={'retired':retire,'retained':keep,'public_url':'https://36.133.88.94:6444/','backup':str(backup),'legacy_fay_speech_stopped':True,'persistent_startup':'xiaolin.service with current-only.conf'}
(base/'deployment/current-runtime.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report))
