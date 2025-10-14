#!/bin/bash
# ==================================================================
# 🧪 CheckMK FRP Environment - Pre-Deployment Checker
# ==================================================================
# Verifica che l'ambiente sia pronto per il test di mail_realip_hybrid
# ==================================================================

set -euo pipefail

# ==================== CONFIGURAZIONE ====================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ==================== FUNZIONI UTILITY ====================
log() {
    echo -e "${BLUE}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $*"
}

success() {
    echo -e "${GREEN}✅ $*${NC}"
}

warning() {
    echo -e "${YELLOW}⚠️  $*${NC}"
}

error() {
    echo -e "${RED}❌ $*${NC}"
}

check_item() {
    local description="$1"
    local command="$2"
    local required="${3:-true}"
    
    echo -n "🔍 $description... "
    
    if eval "$command" >/dev/null 2>&1; then
        success "OK"
        return 0
    else
        if [[ "$required" == "true" ]]; then
            error "FAIL"
            return 1
        else
            warning "MISSING (opzionale)"
            return 0
        fi
    fi
}

# ==================== ENVIRONMENT CHECKS ====================
check_checkmk_environment() {
    log "📋 Controllo Ambiente CheckMK"
    
    check_item "Variabile OMD_SITE" '[[ -n "${OMD_SITE:-}" ]]'
    check_item "Directory CheckMK" '[[ -d "/omd/sites/${OMD_SITE:-default}" ]]'
    check_item "Utente CheckMK" '[[ "$(whoami)" == "${OMD_SITE:-default}" ]] || [[ $EUID -eq 0 ]]'
    check_item "Apache CheckMK attivo" 'systemctl is-active apache2 || pgrep apache'
    check_item "Directory notifiche" '[[ -d "/omd/sites/${OMD_SITE:-default}/local/share/check_mk/notifications" ]]'
}

check_frp_configuration() {
    log "🌐 Controllo Configurazione FRP"
    
    # Check CONFIG_APACHE_TCP_ADDR
    local apache_addr
    if [[ -f "/omd/sites/${OMD_SITE:-default}/etc/omd/site.conf" ]]; then
        apache_addr=$(grep "CONFIG_APACHE_TCP_ADDR" "/omd/sites/${OMD_SITE:-default}/etc/omd/site.conf" | cut -d"'" -f2 2>/dev/null || echo "")
        if [[ "$apache_addr" == "127.0.0.1" ]]; then
            success "CONFIG_APACHE_TCP_ADDR = 127.0.0.1 (FRP compatible)"
        else
            warning "CONFIG_APACHE_TCP_ADDR = $apache_addr (potrebbe non essere FRP)"
        fi
    else
        warning "File site.conf non trovato"
    fi
    
    # Check CONFIG_APACHE_TCP_PORT
    local apache_port
    if [[ -f "/omd/sites/${OMD_SITE:-default}/etc/omd/site.conf" ]]; then
        apache_port=$(grep "CONFIG_APACHE_TCP_PORT" "/omd/sites/${OMD_SITE:-default}/etc/omd/site.conf" | cut -d"'" -f2 2>/dev/null || echo "")
        if [[ -n "$apache_port" ]] && [[ "$apache_port" != "80" ]]; then
            success "CONFIG_APACHE_TCP_PORT = $apache_port (FRP custom port)"
        else
            warning "CONFIG_APACHE_TCP_PORT = $apache_port (porta standard)"
        fi
    fi
    
    check_item "Processo FRP attivo" 'pgrep -f frp || pgrep -f tunnel' false
    check_item "Connessione localhost:PORT" "curl -f -s http://127.0.0.1:${apache_port:-5000}/$(whoami)/check_mk/ >/dev/null" false
}

