#!/bin/bash
# ============================================================
#  Installazione / Disinstallazione Checkmk Agent + FRP client
#  Compatibile con OpenWrt / NethSecurity 8 (init: procd)
#  Versione: 3.0 - stabile (socat mode)
# ============================================================

set -e
CUSTOMFEEDS="/etc/opkg/customfeeds.conf"
TMPDIR="/tmp/checkmk-deb"

REPO_BASE="https://downloads.openwrt.org/releases/23.05.0/packages/x86_64/base"
REPO_PACKAGES="https://downloads.openwrt.org/releases/23.05.0/packages/x86_64/packages"

DEB_URL="https://monitoring.nethlab.it/monitoring/check_mk/agents/check-mk-agent_2.4.0p14-1_all.deb"
AGENT_TAR="/tmp/check-mk-agent_2.4.0p14.tar.gz"

FRP_VER="0.64.0"
FRPC_BIN="/usr/local/bin/frpc"
FRPC_CONF="/etc/frp/frpc.toml"
FRPC_INIT="/etc/init.d/frpc"
FRPC_LOG="/var/log/frpc.log"

# ============================================================
# 🧹 Disinstallazione (--uninstall)
# ============================================================
if [ "$1" = "--uninstall" ]; then
    echo "🧹 Disinstallazione Checkmk Agent + FRP client..."
    [ -x "$FRPC_INIT" ] && { /etc/init.d/frpc stop || true; /etc/init.d/frpc disable || true; }
    killall frpc socat >/dev/null 2>&1 || true
    rm -rf /etc/frp "$FRPC_BIN" "$FRPC_INIT" "$FRPC_LOG" >/dev/null 2>&1 || true
    rm -f /usr/bin/check_mk_agent
    rm -rf /etc/check_mk /etc/xinetd.d/check_mk >/dev/null 2>&1 || true
    [ -f /etc/init.d/check_mk_agent ] && { /etc/init.d/check_mk_agent stop || true; /etc/init.d/check_mk_agent disable || true; rm -f /etc/init.d/check_mk_agent; }
    echo "✅ Disinstallazione completata."
    exit 0
fi

# ============================================================
# 1️⃣ Repository
# ============================================================
echo "⚙️  Configuro repository OpenWrt 23.05.0..."
mkdir -p "$(dirname "$CUSTOMFEEDS")"
touch "$CUSTOMFEEDS"

add_repo() {
    local name="$1" url="$2"
    grep -q "$url" "$CUSTOMFEEDS" || echo "src/gz $name $url" >>"$CUSTOMFEEDS"
}
add_repo "openwrt_base" "$REPO_BASE"
add_repo "openwrt_packages" "$REPO_PACKAGES"

# ============================================================
# 2️⃣ Strumenti base
# ============================================================
echo "📦 Aggiorno feed e installo tool..."
opkg update
opkg install binutils tar gzip wget socat ca-certificates || opkg install busybox-full
command -v ar >/dev/null || { echo "❌ 'ar' mancante"; exit 1; }

# ============================================================
# 3️⃣ Checkmk Agent
# ============================================================
echo "⬇️  Scarico Checkmk Agent..."
mkdir -p "$TMPDIR"; cd "$TMPDIR"
wget -q -O check-mk-agent.deb "$DEB_URL"
ar x check-mk-agent.deb
mkdir -p data; tar -xzf data.tar.gz -C data
cd data && tar -czf "$AGENT_TAR" . && cd ..

