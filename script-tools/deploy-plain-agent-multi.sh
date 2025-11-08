#!/bin/bash
# =====================================================
# Deploy Checkmk Agent (plain TCP 6556) su piÃ¹ host via SSH
# Compatibile con Checkmk Raw Edition
# =====================================================

# Lista degli host (hostname o IP)
HOSTS=("marziodemo" "proxmox01" "rocky01" "ns8demo")

# Utente SSH (deve avere sudo/root)
USER="root"

# Flag FORCE
FORCE=0
if [[ "$1" == "--force" ]]; then
    FORCE=1
    echo "âš ï¸ ModalitÃ  FORCE attiva: eventuali file esistenti saranno sovrascritti."
fi

# Script remoto che sarÃ  eseguito su ciascun host
read -r -d '' REMOTE_SCRIPT <<'EOF'
set -e
SOCKET_FILE="/etc/systemd/system/check-mk-agent-plain.socket"
SERVICE_FILE="/etc/systemd/system/check-mk-agent-plain@.service"

if [[ $FORCE -eq 0 ]] && ([[ -f "$SOCKET_FILE" || -f "$SERVICE_FILE" ]]); then
  echo "âš ï¸  Unit plain giÃ  presente, skip..."
  exit 0
fi

echo "ðŸ‘‰ Disabilito agent controller TLS..."
systemctl stop cmk-agent-ctl-daemon 2>/dev/null || true
systemctl disable cmk-agent-ctl-daemon 2>/dev/null || true

echo "ðŸ‘‰ Disabilito il socket systemd standard..."
systemctl stop check-mk-agent.socket 2>/dev/null || true
systemctl disable check-mk-agent.socket 2>/dev/null || true

echo "ðŸ‘‰ Creo unit systemd per agent plain..."
cat >"$SOCKET_FILE" <<EOT
[Unit]
Description=Checkmk Agent (TCP 6556 plain)
Documentation=https://docs.checkmk.com/latest/en/agent_linux.html

[Socket]
ListenStream=6556
Accept=yes

[Install]
WantedBy=sockets.target
EOT

cat >"$SERVICE_FILE" <<EOT
[Unit]
Description=Checkmk Agent (TCP 6556 plain) connection
Documentation=https://docs.checkmk.com/latest/en/agent_linux.html

[Service]
ExecStart=-/usr/bin/check_mk_agent
StandardInput=socket
EOT

echo "ðŸ‘‰ Ricarico systemd..."
systemctl daemon-reload

echo "ðŸ‘‰ Abilito e avvio il nuovo socket..."
systemctl enable --now check-mk-agent-plain.socket

echo "âœ… Host configurato. Test locale:"
/usr/bin/check_mk_agent | head -n 5
EOF

# Loop sugli host
for h in "${HOSTS[@]}"; do
  echo "============================"
  echo "âž¡ï¸  Configuro $h"
  echo "============================"
  ssh -o BatchMode=yes -o ConnectTimeout=10 ${USER}@${h} \
    "FORCE=${FORCE} bash -s" <<< "$REMOTE_SCRIPT"
  echo ""
done
