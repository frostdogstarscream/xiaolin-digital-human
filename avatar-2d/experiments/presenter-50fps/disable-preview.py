"""Remove only this experiment's route and stop only its container."""
from pathlib import Path
import subprocess
conf=Path('/opt/xiaolin/releases/20261110-ports/deployment/nginx.conf')
original=conf.read_text()
block='''        location ^~ /experiments/50fps/ {
            proxy_pass http://127.0.0.1:8788/;
            proxy_set_header Host $http_host;
            proxy_set_header X-Xiaolin-User $remote_user;
        }
'''
if '/experiments/50fps/' in original:
    assert original.count(block)==1,'Configuration changed; review exact experiment route first'
    conf.write_text(original.replace(block,''))
    check=subprocess.run(['docker','exec','xiaolin-nginx-1','nginx','-t'])
    if check.returncode:conf.write_text(original);raise RuntimeError('Nginx check failed; original restored')
    subprocess.run(['docker','exec','xiaolin-nginx-1','nginx','-s','reload'],check=True)
subprocess.run(['docker','stop','-t','20','xiaolin-50fps-preview'],check=True)
print('Only 50fps experiment disabled; source and results retained')
