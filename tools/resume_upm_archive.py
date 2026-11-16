"""Range-resume a pinned UPM tarball and verify its official registry SHA1."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import shutil
import time
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument('package')
parser.add_argument('version')
parser.add_argument('--workers', type=int, default=16)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1] / '_downloads/upm'
meta = json.loads((root / (args.package + '.json')).read_text(encoding='utf-8'))['versions'][args.version]
dist = meta['dist']
destination = root / f'{args.package}-{args.version}.tgz'
partial = destination.with_suffix('.tgz.part')
if destination.exists():
    with destination.open('rb') as file:
        assert hashlib.file_digest(file, 'sha1').hexdigest() == dist['shasum']
    print('Archive already verified')
    raise SystemExit(0)
url = dist['tarball']
for _ in range(10):
    try:
        response = urllib.request.urlopen(urllib.request.Request(url, method='HEAD'), timeout=30)
        url = response.url
        total = int(response.headers['Content-Length'])
        response.close()
        break
    except Exception:
        time.sleep(1)
else:
    raise RuntimeError('Unable to read official archive length')
start = partial.stat().st_size if partial.exists() else 0
chunks = root / (destination.name + '.chunks')
chunks.mkdir(exist_ok=True)
size = 4 * 1024 * 1024

def fetch(offset):
    end = min(offset + size, total) - 1
    path = chunks / str(offset)
    for attempt in range(40):
        received = path.stat().st_size if path.exists() else 0
        begin = offset + received
        if begin > end:
            return offset
        try:
            req = urllib.request.Request(url, headers={'Range': f'bytes={begin}-{end}', 'Accept-Encoding': 'identity'})
            with urllib.request.urlopen(req, timeout=45) as response:
                assert response.status == 206
                assert response.headers['Content-Range'] == f'bytes {begin}-{end}/{total}'
                with path.open('ab') as output:
                    while data := response.read(64 * 1024):
                        output.write(data)
            assert path.stat().st_size == end - offset + 1
            return offset
        except Exception as error:
            print('Retry', args.package, offset, type(error).__name__, flush=True)
            time.sleep(1)
    raise RuntimeError(f'Unable to download {args.package} offset {offset}')

offsets = list(range(start, total, size))
print(args.package, 'resuming', start, 'of', total, flush=True)
with ThreadPoolExecutor(max_workers=args.workers) as pool:
    for count, future in enumerate(as_completed([pool.submit(fetch, offset) for offset in offsets]), 1):
        future.result()
        print(args.package, f'{count}/{len(offsets)} parts', flush=True)
assembled = destination.with_suffix('.tgz.assembled')
with assembled.open('wb') as output:
    if start:
        with partial.open('rb') as source:
            remaining = start
            while remaining:
                data = source.read(min(1024 * 1024, remaining))
                if not data:
                    raise RuntimeError('Partial archive prefix changed while downloading')
                output.write(data)
                remaining -= len(data)
    for offset in offsets:
        with (chunks / str(offset)).open('rb') as source:
            shutil.copyfileobj(source, output)
assert assembled.stat().st_size == total
with assembled.open('rb') as file:
    assert hashlib.file_digest(file, 'sha1').hexdigest() == dist['shasum'], 'Official archive checksum mismatch'
assembled.replace(destination)
print(args.package, 'archive verified', flush=True)
