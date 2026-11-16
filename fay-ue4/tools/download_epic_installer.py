"""Download the already resolved official Epic installer in verified byte ranges."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import urllib.request
from urllib.parse import urlparse
import os


def main():
    root = Path(__file__).resolve().parents[1] / 'installers'
    url = (root / 'epic-source-url.txt').read_text(encoding='ascii').strip()
    if urlparse(url).scheme != 'https' or urlparse(url).hostname != 'epicgames-download1.akamaized.net':
        raise ValueError('Unexpected download host')
    with urllib.request.urlopen(urllib.request.Request(url, method='HEAD'), timeout=30) as r:
        length = int(r.headers['Content-Length'])
    target = root / 'EpicInstaller-verified-ranges.msi'
    if target.exists(): raise FileExistsError(target)
    part_root = root / 'epic-parts'
    part_root.mkdir(exist_ok=True)
    count = 12
    chunk = (length + count - 1) // count
    def fetch(index):
        start = index * chunk; end = min(length - 1, start + chunk - 1)
        part = part_root / ('%02d.part' % index)
        req = urllib.request.Request(url, headers={'Range': 'bytes=%d-%d' % (start, end)})
        with urllib.request.urlopen(req, timeout=120) as r:
            if r.status != 206 or r.headers.get('Content-Range') != 'bytes %d-%d/%d' % (start, end, length):
                raise ValueError('Server did not honor requested range')
            with part.open('wb') as out:
                while True:
                    data = r.read(1024 * 256)
                    if not data: break
                    out.write(data)
        if part.stat().st_size != end - start + 1: raise ValueError('Incomplete part')
        return index
    with ThreadPoolExecutor(max_workers=count) as pool:
        for f in as_completed([pool.submit(fetch, i) for i in range(count)]):
            print('Completed part', f.result() + 1, 'of', count, flush=True)
    temporary = target.with_suffix('.assembling')
    with temporary.open('wb') as out:
        for i in range(count):
            with (part_root / ('%02d.part' % i)).open('rb') as inp:
                while True:
                    data = inp.read(1024 * 1024)
                    if not data: break
                    out.write(data)
    if temporary.stat().st_size != length: raise ValueError('Incorrect total size')
    os.replace(temporary, target)
    print('Saved', target, 'bytes', length, 'Authenticode verification still required', flush=True)


if __name__ == '__main__': main()
