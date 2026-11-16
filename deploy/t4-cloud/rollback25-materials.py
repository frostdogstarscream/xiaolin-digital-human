"""Restore the frozen 25 fps baseline without restoring historical business data."""
import hashlib
import json
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

BASE = Path('/opt/xiaolin')
record = json.loads((BASE / 'deployment/material-release.json').read_text())
baseline = Path(record['baseline'])
for name, expected in json.loads((baseline / 'sha256.json').read_text()).items():
    with (baseline / name).open('rb') as source:
        assert hashlib.file_digest(source, 'sha256').hexdigest() == expected, name
settings = BASE / 'evaluations/presenter-v2-1080/avatar-2d/runtime/qwen-realtime-v2/settings.json'
shutil.copyfile(baseline / 'private/settings.json', settings)
subprocess.run(['docker', 'update', '--restart=unless-stopped', 'xiaolin-qwen-musetalk-v2'], check=True)
subprocess.run(['docker', 'start', 'xiaolin-qwen-musetalk-v2'], check=True)
deadline = time.monotonic() + 120
while True:
    try:
        with urllib.request.urlopen('http://127.0.0.1:8772/api/health', timeout=3) as response:
            if json.load(response)['status'] == 'ready':
                break
    except Exception:
        if time.monotonic() >= deadline:
            raise
    time.sleep(1)
shutil.copyfile(baseline / 'private/nginx.conf', BASE / 'releases/20261110-ports/deployment/nginx.conf')
subprocess.run(['docker', 'exec', 'xiaolin-nginx-1', 'nginx', '-t'], check=True)
subprocess.run(['docker', 'exec', 'xiaolin-nginx-1', 'nginx', '-s', 'reload'], check=True)
shutil.copyfile(baseline / 'private/control-current.sh', BASE / 'deployment/control-current.sh')
shutil.copyfile(Path(record['previous_release']) / 'runtime-before.json', BASE / 'deployment/current-runtime.json')
for container in [record['previous_container'], record['container']]:
    subprocess.run(['docker', 'update', '--restart=no', container], check=True)
    subprocess.run(['docker', 'stop', '-t', '45', container], check=True)
print('FROZEN_25FPS_RESTORED; live knowledge and memory retained')
