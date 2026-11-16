#!/bin/sh
set -eu
root=/opt/xiaolin/evaluations/musetalk-t4-20261111
docker stop xiaolin-musetalk-eval-20261111
docker run -d --name xiaolin-musetalk-taesd-eval-20261111 --network bridge \
  --device nvidia.com/gpu=GPU-d83c041f-3543-6c67-faf0-23f3d1910f44 \
  --shm-size 2g --cpus 8 --memory 24g \
  -e MUSE_DECODER_VARIANT=taesd -e OMP_NUM_THREADS=4 \
  -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 -e SDL_AUDIODRIVER=dummy \
  -v /opt/xiaolin/releases/20261110-ports:/app:ro \
  -v /opt/xiaolin/shared/assets:/shared/assets:ro \
  -v /opt/xiaolin/shared/assets/avatar-2d/runtime/avatars:/shared/data/presenter-runtime/avatars:ro \
  -v "$root/musetalk-eval:/eval" -w /eval \
  xiaolin-presenter:20261110-ports python service/server.py
docker exec -i xiaolin-musetalk-taesd-eval-20261111 python - <<'PY'
import json,time,urllib.request,urllib.error
deadline=time.monotonic()+120
while time.monotonic()<deadline:
    try:
        state=json.load(urllib.request.urlopen('http://127.0.0.1:8768/api/health',timeout=3))['state']
        if state=='ready':break
        if state=='error':raise RuntimeError('Evaluation model failed to load')
    except urllib.error.URLError:pass
    time.sleep(1)
else:raise TimeoutError('Evaluation startup deadline exceeded')
PY
docker exec -d xiaolin-musetalk-taesd-eval-20261111 sh -c \
  'python -u tests/check_realtime.py --seconds 300 --resume-candidate > outputs/run03-taesd-realtime.log 2>&1'
