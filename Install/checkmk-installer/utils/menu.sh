#!/usr/bin/env bash
# menu.sh - Interactive menu system

# Source dependencies
UTILS_DIR="$(dirname "${BASH_SOURCE[0]}")"
source "${UTILS_DIR}/colors.sh"
source "${UTILS_DIR}/logger.sh"

# Menu state
declare -g MENU_SELECTION=""
declare -g MENU_CONTINUE=true

# Display menu with options
show_menu() {
  local title="$1"
  shift
  local options=("$@")
  
  clear
  print_header "$title"
  
  for i in "${!options[@]}"; do
    local num=$((i + 1))
    echo -e "  ${CYAN}${num})${NC} ${options[$i]}"
  done
  
  echo ""
  print_separator
  echo ""
}

# Get user selection
get_selection() {
  local max="$1"
  local prompt="${2:-Scegli un'opzione}"
  
  while true; do
    echo -ne "${MAGENTA}${SYMBOL_ARROW}${NC} ${WHITE}${prompt} [1-${max}]:${NC} "
    read -r selection
    
    if [[ "$selection" =~ ^[0-9]+$ ]] && [[ $selection -ge 1 ]] && [[ $selection -le $max ]]; then
      MENU_SELECTION="$selection"
      return 0
    else
      print_error "Selezione non valida. Inserisci un numero tra 1 e $max"
    fi
  done
}

# Confirm action
confirm() {
  local prompt="${1:-Continuare?}"
  local default="${2:-n}"
  
  local yn_prompt="[s/n]"
  [[ "$default" == "y" ]] && yn_prompt="[S/n]"
  [[ "$default" == "n" ]] && yn_prompt="[s/N]"
  
  while true; do
    echo -ne "${YELLOW}${SYMBOL_QUESTION}${NC} ${WHITE}${prompt} ${yn_prompt}:${NC} "
    read -r answer
    
    # Use default if empty
    [[ -z "$answer" ]] && answer="$default"
    
    case "${answer,,}" in
      s|y|si|yes)
        return 0
        ;;
      n|no)
        return 1
        ;;
      *)
        print_error "Risposta non valida. Inserisci 's' o 'n'"
        ;;
    esac
  done
}

# Press any key to continue
press_any_key() {
  local prompt="${1:-Premi un tasto per continuare...}"
  echo ""
  echo -ne "${GRAY}${prompt}${NC}"
  read -n 1 -s -r
  echo ""
}

# Input text with validation
input_text() {
  local prompt="$1"
  local default="$2"
  local validation="${3:-.*}"  # Regex for validation
  
  local default_display=""
  [[ -n "$default" ]] && default_display=" [${default}]"
  
  while true; do
    echo -ne "${CYAN}${SYMBOL_ARROW}${NC} ${WHITE}${prompt}${default_display}:${NC} "
    read -r input
    
    # Use default if empty
    [[ -z "$input" ]] && input="$default"
    
    # Validate
    if [[ "$input" =~ $validation ]]; then
      echo "$input"
      return 0
    else
      print_error "Input non valido. Riprova."
    fi
  done
}

# Input password (hidden)
input_password() {
  local prompt="$1"
  local confirm="${2:-false}"
  
  while true; do
    echo -ne "${CYAN}${SYMBOL_ARROW}${NC} ${WHITE}${prompt}:${NC} "
    read -s -r password
    echo ""
    
    if [[ "$confirm" == "true" ]]; then
      echo -ne "${CYAN}${SYMBOL_ARROW}${NC} ${WHITE}Conferma password:${NC} "
      read -s -r password2
      echo ""
      
      if [[ "$password" == "$password2" ]]; then
        echo "$password"
        return 0
      else
        print_error "Le password non corrispondono. Riprova."
      fi
    else
      echo "$password"
      return 0
    fi
  done
}

