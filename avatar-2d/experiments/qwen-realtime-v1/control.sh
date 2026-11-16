#!/usr/bin/env bash
set -euo pipefail
case "${1:-status}" in
  start) docker start xiaolin-qwen-realtime-v1 ;;
  stop) docker stop --timeout 20 xiaolin-qwen-realtime-v1 ;;
  status)
    docker inspect xiaolin-qwen-realtime-v1 --format '{{.State.Status}}'
    curl -fsS http://127.0.0.1:8770/api/health
    ;;
  logs) docker logs --tail 100 xiaolin-qwen-realtime-v1 ;;
  *) echo 'Usage: control.sh start|stop|status|logs'; exit 2 ;;
esac
