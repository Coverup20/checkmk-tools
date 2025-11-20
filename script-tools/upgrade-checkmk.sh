#!/bin/bash
# ==========================================================
#  CheckMK RAW - Upgrade Script con Controllo Versione
#  Verifica versione corrente, scarica ultima disponibile,
#  richiede conferma e procede con upgrade automatico
#  Autore: ChatGPT per Marzio Bordin
# ==========================================================

set -e

SITE_NAME="monitoring"
CHECKMK_EDITION="cre"  # cre = CheckMK Raw Edition
DOWNLOAD_DIR="/tmp/checkmk-upgrade"
BACKUP_DIR="/opt/omd/backups"

# Colori per output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# ==========================================================
# Funzioni di utilità
# ==========================================================

print_header() {
    echo -e "\n${CYAN}========================================${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}========================================${NC}\n"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

# ==========================================================
# Controllo prerequisiti
# ==========================================================

check_prerequisites() {
    print_header "Controllo Prerequisiti"
    
    # Verifica root
    if [[ $EUID -ne 0 ]]; then
        print_error "Questo script deve essere eseguito come root"
        exit 1
    fi
    print_success "Esecuzione come root: OK"
    
    # Verifica esistenza sito
    if ! omd sites | grep -q "^$SITE_NAME"; then
        print_error "Sito CheckMK '$SITE_NAME' non trovato"
        echo "Siti disponibili:"
        omd sites
        exit 1
    fi
    print_success "Sito '$SITE_NAME' trovato"
    
    # Verifica connessione internet
    if ! ping -c 1 checkmk.com &> /dev/null; then
        print_error "Nessuna connessione internet disponibile"
        exit 1
    fi
    print_success "Connessione internet: OK"
    
    # Crea directory temporanea
    mkdir -p "$DOWNLOAD_DIR"
    print_success "Directory temporanea: $DOWNLOAD_DIR"
}

# ==========================================================
# Ottieni versione corrente
# ==========================================================

get_current_version() {
    print_header "Versione Corrente Installata"
    
    # Ottieni versione dal sito
    CURRENT_VERSION=$(omd version "$SITE_NAME" | grep -oP '\d+\.\d+\.\d+p\d+')
    
    if [[ -z "$CURRENT_VERSION" ]]; then
        print_error "Impossibile rilevare la versione corrente"
        exit 1
    fi
    
    print_info "Versione installata: ${GREEN}$CURRENT_VERSION${NC}"
    echo "$CURRENT_VERSION"
}

# ==========================================================
# Ottieni ultima versione disponibile
# ==========================================================

get_latest_version() {
    print_header "Verifica Ultima Versione Disponibile"
    
    print_info "Recupero informazioni da checkmk.com..."
    
    # Scarica la pagina di download
    local download_page=$(curl -s "https://checkmk.com/download")
    
    # Estrai l'ultima versione RAW disponibile
    LATEST_VERSION=$(echo "$download_page" | grep -oP 'check-mk-raw-\K\d+\.\d+\.\d+p\d+' | head -1)
    
    if [[ -z "$LATEST_VERSION" ]]; then
        print_error "Impossibile recuperare l'ultima versione disponibile"
        exit 1
    fi
    
    print_info "Ultima versione disponibile: ${GREEN}$LATEST_VERSION${NC}"
    echo "$LATEST_VERSION"
}

# ==========================================================
# Confronta versioni
# ==========================================================

compare_versions() {
    local current="$1"
    local latest="$2"
    
    print_header "Confronto Versioni"
    
    echo -e "${BLUE}Versione corrente:${NC}    $current"
    echo -e "${BLUE}Versione disponibile:${NC} $latest"
    echo ""
    
    if [[ "$current" == "$latest" ]]; then
        print_success "Stai già utilizzando l'ultima versione disponibile!"
        echo -e "\n${GREEN}Nessun aggiornamento necessario.${NC}\n"
        exit 0
    else
        print_warning "È disponibile una nuova versione"
        return 1
    fi
}

# ==========================================================
# Conferma upgrade
# ==========================================================

confirm_upgrade() {
    local current="$1"
    local latest="$2"
    
    print_header "Conferma Upgrade"
    
    echo -e "${YELLOW}Stai per aggiornare CheckMK:${NC}"
    echo -e "  Da: ${RED}$current${NC}"
    echo -e "  A:  ${GREEN}$latest${NC}"
    echo ""
    echo -e "${YELLOW}Operazioni che verranno eseguite:${NC}"
    echo "  1. Backup automatico del sito corrente"
    echo "  2. Download della nuova versione"
    echo "  3. Stop del sito '$SITE_NAME'"
    echo "  4. Upgrade alla versione $latest"
    echo "  5. Avvio del sito aggiornato"
    echo ""
    
    read -p "Vuoi procedere con l'upgrade? (s/N): " confirm
    
    if [[ ! "$confirm" =~ ^[sS]$ ]]; then
        print_warning "Upgrade annullato dall'utente"
        exit 0
    fi
    
    print_success "Upgrade confermato, procedo..."
}

# ==========================================================
# Backup del sito
# ==========================================================

backup_site() {
    print_header "Backup Sito CheckMK"
    
    local backup_file="$BACKUP_DIR/${SITE_NAME}_pre-upgrade_$(date +%Y%m%d_%H%M%S).tar.gz"
    
    print_info "Creazione backup in: $backup_file"
    
    if omd backup "$SITE_NAME" "$backup_file"; then
        print_success "Backup completato con successo"
        print_info "File backup: $backup_file"
    else
        print_error "Errore durante il backup"
        exit 1
    fi
}

# ==========================================================
# Download nuova versione
# ==========================================================

download_version() {
    local version="$1"
    
    print_header "Download CheckMK $version"
    
    # Rileva distribuzione
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        OS_ID="$ID"
        OS_VERSION_ID="$VERSION_ID"
    else
        print_error "Impossibile rilevare la distribuzione"
        exit 1
    fi
    
    print_info "Sistema operativo: $OS_ID $OS_VERSION_ID"
    
    # Determina il pacchetto da scaricare
    local package_name=""
    local download_url=""
    
    case "$OS_ID" in
        ubuntu)
            if [[ "$OS_VERSION_ID" == "24.04" ]]; then
                package_name="check-mk-raw-${version}_0.noble_amd64.deb"
            elif [[ "$OS_VERSION_ID" == "22.04" ]]; then
                package_name="check-mk-raw-${version}_0.jammy_amd64.deb"
            elif [[ "$OS_VERSION_ID" == "20.04" ]]; then
                package_name="check-mk-raw-${version}_0.focal_amd64.deb"
            else
                print_error "Versione Ubuntu non supportata: $OS_VERSION_ID"
                exit 1
            fi
            ;;
        debian)
            if [[ "$OS_VERSION_ID" == "12" ]]; then
                package_name="check-mk-raw-${version}_0.bookworm_amd64.deb"
            elif [[ "$OS_VERSION_ID" == "11" ]]; then
                package_name="check-mk-raw-${version}_0.bullseye_amd64.deb"
            else
                print_error "Versione Debian non supportata: $OS_VERSION_ID"
                exit 1
            fi
            ;;
        *)
            print_error "Distribuzione non supportata: $OS_ID"
            exit 1
            ;;
    esac
    
    download_url="https://download.checkmk.com/checkmk/${version}/${package_name}"
    local local_file="$DOWNLOAD_DIR/$package_name"
    
    print_info "URL download: $download_url"
    print_info "File locale: $local_file"
    
    # Verifica se già scaricato
    if [[ -f "$local_file" ]]; then
        print_warning "File già presente, lo riutilizzo"
    else
        print_info "Download in corso..."
        if wget -q --show-progress -O "$local_file" "$download_url"; then
            print_success "Download completato"
        else
            print_error "Errore durante il download"
            exit 1
        fi
    fi
    
    echo "$local_file"
}

