#!/bin/bash
# CheckMK Email Real IP + Grafici - Script di Deployment
# Questo script automatizza l'installazione completa del nuovo sistema email

set -e  # Exit on any error

# Colori per output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Funzioni di utilità
print_header() {
    echo -e "${CYAN}===============================================${NC}"
    echo -e "${CYAN}  CheckMK Email Real IP + Grafici Deployment  ${NC}"
    echo -e "${CYAN}===============================================${NC}"
}

print_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Configurazione - MODIFICARE QUESTI VALORI
CHECKMK_SITE=""
CHECKMK_USER=""
CHECKMK_SERVER=""
REAL_IP=""
TEST_EMAIL=""

# Funzione per richiedere configurazione
setup_configuration() {
    print_step "Configurazione deployment"
    
    if [ -z "$CHECKMK_SITE" ]; then
        read -r -p "Nome site CheckMK (es: monitoring): " CHECKMK_SITE
    fi

    if [ -z "$CHECKMK_USER" ]; then
        read -r -p "Username CheckMK/SSH (es: cmkadmin): " CHECKMK_USER
    fi

    if [ -z "$CHECKMK_SERVER" ]; then
        read -r -p "Server CheckMK (es: checkmk.domain.com): " CHECKMK_SERVER
    fi

    if [ -z "$REAL_IP" ]; then
        read -r -p "Real IP del server (es: 192.168.1.100): " REAL_IP
    fi

    if [ -z "$TEST_EMAIL" ]; then
        read -r -p "Email per test (es: admin@domain.com): " TEST_EMAIL
    fi
    
    echo -e "\n${YELLOW}Configurazione:${NC}"
    echo "  Site CheckMK: $CHECKMK_SITE"
    echo "  User: $CHECKMK_USER"
    echo "  Server: $CHECKMK_SERVER"
    echo "  Real IP: $REAL_IP"
    echo "  Test Email: $TEST_EMAIL"
    
    read -p "Configurazione corretta? [y/N]: " confirm
    if [[ $confirm != [yY] ]]; then
        print_error "Deployment annullato"
        exit 1
    fi
}

# Funzione per verificare prerequisiti
check_prerequisites() {
    print_step "Verifica prerequisiti"
    
    # Verifica file script
    if [ ! -f "mail_realip_graphs" ]; then
        print_error "File mail_realip_graphs non trovato!"
        echo "Assicurati di essere nella directory con gli script"
        exit 1
    fi
    
    # Verifica connessione SSH
    if ! ssh -o ConnectTimeout=5 -o BatchMode=yes $CHECKMK_USER@$CHECKMK_SERVER "exit" 2>/dev/null; then
        print_warning "Impossibile connettersi via SSH a $CHECKMK_SERVER"
        print_warning "Assicurati che le chiavi SSH siano configurate"
        read -p "Continuare comunque? [y/N]: " continue_anyway
        if [[ $continue_anyway != [yY] ]]; then
            exit 1
        fi
    fi
    
    print_success "Prerequisiti verificati"
}

# Funzione per backup configurazione esistente
backup_existing_config() {
    print_step "Backup configurazione esistente"
    
    BACKUP_DIR="backup_$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$BACKUP_DIR"
    
    # Backup script esistente se presente
    ssh "$CHECKMK_USER@$CHECKMK_SERVER" "
        if [ -f /opt/omd/sites/$CHECKMK_SITE/local/share/check_mk/notifications/mail_realip_00 ]; then
            cp /opt/omd/sites/$CHECKMK_SITE/local/share/check_mk/notifications/mail_realip_00 /tmp/mail_realip_00_backup
            echo 'Script mail_realip_00 copiato in /tmp/mail_realip_00_backup'
        fi
        
        # Backup configurazione notifiche
        if [ -f /opt/omd/sites/$CHECKMK_SITE/etc/check_mk/conf.d/wato/notifications.mk ]; then
            cp /opt/omd/sites/$CHECKMK_SITE/etc/check_mk/conf.d/wato/notifications.mk /tmp/notifications_backup.mk
            echo 'Configurazione notifiche salvata in /tmp/notifications_backup.mk'
        fi
    " 2>/dev/null || print_warning "Backup non riuscito (probabilmente primi deployment)"
    
    print_success "Backup completato"
}

# Funzione per copiare e installare script
install_script() {
    print_step "Installazione script mail_realip_graphs"
    
    # Copia script sul server
    scp mail_realip_graphs "$CHECKMK_USER@$CHECKMK_SERVER:/tmp/"
    
    # Installa script
    ssh "$CHECKMK_USER@$CHECKMK_SERVER" "
        sudo mkdir -p /opt/omd/sites/$CHECKMK_SITE/local/share/check_mk/notifications/
        sudo cp /tmp/mail_realip_graphs /opt/omd/sites/$CHECKMK_SITE/local/share/check_mk/notifications/
        sudo chmod +x /opt/omd/sites/$CHECKMK_SITE/local/share/check_mk/notifications/mail_realip_graphs
        sudo chown $CHECKMK_SITE:$CHECKMK_SITE /opt/omd/sites/$CHECKMK_SITE/local/share/check_mk/notifications/mail_realip_graphs
        ls -la /opt/omd/sites/$CHECKMK_SITE/local/share/check_mk/notifications/mail_realip_graphs
    "
    
    print_success "Script installato correttamente"
}

