#!/bin/sh
# Read-only inventory. No service changes and no credential/config dumps.
set -eu
date -u '+%Y-%m-%dT%H:%M:%SZ'
hostname
nvidia-smi --query-gpu=index,uuid,name,memory.total,memory.used,utilization.gpu --format=csv
nvidia-smi --query-compute-apps=gpu_uuid,pid,process_name,used_memory --format=csv
readlink -f /opt/xiaolin/current
docker ps --format '{{.Names}} {{.Image}} {{.Status}}'
docker image ls --format '{{.Repository}}:{{.Tag}} {{.Size}}'
df -h /opt/xiaolin
free -h
for directory in /opt/xiaolin/experiments /opt/xiaolin/shared/assets; do
    if [ -d "$directory" ]; then
        find "$directory" -mindepth 1 -maxdepth 2 -type d
    fi
done