# ==========================================================
# Installazione nuova versione
# ==========================================================

install_version() {
    local package_file="$1"
    
    print_header "Installazione Nuova Versione"
    
    print_info "Installazione del pacchetto: $(basename "$package_file")"
    
    # Determina il tipo di pacchetto e installa
    if [[ "$package_file" == *.deb ]]; then
        if dpkg -i "$package_file"; then
            print_success "Pacchetto installato con successo"
        else
            print_error "Errore durante l'installazione del pacchetto"
            exit 1
        fi
    elif [[ "$package_file" == *.rpm ]]; then
        if rpm -U "$package_file"; then
            print_success "Pacchetto installato con successo"
        else
            print_error "Errore durante l'installazione del pacchetto"
            exit 1
        fi
    else
        print_error "Tipo di pacchetto non riconosciuto"
        exit 1
    fi
}

# ==========================================================
# Upgrade del sito
# ==========================================================

upgrade_site() {
    local target_version="$1"
    
    print_header "Upgrade Sito '$SITE_NAME'"
    
    # Stop del sito
    print_info "Stop del sito..."
    if omd stop "$SITE_NAME"; then
        print_success "Sito fermato"
    else
        print_error "Errore durante lo stop del sito"
        exit 1
    fi
    
    # Upgrade del sito
    print_info "Upgrade alla versione $target_version..."
    if omd update "$SITE_NAME"; then
        print_success "Upgrade completato"
    else
        print_error "Errore durante l'upgrade"
        print_warning "Tentativo di rollback..."
        omd start "$SITE_NAME"
        exit 1
    fi
    
    # Avvio del sito
    print_info "Avvio del sito aggiornato..."
    if omd start "$SITE_NAME"; then
        print_success "Sito avviato correttamente"
    else
        print_error "Errore durante l'avvio del sito"
        exit 1
    fi
}

