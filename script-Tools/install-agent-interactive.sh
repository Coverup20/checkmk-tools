#!/bin/bash
# =====================================================
# Script Interattivo: Installazione CheckMK Agent + FRPC (opzionale)
# - Installa agent CheckMK in modalità plain (TCP 6556)
# - Opzionalmente installa e configura FRPC client
# - Configurazione guidata interattiva
# =====================================================

set -e

# Colori per output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Variabili globali
CHECKMK_VERSION="2.4.0p12"
FRP_VERSION="0.64.0"
FRP_URL="https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/frp_${FRP_VERSION}_linux_amd64.tar.gz"

echo -e "${CYAN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║  Installazione Interattiva CheckMK Agent + FRPC          ║${NC}"
echo -e "${CYAN}║  Version: 1.0 - $(date +%Y-%m-%d)                                ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════════════════╝${NC}"

# =====================================================
# Funzione: Rileva sistema operativo
# =====================================================
detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS=$ID
        VER=$VERSION_ID
    elif type lsb_release >/dev/null 2>&1; then
        OS=$(lsb_release -si | tr '[:upper:]' '[:lower:]')
        VER=$(lsb_release -sr)
    else
        OS=$(uname -s)
        VER=$(uname -r)
    fi
    
    case $OS in
        ubuntu|debian)
            PKG_TYPE="deb"
            PKG_MANAGER="apt"
            ;;
        centos|rhel|rocky|almalinux)
            PKG_TYPE="rpm"
            PKG_MANAGER="yum"
            ;;
        *)
            echo -e "${RED}✗ Sistema operativo non supportato: $OS${NC}"
            exit 1
            ;;
    esac
    
    echo -e "${GREEN}✓ Sistema rilevato: $OS $VER ($PKG_TYPE)${NC}"
}

# =====================================================
# Funzione: Installa CheckMK Agent
# =====================================================
install_checkmk_agent() {
    echo -e "\n${BLUE}═══ INSTALLAZIONE CHECKMK AGENT ═══${NC}"
    
    # URL pacchetti
    if [ "$PKG_TYPE" = "deb" ]; then
        AGENT_URL="https://monitoring.nethlab.it/monitoring/check_mk/agents/check-mk-agent_${CHECKMK_VERSION}-1_all.deb"
        AGENT_FILE="check-mk-agent.deb"
    else
        AGENT_URL="https://monitoring.nethlab.it/monitoring/check_mk/agents/check-mk-agent-${CHECKMK_VERSION}-1.noarch.rpm"
        AGENT_FILE="check-mk-agent.rpm"
    fi
    
    echo -e "${YELLOW}📦 Download agent da: $AGENT_URL${NC}"
    
    cd /tmp
    wget -q --show-progress "$AGENT_URL" -O "$AGENT_FILE"
    
    echo -e "${YELLOW}📦 Installazione pacchetto...${NC}"
    if [ "$PKG_TYPE" = "deb" ]; then
        dpkg -i "$AGENT_FILE"
        apt-get install -f -y 2>/dev/null || true
    else
        rpm -Uvh "$AGENT_FILE"
    fi
    
    rm -f "$AGENT_FILE"
    echo -e "${GREEN}✓ Agent CheckMK installato${NC}"
}

