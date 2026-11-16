import json
import subprocess
from pathlib import Path

record = json.loads(Path('/opt/xiaolin/deployment/material-release.json').read_text())
release = Path(record['release'])
assert (release / 'material-cache/complete.json').exists(), 'Material build is incomplete'
info = json.loads((release / 'previous-container.json').read_text())
args = ['docker', 'run', '-d', '--name', record['container'], '--restart', 'no', '--network', 'host',
        '--device', 'nvidia.com/gpu=GPU-d83c041f-3543-6c67-faf0-23f3d1910f44', '--shm-size', '2g']
overridden = ['QWEN_DEMO_PORT=', 'QWEN_STATE_DIR=', 'XIAOLIN_MATERIAL_CACHE=']
for value in info['Config']['Env']:
    if not any(value.startswith(prefix) for prefix in overridden):
        args += ['-e', value]
for value in ['QWEN_DEMO_PORT=' + str(record['port']), 'QWEN_STATE_DIR=/formal/state',
              'XIAOLIN_MATERIAL_CACHE=/formal/material-cache']:
    args += ['-e', value]
for mount in info['Mounts']:
    if mount['Destination'] != '/formal':
        args += ['-v', mount['Source'] + ':' + mount['Destination'] + ('' if mount['RW'] else ':ro')]
args += ['-v', str(release) + ':/formal', '-w', '/formal/avatar-2d', info['Config']['Image'],
         'python', '/formal/avatar-2d/experiments/qwen-realtime-v2/gateway50.py']
print(subprocess.check_output(args, text=True))