# Select from list
select_from_list() {
  local prompt="$1"
  shift
  local items=("$@")
  
  echo -e "${WHITE}${prompt}:${NC}"
  echo ""
  
  for i in "${!items[@]}"; do
    local num=$((i + 1))
    echo -e "  ${CYAN}${num})${NC} ${items[$i]}"
  done
  
  echo ""
  
  while true; do
    echo -ne "${MAGENTA}${SYMBOL_ARROW}${NC} ${WHITE}Selezione [1-${#items[@]}]:${NC} "
    read -r selection
    
    if [[ "$selection" =~ ^[0-9]+$ ]] && [[ $selection -ge 1 ]] && [[ $selection -le ${#items[@]} ]]; then
      echo "${items[$((selection - 1))]}"
      return 0
    else
      print_error "Selezione non valida"
    fi
  done
}

# Multi-select from list (returns array indices)
multi_select() {
  local prompt="$1"
  shift
  local items=("$@")
  local -a selected=()
  
  echo -e "${WHITE}${prompt}${NC}"
  echo -e "${GRAY}(Inserisci i numeri separati da spazi, o 'all' per tutti)${NC}"
  echo ""
  
  for i in "${!items[@]}"; do
    local num=$((i + 1))
    echo -e "  ${CYAN}${num})${NC} ${items[$i]}"
  done
  
  echo ""
  
  while true; do
    echo -ne "${MAGENTA}${SYMBOL_ARROW}${NC} ${WHITE}Selezioni:${NC} "
    read -r -a selections
    
    # Check for 'all'
    if [[ "${selections[0],,}" == "all" ]]; then
      for i in "${!items[@]}"; do
        selected+=("$i")
      done
      break
    fi
    
    # Validate selections
    local valid=true
    for sel in "${selections[@]}"; do
      if ! [[ "$sel" =~ ^[0-9]+$ ]] || [[ $sel -lt 1 ]] || [[ $sel -gt ${#items[@]} ]]; then
        valid=false
        break
      fi
    done
    
    if [[ "$valid" == "true" ]]; then
      for sel in "${selections[@]}"; do
        selected+=("$((sel - 1))")
      done
      break
    else
      print_error "Selezione non valida. Riprova."
    fi
  done
  
  # Return selected indices
  echo "${selected[@]}"
}

# Show progress with steps
show_progress_steps() {
  local current="$1"
  local total="$2"
  local description="$3"
  
  print_step "$current" "$total" "$description"
  print_progress "$current" "$total"
}

# Display a fancy box with text
display_box() {
  local title="$1"
  shift
  local lines=("$@")
  local max_width=60
  
  # Calculate actual max width from content
  for line in "${lines[@]}"; do
    local len=${#line}
    [[ $len -gt $max_width ]] && max_width=$len
  done
  
  max_width=$((max_width + 4))
  
  # Top border
  echo -e "${CYAN}${BOX_TL}$(printf "${BOX_H}%.0s" $(seq 1 $max_width))${BOX_TR}${NC}"
  
  # Title
  if [[ -n "$title" ]]; then
    local title_padding=$(( (max_width - ${#title} - 2) / 2 ))
    printf "${CYAN}${BOX_V}${NC}%${title_padding}s${BOLD}${WHITE} %s ${NC}%${title_padding}s${CYAN}${BOX_V}${NC}\n" "" "$title" ""
    echo -e "${CYAN}${BOX_VR}$(printf "${BOX_H}%.0s" $(seq 1 $max_width))${BOX_VL}${NC}"
  fi
  
  # Content lines
  for line in "${lines[@]}"; do
    local padding=$((max_width - ${#line} - 2))
    printf "${CYAN}${BOX_V}${NC} ${WHITE}%s${NC}%${padding}s${CYAN}${BOX_V}${NC}\n" "$line" ""
  done
  
  # Bottom border
  echo -e "${CYAN}${BOX_BL}$(printf "${BOX_H}%.0s" $(seq 1 $max_width))${BOX_BR}${NC}"
}

# Show main installer menu
show_main_menu() {
  local options=(
    "${SYMBOL_SERVER} Installazione Server Completa (CheckMK + Scripts + Ydea + FRPC)"
    "${SYMBOL_CLIENT} Installazione Client Agent (Agent CheckMK + FRPC)"
    "${SYMBOL_SCRIPT} Deploy Scripts Monitoraggio (Solo scripts)"
    "${SYMBOL_TICKET} Installa Ydea Toolkit (Solo toolkit Ydea)"
    "${SYMBOL_WRENCH} Installazione Personalizzata (Scegli moduli)"
    "${SYMBOL_REFRESH} Aggiorna Scripts (da locale)"
    "${SYMBOL_CLOUD} Aggiorna Scripts (da GitHub)"
    "${SYMBOL_GEAR} Configurazione Guidata"
    "${SYMBOL_INFO} Mostra Configurazione Corrente"
    "${SYMBOL_ERROR} Esci"
  )
  
  show_menu "CheckMK Installer v1.0 - Menu Principale" "${options[@]}"
  get_selection "${#options[@]}"
}
