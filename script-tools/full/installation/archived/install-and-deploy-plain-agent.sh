#!/bin/bash
# Installa e deploya CheckMK Agent in modalita Plain TCP su host multipli via SSH
# Uso: ./install-and-deploy-plain-agent.sh

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

CMK_SITE="monitoring"
CMK_SERVER="monitoring.nethlab.it"
CMK_SITE_URL="https://$CMK_SERVER/$CMK_SITE/check_mk/agents"

echo -e "${CYAN}+========================================================+${NC}"
echo -e "${CYAN}|  Installazione CheckMK Agent Plain TCP (Multi-Host)  |${NC}"
echo -e "${CYAN}+========================================================+${NC}\n"

# Richiedi lista host
echo -e "${YELLOW}Inserisci uno o piu host separati da spazi:${NC}"
read -r -a HOSTS

if [ ${#HOSTS[@]} -eq 0 ]; then
    echo -e "${RED}ERR Nessun host specificato${NC}"
    exit 1
fi
echo -e "\n${GREEN}OK Host da configurare: ${HOSTS[*]}${NC}\n"

# Rileva ultima versione disponibile
echo -e "${YELLOW} Rilevamento ultima versione CheckMK Agent...${NC}"

DEB_URL=$(curl -sL "$CMK_SITE_URL/" | grep -oP 'check-mk-agent_[0-9.p]+-[0-9]+_all\.deb' | sort -V | tail -1)
RPM_URL=$(curl -sL "$CMK_SITE_URL/" | grep -oP 'check-mk-agent-[0-9.p]+-[0-9]+\.noarch\.rpm' | sort -V | tail -1)

if [[ -z "$DEB_URL" ]] || [[ -z "$RPM_URL" ]]; then
    echo -e "${RED}ERR Errore nel rilevamento versione agent${NC}"
    exit 1
fi

DEB_FULL="$CMK_SITE_URL/$DEB_URL"
RPM_FULL="$CMK_SITE_URL/$RPM_URL"

echo -e "${GREEN}OK Ultima versione trovata:${NC}"
echo -e "  - DEB: $DEB_FULL"
echo -e "  - RPM: $RPM_FULL\n"

# Funzione: Installa agent su host remoto
install_agent_on_host() {
    local HOST=$1
    
    echo -e "${CYAN}+========================================================+${NC}"
    echo -e "${CYAN}|  Installo + configuro $HOST${NC}"
    echo -e "${CYAN}+========================================================+${NC}\n"
    
    # Rileva OS
    OS_TYPE=$(ssh -o ConnectTimeout=10 root@"$HOST" "grep -oP '^ID=\K.*' /etc/os-release | tr -d '\"'" 2>/dev/null || echo "unknown")
    
    if [[ "$OS_TYPE" =~ (debian|ubuntu) ]]; then
    echo -e "${GREEN}OK Host Debian/Ubuntu rilevato, installo DEB...${NC}"
        ssh root@"$HOST" "wget -qO /tmp/check-mk-agent.deb '$DEB_FULL' && dpkg -i /tmp/check-mk-agent.deb; rm -f /tmp/check-mk-agent.deb"
elif [[ "$OS_TYPE" =~ (rhel|centos|rocky|almalinux|fedora) ]]; then
    echo -e "${GREEN}OK Host RHEL/CentOS/Rocky rilevato, installo RPM...${NC}"
        ssh root@"$HOST" "wget -qO /tmp/check-mk-agent.rpm '$RPM_FULL' && rpm -Uvh /tmp/check-mk-agent.rpm; rm -f /tmp/check-mk-agent.rpm"
else         echo -e "${RED}ERR OS non supportato: $OS_TYPE${NC}"
        return 1
    fi
    
    # Configura modalita plain
    echo -e "${GREEN}OK Disabilito TLS e socket systemd standard...${NC}"
    ssh root@"$HOST" "systemctl stop check-mk-agent.socket check-mk-agent@.service 2>/dev/null || true; systemctl disable check-mk-agent.socket 2>/dev/null || true"
    
    echo -e "${GREEN}OK Creo unit systemd per agent plain...${NC}"
    ssh root@"$HOST" 'cat > /etc/systemd/system/check-mk-agent-plain.socket <<EOF
[Unit]
Description=Checkmk Agent (TCP 6556 plain)
Documentation=https://docs.checkmk.com/latest/en/agent_linux.html

[Socket]
ListenStream=6556
Accept=yes

[Install]
WantedBy=sockets.target
EOF'

    ssh root@"$HOST" 'cat > /etc/systemd/system/check-mk-agent-plain@.service <<EOF
[Unit]
Description=Checkmk Agent (TCP 6556 plain) connection
Documentation=https://docs.checkmk.com/latest/en/agent_linux.html

[Service]
ExecStart=-/usr/bin/check_mk_agent
StandardInput=socket
EOF'

    echo -e "${GREEN}OK Ricarico systemd...${NC}"
    ssh root@"$HOST" "systemctl daemon-reload"
    
    echo -e "${GREEN}OK Abilito e avvio il nuovo socket...${NC}"
    ssh root@"$HOST" "systemctl enable --now check-mk-agent-plain.socket"
    
    # Verifica funzionamento
    echo -e "${CYAN}OK Plain agent attivo. Test locale:${NC}"
    ssh root@"$HOST" "echo 'test' | nc localhost 6556 | head -5"
    
    echo -e "${GREEN}OKOKOK Installazione completata su $HOST OKOKOK${NC}\n"
}

# Processa tutti gli host
for HOST in "${HOSTS[@]}"; do
    if ! install_agent_on_host "$HOST"; then
    echo -e "${RED}ERR Errore durante installazione su $HOST${NC}\n"
        continue
    fi
done
echo -e "${GREEN}+========================================================+${NC}"
echo -e "${GREEN}|         INSTALLAZIONE COMPLETATA SU TUTTI GLI HOST    |${NC}"
echo -e "${GREEN}+========================================================+${NC}\n"

echo -e "${YELLOW}Prossimi passi:${NC}"
echo -e "  1. Aggiungi gli host al server CheckMK"
echo -e "  2. Verifica connettivita: ${CYAN}cmk -d <hostname>${NC}"
echo -e "  3. Esegui service discovery: ${CYAN}cmk -I <hostname>${NC}\n"