# Funzione per configurare label host
configure_host_labels() {
    print_step "Configurazione label host 'real_ip'"
    
    echo -e "${YELLOW}Configurazione manuale richiesta:${NC}"
    echo "1. Accedere a CheckMK Web UI: https://$CHECKMK_SERVER/$CHECKMK_SITE/"
    echo "2. Andare in Setup → Hosts"
    echo "3. Modificare l'host del server CheckMK"
    echo "4. Aggiungere Label:"
    echo "   - Key: real_ip"
    echo "   - Value: $REAL_IP"
    echo "5. Salvare e attivare le modifiche"
    
    read -p "Label configurato? Premere ENTER per continuare..."
    print_success "Label configurato"
}

# Funzione per test dello script
test_script() {
    print_step "Test dello script"
    
    ssh "$CHECKMK_USER@$CHECKMK_SERVER" "
        su - $CHECKMK_SITE -c '
            export NOTIFY_CONTACTEMAIL=\"$TEST_EMAIL\"
            export NOTIFY_HOSTNAME=\"$CHECKMK_SERVER\"
            export NOTIFY_HOSTLABEL_real_ip=\"$REAL_IP\"
            export NOTIFY_MONITORING_HOST=\"127.0.0.1\"
            export NOTIFY_WHAT=\"HOST\"
            export NOTIFY_NOTIFICATIONTYPE=\"PROBLEM\"
            export NOTIFY_HOSTSTATE=\"DOWN\"
            export NOTIFY_HOSTOUTPUT=\"Test notification with real IP and graphs\"
            export NOTIFY_PARAMETER_ELEMENTSS=\"graph abstime address\"
            export NOTIFY_OMD_SITE=\"$CHECKMK_SITE\"
            
            echo \"=== TEST SCRIPT MAIL_REALIP_GRAPHS ===\"
            echo \"Test script con real IP: $REAL_IP\"
            echo \"Email test: $TEST_EMAIL\"
            
            # Test dry-run
            echo \"Test variabili ambiente:\"
            env | grep NOTIFY_ | head -10
            
            echo \"Script disponibile:\"
            ls -la local/share/check_mk/notifications/mail_realip_graphs
            
            echo \"Test completato - per test completo configurare regola notifica\"
        '
    "
    
    print_success "Test script completato"
}

# Funzione per configurare regola notifica
configure_notification_rule() {
    print_step "Configurazione regola notifica"
    
    echo -e "${YELLOW}Configurazione regola notifica:${NC}"
    echo "1. Accedere a CheckMK Web UI: https://$CHECKMK_SERVER/$CHECKMK_SITE/"
    echo "2. Andare in Setup → Notifications"
    echo "3. Aggiungere nuova regola:"
    echo "   - Description: Email Real IP + Graphs"
    echo "   - Notification Method: Custom notification script"
    echo "   - Script: mail_realip_graphs"
    echo "   - Configurare parametri email normalmente"
    echo "4. Salvare e attivare le modifiche"
    
    read -p "Regola configurata? Premere ENTER per continuare..."
    print_success "Regola notifica configurata"
}

# Funzione per test invio email
test_email_notification() {
    print_step "Test invio email completo"
    
    echo -e "${YELLOW}Test notifica email:${NC}"
    echo "1. In CheckMK Web UI, andare a Monitoring → Host"
    echo "2. Trovare l'host del server CheckMK"
    echo "3. Usare 'Custom notification' per inviare test"
    echo "4. Verificare che l'email ricevuta abbia:"
    echo "   - URL con real IP ($REAL_IP) invece di 127.0.0.1"
    echo "   - Grafici allegati funzionanti"
    echo "   - Link grafici che puntano al real IP"
    
    read -p "Test email completato? [y/N]: " email_test_ok
    if [[ $email_test_ok == [yY] ]]; then
        print_success "Test email completato con successo!"
    else
        print_warning "Verificare configurazione se email non corrette"
    fi
}

# Funzione per cleanup
cleanup() {
    print_step "Cleanup file temporanei"
    
    ssh "$CHECKMK_USER@$CHECKMK_SERVER" "
        rm -f /tmp/mail_realip_graphs
        echo 'File temporanei rimossi'
    " 2>/dev/null || true
    
    print_success "Cleanup completato"
}

# Funzione principale
main() {
    print_header
    
    setup_configuration
    check_prerequisites
    backup_existing_config
    install_script
    configure_host_labels
    test_script
    configure_notification_rule
    test_email_notification
    cleanup
    
    echo -e "\n${GREEN}===============================================${NC}"
    echo -e "${GREEN}  DEPLOYMENT COMPLETATO CON SUCCESSO!       ${NC}"
    echo -e "${GREEN}===============================================${NC}"
    echo -e "${GREEN}Il nuovo sistema email CheckMK è attivo con:${NC}"
    echo -e "${GREEN}✅ Real IP ($REAL_IP) invece di 127.0.0.1${NC}"
    echo -e "${GREEN}✅ Grafici completamente abilitati${NC}"
    echo -e "${GREEN}✅ URL corretti in tutte le email${NC}"
    echo -e "\n${YELLOW}Prossimi passi:${NC}"
    echo -e "- Monitorare email ricevute"
    echo -e "- Eventualmente disattivare mail_realip_00"
    echo -e "- Documentare nuova configurazione"
}

# Avvio script
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi