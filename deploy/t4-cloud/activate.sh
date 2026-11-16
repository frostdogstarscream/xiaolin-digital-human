#!/bin/bash
set -euo pipefail
base=/opt/xiaolin
version=$(sed -n 's/^XIAOLIN_VERSION=//p' "$base/deployment/compose.env")
for component in presenter asr fay turn; do
    docker image inspect "xiaolin-$component:$version" >/dev/null
done
docker image inspect nginx:1.28-alpine >/dev/null
test -f "$base/deployment/verified-assets.json"
chmod 700 "$base/deployment/control.sh"
install -m 644 "$base/deployment/xiaolin.service" /etc/systemd/system/xiaolin.service
ufw allow 6025/tcp
ufw allow 6443/tcp
ufw allow 6478/tcp
ufw allow 6478/udp
ufw allow 10000:10099/udp
ufw default deny incoming
ufw default allow outgoing
ufw --force enable
systemctl daemon-reload
if systemctl is-enabled --quiet xiaolin-ssh-portmap.service; then
    systemctl restart xiaolin-ssh-portmap.service
fi
systemctl enable --now xiaolin.service
echo CLOUD_SERVICES_ACTIVATED
