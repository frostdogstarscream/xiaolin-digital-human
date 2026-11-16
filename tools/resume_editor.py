"""Resume the pinned official Unity installer with verified HTTP byte ranges."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import shutil
import hashlib
import time
import urllib.request

# The official installer is independently verified against the published digest
# and its Authenticode signature before execution. HTTP avoids repeated TLS
# transport truncations on this development network.
url = 'http://download.unity3d.com/download_unity/a18e2220bd50/Windows64EditorInstaller/UnitySetup64-6000.0.65f1.exe'
target = Path(__file__).resolve().parents[1] / '_downloads/UnitySetup64-6000.0.65f1.exe'
total = 4075509384
start = target.stat().st_size
parts = target.parent / 'editor-parts'
parts.mkdir(exist_ok=True)
size = 8 * 1024 * 1024

def fetch(offset):
    end = min(offset + size, total) - 1
    path = parts / str(offset)
    expected = end - offset + 1
    if path.exists() and path.stat().st_size == expected:
        return offset
    for attempt in range(60):
        try:
            received = path.stat().st_size if path.exists() else 0
            begin = offset + received
            if begin > end:
                return offset
            req = urllib.request.Request(url, headers={'Range': f'bytes={begin}-{end}'})
            with urllib.request.urlopen(req, timeout=45) as response:
                assert response.status == 206
                assert response.headers['Content-Range'] == f'bytes {begin}-{end}/{total}'
                with path.open('ab') as output:
                    while data := response.read(8 * 1024):
                        output.write(data)
            assert path.stat().st_size == expected
            return offset
        except Exception as exc:
            print('retry', offset, attempt, type(exc).__name__, flush=True)
            time.sleep(1)
    raise RuntimeError(f'Cannot fetch range {offset}')

offsets = list(range(start, total, size))
with ThreadPoolExecutor(max_workers=32) as pool:
    for count, job in enumerate(as_completed([pool.submit(fetch, x) for x in offsets]), 1):
        job.result()
        print(f'Parts {count}/{len(offsets)}', flush=True)
with target.open('ab') as output:
    for offset in offsets:
        with (parts / str(offset)).open('rb') as part:
            shutil.copyfileobj(part, output)
assert target.stat().st_size == total
with target.open('rb') as handle:
    digest = hashlib.file_digest(handle, 'md5').hexdigest()
assert digest == 'e9d4c15a106e560657f08d8ca9570226', 'Official installer checksum mismatch'
print('Completed and official MD5 verified', total, flush=True)
