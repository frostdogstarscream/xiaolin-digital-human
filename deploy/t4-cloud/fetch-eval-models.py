"""Fetch frozen artifacts from a mirror; accept only the pre-recorded SHA256."""
import concurrent.futures
import hashlib
import json
import subprocess
import time
from pathlib import Path

ROOT = Path('/opt/xiaolin/evaluations/musetalk-t4-20261111/musetalk-eval')


def fetch(item):
    path = ROOT / 'models' / item['destination']
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and hashlib.file_digest(path.open('rb'), 'sha256').hexdigest() == item['sha256']:
        return item['destination']
    temporary = path.with_suffix(path.suffix + '.partial')
    url = item['url'].replace('https://huggingface.co/', 'https://hf-mirror.com/', 1)
    subprocess.run(['curl', '-fL', '--retry', '3', '--connect-timeout', '20', '--max-time', '1800',
                    '-o', str(temporary), url], check=True)
    actual = hashlib.file_digest(temporary.open('rb'), 'sha256').hexdigest()
    if actual != item['sha256']:
        raise RuntimeError('SHA256 mismatch: ' + item['destination'])
    temporary.replace(path)
    print('VERIFIED', item['destination'], flush=True)
    return item['destination']


if __name__ == '__main__':
    started = time.time()
    manifest = json.loads((ROOT / 'models/manifest.json').read_text())
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        files = list(pool.map(fetch, manifest['files']))
    (ROOT / 'docs/download-result.json').write_text(json.dumps({
        'status': 'ALL_HASHES_VERIFIED', 'seconds': time.time() - started,
        'transport': 'hf-mirror.com', 'files': files}, indent=2))
    print('ALL_HASHES_VERIFIED', flush=True)
