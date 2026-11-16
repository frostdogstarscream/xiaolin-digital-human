"""Materialize version-specific TURN ports without changing secrets or persistent data."""
import json,os,subprocess
from pathlib import Path
base=Path('/opt/xiaolin');release=(base/'current').resolve();shared=base/'shared/config'
path=release/'deployment/ports.json'
ports=json.loads(path.read_text()) if path.exists() else dict(origin='https://36.133.88.94',turn=3478,relay_min=49160,relay_max=49209)
private_ip=subprocess.check_output(['hostname','-I'],text=True).split()[0]
secret=(shared/'turn-secret').read_text().strip()
text=f'''listening-port={ports['turn']}
listening-ip=0.0.0.0
relay-ip={private_ip}
external-ip=36.133.88.94/{private_ip}
min-port={ports['relay_min']}
max-port={ports['relay_max']}
realm=xiaolin
fingerprint
use-auth-secret
static-auth-secret={secret}
user-quota=8
total-quota=32
no-cli
no-multicast-peers
denied-peer-ip=127.0.0.0-127.255.255.255
denied-peer-ip=169.254.0.0-169.254.255.255
'''
destination=shared/'turnserver.conf'
temporary=destination.with_suffix('.tmp');temporary.write_text(text);os.chmod(temporary,0o600);temporary.replace(destination)
access=shared/'web-access.json'
if access.exists():
    data=json.loads(access.read_text());data['url']=ports['origin']+'/'
    temporary=access.with_suffix('.tmp');temporary.write_text(json.dumps(data,indent=2));os.chmod(temporary,0o600);temporary.replace(access)
print(json.dumps(dict(version=release.name,origin=ports['origin'],turn_port=ports['turn'],secrets_preserved=True)))
