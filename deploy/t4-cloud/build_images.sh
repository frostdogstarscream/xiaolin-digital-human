#!/bin/bash
set -euo pipefail
cd /opt/xiaolin/deployment
version=$(sed -n 's/^XIAOLIN_VERSION=//p' compose.env)
docker pull docker.m.daocloud.io/library/python:3.12-slim-bookworm
docker tag docker.m.daocloud.io/library/python:3.12-slim-bookworm python:3.12-slim-bookworm
for service in presenter asr fay; do
    DOCKER_BUILDKIT=0 docker build --target "$service" -t "xiaolin-$service:$version" .
done
DOCKER_BUILDKIT=0 docker build -f Dockerfile.turn -t "xiaolin-turn:$version" .
docker pull docker.m.daocloud.io/library/nginx:1.28-alpine
docker tag docker.m.daocloud.io/library/nginx:1.28-alpine nginx:1.28-alpine
docker images --digests --format '{{json .}}' > image-manifest.jsonl
echo IMAGE_BUILD_COMPLETE
