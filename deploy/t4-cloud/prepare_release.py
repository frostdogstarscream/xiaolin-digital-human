"""Create a versioned release with shared mutable data and restricted credentials."""
import hashlib
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

BASE = Path('/opt/xiaolin')
DEPLOY = BASE / 'deployment'
SHARED = BASE / 'shared'
version = sys.argv[1]
if not version.replace('-', '').isalnum():
    raise ValueError('Invalid version')
release = BASE / 'releases' / version
release.mkdir(parents=True, exist_ok=True)
subprocess.run(['tar', '-xzf', str(DEPLOY / 'application.tar.gz'), '-C', str(release)], check=True)
manifest = json.loads((DEPLOY / 'application-manifest.json').read_text())
for item in manifest['files']:
    path = release / item['path']
    if hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
        raise RuntimeError('Application digest mismatch: ' + item['path'])
for folder in ('config', 'certs', 'data', 'assets'):
    (SHARED / folder).mkdir(exist_ok=True)
os.chmod(SHARED, 0o700)
for filename in ('system.conf', 'config.json'):
    source = DEPLOY / ('authorized-' + filename)
    destination = SHARED / 'config' / filename
    if source.exists():
        if destination.exists():
            raise RuntimeError('Existing target configuration must not be overwritten')
        source.replace(destination)
        os.chmod(destination, 0o600)


def link(relative, target):
    path = release / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        if os.readlink(path) != target:
            raise RuntimeError('Unexpected deployment symlink')
    elif path.exists():
        raise RuntimeError('Unexpected deployment path: ' + relative)
    else:
        path.symlink_to(target)


native = 'fay-ue4/runtime/fay-local/app/'
for filename in ('system.conf', 'config.json'):
    link(native + filename, '/shared/config/' + filename)
for folder in ('memory', 'cache_data', 'samples', 'logs'):
    destination = SHARED / 'data' / ('native-' + folder)
    destination.mkdir(exist_ok=True)
    link(native + folder, '/shared/data/native-' + folder)
registry = SHARED / 'data/mcp-registry'
registry.mkdir(exist_ok=True)
for name, value in [('mcp_servers.json', []), ('mcp_tool_states.json', {}), ('mcp_prestart_tools.json', {})]:
    path = registry / name
    if not path.exists():
        path.write_text(json.dumps(value))
link(native + 'faymcp/data', '/shared/data/mcp-registry')
for name, target in [('avatar-2d/runtime', 'presenter-runtime'), ('attendance-mcp/runtime', 'attendance-runtime')]:
    (SHARED / 'data' / target).mkdir(exist_ok=True)
    link(name, '/shared/data/' + target)
avatars = SHARED / 'data/presenter-runtime/avatars'
if not avatars.exists() and not avatars.is_symlink():
    avatars.symlink_to('/shared/assets/avatar-2d/runtime/avatars')
link('avatar-2d/models', '/shared/assets/avatar-2d/models')
(release / native / 'qa.csv').write_text('')
secret = SHARED / 'config/turn-secret'
if not secret.exists():
    secret.write_text(secrets.token_urlsafe(40))
    os.chmod(secret, 0o600)
private_ip = subprocess.check_output(['hostname', '-I'], text=True).split()[0]
ports = json.loads((release / 'deployment/ports.json').read_text())
turn = f'''listening-port={ports['turn']}
listening-ip=0.0.0.0
relay-ip={private_ip}
external-ip=36.133.88.94/{private_ip}
min-port={ports['relay_min']}
max-port={ports['relay_max']}
realm=xiaolin
fingerprint
use-auth-secret
static-auth-secret={secret.read_text().strip()}
user-quota=8
total-quota=32
no-cli
no-multicast-peers
denied-peer-ip=127.0.0.0-127.255.255.255
denied-peer-ip=169.254.0.0-169.254.255.255
'''
(SHARED / 'config/turnserver.conf').write_text(turn)
os.chmod(SHARED / 'config/turnserver.conf', 0o600)
gpu = subprocess.check_output(['nvidia-smi', '--query-gpu=uuid', '--format=csv,noheader'], text=True).splitlines()[0]
environment = f'XIAOLIN_RELEASE={release}\nXIAOLIN_VERSION={version}\nXIAOLIN_GPU_UUID={gpu}\nXIAOLIN_PRIVATE_IP={private_ip}\n'
(DEPLOY / 'compose.env').write_text(environment)
current = BASE / 'current'
if current.is_symlink():
    current.unlink()
current.symlink_to(release)
print(json.dumps({'release': str(release), 'verified_files': len(manifest['files']), 'gpu_uuid': gpu,
    'fresh_history': True, 'credentials_configured': True}))
