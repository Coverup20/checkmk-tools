#!/bin/bash
# ================================================
# Deploy Checkmk Agent in modalità Plain TCP 6556
# Compatibile con Checkmk Raw Edition
# ================================================

set -e

SOCKET_FILE="/etc/systemd/system/check-mk-agent-plain.socket"
SERVICE_FILE="/etc/systemd/system/check-mk-agent-plain@.service"

FORCE=0
if [[ "$1" == "--force" ]]; then
    FORCE=1
    echo "⚠️  Modalità FORCE attiva: eventuali file esistenti saranno sovrascritti."
fi

# --- Check esistenza ---
if [[ $FORCE -eq 0 ]] && ([[ -f "$SOCKET_FILE" ]] || [[ -f "$SERVICE_FILE" ]]); then
    echo "⚠️  ATTENZIONE: esiste già un file service/socket plain:"
    [[ -f "$SOCKET_FILE" ]] && echo " - $SOCKET_FILE"
    [[ -f "$SERVICE_FILE" ]] && echo " - $SERVICE_FILE"
    echo "Usa $0 --force se vuoi sovrascriverli."
    exit 1
fi

echo "👉 Disabilito agent controller TLS (cmk-agent-ctl-daemon)..."
systemctl stop cmk-agent-ctl-daemon 2>/dev/null || true
systemctl disable cmk-agent-ctl-daemon 2>/dev/null || true

echo "👉 Disabilito il socket systemd standard..."
systemctl stop check-mk-agent.socket 2>/dev/null || true
systemctl disable check-mk-agent.socket 2>/dev/null || true

echo "👉 Creo unit systemd per agent plain..."
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

echo "👉 Ricarico systemd..."
systemctl daemon-reload

echo "👉 Abilito e avvio il nuovo socket..."
systemctl enable --now check-mk-agent-plain.socket

echo "✅ Completato. Verifica con:"
echo "   ss -tlnp | grep 6556"
echo "   nc 127.0.0.1 6556 | head"

