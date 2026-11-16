import datetime
import hashlib
import json
import subprocess
from pathlib import Path

base = Path('/opt/xiaolin')
record = json.loads((base / 'deployment/material-release.json').read_text())
release = Path(record['release'])
files = {}
for path in (release / 'avatar-2d/experiments').rglob('*'):
    if path.is_file() and '__pycache__' not in path.parts and path.suffix in ['.py', '.html', '.js', '.css', '.json']:
        files[str(path.relative_to(release))] = hashlib.sha256(path.read_bytes()).hexdigest()
(release / 'release-files-sha256.json').write_text(json.dumps(files, indent=2))
info = json.loads(subprocess.check_output(['docker', 'inspect', record['container']], text=True))[0]
report = dict(release=record['release'], container=record['container'],
              state=info['State']['Status'], restart=info['HostConfig']['RestartPolicy']['Name'],
              material_cache=json.loads((release / 'material-cache/complete.json').read_text()),
              validation=json.loads((release / 'validation-materials.json').read_text())['status'],
              rollback_previous='/opt/xiaolin/deployment/rollback-material-release.py',
              baseline25=record['baseline'], code_files=len(files))
(release / 'deployment-audit.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report))
