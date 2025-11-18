#!/bin/bash
# ==================================================
# Installazione FRPC client (0.64.0) - DRY RUN
# Non modifica nulla, stampa solo le azioni che
# verrebbero eseguite
# ==================================================

FRP_VERSION="0.64.0"
FRP_URL_DEFAULT="https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/frp_${FRP_VERSION}_linux_amd64.tar.gz"

echo "=== DRY RUN Installazione FRPC Client ==="

# ----------------------------
# 1. Rileva sistema operativo
# ----------------------------
if grep -qi "rocky" /etc/os-release; then
    OS_TYPE="rockylinux"
elif grep -qi "nethserver" /etc/os-release; then
    OS_TYPE="nethserver"
elif grep -qi "debian" /etc/os-release; then
    if dpkg -l | grep -q pve-manager; then
        OS_TYPE="proxmox"
    else
        OS_TYPE="debian"
    fi
else
    OS_TYPE="altro"
fi
echo "Rilevato sistema operativo: $OS_TYPE"

# ----------------------------
# 2. Parametri richiesti
# ----------------------------
read -p "URL pacchetto FRP [default: $FRP_URL_DEFAULT]: " FRP_URL
FRP_URL=${FRP_URL:-$FRP_URL_DEFAULT}

read -p "Nome host (es: rl94ns8): " HOSTNAME
read -p "Porta remota da usare: " REMOTE_PORT

# ----------------------------
# 3. Simulazione installazione
# ----------------------------
echo
echo "--- Azioni che verrebbero eseguite ---"
echo "1. Scarico pacchetto da: $FRP_URL"
echo "2. Estraggo e installo frpc in /usr/local/bin/"
echo "3. Creo config TOML in /etc/frp/frpc.toml con:"
echo "   - server_addr = monitor.nethlab.it"
echo "   - hostname    = $HOSTNAME"
echo "   - remote_port = $REMOTE_PORT"
echo

# ----------------------------
# 4. Simulazione servizio
# ----------------------------
case "$OS_TYPE" in
  rockylinux|debian|proxmox)
    echo "--- Creerei un systemd unit file in /etc/systemd/system/frpc.service ---"
    echo "[Unit]"
    echo "Description=FRP Client Service ($OS_TYPE)"
    echo "After=network.target"
    echo
    echo "[Service]"
    echo "ExecStart=/usr/local/bin/frpc -c /etc/frp/frpc.toml"
    echo "Restart=on-failure"
    echo "RestartSec=5s"
    echo "User=root"
    echo
    echo "[Install]"
    echo "WantedBy=multi-user.target"
    ;;
  nethserver)
    echo "--- Creerei un template e-smith in /etc/e-smith/templates-custom/etc/systemd/system/frpc.service/10base ---"
    echo "Poi eseguirei:"
    echo "   config set frpc service status enabled"
    echo "   signal-event runlevel-adjust"
    ;;
  *)
    echo "âš ï¸ Sistema operativo non riconosciuto: nessuna azione eseguita"
    ;;
esac

# ----------------------------
# 5. Conclusione
# ----------------------------
echo
echo "=== DRY RUN completato ==="
echo "Nessun file Ã¨ stato modificato."
