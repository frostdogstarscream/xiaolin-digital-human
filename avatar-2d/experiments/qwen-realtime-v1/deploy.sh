#!/usr/bin/env bash
set -euo pipefail
EVAL=/opt/xiaolin/evaluations/presenter-v2-1080
test -f "$EVAL/avatar-2d/runtime/presenter-v2-1080/avatars/idle/frames.npy"
docker run -d --name xiaolin-qwen-realtime-v1 --restart unless-stopped --network host \
  --device nvidia.com/gpu=GPU-d83c041f-3543-6c67-faf0-23f3d1910f44 \
  -e NVIDIA_DRIVER_CAPABILITIES=compute,utility,video -e XIAOLIN_PRECISION=fp32 \
  -e XIAOLIN_VIDEO_ENCODER=h264_nvenc -e QWEN_DEMO_PORT=8770 \
  -e QWEN_DEMO_ORIGIN=https://36.133.88.94:6444 \
  -e FAY_SYSTEM_CONF=/config/fay-system.conf \
  -e XIAOLIN_DEPLOYMENT=/app/avatar-2d/service -e XIAOLIN_TURN_HOST=36.133.88.94 \
  -e XIAOLIN_TURN_PORT=6478 -e XIAOLIN_TURN_TRANSPORTS=tcp \
  -e XIAOLIN_TURN_SECRET_FILE=/config/turn-secret \
  -e XIAOLIN_BIND_IP=192.168.0.116 -e XIAOLIN_ICE_MIN_PORT=10100 -e XIAOLIN_ICE_MAX_PORT=10149 \
  -e OMP_NUM_THREADS=4 -e OPENBLAS_NUM_THREADS=4 -e MKL_NUM_THREADS=4 \
  -e HF_HUB_OFFLINE=1 -e MODELSCOPE_OFFLINE=1 -e SDL_AUDIODRIVER=dummy \
  -v /opt/xiaolin/current:/app:ro -v "$EVAL:/eval" \
  -v /opt/xiaolin/shared/assets/avatar-2d/models:/eval/avatar-2d/models:ro \
  -v /opt/xiaolin/shared/config/system.conf:/config/fay-system.conf:ro \
  -v /opt/xiaolin/shared/config/turn-secret:/config/turn-secret:ro \
  -w /eval/avatar-2d xiaolin-presenter:20261110-ports \
  python /eval/avatar-2d/experiments/qwen-realtime-v1/gateway.py
