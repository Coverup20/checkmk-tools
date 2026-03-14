#!/usr/bin/env bash
set -euo pipefail

# Deploy Checkmk Agent in modalita plain TCP 6556 (systemd).
# Uso:
#   sudo ./deploy-plain-agent.sh [--force]

SOCKET_FILE="/etc/systemd/system/check-mk-agent-plain.socket"
SERVICE_FILE="/etc/systemd/system/check-mk-agent-plain@.service"

FORCE=0
if [[ "${1:-}" == "--force" ]]; then
    FORCE=1
    echo "[INFO] Modalita FORCE: sovrascrivo file esistenti"
fi

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
    echo "[ERR] Eseguire come root (sudo)" >&2
    exit 1
fi

if [[ $FORCE -eq 0 ]] && { [[ -f "$SOCKET_FILE" ]] || [[ -f "$SERVICE_FILE" ]]; }; then
    echo "[WARN] Unita' plain gia' presenti:" >&2
    [[ -f "$SOCKET_FILE" ]] && echo "- $SOCKET_FILE" >&2
    [[ -f "$SERVICE_FILE" ]] && echo "- $SERVICE_FILE" >&2
    echo "Usa --force per sovrascrivere." >&2
    exit 1
fi

echo "[INFO] Disabilito agent TLS (cmk-agent-ctl-daemon) se presente"
systemctl stop cmk-agent-ctl-daemon 2>/dev/null || true
systemctl disable cmk-agent-ctl-daemon 2>/dev/null || true

echo "[INFO] Disabilito socket standard Checkmk (check-mk-agent.socket) se presente"
systemctl stop check-mk-agent.socket 2>/dev/null || true
systemctl disable check-mk-agent.socket 2>/dev/null || true

echo "[INFO] Scrivo unita' systemd per agent plain (porta 6556)"
cat >"$SOCKET_FILE" <<'EOF'
[Unit]
Description=Checkmk Agent (TCP 6556 plain)
Documentation=https://docs.checkmk.com/latest/en/agent_linux.html

[Socket]
ListenStream=6556
Accept=yes

[Install]
WantedBy=sockets.target
EOF

cat >"$SERVICE_FILE" <<'EOF'
[Unit]
Description=Checkmk Agent (TCP 6556 plain) connection
Documentation=https://docs.checkmk.com/latest/en/agent_linux.html

[Service]
ExecStart=-/usr/bin/check_mk_agent
StandardInput=socket
EOF

echo "[INFO] Ricarico systemd e avvio il socket"
systemctl daemon-reload
systemctl enable --now check-mk-agent-plain.socket

echo "[OK] Completato"
echo "Verifica:"
echo "- ss -tlnp | grep 6556"
echo "- nc 127.0.0.1 6556 | head"
