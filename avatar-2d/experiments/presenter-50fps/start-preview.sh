#!/bin/sh
set -eu
ROOT=/opt/xiaolin/evaluations/presenter-v2-1080
mkdir -p "$ROOT/avatar-2d/outputs/presenter-50fps/logs"
touch "$ROOT/avatar-2d/outputs/presenter-50fps/logs/livetalking.log"
if docker inspect xiaolin-50fps-preview >/dev/null 2>&1; then
    docker start xiaolin-50fps-preview
    exit 0
fi
docker run -d --name xiaolin-50fps-preview --network host --gpus device=0 --cpus 12 \
  -e NVIDIA_DRIVER_CAPABILITIES=compute,utility,video -e XIAOLIN_PRECISION=fp32 \
  -e XIAOLIN_50_PRECISION=fp16 -e OPENBLAS_NUM_THREADS=1 -e OMP_NUM_THREADS=4 -e MKL_NUM_THREADS=1 \
  -e CUDNN_CONV_WSCAP_DBG=256 -e XIAOLIN_TURN_HOST=36.133.88.94 -e XIAOLIN_TURN_PORT=6478 \
  -e XIAOLIN_TURN_TRANSPORTS=tcp -e XIAOLIN_TURN_SECRET_FILE=/config/turn-secret \
  -e XIAOLIN_BIND_IP=192.168.0.116 -e XIAOLIN_ICE_MIN_PORT=10200 -e XIAOLIN_ICE_MAX_PORT=10249 \
  -v /opt/xiaolin/shared/config/turn-secret:/config/turn-secret:ro \
  -v /opt/xiaolin/current:/app:ro -v "$ROOT:/eval:ro" \
  -v "$ROOT/avatar-2d/outputs/presenter-50fps/logs/livetalking.log:/eval/avatar-2d/livetalking.log" \
  -v /opt/xiaolin/shared/assets/avatar-2d/models:/eval/avatar-2d/models:ro \
  -w /eval/avatar-2d xiaolin-presenter:20261110-ports python experiments/presenter-50fps/review_server.py
