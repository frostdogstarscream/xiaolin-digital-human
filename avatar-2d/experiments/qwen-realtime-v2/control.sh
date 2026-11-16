#!/usr/bin/env bash
set -euo pipefail
case "${1:-status}" in
  start)
    docker start xiaolin-qwen-realtime-v2
    for attempt in $(seq 1 60); do
      if curl -fsS http://127.0.0.1:8771/api/health >/dev/null 2>&1; then exit 0; fi
      sleep 1
    done
    echo 'Service readiness timed out'; exit 1
    ;;
  stop) docker stop --timeout 20 xiaolin-qwen-realtime-v2 ;;
  status)
    docker inspect xiaolin-qwen-realtime-v2 --format '{{.State.Status}}'
    curl -fsS http://127.0.0.1:8771/api/health
    ;;
  logs) docker logs --tail 100 xiaolin-qwen-realtime-v2 ;;
  *) echo 'Usage: control.sh start|stop|status|logs'; exit 2 ;;
esac
