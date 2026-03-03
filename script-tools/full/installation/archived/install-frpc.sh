#!/usr/bin/env bash
set -euo pipefail

# Installazione e configurazione FRPC client (0.64.0)
# Output semplice (ASCII-only).

FRP_VERSION="0.64.0"
FRP_URL_DEFAULT="https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/frp_${FRP_VERSION}_linux_amd64.tar.gz"

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
    echo "[ERR] Eseguire come root (sudo)" >&2
    exit 1
fi

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

echo "[INFO] OS rilevato: $OS_TYPE"

read -r -p "URL pacchetto FRP [default: $FRP_URL_DEFAULT]: " FRP_URL
FRP_URL="${FRP_URL:-$FRP_URL_DEFAULT}"
read -r -p "Nome host (es: rl94ns8): " HOSTNAME
read -r -p "Porta remota da usare: " REMOTE_PORT
read -r -s -p "Token FRP (auth.token): " AUTH_TOKEN
echo

if [[ -z "$HOSTNAME" || -z "$REMOTE_PORT" || -z "$AUTH_TOKEN" ]]; then
    echo "[ERR] Parametri mancanti" >&2
    exit 1
fi

echo "[INFO] Download FRP: $FRP_URL"
mkdir -p /usr/local/src
cd /usr/local/src
rm -rf "frp_${FRP_VERSION}_linux_amd64" frp.tar.gz 2>/dev/null || true
wget -q "$FRP_URL" -O frp.tar.gz
tar xzf frp.tar.gz
cd "frp_${FRP_VERSION}_linux_amd64"

echo "[INFO] Installo frpc in /usr/local/bin/frpc"
systemctl stop frpc 2>/dev/null || true
install -m 0755 frpc /usr/local/bin/frpc

echo "[INFO] Scrivo /etc/frp/frpc.toml"
mkdir -p /etc/frp
cat > /etc/frp/frpc.toml <<EOF
[common]
server_addr = "monitor.nethlab.it"
server_port = 7000
auth.method = "token"
auth.token  = "$AUTH_TOKEN"
tls.enable  = true
log.to      = "/var/log/frpc.log"
log.level   = "info"

[$HOSTNAME]
type        = "tcp"
local_ip    = "127.0.0.1"
local_port  = 6556
remote_port = $REMOTE_PORT
EOF

echo "[INFO] Scrivo unita' systemd /etc/systemd/system/frpc.service"
cat > /etc/systemd/system/frpc.service <<EOF
[Unit]
Description=FRP Client Service
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/frpc -c /etc/frp/frpc.toml
Restart=on-failure
RestartSec=5s
User=root

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now frpc

echo "[OK] Installazione completata"
systemctl status frpc -l --no-pager || true
