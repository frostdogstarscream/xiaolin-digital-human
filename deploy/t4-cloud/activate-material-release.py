import json
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

BASE = Path('/opt/xiaolin')
record = json.loads((BASE / 'deployment/material-release.json').read_text())
release = Path(record['release'])
validation = json.loads((release / 'validation-materials.json').read_text())
assert validation['status'] == 'PASSED'
assert all(validation['actions_completed'].get(name, 0) >= 1 for name in ['welcome-wave', 'goodbye-wave', 'explain-open-palms', 'acknowledge-nod'])
with urllib.request.urlopen('http://127.0.0.1:8774/api/health') as response:
    health = json.load(response)
assert health['status'] == 'ready' and health['material_version'] == 'graded-transitions-v1'
# Copy the latest business switches at the deployment boundary.
old_settings = Path(record['previous_release']) / 'state/settings.json'
settings = json.loads(old_settings.read_text())
settings.pop('revision', None)
settings['lipsync_backend'] = 'wav2lip'
request = urllib.request.Request('http://127.0.0.1:8774/api/settings', data=json.dumps(settings).encode(),
                                 headers={'Content-Type': 'application/json', 'Origin': 'http://127.0.0.1:8774'}, method='POST')
with urllib.request.urlopen(request) as response:
    assert response.status == 200
nginx = BASE / 'releases/20261110-ports/deployment/nginx.conf'
source = nginx.read_text()
assert 'proxy_pass http://127.0.0.1:8773;' in source
nginx.write_text(source.replace('proxy_pass http://127.0.0.1:8773;', 'proxy_pass http://127.0.0.1:8774;'))
try:
    subprocess.run(['docker', 'exec', 'xiaolin-nginx-1', 'nginx', '-t'], check=True)
    subprocess.run(['docker', 'update', '--restart=unless-stopped', record['container']], check=True)
    subprocess.run(['docker', 'exec', 'xiaolin-nginx-1', 'nginx', '-s', 'reload'], check=True)
except Exception:
    nginx.write_text(source)
    subprocess.run(['docker', 'exec', 'xiaolin-nginx-1', 'nginx', '-s', 'reload'], check=True)
    subprocess.run(['docker', 'update', '--restart=no', record['container']], check=True)
    raise
control = BASE / 'deployment/control-current.sh'
control.write_text(control.read_text().replace(record['previous_container'], record['container']))
subprocess.run(['docker', 'update', '--restart=no', record['previous_container']], check=True)
subprocess.run(['docker', 'stop', '-t', '45', record['previous_container']], check=True)
runtime_path = BASE / 'deployment/current-runtime.json'
runtime = json.loads(runtime_path.read_text())
for key in ['retained', 'retired']:
    if isinstance(runtime.get(key), list):
        runtime[key] = [record['container'] if value == record['previous_container'] else value for value in runtime[key]]
runtime['retired'] = list(dict.fromkeys([value for value in runtime.get('retired', []) if value != record['container']] + [record['previous_container']]))
runtime.update(formal_fps=50, formal_release=record['release'], formal_container=record['container'],
               material_version='graded-transitions-v1', graded_actions=4, bridge_seconds=.3)
runtime_path.write_text(json.dumps(runtime, indent=2))
candidate = dict(release=record['release'], container=record['container'], candidate_port=8774, fps=50,
                 lipsync_backend='wav2lip', precision='fp16', baseline=record['baseline'], material_version='graded-transitions-v1')
(BASE / 'deployment/formal50-candidate.json').write_text(json.dumps(candidate, indent=2))
shutil.copy2(BASE / 'deployment/rollback-formal25.py', release / 'previous-rollback-formal25.py')
shutil.copy2(release / 'rollback25-materials.py', BASE / 'deployment/rollback-formal25.py')
(release / 'activated.json').write_text(json.dumps(candidate, indent=2))
print(json.dumps(candidate))
