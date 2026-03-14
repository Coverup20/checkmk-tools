#!/bin/bash

###############################################################################
# Script: setup-auto-upgrade-checkmk.sh
# Descrizione: Configura upgrade automatici di CheckMK tramite crontab
# Autore: Generato per checkmk-tools
# Data: 2026-01-12
###############################################################################

set -euo pipefail

# Colori per output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Funzione per stampare messaggi colorati
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
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

# Verifica permessi root
if [ "$EUID" -ne 0 ]; then
    print_error "Questo script deve essere eseguito come root o con sudo"
    exit 1
fi

# Verifica che omd sia installato
if ! command -v omd &> /dev/null; then
    print_error "CheckMK (omd) non è installato su questo sistema"
    exit 1
fi

# URL dello script full che esegue l'upgrade
UPGRADE_SCRIPT_URL="https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/full/upgrade_maintenance/upgrade-checkmk.sh"

print_info "Verrà utilizzato lo script remoto da GitHub"
print_info "URL: $UPGRADE_SCRIPT_URL"
print_success "Lo script scaricherà automaticamente l'ultima versione ad ogni esecuzione"

# Banner
echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║    Configurazione Upgrade Automatici CheckMK                  ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""

print_warning "ATTENZIONE: Stai per configurare upgrade AUTOMATICI di CheckMK!"
echo ""
echo "Considerazioni importanti:"
echo "  - Lo script farà backup automatico prima di ogni upgrade"
echo "  - L'upgrade sarà completamente non interattivo"
echo "  - Il sito CheckMK sarà riavviato durante l'upgrade"
echo "  - Gli upgrade avverranno SOLO se disponibile una nuova versione"
echo ""

read -p "Sei sicuro di voler procedere? [s/N]: " proceed
if [[ ! $proceed =~ ^[Ss]$ ]]; then
    print_warning "Operazione annullata"
    exit 0
fi

LOG_FILE="/var/log/auto-upgrade-checkmk.log"

echo ""

# Menu interattivo per la frequenza
echo -e "${YELLOW}Seleziona la frequenza degli upgrade automatici:${NC}"
echo ""
echo "  1) Settimanale  - Ogni domenica alle 02:00 (CONSIGLIATO)"
echo "  2) Mensile      - Il primo giorno del mese alle 02:00"
echo "  3) Personalizzato - Specifica orario e frequenza custom"
echo "  4) Annulla"
echo ""

read -p "Scelta [1-4]: " choice

case $choice in
    1)
        CRON_SCHEDULE="0 2 * * 0"
        DESCRIPTION="Settimanale (domenica) alle 02:00"
        ;;
    2)
        CRON_SCHEDULE="0 2 1 * *"
        DESCRIPTION="Mensile (1° del mese) alle 02:00"
        ;;
    3)
        echo ""
        print_info "Inserisci la pianificazione cron personalizzata"
        echo "Formato: minuto ora giorno mese giornosettimana"
        echo "Esempio: 0 2 * * 0 (ogni domenica alle 2:00)"
        echo "Esempio: 0 3 1 * * (1° del mese alle 3:00)"
        echo ""
        read -p "Inserisci la pianificazione cron: " CRON_SCHEDULE
        DESCRIPTION="Personalizzato: $CRON_SCHEDULE"
        
        # Validazione base della sintassi cron
        if ! [[ $CRON_SCHEDULE =~ ^[0-9\*\,\-\/]+[[:space:]]+[0-9\*\,\-\/]+[[:space:]]+[0-9\*\,\-\/]+[[:space:]]+[0-9\*\,\-\/]+[[:space:]]+[0-9\*\,\-\/]+$ ]]; then
            print_error "Formato cron non valido"
            exit 1
        fi
        ;;
    4)
        print_warning "Operazione annullata"
        exit 0
        ;;
    *)
        print_error "Scelta non valida"
        exit 1
        ;;
esac

echo ""
print_info "Configurazione selezionata: ${DESCRIPTION}"

# Chiedi conferma sull'orario
read -p "Vuoi modificare l'orario? [s/N]: " modify_time
if [[ $modify_time =~ ^[Ss]$ ]]; then
    echo ""
    read -p "Inserisci l'ora (0-23): " hour
    read -p "Inserisci i minuti (0-59): " minute
    
    # Validazione
    if ! [[ $hour =~ ^[0-9]+$ ]] || [ "$hour" -lt 0 ] || [ "$hour" -gt 23 ]; then
        print_error "Ora non valida"
        exit 1
    fi
    
    if ! [[ $minute =~ ^[0-9]+$ ]] || [ "$minute" -lt 0 ] || [ "$minute" -gt 59 ]; then
        print_error "Minuti non validi"
        exit 1
    fi
    
    # Sostituisci minuto e ora nella pianificazione
    CRON_SCHEDULE="$minute $hour $(echo $CRON_SCHEDULE | cut -d' ' -f3-)"
    print_info "Nuova pianificazione: $CRON_SCHEDULE"
fi

# Opzione per notifiche email
echo ""
read -p "Vuoi ricevere notifiche email sui risultati degli upgrade? [s/N]: " enable_email
EMAIL_NOTIFY=""
if [[ $enable_email =~ ^[Ss]$ ]]; then
    read -p "Inserisci l'indirizzo email: " email_address
    
    # Validazione base email
    if [[ $email_address =~ ^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]]; then
        EMAIL_NOTIFY=" && (cat /tmp/checkmk-upgrade-report.txt | mail -s \"✅ CheckMK Auto-Upgrade Report - \$(hostname)\" $email_address) || (echo -e \"❌ ERRORE UPGRADE CheckMK\\n\\nServer: \$(hostname)\\nData: \$(date)\\n\\nVerifica i log manualmente.\" | mail -s \"[ERROR] CheckMK Auto-Upgrade Failed - \$(hostname)\" $email_address)"
        print_success "Notifiche email configurate per: $email_address"
        
        # Verifica se mail è installato
        if ! command -v mail &> /dev/null; then
            print_warning "Il comando 'mail' non è installato. Installalo con: apt install mailutils"
            read -p "Vuoi procedere comunque? [s/N]: " proceed_anyway
            if [[ ! $proceed_anyway =~ ^[Ss]$ ]]; then
                exit 0
            fi
        fi
    else
        print_error "Indirizzo email non valido"
        exit 1
    fi
