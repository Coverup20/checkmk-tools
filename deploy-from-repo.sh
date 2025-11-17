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
  "Ydea-Toolkit/ydea-toolkit.sh:/opt/ydea-toolkit/ydea-toolkit.sh:yes:Ydea Toolkit principale"
  "script-notify-checkmk/mail_realip:/usr/local/bin/notify-checkmk/mail_realip:yes:Script notifiche mail CheckMK"
  "script-notify-checkmk/telegram_realip:/usr/local/bin/notify-checkmk/telegram_realip:yes:Script notifiche Telegram"
  "script-notify-checkmk/ydea_realip:/usr/local/bin/notify-checkmk/ydea_realip:yes:Script notifiche Ydea"
)

# ===== Funzioni Helper =====
print_header() {
  echo -e "\n${CYAN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
  echo -e "${CYAN}${BOLD}  $1${RESET}"
  echo -e "${CYAN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}\n"
}

print_step() {
  echo -e "${BLUE}▶${RESET} $1"
}

print_success() {
  echo -e "${GREEN}✅${RESET} $1"
}

print_error() {
  echo -e "${RED}❌${RESET} $1"
}

print_warning() {
  echo -e "${YELLOW}⚠️${RESET}  $1"
}

print_info() {
  echo -e "${CYAN}ℹ️${RESET}  $1"
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
      echo -e "    📁 Source: $src"
      echo -e "    📍 Dest:   $dest"
      
      # Verifica se già presente
      if [[ -f "$dest" ]]; then
        echo -e "    ${YELLOW}⚠️  File già presente in destinazione${RESET}"
      fi
    else
      echo -e "${RED}[$index]${RESET} ${BOLD}$desc${RESET} ${RED}(NON TROVATO)${RESET}"
      echo -e "    📁 Source: $src"
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
  local dest_dir=$(dirname "$dest")
  
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
  return 0
}

# ===== Deploy interattivo =====
interactive_deploy() {
  print_header "🚀 DEPLOY INTERATTIVO"
  
  echo -e "${BOLD}Opzioni:${RESET}"
  echo "  [a] Deploy tutto"
  echo "  [s] Selezione singoli file"
  echo "  [q] Esci"
  echo ""
  
  read -p "Scegli un'opzione [a/s/q]: " choice
  
  case "$choice" in
    a|A)
      print_info "Deploy di tutti i file..."
      local success=0
      local failed=0
      
      for entry in "${DEPLOY_MAP[@]}"; do
        if deploy_file "$entry"; then
          ((success++))
        else
          ((failed++))
        fi
        echo ""
      done
      
      echo -e "\n${BOLD}Riepilogo:${RESET}"
      echo -e "  ${GREEN}✅ Successo: $success${RESET}"
      if [[ $failed -gt 0 ]]; then
        echo -e "  ${RED}❌ Falliti: $failed${RESET}"
      fi
      ;;
      
    s|S)
      show_available_files
      echo -e "${BOLD}Inserisci i numeri dei file da deployare (es: 1 3 4) o 'a' per tutti:${RESET}"
      read -p "> " selections
      
      if [[ "$selections" == "a" || "$selections" == "A" ]]; then
        for entry in "${DEPLOY_MAP[@]}"; do
          deploy_file "$entry"
          echo ""
        done
      else
        for num in $selections; do
          if [[ "$num" =~ ^[0-9]+$ ]] && [[ $num -ge 1 ]] && [[ $num -le ${#DEPLOY_MAP[@]} ]]; then
            local index=$((num - 1))
            deploy_file "${DEPLOY_MAP[$index]}"
            echo ""
          else
            print_warning "Numero non valido: $num"
          fi
        done
      fi
      ;;
      
    q|Q)
      print_info "Uscita..."
      exit 0
      ;;
      
    *)
      print_error "Opzione non valida"
      exit 1
      ;;
  esac
}

# ===== Menu principale =====
main_menu() {
  print_header "🔄 DEPLOY AUTOMATICO DA REPOSITORY"
  
  echo -e "${BOLD}Cosa vuoi fare?${RESET}"
  echo "  [1] Solo git pull (aggiorna repository)"
  echo "  [2] Git pull + deploy interattivo"
  echo "  [3] Git pull + deploy tutto automatico"
  echo "  [4] Solo deploy (senza git pull)"
  echo "  [5] Mostra stato attuale"
  echo "  [q] Esci"
  echo ""
  
  read -p "Scegli un'opzione [1-5/q]: " main_choice
  
  case "$main_choice" in
    1)
      check_prerequisites
      update_repository
      ;;
      
    2)
      check_prerequisites
      update_repository
      echo ""
      interactive_deploy
      ;;
      
    3)
      check_prerequisites
      update_repository
      echo ""
      print_info "Deploy automatico di tutti i file..."
      for entry in "${DEPLOY_MAP[@]}"; do
        deploy_file "$entry"
        echo ""
      done
      ;;
      
    4)
      check_prerequisites
      interactive_deploy
      ;;
      
    5)
      show_status
      ;;
      
    q|Q)
      print_info "Uscita..."
      exit 0
      ;;
      
    *)
      print_error "Opzione non valida"
      exit 1
      ;;
  esac
  
  echo ""
  print_success "Operazione completata!"
}

# ===== Mostra stato =====
show_status() {
  print_header "📊 STATO ATTUALE"
  
  print_step "Repository: $REPO_PATH"
  if [[ "$SCRIPT_USER" != "$DEPLOY_USER" ]]; then
    sudo -u "$DEPLOY_USER" bash -c "cd '$REPO_PATH' && git log -1 --oneline"
  else
    cd "$REPO_PATH" && git log -1 --oneline
  fi
  
  echo ""
  print_step "File deployati:"
  
  for entry in "${DEPLOY_MAP[@]}"; do
    IFS=':' read -r src dest needs_sudo desc <<< "$entry"
    
    if [[ -f "$dest" ]]; then
      local mod_date=$(stat -c %y "$dest" 2>/dev/null | cut -d' ' -f1,2 | cut -d'.' -f1 || stat -f "%Sm" -t "%Y-%m-%d %H:%M:%S" "$dest" 2>/dev/null)
      echo -e "  ${GREEN}✅${RESET} $desc"
      echo -e "     ${CYAN}→${RESET} $dest"
      echo -e "     ${YELLOW}⏰${RESET} $mod_date"
    else
      echo -e "  ${RED}❌${RESET} $desc"
      echo -e "     ${CYAN}→${RESET} $dest (NON PRESENTE)"
    fi
    echo ""
  done
}

# ===== Entry point =====
main() {
  # Se eseguito con argomenti, modalità non interattiva
  if [[ $# -gt 0 ]]; then
    case "$1" in
      --pull-only)
        check_prerequisites
        update_repository
        ;;
      --deploy-all)
        check_prerequisites
        update_repository
        for entry in "${DEPLOY_MAP[@]}"; do
          deploy_file "$entry"
        done
        ;;
      --status)
        show_status
        ;;
      --help)
        echo "Uso: $0 [opzione]"
        echo ""
        echo "Opzioni:"
        echo "  --pull-only    Solo git pull"
        echo "  --deploy-all   Git pull + deploy tutto"
        echo "  --status       Mostra stato"
        echo "  --help         Mostra questo help"
        echo ""
        echo "Senza opzioni: modalità interattiva"
        ;;
      *)
        print_error "Opzione non valida. Usa --help per vedere le opzioni"
        exit 1
        ;;
    esac
  else
    # Modalità interattiva
    main_menu
  fi
}

# Esegui
main "$@"
