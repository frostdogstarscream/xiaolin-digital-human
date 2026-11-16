"""Publish only read-only preview route; preserve 6444 production upstream/auth."""
from pathlib import Path
import subprocess
root=Path('/opt/xiaolin/evaluations/presenter-v2-1080/avatar-2d')
conf=Path('/opt/xiaolin/releases/20261110-ports/deployment/nginx.conf')
backup=root/'experiments/presenter-50fps/nginx.before-review.conf'
original=conf.read_text()
if not backup.exists():backup.write_text(original)
if '/experiments/50fps/' not in original:
    needle='        client_max_body_size 1m;\n'
    assert original.count(needle)==1
    addition='''        location ^~ /experiments/50fps/ {
            proxy_pass http://127.0.0.1:8788/;
            proxy_set_header Host $http_host;
            proxy_set_header X-Xiaolin-User $remote_user;
        }
'''
    conf.write_text(original.replace(needle,needle+addition))
    check=subprocess.run(['docker','exec','xiaolin-nginx-1','nginx','-t'],capture_output=True,text=True)
    if check.returncode:
        conf.write_text(original);raise RuntimeError(check.stderr)
    subprocess.run(['docker','exec','xiaolin-nginx-1','nginx','-s','reload'],check=True)
print('Read-only preview added; same authentication; original upstream preserved')