# ==========================================================
# Verifica post-upgrade
# ==========================================================

verify_upgrade() {
    print_header "Verifica Post-Upgrade"
    
    # Verifica versione
    local new_version=$(omd version "$SITE_NAME" | grep -oP '\d+\.\d+\.\d+p\d+')
    print_info "Versione attuale: $new_version"
    
    # Verifica status sito
    print_info "Controllo status sito..."
    omd status "$SITE_NAME"
    
    # Verifica accesso web
    print_info "Verifica accesso web..."
    local site_url="http://localhost/monitoring"
    if curl -s -o /dev/null -w "%{http_code}" "$site_url" | grep -q "200\|302\|301"; then
        print_success "Sito web accessibile"
    else
        print_warning "Impossibile verificare l'accesso web"
    fi
    
    print_success "Upgrade completato con successo!"
}

# ==========================================================
# Cleanup
# ==========================================================

cleanup() {
    print_header "Pulizia File Temporanei"
    
    read -p "Vuoi eliminare i file di download? (s/N): " cleanup_confirm
    
    if [[ "$cleanup_confirm" =~ ^[sS]$ ]]; then
        rm -rf "$DOWNLOAD_DIR"
        print_success "File temporanei eliminati"
    else
        print_info "File mantenuti in: $DOWNLOAD_DIR"
    fi
}

# ==========================================================
# Main
# ==========================================================

main() {
    print_header "CheckMK Upgrade Script"
    
    # 1. Controllo prerequisiti
    check_prerequisites
    
    # 2. Ottieni versione corrente
    CURRENT_VERSION=$(get_current_version)
    
    # 3. Ottieni ultima versione disponibile
    LATEST_VERSION=$(get_latest_version)
    
    # 4. Confronta versioni
    if compare_versions "$CURRENT_VERSION" "$LATEST_VERSION"; then
        exit 0
    fi
    
    # 5. Richiedi conferma
    confirm_upgrade "$CURRENT_VERSION" "$LATEST_VERSION"
    
    # 6. Backup del sito
    backup_site
    
    # 7. Download nuova versione
    PACKAGE_FILE=$(download_version "$LATEST_VERSION")
    
    # 8. Installazione nuova versione
    install_version "$PACKAGE_FILE"
    
    # 9. Upgrade del sito
    upgrade_site "$LATEST_VERSION"
    
    # 10. Verifica
    verify_upgrade
    
    # 11. Cleanup
    cleanup
    
    print_header "🎉 Upgrade Completato! 🎉"
    echo -e "${GREEN}CheckMK è stato aggiornato da $CURRENT_VERSION a $LATEST_VERSION${NC}"
    echo ""
    print_info "Backup disponibile in: $BACKUP_DIR"
    echo ""
}

# Esegui main
main
