"""Issue a dedicated IP certificate and a separate authenticated web login."""
import hashlib
import json
import os
import secrets
import subprocess
from pathlib import Path

ROOT = Path('/opt/xiaolin/shared')
CERTS = ROOT / 'certs'
CONFIG = ROOT / 'config'
CERTS.mkdir(exist_ok=True)
CONFIG.mkdir(exist_ok=True)


def openssl(*arguments):
    subprocess.run(['openssl', *arguments], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if not (CERTS / 'ca.crt').exists():
    openssl('req', '-x509', '-newkey', 'rsa:3072', '-sha256', '-days', '3650', '-noenc',
        '-keyout', str(CERTS / 'ca.key'), '-out', str(CERTS / 'ca.crt'),
        '-subj', '/CN=Xiaolin T4 Local Root CA',
        '-addext', 'basicConstraints=critical,CA:TRUE',
        '-addext', 'keyUsage=critical,keyCertSign,cRLSign')
    openssl('req', '-new', '-newkey', 'rsa:2048', '-noenc',
        '-keyout', str(CERTS / 'server.key'), '-out', str(CERTS / 'server.csr'),
        '-subj', '/CN=36.133.88.94')
    extensions = CERTS / 'server.ext'
    extensions.write_text('subjectAltName=IP:36.133.88.94\nbasicConstraints=critical,CA:FALSE\n'
        'keyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n')
    openssl('x509', '-req', '-in', str(CERTS / 'server.csr'), '-CA', str(CERTS / 'ca.crt'),
        '-CAkey', str(CERTS / 'ca.key'), '-CAcreateserial', '-out', str(CERTS / 'server.crt'),
        '-days', '365', '-sha256', '-extfile', str(extensions))
for filename in ('ca.key', 'server.key'):
    os.chmod(CERTS / filename, 0o600)
access = CONFIG / 'web-access.json'
if not access.exists():
    password = secrets.token_urlsafe(24)
    hashed = subprocess.run(['openssl', 'passwd', '-6', '-stdin'], input=password + '\n',
        text=True, capture_output=True, check=True).stdout.strip()
    (CONFIG / 'access.htpasswd').write_text('xiaolin:' + hashed + '\n')
    os.chmod(CONFIG / 'access.htpasswd', 0o644)
    access.write_text(json.dumps(dict(url='https://36.133.88.94:6443/', username='xiaolin', password=password), indent=2))
    os.chmod(access, 0o600)
receipt = dict(https_ip='36.133.88.94',
    ca_file_sha256=hashlib.sha256((CERTS / 'ca.crt').read_bytes()).hexdigest(),
    dedicated_ca=True, web_access_configured=True)
(ROOT.parent / 'deployment/access-receipt.json').write_text(json.dumps(receipt, indent=2))
print(json.dumps(receipt))
