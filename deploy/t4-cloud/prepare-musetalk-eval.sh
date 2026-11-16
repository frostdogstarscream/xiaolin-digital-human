#!/bin/sh
set -eu
root=/opt/xiaolin/evaluations/musetalk-t4-20261111
test -f "$root/musetalk-eval/docs/download-result.json"
test ! -f "$root/prepared.ok"
mkdir -p "$root/musetalk-eval/outputs" "$root/musetalk-eval/docs"
python3 - "$root" <<'PY'
import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1])/'musetalk-eval'
manifest=json.loads((root/'models/manifest.json').read_text())
for item in manifest['files']:
    path=root/'models'/item['destination']
    assert hashlib.file_digest(path.open('rb'),'sha256').hexdigest()==item['sha256'],str(path)
for item in json.loads((root/'fixtures/manifest.json').read_text())['fixtures']:
    path=root/item['file']
    assert hashlib.file_digest(path.open('rb'),'sha256').hexdigest()==item['sha256'],str(path)
p=root/'service/bootstrap.py'
s=p.read_text().replace("AVATAR=WORKSPACE/'avatar-2d'","AVATAR=Path('/app/avatar-2d')")
s=s.replace("FFMPEG=WORKSPACE/'fay-ue4/runtime/fay-local/app/test/ovr_lipsync/ffmpeg/bin/ffmpeg.exe'","FFMPEG=Path('/usr/bin/ffmpeg')")
p.write_text(s)
(root/'docs/transfer-validation.json').write_text(json.dumps({'models_sha256_verified':True,'fixtures_sha256_verified':True,'source':'existing frozen local evaluation','production_modified':False},indent=2))
PY
touch "$root/prepared.ok"
docker run -d --name xiaolin-musetalk-eval-20261111 --network bridge \
  --device nvidia.com/gpu=GPU-d83c041f-3543-6c67-faf0-23f3d1910f44 \
  --shm-size 2g --cpus 8 --memory 24g \
  -e OMP_NUM_THREADS=4 -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
  -e HF_HUB_DISABLE_TELEMETRY=1 -e SDL_AUDIODRIVER=dummy \
  -v /opt/xiaolin/releases/20261110-ports:/app:ro \
  -v /opt/xiaolin/shared/assets:/shared/assets:ro \
  -v /opt/xiaolin/shared/assets/avatar-2d/runtime/avatars:/shared/data/presenter-runtime/avatars:ro \
  -v "$root/musetalk-eval:/eval" \
  -w /eval xiaolin-presenter:20261110-ports python service/server.py