# =====================================================
# Funzione: Configura Agent Plain (TCP 6556)
# =====================================================
configure_plain_agent() {
    echo -e "\n${BLUE}═══ CONFIGURAZIONE AGENT PLAIN ═══${NC}"
    
    SOCKET_FILE="/etc/systemd/system/check-mk-agent-plain.socket"
    SERVICE_FILE="/etc/systemd/system/check-mk-agent-plain@.service"
    
    echo -e "${YELLOW}🔧 Disabilito TLS e socket standard...${NC}"
    systemctl stop cmk-agent-ctl-daemon 2>/dev/null || true
    systemctl disable cmk-agent-ctl-daemon 2>/dev/null || true
    systemctl stop check-mk-agent.socket 2>/dev/null || true
    systemctl disable check-mk-agent.socket 2>/dev/null || true
    
    echo -e "${YELLOW}🔧 Creo unit systemd per agent plain...${NC}"
    
    cat > "$SOCKET_FILE" <<'EOF'
[Unit]
Description=Checkmk Agent (TCP 6556 plain)
Documentation=https://docs.checkmk.com/latest/en/agent_linux.html

[Socket]
ListenStream=6556
Accept=yes

[Install]
WantedBy=sockets.target
EOF
    
    cat > "$SERVICE_FILE" <<'EOF'
[Unit]
Description=Checkmk Agent (TCP 6556 plain) connection
Documentation=https://docs.checkmk.com/latest/en/agent_linux.html

[Service]
ExecStart=-/usr/bin/check_mk_agent
StandardInput=socket
EOF
    
    echo -e "${YELLOW}🔧 Ricarico systemd e avvio socket...${NC}"
    systemctl daemon-reload
    systemctl enable --now check-mk-agent-plain.socket
    
    echo -e "${GREEN}✓ Agent plain configurato su porta 6556${NC}"
    
    # Test locale
    echo -e "\n${CYAN}📊 Test agent locale:${NC}"
    /usr/bin/check_mk_agent | head -n 5
}

# =====================================================
# Funzione: Installa FRPC
# =====================================================
install_frpc() {
    echo -e "\n${BLUE}═══ INSTALLAZIONE FRPC CLIENT ═══${NC}"
    
    echo -e "${YELLOW}📦 Download FRPC v${FRP_VERSION}...${NC}"
    cd /usr/local/src || exit 1
    wget -q --show-progress "$FRP_URL" -O frp.tar.gz
    
    echo -e "${YELLOW}📦 Estrazione...${NC}"
    tar xzf frp.tar.gz
    cd "frp_${FRP_VERSION}_linux_amd64" || exit 1
    
    systemctl stop frpc 2>/dev/null || true
    cp frpc /usr/local/bin/frpc
    chmod +x /usr/local/bin/frpc
    
    rm -f /usr/local/src/frp.tar.gz
    
    echo -e "${GREEN}✓ FRPC installato in /usr/local/bin/frpc${NC}"
}

# =====================================================
# Funzione: Configura FRPC
# =====================================================
configure_frpc() {
    echo -e "\n${BLUE}═══ CONFIGURAZIONE FRPC ═══${NC}"
    
    # Hostname corrente come default
    CURRENT_HOSTNAME=$(hostname)
    
    echo -e "${YELLOW}Inserisci le informazioni per la configurazione FRPC:${NC}\n"
    
    # Nome host
    read -p "$(echo -e ${CYAN}Nome host ${NC}[default: $CURRENT_HOSTNAME]: )" FRPC_HOSTNAME
    FRPC_HOSTNAME=${FRPC_HOSTNAME:-$CURRENT_HOSTNAME}
    
    # Server remoto
    read -p "$(echo -e ${CYAN}Server FRP remoto ${NC}[default: monitor.nethlab.it]: )" FRP_SERVER
    FRP_SERVER=${FRP_SERVER:-"monitor.nethlab.it"}
    
    # Porta remota
    read -p "$(echo -e ${CYAN}Porta remota ${NC}[es: 20001]: )" REMOTE_PORT
    while [ -z "$REMOTE_PORT" ]; do
        echo -e "${RED}✗ Porta remota obbligatoria!${NC}"
        read -p "$(echo -e ${CYAN}Porta remota: ${NC})" REMOTE_PORT
    done
    
    # Token di sicurezza
    read -p "$(echo -e ${CYAN}Token di sicurezza ${NC}[default: conduit-reenact-talon-macarena-demotion-vaguely]: )" AUTH_TOKEN
    AUTH_TOKEN=${AUTH_TOKEN:-"conduit-reenact-talon-macarena-demotion-vaguely"}
    
    # Crea directory config
    mkdir -p /etc/frp
    
    # Genera configurazione TOML
    echo -e "\n${YELLOW}📝 Creazione file /etc/frp/frpc.toml...${NC}"
    
    cat > /etc/frp/frpc.toml <<EOF
# Configurazione FRPC Client
# Generato il $(date)

serverAddr = "$FRP_SERVER"
serverPort = 7000

auth.method = "token"
auth.token  = "$AUTH_TOKEN"

transport.tls.enable = true

log.to = "/var/log/frpc.log"
log.level = "info"
log.maxDays = 7

[[$FRPC_HOSTNAME]]
type        = "tcp"
localIP     = "127.0.0.1"
localPort   = 6556
remotePort  = $REMOTE_PORT
EOF
    
    echo -e "${GREEN}✓ File di configurazione creato${NC}"
    
    # Mostra configurazione
    echo -e "\n${CYAN}📋 Configurazione FRPC:${NC}"
    echo -e "   Server:      ${GREEN}$FRP_SERVER:7000${NC}"
    echo -e "   Tunnel:      ${GREEN}$FRPC_HOSTNAME${NC}"
    echo -e "   Porta remota: ${GREEN}$REMOTE_PORT${NC}"
    echo -e "   Porta locale: ${GREEN}6556${NC}"
    
    # Crea servizio systemd
    echo -e "\n${YELLOW}🔧 Creazione servizio systemd...${NC}"
    
    cat > /etc/systemd/system/frpc.service <<EOF
[Unit]
Description=FRP Client Service
After=network.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/frpc -c /etc/frp/frpc.toml
Restart=on-failure
RestartSec=5s
User=root
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
    
    systemctl daemon-reload
    systemctl enable frpc
    systemctl restart frpc
    
    sleep 2
    
    # Verifica stato
    if systemctl is-active --quiet frpc; then
        echo -e "${GREEN}✓ FRPC avviato con successo${NC}"
        echo -e "\n${CYAN}📊 Status:${NC}"
        systemctl status frpc --no-pager -l | head -n 10
    else
        echo -e "${RED}✗ Errore nell'avvio di FRPC${NC}"
        echo -e "${YELLOW}Log:${NC}"
        journalctl -u frpc -n 20 --no-pager
    fi
}

