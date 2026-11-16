from pathlib import Path
import subprocess
root=Path('/opt/xiaolin/evaluations/presenter-v2-1080');path=Path('/opt/xiaolin/current/deployment/nginx.conf')
original=path.read_bytes();text=original.decode();backup=root/'nginx-before-capabilities-v2.conf'
if not backup.exists():backup.write_bytes(original)
if 'proxy_pass http://127.0.0.1:8770;' in text:
    assert text.count('proxy_pass http://127.0.0.1:8770;')==1
    updated=text.replace('proxy_pass http://127.0.0.1:8770;','proxy_pass http://127.0.0.1:8771;')
    updated=updated.replace('proxy_set_header Host $http_host;','proxy_set_header Host $http_host;\n            proxy_set_header X-Xiaolin-User $remote_user;')
    path.write_text(updated)
    result=subprocess.run(['docker','exec','xiaolin-nginx-1','nginx','-t'],capture_output=True)
    if result.returncode:path.write_bytes(original);raise SystemExit('Invalid Nginx config; restored')
    subprocess.run(['docker','exec','xiaolin-nginx-1','nginx','-s','reload'],check=True)
else:assert 'proxy_pass http://127.0.0.1:8771;' in text
print('Realtime 6444 switched to capability v2; production 6443 retained')
