"""Collect installed Python redistribution notices without importing application dependencies."""
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
destination = ROOT / 'licenses/PythonDependencies'
destination.mkdir(parents=True, exist_ok=True)
manifest = []
for dist in importlib.metadata.distributions():
    name = dist.metadata.get('Name', '')
    if not name:
        continue
    folder = destination / (name.replace('/', '_') + '-' + dist.version)
    copied = []
    for item in dist.files or []:
        basename = Path(str(item)).name.lower()
        if not basename.startswith(('license', 'licence', 'copying', 'notice')):
            continue
        source = Path(dist.locate_file(item))
        if not source.is_file():
            continue
        folder.mkdir(exist_ok=True)
        target = folder / (str(item).replace('/', '__').replace('\\', '__'))
        shutil.copyfile(source, target)
        copied.append(str(target.relative_to(destination)))
    manifest.append({'name': name, 'version': dist.version,
                     'license_expression': dist.metadata.get('License-Expression'), 'notices': copied})
for candidate in ('LICENSE.txt', 'LICENSE'):
    path = Path(sys.base_prefix) / candidate
    if path.is_file():
        shutil.copyfile(path, destination / 'Python-LICENSE.txt')
        break
(destination / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'Collected installed distribution notices for {len(manifest)} packages.')

unity_destination = ROOT / 'licenses/UnityPackages'
unity_manifest = []
for package in sorted((ROOT / 'unity/Packages').iterdir()):
    metadata = package / 'package.json'
    if not metadata.is_file():
        continue
    value = json.loads(metadata.read_text(encoding='utf-8-sig'))
    copied = []
    for source in package.rglob('*'):
        if not source.is_file() or source.suffix == '.meta':
            continue
        if not source.name.lower().startswith(('license', 'licence', 'copying', 'notice', 'third party notices', 'third-party-notices')):
            continue
        target = unity_destination / package.name / source.relative_to(package)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        copied.append(str(target.relative_to(unity_destination)))
    unity_manifest.append({'name': value['name'], 'version': value['version'], 'notices': copied})
unity_destination.mkdir(parents=True, exist_ok=True)
(unity_destination / 'manifest.json').write_text(json.dumps(unity_manifest, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'Collected embedded Unity package notices for {len(unity_manifest)} packages.')
