"""Stage the approved color and transition release alongside the current service."""
import datetime
import json
import shutil
import subprocess
from pathlib import Path

BASE = Path('/opt/xiaolin')
previous = json.loads((BASE / 'deployment/formal50-candidate.json').read_text())
source = Path(previous['release'])
release = BASE / 'releases' / ('formal50-materials-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
root = release / 'avatar-2d'
root.mkdir(parents=True)
for name in ['qwen-realtime-v2', 'presenter-v2-1080', 'presenter-50fps']:
    shutil.copytree(source / 'avatar-2d/experiments' / name, root / 'experiments' / name,
                    ignore=shutil.ignore_patterns('__pycache__', '*.before-*'))
for name in ['assets', 'runtime', 'models', 'tools', 'outputs']:
    (root / name).symlink_to('/eval/avatar-2d/' + name, target_is_directory=True)
(root / 'service').symlink_to('/app/avatar-2d/service', target_is_directory=True)
shutil.copy2(source / 'avatar-2d/source-manifest.json', root / 'source-manifest.json')
(release / 'state').mkdir(mode=0o700)
shutil.copy2(source / 'state/settings.json', release / 'state/settings.json')
(release / 'state/capabilities.sqlite3').symlink_to('/eval/avatar-2d/runtime/qwen-realtime-v2/capabilities.sqlite3')
for name in ['nginx.conf', 'control-current.sh', 'current-runtime.json', 'formal50-candidate.json']:
    original = BASE / ('releases/20261110-ports/deployment/' if name == 'nginx.conf' else 'deployment/') / name
    shutil.copy2(original, release / ('previous-' + name))
info = json.loads(subprocess.check_output(['docker', 'inspect', previous['container']], text=True))[0]
(release / 'previous-container.json').write_text(json.dumps(info, indent=2))
(release / 'previous-container.json').chmod(0o600)
record = dict(release=str(release), previous_release=str(source), previous_container=previous['container'],
              container='xiaolin-formal50-materials', port=8774, baseline=previous['baseline'])
(BASE / 'deployment/material-release.json').write_text(json.dumps(record, indent=2))
print(json.dumps(record))
