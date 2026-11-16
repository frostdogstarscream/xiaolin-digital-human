"""Bounded range download of one frozen model; verify before publishing."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import subprocess
from pathlib import Path

root = Path('/opt/xiaolin/evaluations/musetalk-t4-20261111/musetalk-eval')
item = next(x for x in json.loads((root/'models/manifest.json').read_text())['files']
            if x['destination'] == 'whisper/pytorch_model.bin')
parts = root/'models/whisper/range-download'
parts.mkdir(exist_ok=True)
size = item['bytes']
chunk = 4 * 1024 * 1024
url = item['url'].replace('https://huggingface.co/', 'https://hf-mirror.com/') + '?download=true'


def fetch(start):
    end = min(start + chunk, size) - 1
    target = parts/str(start)
    subprocess.run(['curl', '-fLs', '--retry', '2', '--max-time', '180',
                    '--range', f'{start}-{end}', '-o', str(target), url], check=True)
    assert target.stat().st_size == end-start+1
    return target


with ThreadPoolExecutor(max_workers=12) as pool:
    files = list(pool.map(fetch, range(0, size, chunk)))
combined = parts/'combined.bin'
with combined.open('wb') as out:
    for p in files:
        out.write(p.read_bytes())
assert hashlib.file_digest(combined.open('rb'), 'sha256').hexdigest() == item['sha256']
combined.replace(root/'models'/item['destination'])
print('WHISPER_SHA256_VERIFIED', flush=True)
