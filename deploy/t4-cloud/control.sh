#!/bin/bash
set -euo pipefail
base=/opt/xiaolin
compose=(docker compose --env-file "$base/deployment/compose.env" -f "$base/current/deployment/compose.yaml")
case "${1:-status}" in
    start)
        if test -f "$base/deployment/configure_runtime.py"; then
            python3 "$base/deployment/configure_runtime.py"
        fi
        "${compose[@]}" up -d ;;
    stop)
        "${compose[@]}" stop -t 30 presenter
        if curl -fsS --max-time 5 -X POST -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:5000/api/get-run-status | grep -q 'true'; then
            curl -fsS --max-time 120 -X POST -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:5000/api/stop-live >/dev/null
        fi
        "${compose[@]}" down -t 45
        ;;
    status) "${compose[@]}" ps ;;
    logs) "${compose[@]}" logs --tail 100 ;;
    rollback)
        version=${2:?Supply a previous release version}
        [[ "$version" =~ ^[a-zA-Z0-9-]+$ ]] || exit 2
        target="$base/releases/$version"
        test -f "$target/deployment/compose.yaml"
        "$0" stop
        ln -sfn "$target" "$base/current"
        sed -i "s#^XIAOLIN_RELEASE=.*#XIAOLIN_RELEASE=$target#;s/^XIAOLIN_VERSION=.*/XIAOLIN_VERSION=$version/" "$base/deployment/compose.env"
        "$0" start
        ;;
    *) exit 2 ;;
esac
