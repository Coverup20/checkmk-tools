#!/bin/bash
# ==========================================================
#  Auto Git Sync - Clone iniziale e Pull automatico
#  Clona il repository alla prima esecuzione e poi
#  esegue git pull ogni minuto automaticamente
#  Autore: ChatGPT per Marzio Bordin
# ==========================================================

# Imposta PATH per systemd
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# Configurazione
REPO_URL="https://github.com/Coverup20/checkmk-tools.git"
TARGET_DIR="$HOME/checkmk-tools"
SYNC_INTERVAL="${1:-60}"  # Primo parametro o default 60 secondi
LOG_FILE="/var/log/auto-git-sync.log"

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

log_message() {
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] $1" | tee -a "$LOG_FILE"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
    log_message "INFO: $1"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
    log_message "SUCCESS: $1"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
    log_message "WARNING: $1"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
    log_message "ERROR: $1"
}

print_header() {
    echo -e "\n${CYAN}========================================${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}========================================${NC}\n"
}

# ==========================================================
# Verifica e clona repository se necessario
# ==========================================================

init_repository() {
    print_header "Inizializzazione Repository"
    
    # Verifica se la directory esiste
    if [[ -d "$TARGET_DIR" ]]; then
        # Verifica se è un repository git valido
        if [[ -d "$TARGET_DIR/.git" ]]; then
            print_success "Repository già esistente in: $TARGET_DIR"
            
            # Verifica il remote
            cd "$TARGET_DIR" || exit 1
            local current_remote=$(git remote get-url origin 2>/dev/null)
            
            if [[ "$current_remote" == "$REPO_URL" ]]; then
                print_success "Remote corretto: $REPO_URL"
            else
                print_warning "Remote diverso rilevato: $current_remote"
                print_info "Aggiorno remote a: $REPO_URL"
                git remote set-url origin "$REPO_URL"
            fi
            
            return 0
        else
            print_warning "Directory esistente ma non è un repository git"
            print_info "Rimuovo directory e procedo con il clone..."
            rm -rf "$TARGET_DIR"
        fi
    fi
    
    # Clone del repository
    print_info "Clonazione repository da: $REPO_URL"
    print_info "Destinazione: $TARGET_DIR"
    
    if git clone "$REPO_URL" "$TARGET_DIR"; then
        print_success "Repository clonato con successo!"
        cd "$TARGET_DIR" || exit 1
        
        # Mostra informazioni sul repository
        local branch=$(git branch --show-current)
        local commit=$(git rev-parse --short HEAD)
        print_info "Branch: $branch"
        print_info "Commit: $commit"
        
        return 0
    else
        print_error "Errore durante il clone del repository"
        return 1
    fi
}

# ==========================================================
# Esegue git pull
# ==========================================================

do_git_pull() {
    cd "$TARGET_DIR" || {
        print_error "Impossibile accedere alla directory: $TARGET_DIR"
        return 1
    }
    
    # Salva commit corrente
    local old_commit=$(git rev-parse --short HEAD)
    
    # Verifica se ci sono modifiche locali
    if ! git diff-index --quiet HEAD --; then
        print_warning "Modifiche locali rilevate"
        print_info "Eseguo stash delle modifiche locali..."
        git stash save "Auto-stash before pull $(date '+%Y-%m-%d %H:%M:%S')" >/dev/null 2>&1
    fi
    
    # Esegue il pull
    local pull_output=$(git pull origin main 2>&1)
    local pull_status=$?
    
    if [[ $pull_status -eq 0 ]]; then
        local new_commit=$(git rev-parse --short HEAD)
        
        if [[ "$old_commit" != "$new_commit" ]]; then
            print_success "Repository aggiornato: $old_commit → $new_commit"
            
            # Mostra i file modificati
            print_info "File modificati:"
            git diff --name-status "$old_commit" "$new_commit" | while read -r status file; do
                case "$status" in
                    A) echo "  ${GREEN}+ $file${NC}" ;;
                    M) echo "  ${YELLOW}~ $file${NC}" ;;
                    D) echo "  ${RED}- $file${NC}" ;;
                    *) echo "  $status $file" ;;
                esac
            done
            
            return 0
        else
            print_info "Repository già aggiornato (nessuna modifica)"
            return 0
        fi
    else
        print_error "Errore durante il pull"
        echo "$pull_output" | tee -a "$LOG_FILE"
        return 1
    fi
}

# ==========================================================
# Loop principale
# ==========================================================

run_sync_loop() {
    print_header "Auto Git Sync Attivo"
    
    print_info "Repository: $REPO_URL"
    print_info "Directory locale: $TARGET_DIR"
    print_info "Intervallo sync: ${SYNC_INTERVAL}s (ogni minuto)"
    print_info "Log file: $LOG_FILE"
    echo ""
    print_warning "Premi Ctrl+C per interrompere"
    echo ""
    
    local sync_count=0
    
    while true; do
        sync_count=$((sync_count + 1))
        
        echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        print_info "Sync #$sync_count - $(date '+%Y-%m-%d %H:%M:%S')"
        
        if do_git_pull; then
            print_success "Sync completato"
        else
            print_error "Sync fallito"
        fi
        
        print_info "Prossimo sync tra ${SYNC_INTERVAL}s..."
        sleep "$SYNC_INTERVAL"
    done
}

# ==========================================================
# Gestione segnali
# ==========================================================

cleanup() {
    echo ""
    print_warning "Ricevuto segnale di interruzione"
    print_info "Arresto Auto Git Sync..."
    log_message "Auto Git Sync terminato"
    exit 0
}

trap cleanup SIGINT SIGTERM

# ==========================================================
# Main
# ==========================================================

main() {
    # Verifica git installato
    if ! command -v git &> /dev/null; then
        print_error "Git non è installato"
        exit 1
    fi
    
    # Crea directory per log se non esiste
    sudo mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || LOG_FILE="$HOME/auto-git-sync.log"
    sudo touch "$LOG_FILE" 2>/dev/null || LOG_FILE="$HOME/auto-git-sync.log"
    
    print_header "Auto Git Sync - Avvio"
    log_message "=== Auto Git Sync Started ==="
    
    # Inizializza repository
    if ! init_repository; then
        print_error "Impossibile inizializzare il repository"
        exit 1
    fi
    
    # Esegui primo sync immediato
    print_header "Primo Sync"
    do_git_pull
    
    # Avvia loop di sync
    run_sync_loop
}

# Controlla se script eseguito direttamente
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
