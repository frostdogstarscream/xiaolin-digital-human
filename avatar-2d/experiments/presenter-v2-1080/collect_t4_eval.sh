#!/usr/bin/env bash
set -euo pipefail
EVAL=/opt/xiaolin/evaluations/presenter-v2-1080
RUN=${1:-run01}
[[ "$RUN" =~ ^run[0-9][0-9]$ ]]
test "$(docker inspect "xiaolin-v2-sustained-$RUN" --format '{{.State.Status}}')" = exited
docker logs "xiaolin-v2-sustained-$RUN" > "$EVAL/$RUN.log" 2>&1
docker inspect "xiaolin-v2-sustained-$RUN" --format '{{json .State}}' > "$EVAL/$RUN-container-state.json"
docker ps --filter label=com.docker.compose.project=xiaolin --format '{{.Names}} {{.Status}}' > "$EVAL/production-after.txt"
nvidia-smi --query-gpu=index,uuid,name,memory.used,memory.total,utilization.gpu --format=csv > "$EVAL/gpu-after.txt"
readlink -f /opt/xiaolin/current > "$EVAL/production-current-after.txt"
tar -czf "$EVAL/t4-$RUN-evidence.tar.gz" -C "$EVAL" \
  deployment-record.json image-id.txt model-sha256.txt script-sha256.txt \
  probe-result.json host-nvidia-smi.txt requirements-frozen.txt restore.log \
  production-before.txt production-after.txt gpu-after.txt production-current-after.txt \
  "$RUN.log" "$RUN-container-state.json" \
  avatar-2d/outputs/presenter-v2-1080/t4-reconstruction.json \
  "avatar-2d/outputs/presenter-v2-1080/t4-$RUN"
sha256sum "$EVAL/t4-$RUN-evidence.tar.gz"
cat "$EVAL/gpu-after.txt"
cat "$EVAL/production-after.txt"
