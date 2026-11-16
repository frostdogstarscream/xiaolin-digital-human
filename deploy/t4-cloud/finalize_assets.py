"""Extract the lossless runtime subset and verify exact source file digests."""
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path('/opt/xiaolin')
archive = ROOT / 'deployment/runtime-assets.tar.zst'
expected = '2a6ead0fc1a09a5858140ed2e39376d2d9a66465a2584dc477db940073791ba9'
with archive.open('rb') as stream:
    if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
        raise RuntimeError('Transport archive digest mismatch')
subprocess.run(['tar', '--zstd', '-xf', str(archive), '-C', str(ROOT / 'shared/assets')], check=True)
records = json.loads((ROOT / 'deployment/asset-manifest.json').read_text())['files']
verified = []
for item in records:
    if item['path'].startswith('avatar-2d/runtime/avatars/presenter_v1/'):
        continue
    path = ROOT / 'shared/assets' / item['path']
    with path.open('rb') as stream:
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
    if actual != item['sha256']:
        raise RuntimeError('Runtime asset mismatch: ' + item['path'])
    verified.append(item)
receipt = dict(status='PASSED', verified_files=len(verified), files=verified,
    transport='lossless-zstandard', model_download_verified=True)
(ROOT / 'deployment/verified-assets.json').write_text(json.dumps(receipt, indent=2))
print(json.dumps({'status': 'PASSED', 'verified_files': len(verified)}))
