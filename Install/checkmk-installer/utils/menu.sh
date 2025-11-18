#!/usr/bin/env bash
# menu.sh - Menu and UI utilities

# Source colors if not already loaded
[[ -z "$GREEN" ]] && source "$(dirname "${BASH_SOURCE[0]}")/colors.sh"

#############################################
# Show menu with options
#############################################
show_menu() {
  local title="$1"
  shift
  local options=("$@")
  
  echo ""
  echo -e "${CYAN}${BOX_TL}$(printf "${BOX_H}%.0s" {1..60})${BOX_TR}${NC}"
  printf "${CYAN}${BOX_V}${NC}%20s${BOLD}${WHITE} %s ${NC}%*s${CYAN}${BOX_V}${NC}\n" "" "$title" $((60 - ${#title} - 20)) ""
  echo -e "${CYAN}${BOX_BL}$(printf "${BOX_H}%.0s" {1..60})${BOX_BR}${NC}"
  echo ""
  
  for i in "${!options[@]}"; do
    local num=$((i + 1))
    echo -e "  ${CYAN}${num})${NC} ${options[$i]}"
  done
  
  echo ""
}

#############################################
# Get user selection
#############################################
get_selection() {
  local max=$1
  local prompt="${2:-Scegli un'opzione}"
  
  while true; do
    read -p "${MAGENTA}${SYMBOL_ARROW}${NC} ${WHITE}${prompt} (1-${max}):${NC} " MENU_SELECTION
    
    if [[ "$MENU_SELECTION" =~ ^[0-9]+$ ]] && \
       [[ $MENU_SELECTION -ge 1 ]] && \
       [[ $MENU_SELECTION -le $max ]]; then
      export MENU_SELECTION
      return 0
    fi
    
    print_error "Selezione non valida. Inserisci un numero tra 1 e ${max}"
  done
}

#############################################
# Confirm action
#############################################
confirm() {
  local prompt="$1"
  local default="${2:-n}"
  
  while true; do
    if [[ "$default" == "y" ]]; then
      read -p "${YELLOW}${prompt} (Y/n):${NC} " -r response
      response=${response:-y}
    else
      read -p "${YELLOW}${prompt} (y/N):${NC} " -r response
      response=${response:-n}
    fi
    
    case "$response" in
      [yY]|[yY][eE][sS])
        return 0
        ;;
      [nN]|[nN][oO])
        return 1
        ;;
      *)
        print_error "Risposta non valida. Inserisci 's' o 'n'"
        ;;
    esac
  done
}

#############################################
# Multi-select menu
#############################################
multi_select() {
  local prompt="$1"
  shift
  local items=("$@")
  local selected=()
  
  echo ""
  echo -e "${CYAN}${prompt}${NC}"
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
    
    if $valid; then
      for sel in "${selections[@]}"; do
        selected+=("$((sel - 1))")
      done
      break
    fi
    
    print_error "Selezione non valida"
  done
  
  # Return selected indices
  echo "${selected[@]}"
}

#############################################
# Show progress with steps
#############################################
show_progress_steps() {
  local current="$1"
  local total="$2"
  local description="$3"
  
  print_step "$current" "$total" "$description"
  print_progress "$current" "$total"
}

#############################################
# Display a fancy box with text
#############################################
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
  echo ""
  echo -e "${CYAN}${BOX_TL}$(printf "${BOX_H}%.0s" $(seq 1 $max_width))${BOX_TR}${NC}"
  
  # Title
  local title_len=${#title}
  local padding=$(( (max_width - title_len - 2) / 2 ))
  printf "${CYAN}${BOX_V}${NC}%${padding}s${BOLD}${WHITE} %s ${NC}%*s${CYAN}${BOX_V}${NC}\n" \
    "" "$title" $((max_width - title_len - padding - 2)) ""
  
  # Middle border
  echo -e "${CYAN}${BOX_VR}$(printf "${BOX_H}%.0s" $(seq 1 $max_width))${BOX_VL}${NC}"
  
  # Content
  for line in "${lines[@]}"; do
    printf "${CYAN}${BOX_V}${NC}  %-*s${CYAN}${BOX_V}${NC}\n" $((max_width - 2)) "$line"
  done
  
  # Bottom border
  echo -e "${CYAN}${BOX_BL}$(printf "${BOX_H}%.0s" $(seq 1 $max_width))${BOX_BR}${NC}"
  echo ""
}

#############################################
# Input functions
#############################################
input_text() {
  local prompt="$1"
  local default="$2"
  local result
  
  if [[ -n "$default" ]]; then
    read -p "${WHITE}${prompt}${NC} [${CYAN}${default}${NC}]: " result
    echo "${result:-$default}"
  else
    read -p "${WHITE}${prompt}${NC}: " result
    echo "$result"
  fi
}

input_password() {
  local prompt="$1"
  local result
  
  read -s -p "${WHITE}${prompt}${NC}: " result
  echo "" >&2
  echo "$result"
}

input_number() {
  local prompt="$1"
  local default="$2"
  local result
  
  while true; do
    if [[ -n "$default" ]]; then
      read -p "${WHITE}${prompt}${NC} [${CYAN}${default}${NC}]: " result
      result="${result:-$default}"
    else
      read -p "${WHITE}${prompt}${NC}: " result
    fi
    
    if [[ "$result" =~ ^[0-9]+$ ]]; then
      echo "$result"
      return 0
    fi
    
    print_error "Inserisci un numero valido"
  done
}

select_from_list() {
  local prompt="$1"
  shift
  local options=("$@")
  
  echo ""
  echo -e "${CYAN}${prompt}${NC}"
  echo ""
  
  for i in "${!options[@]}"; do
    local num=$((i + 1))
    echo -e "  ${CYAN}${num})${NC} ${options[$i]}"
  done
  
  echo ""
  
  while true; do
    read -p "${MAGENTA}${SYMBOL_ARROW}${NC} ${WHITE}Seleziona (1-${#options[@]}):${NC} " selection
    
    if [[ "$selection" =~ ^[0-9]+$ ]] && \
       [[ $selection -ge 1 ]] && \
       [[ $selection -le ${#options[@]} ]]; then
      echo "${options[$((selection - 1))]}"
      return 0
    fi
    
    print_error "Selezione non valida"
  done
}

press_any_key() {
  read -n 1 -s -r -p "Press any key to continue..."
  echo ""
}

#############################################
# Show main installer menu
#############################################
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
