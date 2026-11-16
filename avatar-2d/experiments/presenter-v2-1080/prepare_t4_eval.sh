#!/usr/bin/env bash
set -euo pipefail
EVAL=/opt/xiaolin/evaluations/presenter-v2-1080
python3 - <<'PY'
import hashlib,json,shutil,zipfile
from pathlib import Path
root=Path('/opt/xiaolin/evaluations/presenter-v2-1080')
source=root/'source-delivery.zip'
assert hashlib.file_digest(source.open('rb'),'sha256').hexdigest()=='ef9a2eb56b56893556ee7c8e4c9ff7102a9346bb984667e6e4b9c5f5d4030bce'
with zipfile.ZipFile(source) as archive:
    assert len(archive.namelist())==len(set(archive.namelist()))
    for name in archive.namelist():
        assert (root/name).resolve().is_relative_to(root)
    assert archive.testzip() is None
    archive.extractall(root)
for filename in ('check_t4_sustained','restore_sources'):
    latest=root/(filename+'.latest.py')
    if latest.exists():
        shutil.copy2(latest,root/'avatar-2d/experiments/presenter-v2-1080'/(filename+'.py'))
manifest=Path('/opt/xiaolin/current/avatar-2d/source-manifest.json')
shutil.copy2(manifest,root/'avatar-2d/source-manifest.json')
(root/'avatar-2d/models').mkdir(exist_ok=True)
record=dict(archive_sha256=hashlib.file_digest(source.open('rb'),'sha256').hexdigest(),
    vendor=json.loads(manifest.read_text()),root=str(root),production_release=Path('/opt/xiaolin/current').resolve().as_posix())
record['script_sha256']={p.name:hashlib.file_digest(p.open('rb'),'sha256').hexdigest()
    for p in (root/'avatar-2d/experiments/presenter-v2-1080').glob('*.py')}
(root/'deployment-record.json').write_text(json.dumps(record,indent=2))
print('Verified and extracted isolated evaluation bundle')
PY
docker run -d --name xiaolin-v2-restore --network none \
  -e OMP_NUM_THREADS=4 -e OPENBLAS_NUM_THREADS=4 \
  -v "$EVAL:/eval" -w /eval/avatar-2d \
  xiaolin-presenter:20261110-ports \
  python /eval/avatar-2d/experiments/presenter-v2-1080/restore_sources.py
