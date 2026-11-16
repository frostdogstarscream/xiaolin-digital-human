import json
import subprocess
from pathlib import Path

record = json.loads(Path('/opt/xiaolin/deployment/material-release.json').read_text())
release = Path(record['release'])
info = json.loads((release / 'previous-container.json').read_text())
args = ['docker', 'run', '-d', '--name', 'xiaolin-material-build', '--network', 'host', '--cpus', '6',
        '-e', 'OPENBLAS_NUM_THREADS=1', '-e', 'OMP_NUM_THREADS=4']
for mount in info['Mounts']:
    if mount['Destination'] != '/formal':
        args += ['-v', mount['Source'] + ':' + mount['Destination'] + ':ro']
args += ['-v', str(release) + ':/formal', info['Config']['Image'], 'python', '-u', '/formal/build-material-cache.py']
print(subprocess.check_output(args, text=True))
