"""Add one authenticated TLS listener; retain and validate the production config."""
import hashlib,subprocess
from pathlib import Path
root=Path('/opt/xiaolin/evaluations/presenter-v2-1080')
path=Path('/opt/xiaolin/current/deployment/nginx.conf')
original=path.read_bytes()
backup=root/'nginx-before-realtime-v1.conf'
if not backup.exists():backup.write_bytes(original)
text=original.decode()
block='''
    server {
        listen 6444 ssl;
        server_name 36.133.88.94;
        ssl_certificate /certs/server.crt;
        ssl_certificate_key /certs/server.key;
        ssl_protocols TLSv1.2 TLSv1.3;
        auth_basic "Xiaolin Realtime Trial";
        auth_basic_user_file /config/access.htpasswd;
        client_max_body_size 1m;
        location / {
            proxy_pass http://127.0.0.1:8770;
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
'''
if 'listen 6444 ssl;' not in text:
    assert text.rstrip().endswith('}')
    updated=text.rstrip()[:-1]+block+'}\n'
    # Existing bind-mounted inode stays intact. Running workers keep old config until validation/reload.
    path.write_text(updated)
    result=subprocess.run(['docker','exec','xiaolin-nginx-1','nginx','-t'],capture_output=True,text=True)
    if result.returncode:
        path.write_bytes(original);raise SystemExit('Nginx validation failed; previous file restored')
    subprocess.run(['docker','exec','xiaolin-nginx-1','nginx','-s','reload'],check=True)
else:assert 'proxy_pass http://127.0.0.1:8770;' in text
print('Authenticated realtime trial published on TLS 6444; original 6443 listener retained')
print('Previous Nginx config SHA256: '+hashlib.sha256(backup.read_bytes()).hexdigest())
