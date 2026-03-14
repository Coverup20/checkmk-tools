#!/usr/bin/env bash
# deploy-from-repo.sh - Script interattivo per deployment da repository
# Automatizza: git pull + copia file nelle destinazioni corrette

set -euo pipefail

# ===== Configurazione =====
REPO_PATH="/omd/sites/monitoring/checkmk-tools"
DEPLOY_USER="monitoring"
SCRIPT_USER=$(whoami)

# Colori per output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

# ===== Mappa dei file da deployare =====
# Formato: "source_path:destination_path:needs_sudo:description"
declare -a DEPLOY_MAP=(
  "Ydea-Toolkit/full/ydea-toolkit.sh:/opt/ydea-toolkit/ydea-toolkit.sh:yes:Ydea Toolkit principale"
  "script-notify-checkmk/full/mail_realip:/usr/local/bin/notify-checkmk/mail_realip:yes:Script notifiche mail CheckMK"
  "script-notify-checkmk/full/telegram_realip:/usr/local/bin/notify-checkmk/telegram_realip:yes:Script notifiche Telegram"
  "script-notify-checkmk/full/ydea_la:/usr/local/bin/notify-checkmk/ydea_la:yes:Script notifiche Ydea"
  "script-notify-checkmk/full/ydea_ag:/usr/local/bin/notify-checkmk/ydea_ag:yes:Script notifiche Ydea AG"
)

# ===== Funzioni Helper =====
print_header() {
  echo -e "\n${CYAN}${BOLD}========================================${RESET}"
  echo -e "${CYAN}${BOLD}  $1${RESET}"
  echo -e "${CYAN}${BOLD}========================================${RESET}\n"
}

print_step() {
  echo -e "${BLUE}▶${RESET} $1"
}

print_success() {
  echo -e "${GREEN}✓${RESET} $1"
}

print_error() {
  echo -e "${RED}✗${RESET} $1"
}

print_warning() {
  echo -e "${YELLOW}⚠${RESET}  $1"
}

print_info() {
  echo -e "${CYAN}ℹ${RESET}  $1"
}

# ===== Verifica prerequisiti =====
check_prerequisites() {
  print_step "Verifica prerequisiti..."
  
  # Verifica repository
  if [[ ! -d "$REPO_PATH" ]]; then
    print_error "Repository non trovato: $REPO_PATH"
    exit 1
  fi
  
  # Verifica git
  if ! command -v git &> /dev/null; then
    print_error "git non installato"
    exit 1
  fi
  
  print_success "Prerequisiti verificati"
}

# ===== Pull dal repository =====
update_repository() {
  print_step "Aggiornamento repository..."
  
  if [[ "$SCRIPT_USER" != "$DEPLOY_USER" ]]; then
    print_info "Switching a utente $DEPLOY_USER per git pull..."
    sudo -u "$DEPLOY_USER" bash -c "cd '$REPO_PATH' && git pull"
  else
    cd "$REPO_PATH" && git pull
  fi
  
  print_success "Repository aggiornato"
}

# ===== Mostra file disponibili =====
show_available_files() {
  print_header "📦 FILE DISPONIBILI PER DEPLOY"
  
  local index=1
  for entry in "${DEPLOY_MAP[@]}"; do
    IFS=':' read -r src dest needs_sudo desc <<< "$entry"
    local full_src="$REPO_PATH/$src"
    
    if [[ -f "$full_src" ]]; then
      echo -e "${GREEN}[$index]${RESET} ${BOLD}$desc${RESET}"
      echo -e "    📄 Source: $src"
      echo -e "    📌 Dest:   $dest"
      
      # Verifica se già presente
      if [[ -f "$dest" ]]; then
        echo -e "    ${YELLOW}⚠  File già presente in destinazione${RESET}"
      fi
    else
      echo -e "${RED}[$index]${RESET} ${BOLD}$desc${RESET} ${RED}(NON TROVATO)${RESET}"
      echo -e "    📄 Source: $src"
    fi
    
    echo ""
    ((index++))
  done
}

# ===== Deploy singolo file =====
deploy_file() {
  local entry="$1"
  IFS=':' read -r src dest needs_sudo desc <<< "$entry"
  
  local full_src="$REPO_PATH/$src"
  local dest_dir
  dest_dir=$(dirname "$dest")
  
  print_step "Deploy: $desc"
  
  # Verifica source
  if [[ ! -f "$full_src" ]]; then
    print_error "File sorgente non trovato: $full_src"
    return 1
  fi
  
  # Crea directory destinazione se non esiste
  if [[ ! -d "$dest_dir" ]]; then
    print_info "Creazione directory: $dest_dir"
    if [[ "$needs_sudo" == "yes" ]]; then
      sudo mkdir -p "$dest_dir"
    else
      mkdir -p "$dest_dir"
    fi
  fi
  
  # Backup se esiste
  if [[ -f "$dest" ]]; then
    local backup="${dest}.backup.$(date +%Y%m%d_%H%M%S)"
    print_info "Backup: $backup"
    if [[ "$needs_sudo" == "yes" ]]; then
      sudo cp "$dest" "$backup"
    else
      cp "$dest" "$backup"
    fi
  fi
  
  # Copia file
  if [[ "$needs_sudo" == "yes" ]]; then
    sudo cp "$full_src" "$dest"
    sudo chmod +x "$dest" 2>/dev/null || true
  else
    cp "$full_src" "$dest"
    chmod +x "$dest" 2>/dev/null || true
  fi
  
  print_success "Deploy completato: $dest"
}

# ===== Deploy tutti i file =====
deploy_all() {
  print_header "🚀 DEPLOY TUTTI I FILE"
  
  local deployed=0
  local failed=0
  
  for entry in "${DEPLOY_MAP[@]}"; do
    if deploy_file "$entry"; then
      ((deployed++))
    else
      ((failed++))
    fi
    echo ""
  done
  
  print_header "📊 RIEPILOGO"
  echo -e "Deployed: ${GREEN}$deployed${RESET}"
  echo -e "Failed:   ${RED}$failed${RESET}"
}

# ===== Menu interattivo =====
show_menu() {
  print_header "🔧 DEPLOY FROM REPOSITORY"
  
  echo "1) Mostra file disponibili"
  echo "2) Deploy tutti i file"
  echo "3) Deploy file specifico"
  echo "4) Aggiorna repository (git pull)"
  echo "5) Esci"
  echo ""
  read -p "Scelta: " choice
  
  case $choice in
    1)
      show_available_files
      read -p "Premi INVIO per continuare..."
      show_menu
      ;;
    2)
      update_repository
      deploy_all
      read -p "Premi INVIO per continuare..."
      show_menu
      ;;
    3)
      show_available_files
      read -p "Inserisci numero file da deployare: " num
      if [[ $num =~ ^[0-9]+$ ]] && [[ $num -ge 1 ]] && [[ $num -le ${#DEPLOY_MAP[@]} ]]; then
        update_repository
        deploy_file "${DEPLOY_MAP[$((num-1))]}"
      else
        print_error "Numero non valido"
      fi
      read -p "Premi INVIO per continuare..."
      show_menu
      ;;
    4)
      update_repository
      read -p "Premi INVIO per continuare..."
      show_menu
      ;;
    5)
      echo "Bye!"
      exit 0
      ;;
    *)
      print_error "Scelta non valida"
      show_menu
      ;;
  esac
}

# ===== Main =====
main() {
  check_prerequisites
  show_menu
}

main "$@"
