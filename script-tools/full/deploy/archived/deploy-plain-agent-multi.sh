#!/usr/bin/env bash
set -euo pipefail

# Deploy Checkmk Agent in modalita plain TCP 6556 su piu host via SSH.
# Configura unita' systemd (socket+service) e disabilita il socket TLS standard.
# Uso:
#   sudo ./deploy-plain-agent-multi.sh [--force] [--user root] host1 host2 ...
# Se non passi host come argomenti, usa la lista DEFAULT_HOSTS.

DEFAULT_HOSTS=("marziodemo" "proxmox01" "rocky01" "ns8demo")
SSH_USER="root"
FORCE=0

ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --force)
            FORCE=1
            shift
            ;;
        --user)
            SSH_USER="${2:-root}"
            shift 2
            ;;
        -h|--help)
            echo "Uso: sudo $0 [--force] [--user root] host1 host2 ..."
            exit 0
            ;;
        *)
            ARGS+=("$1")
            shift
            ;;
    esac
done

HOSTS=()
if [[ ${#ARGS[@]} -gt 0 ]]; then
    HOSTS=("${ARGS[@]}")
else
    HOSTS=("${DEFAULT_HOSTS[@]}")
fi

REMOTE_SCRIPT=$(cat <<'EOF'
set -euo pipefail

SOCKET_FILE="/etc/systemd/system/check-mk-agent-plain.socket"
SERVICE_FILE="/etc/systemd/system/check-mk-agent-plain@.service"

FORCE="${FORCE:-0}"
if [[ "$FORCE" != "1" ]] && { [[ -f "$SOCKET_FILE" ]] || [[ -f "$SERVICE_FILE" ]]; }; then
  echo "[INFO] Unita' plain gia' presenti, skip"
  exit 0
fi

echo "[INFO] Disabilito agent TLS (cmk-agent-ctl-daemon) se presente"
systemctl stop cmk-agent-ctl-daemon 2>/dev/null || true
systemctl disable cmk-agent-ctl-daemon 2>/dev/null || true

echo "[INFO] Disabilito socket standard Checkmk (check-mk-agent.socket) se presente"
systemctl stop check-mk-agent.socket 2>/dev/null || true
systemctl disable check-mk-agent.socket 2>/dev/null || true

echo "[INFO] Scrivo unita' systemd per agent plain (porta 6556)"
cat >"$SOCKET_FILE" <<'EOT'
[Unit]
Description=Checkmk Agent (TCP 6556 plain)
Documentation=https://docs.checkmk.com/latest/en/agent_linux.html

[Socket]
ListenStream=6556
Accept=yes

[Install]
WantedBy=sockets.target
EOT

cat >"$SERVICE_FILE" <<'EOT'
[Unit]
Description=Checkmk Agent (TCP 6556 plain) connection
Documentation=https://docs.checkmk.com/latest/en/agent_linux.html

[Service]
ExecStart=-/usr/bin/check_mk_agent
StandardInput=socket
EOT

systemctl daemon-reload
systemctl enable --now check-mk-agent-plain.socket

echo "[OK] Host configurato"
EOF
)

for host in "${HOSTS[@]}"; do
    echo "[INFO] Configuro $host"
    ssh -o BatchMode=yes -o ConnectTimeout=10 "${SSH_USER}@${host}" "FORCE=${FORCE} bash -s" <<<"$REMOTE_SCRIPT"
done
