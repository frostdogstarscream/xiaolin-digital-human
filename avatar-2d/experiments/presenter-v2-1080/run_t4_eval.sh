#!/usr/bin/env bash
set -euo pipefail
EVAL=/opt/xiaolin/evaluations/presenter-v2-1080
GPU=GPU-d83c041f-3543-6c67-faf0-23f3d1910f44
RUN=${1:-run01}
[[ "$RUN" =~ ^run[0-9][0-9]$ ]]
test "$(docker inspect xiaolin-v2-restore --format '{{.State.ExitCode}}')" = 0
test "$(docker inspect xiaolin-v2-restore --format '{{.State.Status}}')" = exited
test -f "$EVAL/avatar-2d/outputs/presenter-v2-1080/t4-reconstruction.json"
docker run -d --name "xiaolin-v2-sustained-$RUN" --network none \
  --device "nvidia.com/gpu=$GPU" \
  -e NVIDIA_DRIVER_CAPABILITIES=compute,utility,video \
  -e XIAOLIN_PRECISION=fp32 -e XIAOLIN_VIDEO_ENCODER=h264_nvenc \
  -e XIAOLIN_EVAL_GPU_UUID="$GPU" -e XIAOLIN_EVAL_SECONDS=300 \
  -e "XIAOLIN_EVAL_OUTPUT=/eval/avatar-2d/outputs/presenter-v2-1080/t4-$RUN" \
  -e OMP_NUM_THREADS=4 -e OPENBLAS_NUM_THREADS=4 -e MKL_NUM_THREADS=4 \
  -e HF_HUB_OFFLINE=1 -e MODELSCOPE_OFFLINE=1 -e SDL_AUDIODRIVER=dummy \
  -v /opt/xiaolin/current:/app:ro -v "$EVAL:/eval" \
  -v /opt/xiaolin/shared/assets/avatar-2d/models:/eval/avatar-2d/models:ro \
  -w /eval/avatar-2d xiaolin-presenter:20261110-ports \
  python /eval/avatar-2d/experiments/presenter-v2-1080/check_t4_sustained.py