check_existing_notifications() {
    log "📧 Controllo Notifiche Esistenti"
    
    local notify_dir="/omd/sites/${OMD_SITE:-default}/local/share/check_mk/notifications"
    
    if [[ -f "$notify_dir/mail" ]]; then
        success "Script mail standard presente"
    else
        warning "Script mail standard non trovato"
    fi
    
    if [[ -f "$notify_dir/mail_realip_00" ]]; then
        success "Script mail_realip_00 presente"
    else
        warning "Script mail_realip_00 non trovato"
    fi
    
    if [[ -f "$notify_dir/mail_realip_hybrid" ]]; then
        warning "Script mail_realip_hybrid già presente (verrà sovrascritto)"
    else
        success "mail_realip_hybrid non presente (deploy pulito)"
    fi
}

check_test_prerequisites() {
    log "🧪 Controllo Prerequisiti Test"
    
    check_item "Host con label real_ip" 'grep -r "real_ip" "/omd/sites/${OMD_SITE:-default}/etc/check_mk/conf.d/" 2>/dev/null' false
    check_item "Regole notifica configurate" '[[ -f "/omd/sites/${OMD_SITE:-default}/etc/check_mk/conf.d/wato/notifications.mk" ]]' false
    check_item "SMTP configurato" 'grep -i smtp "/omd/sites/${OMD_SITE:-default}/etc/check_mk/conf.d/" 2>/dev/null' false
    
    # Test comando mail
    if command -v mail >/dev/null 2>&1 || command -v sendmail >/dev/null 2>&1; then
        success "Sistema mail disponibile"
    else
        warning "Sistema mail non configurato (test via SMTP richiesto)"
    fi
}

generate_test_commands() {
    log "🚀 Comandi Test Suggeriti"
    
    local site="${OMD_SITE:-default}"
    
    cat << EOF

📋 COMANDI PER IL TEST:
=====================

1️⃣  Deploy con backup:
   sudo ./backup_and_deploy.sh

2️⃣  Test dry-run:
   ./backup_and_deploy.sh --dry-run

3️⃣  Test detection manuale:
   su - $site -c "python3 -c \"
import os
os.environ['NOTIFY_HOSTADDRESS'] = '127.0.0.1:5000'
os.environ['NOTIFY_HOSTLABEL_real_ip'] = '192.168.1.100'
exec(open('/omd/sites/$site/local/share/check_mk/notifications/mail_realip_hybrid').read())
\""

4️⃣  Test notifica completa:
   su - $site -c "echo 'Test notification' | /omd/sites/$site/local/share/check_mk/notifications/mail_realip_hybrid"

5️⃣  Monitor logs:
   tail -f /omd/sites/$site/var/log/notify.log

📧 CONFIGURAZIONE LABEL REAL_IP:
===============================
# In WATO → Host Properties → Custom attributes
# Aggiungi label: real_ip = 192.168.1.100

🔄 ROLLBACK SE NECESSARIO:
=========================
# Esegui script generato automaticamente:
/omd/sites/$site/local/share/check_mk/notifications/backup_*/rollback.sh

EOF
}

# ==================== MAIN FUNCTION ====================
main() {
    echo -e "${BLUE}"
    cat << "EOF"
    ╔══════════════════════════════════════════════════════════════╗
    ║             🧪 CheckMK FRP Pre-Test Checker                 ║
    ║          Validazione ambiente per mail_realip_hybrid        ║
    ╚══════════════════════════════════════════════════════════════╝
EOF
    echo -e "${NC}"
    
    local errors=0
    
    check_checkmk_environment || ((errors++))
    echo
    check_frp_configuration || ((errors++))
    echo
    check_existing_notifications || ((errors++))
    echo
    check_test_prerequisites || ((errors++))
    echo
    
    if [[ $errors -eq 0 ]]; then
        success "🎯 Ambiente pronto per il test!"
        generate_test_commands
    else
        error "⚠️  Trovati $errors problemi. Sistemali prima del test."
        echo
        echo -e "${YELLOW}💡 SUGGERIMENTI:${NC}"
        echo "- Assicurati di essere nell'ambiente OMD corretto"
        echo "- Verifica configurazione FRP attiva"
        echo "- Configura almeno un host con label real_ip"
        exit 1
    fi
}

# Esecuzione
main "$@"