echo "📂 Installo agent..."
cp -f data/usr/bin/check_mk_agent /usr/bin/ 2>/dev/null || true
chmod +x /usr/bin/check_mk_agent
mkdir -p /etc/check_mk /etc/xinetd.d
cp -rf data/etc/check_mk/* /etc/check_mk/ 2>/dev/null || true
rm -rf "$TMPDIR"
echo "✅ Agent installato."

# ============================================================
# 4️⃣ Servizio persistente Checkmk Agent (socat listener)
# ============================================================
echo "⚙️  Creo servizio init.d per Checkmk Agent (porta 6556, persistente con socat)..."

cat >/etc/init.d/check_mk_agent <<'EOF'
#!/bin/sh /etc/rc.common
# Checkmk Agent listener for OpenWrt / NethSecurity
START=98
STOP=10
USE_PROCD=1
PROG=/usr/bin/check_mk_agent

start_service() {
    mkdir -p /var/run
    echo "Starting Checkmk Agent on TCP port 6556..."
    procd_open_instance
    procd_set_param command socat TCP-LISTEN:6556,reuseaddr,fork,keepalive EXEC:$PROG
    procd_set_param respawn  # Auto-restart if socat crashes
    procd_set_param stdout 1
    procd_set_param stderr 1
    procd_close_instance
}

stop_service() {
    echo "Stopping Checkmk Agent..."
    killall socat >/dev/null 2>&1 || true
}
EOF

chmod +x /etc/init.d/check_mk_agent
/etc/init.d/check_mk_agent enable >/dev/null 2>&1 || true
/etc/init.d/check_mk_agent restart

sleep 2
if pgrep -f "socat TCP-LISTEN:6556" >/dev/null 2>&1; then
    echo "✅ Checkmk Agent attivo e persistente sulla porta 6556 (socat mode)."
else
    echo "⚠️  Checkmk Agent non risponde — verifica /usr/bin/check_mk_agent."
fi

# ============================================================
# 5️⃣ FRP client
# ============================================================
echo ""
echo "======================================"
echo " Installazione FRP client (TOML moderno)"
echo " Server remoto: monitor.nethlab.it:7000"
echo "======================================"
read -rp "Vuoi installare e configurare il client FRP? [s/N]: " INSTALL_FRP
INSTALL_FRP=$(echo "$INSTALL_FRP" | tr '[:upper:]' '[:lower:]')

if [[ "$INSTALL_FRP" =~ ^(s|si|y|yes)$ ]]; then
    SERVER_ADDR="monitor.nethlab.it"
    SERVER_PORT="7000"

    while true; do
        read -rp "Inserisci la remote_port da assegnare (es. 6020): " REMOTE_PORT
        [[ "$REMOTE_PORT" =~ ^[0-9]+$ ]] && break || echo "⚠️ Inserisci un numero valido."
    done

    read -rp "Inserisci la chiave/token FRP: " FRP_TOKEN
    DEFAULT_NAME=$(hostname 2>/dev/null || echo "openwrt-host")
    echo ""
    echo "💡 Nome del proxy FRP (univoco per ogni host)"
    echo "   Default suggerito: $DEFAULT_NAME"
    read -rp "Inserisci il nome da usare per questo client [$DEFAULT_NAME]: " PROXY_NAME
    PROXY_NAME=${PROXY_NAME:-$DEFAULT_NAME}

    echo "⬇️  Scarico FRP v$FRP_VER..."
    cd /tmp
    FRP_TGZ="frp_${FRP_VER}_linux_amd64.tar.gz"
    FRP_DL="https://github.com/fatedier/frp/releases/download/v${FRP_VER}/${FRP_TGZ}"
    wget -q -O "$FRP_TGZ" "$FRP_DL"
    tar -xzf "$FRP_TGZ"
    FRP_DIR=$(tar -tzf "$FRP_TGZ" | head -1 | cut -f1 -d"/")
    mkdir -p /usr/local/bin
    cp -f "$FRP_DIR/frpc" "$FRPC_BIN"
    chmod +x "$FRPC_BIN"
    rm -rf "$FRP_TGZ" "$FRP_DIR"

    mkdir -p /etc/frp /var/log
    cat >"$FRPC_CONF" <<EOF
[common]
server_addr = "$SERVER_ADDR"
server_port = $SERVER_PORT
auth.method = "token"
auth.token  = "$FRP_TOKEN"
tls.enable = true
log.to = "$FRPC_LOG"
log.level = "debug"

[$PROXY_NAME]
type        = "tcp"
local_ip    = "127.0.0.1"
local_port  = 6556
remote_port = $REMOTE_PORT
EOF

    cat >"$FRPC_INIT" <<'INIT'
#!/bin/sh /etc/rc.common
START=99
STOP=10
USE_PROCD=1
start_service() {
    procd_open_instance
    procd_set_param command /usr/local/bin/frpc -c /etc/frp/frpc.toml
    procd_set_param respawn
    procd_close_instance
}
stop_service() {
    killall frpc >/dev/null 2>&1 || true
}
INIT
    chmod +x "$FRPC_INIT"
    /etc/init.d/frpc enable >/dev/null 2>&1 || true
    /etc/init.d/frpc start || /usr/local/bin/frpc -c "$FRPC_CONF" &

    sleep 2
    echo ""
    if pgrep -f frpc >/dev/null 2>&1; then
        echo "✅ FRP attivo per proxy [$PROXY_NAME] → porta remota $REMOTE_PORT"
    else
        echo "⚠️  FRP non attivo. Controlla log: tail -f $FRPC_LOG"
    fi
fi

# ============================================================
# 6️⃣ Fine
# ============================================================
echo ""
echo "======================================"
echo " Installazione completata!"
echo " Test agent: nc 127.0.0.1 6556 | head"
echo " Test tunnel: nc 127.0.0.1 <porta_remota> | head (su server FRPS)"
echo " Config FRP: /etc/frp/frpc.toml"
echo " Disinstallazione: bash $0 --uninstall"
echo "======================================"