# =====================================================
# Funzione: Riepilogo finale
# =====================================================
show_summary() {
    echo -e "\n${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║              INSTALLAZIONE COMPLETATA                     ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
    
    echo -e "\n${CYAN}📋 RIEPILOGO:${NC}"
    echo -e "   ✓ CheckMK Agent installato (plain TCP 6556)"
    echo -e "   ✓ Socket systemd attivo: check-mk-agent-plain.socket"
    
    if [ "$INSTALL_FRPC" = "yes" ]; then
        echo -e "   ✓ FRPC Client installato e configurato"
        echo -e "   ✓ Tunnel attivo: $FRP_SERVER:$REMOTE_PORT → localhost:6556"
    fi
    
    echo -e "\n${CYAN}🔧 COMANDI UTILI:${NC}"
    echo -e "   Test agent locale:    ${YELLOW}/usr/bin/check_mk_agent${NC}"
    echo -e "   Status socket:        ${YELLOW}systemctl status check-mk-agent-plain.socket${NC}"
    
    if [ "$INSTALL_FRPC" = "yes" ]; then
        echo -e "   Status FRPC:          ${YELLOW}systemctl status frpc${NC}"
        echo -e "   Log FRPC:             ${YELLOW}journalctl -u frpc -f${NC}"
        echo -e "   Config FRPC:          ${YELLOW}/etc/frp/frpc.toml${NC}"
    fi
    
    echo -e "\n${GREEN}🎉 Installazione terminata con successo!${NC}\n"
}

# =====================================================
# MAIN SCRIPT
# =====================================================

# Verifica permessi root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}✗ Questo script deve essere eseguito come root${NC}"
    exit 1
fi

# Rileva sistema operativo
detect_os

# Installa CheckMK Agent
install_checkmk_agent

# Configura agent plain
configure_plain_agent

# Chiedi se installare FRPC
echo -e "\n${YELLOW}════════════════════════════════════════${NC}"
read -p "$(echo -e ${CYAN}Vuoi installare anche FRPC? ${NC}[s/N]: )" INSTALL_FRPC_INPUT
echo -e "${YELLOW}════════════════════════════════════════${NC}"

INSTALL_FRPC="no"
if [[ "$INSTALL_FRPC_INPUT" =~ ^[sS]$ ]]; then
    INSTALL_FRPC="yes"
    install_frpc
    configure_frpc
else
    echo -e "${YELLOW}⏭️  Installazione FRPC saltata${NC}"
fi

# Mostra riepilogo finale
show_summary

exit 0
