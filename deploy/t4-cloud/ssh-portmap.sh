#!/bin/bash
# IPv4 ingress mapping: external TCP 6025 -> existing OpenSSH TCP 22.
set -euo pipefail
base=/opt/xiaolin/deployment
mode_file="$base/ssh-portmap-6025.mode"
iface=eth0
tag=xiaolin-ssh-6025
mapping=(-p tcp --dport 6025 -m addrtype --dst-type LOCAL -m comment --comment "$tag-nat" -j REDIRECT --to-ports 22)
allow=(-p tcp --dport 22 -m conntrack --ctstate NEW --ctorigdstport 6025 -m comment --comment "$tag-allow" -j ACCEPT)
block=(-i "$iface" -p tcp --dport 22 -m conntrack --ctstate NEW --ctorigdstport 22 -m comment --comment "$tag-block-old" -j REJECT --reject-with tcp-reset)

ensure_rule() {
    local table=$1 chain=$2; shift 2
    iptables -w 10 -t "$table" -C "$chain" "$@" 2>/dev/null || iptables -w 10 -t "$table" -I "$chain" 1 "$@"
}
remove_rule() {
    local table=$1 chain=$2; shift 2
    if iptables -w 10 -t "$table" -C "$chain" "$@" 2>/dev/null; then
        iptables -w 10 -t "$table" -D "$chain" "$@"
    fi
}
case "${1:-status}" in
    start)
        test -r "$mode_file"
        ip link show "$iface" >/dev/null
        ensure_rule nat PREROUTING "${mapping[@]}"
        ensure_rule filter INPUT "${allow[@]}"
        if grep -qx finalized "$mode_file"; then
            ensure_rule filter INPUT "${block[@]}"
        fi
        ;;
    finalize)
        # Invoke only after a new authenticated, host-key-pinned external 6025 session succeeds.
        "$0" start
        ensure_rule filter INPUT "${block[@]}"
        printf 'finalized\n' > "$mode_file"
        ;;
    reopen-old)
        printf 'prepared\n' > "$mode_file"
        remove_rule filter INPUT "${block[@]}"
        ;;
    stop)
        remove_rule filter INPUT "${block[@]}"
        remove_rule filter INPUT "${allow[@]}"
        remove_rule nat PREROUTING "${mapping[@]}"
        ;;
    status)
        printf 'mode='; cat "$mode_file"
        iptables -w 10 -t nat -S PREROUTING | grep "$tag" || true
        iptables -w 10 -S INPUT | grep "$tag" || true
        ;;
    *) exit 2 ;;
esac
