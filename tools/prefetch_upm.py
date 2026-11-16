"""Embed pinned public UPM packages from the official Unity China registry for reproducible builds."""
from concurrent.futures import ThreadPoolExecutor
import argparse
from pathlib import Path
import hashlib
import io
import json
import subprocess
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ROOT / 'unity/Packages'
CACHE = ROOT / '_downloads/upm'
CACHE.mkdir(parents=True, exist_ok=True)
manifest = json.loads((PACKAGES / 'manifest.json').read_text(encoding='utf-8'))
parser = argparse.ArgumentParser()
parser.add_argument('--skip', action='append', default=[])
args = parser.parse_args()
direct = manifest['dependencies']
records = []


def download(url, path):
    if path.exists():
        return
    temp = path.with_suffix(path.suffix + '.part')
    if path.suffix == '.json':
        for attempt in range(8):
            try:
                with urllib.request.urlopen(url, timeout=20) as response:
                    raw = response.read()
                json.loads(raw)
                temp.write_bytes(raw)
                temp.replace(path)
                return
            except Exception as error:
                print('Retry metadata', path.name, type(error).__name__, flush=True)
        raise RuntimeError(f'Unable to fetch metadata {path.name}')
    for attempt in range(30):
        result = subprocess.run(['curl.exe', '--fail', '--location', '--silent', '--show-error',
            '--continue-at', '-', '--connect-timeout', '15', '--max-time', '120', '--output', str(temp), url],
            creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode == 0:
            temp.replace(path)
            return
        print('Resume package', path.name, temp.stat().st_size if temp.exists() else 0, flush=True)
    raise RuntimeError(f'Unable to fetch {path.name}')


def fetch(item):
    name, version = item
    if name.startswith('com.unity.modules.') or name == 'com.unity.ugui':
        return {}
    existing = PACKAGES / name / 'package.json'
    if existing.exists():
        value = json.loads(existing.read_text(encoding='utf-8'))
        meta_path = CACHE / (name + '.json')
        if meta_path.exists():
            package = json.loads(meta_path.read_text(encoding='utf-8'))['versions'][value['version']]
            records.append({'package': name, 'version': value['version'],
                            'url': package['dist']['tarball'], 'sha1': package['dist']['shasum']})
        return value.get('dependencies', {})
    meta_path = CACHE / (name + '.json')
    download('https://packages.unity.cn/' + name, meta_path)
    package = json.loads(meta_path.read_text(encoding='utf-8'))['versions'][version]
    dist = package['dist']
    archive_path = CACHE / f'{name}-{version}.tgz'
    download(dist['tarball'], archive_path)
    raw = archive_path.read_bytes()
    digest = hashlib.sha1(raw).hexdigest()
    if digest != dist['shasum']:
        raise RuntimeError(f'Archive integrity mismatch: {name}')
    destination = PACKAGES / name
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
        for member in archive:
            if not member.isfile():
                continue
            parts = Path(member.name).parts
            if not parts or parts[0] != 'package' or '..' in parts:
                raise RuntimeError(f'Invalid package path: {member.name}')
            path = destination.joinpath(*parts[1:]).resolve()
            if not path.is_relative_to(destination.resolve()):
                raise RuntimeError('Package path escapes destination')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.extractfile(member).read())
    records.append({'package': name, 'version': version, 'url': dist['tarball'], 'sha1': digest})
    print('Embedded', name, version, flush=True)
    return package.get('dependencies', {})


queue = {k: v for k, v in direct.items() if k.startswith('com.unity.')}
seen = set()
while queue:
    batch = [(k, direct.get(k, v)) for k, v in queue.items() if k not in seen and k not in args.skip]
    seen.update(k for k, _ in batch)
    queue = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for dependencies in pool.map(fetch, batch):
            queue.update({k: v for k, v in dependencies.items() if k not in seen})

unitask = PACKAGES / 'com.cysharp.unitask'
if not (unitask / 'package.json').exists():
    url = 'https://codeload.github.com/Cysharp/UniTask/zip/refs/tags/2.5.4'
    source = CACHE / 'unitask-2.5.4.zip'
    download(url, source)
    prefix = 'UniTask-2.5.4/src/UniTask/Assets/Plugins/UniTask/'
    with zipfile.ZipFile(source) as archive:
        for item in archive.infolist():
            if item.is_dir() or not item.filename.startswith(prefix):
                continue
            relative = Path(item.filename[len(prefix):])
            if '..' in relative.parts:
                raise RuntimeError('Invalid UniTask path')
            path = unitask / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.read(item))
    records.append({'package': 'com.cysharp.unitask', 'version': '2.5.4', 'url': url,
                    'sha256': hashlib.sha256(source.read_bytes()).hexdigest()})
    print('Embedded com.cysharp.unitask 2.5.4', flush=True)
lock = ROOT / 'upm-sources.lock.json'
previous = json.loads(lock.read_text(encoding='utf-8')) if lock.exists() else []
mapped = {r['package']: r for r in previous + records}
lock.write_text(json.dumps(list(mapped.values()), indent=2), encoding='utf-8')
