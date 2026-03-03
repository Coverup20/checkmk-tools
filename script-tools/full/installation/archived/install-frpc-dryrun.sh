#!/usr/bin/env bash
set -euo pipefail

# DRY RUN: mostra cosa farebbe install-frpc.sh, senza modifiche.

FRP_VERSION="0.64.0"
FRP_URL_DEFAULT="https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/frp_${FRP_VERSION}_linux_amd64.tar.gz"

OS_TYPE="altro"
if [[ -r /etc/os-release ]]; then
    if grep -qi "rocky" /etc/os-release; then
        OS_TYPE="rockylinux"
    elif grep -qi "nethserver" /etc/os-release; then
        OS_TYPE="nethserver"
    elif grep -qi "debian" /etc/os-release; then
        if command -v dpkg >/dev/null 2>&1 && dpkg -l 2>/dev/null | grep -q pve-manager; then
            OS_TYPE="proxmox"
        else
            OS_TYPE="debian"
        fi
    fi
fi

echo "[DRYRUN] OS rilevato: $OS_TYPE"

read -r -p "URL pacchetto FRP [default: $FRP_URL_DEFAULT]: " FRP_URL
FRP_URL="${FRP_URL:-$FRP_URL_DEFAULT}"
read -r -p "Nome host (es: rl94ns8): " HOSTNAME
read -r -p "Porta remota da usare: " REMOTE_PORT

if [[ -z "$HOSTNAME" || -z "$REMOTE_PORT" ]]; then
    echo "[DRYRUN][ERR] Parametri mancanti" >&2
    exit 1
fi

echo "[DRYRUN] Download: $FRP_URL"
echo "[DRYRUN] Estraggo in: /usr/local/src/frp_${FRP_VERSION}_linux_amd64"
echo "[DRYRUN] Installo binario: /usr/local/bin/frpc"
echo "[DRYRUN] Scrivo config: /etc/frp/frpc.toml"
echo "[DRYRUN] Scrivo unita': /etc/systemd/system/frpc.service"
echo "[DRYRUN] Avvio: systemctl enable --now frpc"

cat <<EOF

[DRYRUN] Esempio frpc.toml (token non incluso):
[common]
server_addr = "monitor.nethlab.it"
server_port = 7000
auth.method = "token"
auth.token  = "<INSERIRE_TOKEN>"
tls.enable  = true
log.to      = "/var/log/frpc.log"
log.level   = "info"

[$HOSTNAME]
type        = "tcp"
local_ip    = "127.0.0.1"
local_port  = 6556
remote_port = $REMOTE_PORT
EOF