fi

# Crea il comando completo con logging e auto-yes usando lo script remoto full
# Usa metodo compatibile con tutti i sistemi (senza process substitution)
# Lo script viene eseguito con auto-conferma tramite echo y per la conferma iniziale
UPGRADE_COMMAND="curl -fsSL $UPGRADE_SCRIPT_URL -o /tmp/upgrade-checkmk.sh && chmod +x /tmp/upgrade-checkmk.sh && echo 'y' | bash /tmp/upgrade-checkmk.sh"
CRON_ENTRY="$CRON_SCHEDULE (echo \"[\$(date)] Starting CheckMK auto-upgrade\" && $UPGRADE_COMMAND && echo \"[\$(date)] CheckMK upgrade completed successfully\"$EMAIL_NOTIFY) >> $LOG_FILE 2>&1"

print_info "Lo script scaricherà automaticamente l'ultima versione ad ogni esecuzione"

echo ""
print_info "Entry crontab che verrà aggiunta:"
echo -e "${GREEN}${CRON_ENTRY}${NC}"
echo ""

# Conferma finale
read -p "Confermi l'aggiunta al crontab? [s/N]: " confirm
if [[ ! $confirm =~ ^[Ss]$ ]]; then
    print_warning "Operazione annullata"
    exit 0
fi

# Backup del crontab corrente
print_info "Creazione backup del crontab corrente..."
BACKUP_DIR="/root/crontab_backups"
mkdir -p "$BACKUP_DIR"
BACKUP_FILE="$BACKUP_DIR/crontab_backup_$(date +%Y%m%d_%H%M%S).txt"
crontab -l > "$BACKUP_FILE" 2>/dev/null || echo "# Nuovo crontab" > "$BACKUP_FILE"
print_success "Backup salvato in: $BACKUP_FILE"

# Verifica se l'entry esiste già
if crontab -l 2>/dev/null | grep -q "upgrade-checkmk\|rupgrade-checkmk"; then
    print_warning "Trovata entry simile già presente nel crontab"
    read -p "Vuoi rimuovere le entry esistenti e aggiungerne una nuova? [s/N]: " remove_old
    
    if [[ $remove_old =~ ^[Ss]$ ]]; then
        # Rimuovi le vecchie entry (sia locali che remote)
        crontab -l 2>/dev/null | grep -v "upgrade-checkmk\|rupgrade-checkmk" | crontab -
        print_success "Vecchie entry rimosse"
    else
        print_warning "Le vecchie entry sono state mantenute. L'upgrade potrebbe essere eseguito più volte."
    fi
fi

# Aggiungi la nuova entry al crontab
print_info "Aggiunta nuova entry al crontab..."
(crontab -l 2>/dev/null; echo "# Auto-upgrade CheckMK: $DESCRIPTION"; echo "$CRON_ENTRY") | crontab -
print_success "Entry aggiunta con successo!"

# Crea il file di log se non esiste
touch "$LOG_FILE"
chmod 644 "$LOG_FILE"
print_info "File di log creato: $LOG_FILE"

# Mostra il crontab corrente
echo ""
print_info "Crontab corrente:"
echo -e "${BLUE}----------------------------------------${NC}"
crontab -l
echo -e "${BLUE}----------------------------------------${NC}"

# Riepilogo finale
echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║              Configurazione Completata con Successo            ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
print_success "Frequenza: $DESCRIPTION"
print_success "Log file: $LOG_FILE"
print_success "Backup crontab: $BACKUP_FILE"
print_success "Script remoto: $UPGRADE_SCRIPT_URL"
if [[ -n "$EMAIL_NOTIFY" ]]; then
    print_success "Notifiche email: $email_address"
fi
echo ""
print_info "IMPORTANTE - Note sulla sicurezza:"
echo "  1. Gli upgrade avverranno AUTOMATICAMENTE alla schedulazione impostata"
echo "  2. Viene creato un backup prima di ogni upgrade"
echo "  3. I backup sono salvati in: /opt/omd/backups/ (mantiene ultimi 3)"
echo "  4. Le versioni CheckMK obsolete vengono rimosse automaticamente"
echo "  5. Monitora regolarmente i log per verificare gli upgrade"
echo "  6. Lo script scarica SEMPRE l'ultima versione da GitHub ad ogni esecuzione"
echo ""
print_info "Per monitorare gli upgrade eseguiti:"
echo -e "  ${YELLOW}tail -f $LOG_FILE${NC}"
echo ""
print_info "Per rimuovere gli upgrade automatici:"
echo -e "  ${YELLOW}crontab -e${NC}  # e rimuovi la riga corrispondente"
echo ""
print_info "Per testare subito l'upgrade manualmente (senza aspettare la schedulazione):"
echo -e "  ${YELLOW}curl -fsSL $UPGRADE_SCRIPT_URL -o /tmp/upgrade-checkmk.sh && chmod +x /tmp/upgrade-checkmk.sh && bash /tmp/upgrade-checkmk.sh${NC}"
echo ""
print_warning "RACCOMANDAZIONE: Esegui prima un test manuale per verificare il funzionamento!"
echo ""

exit 0
