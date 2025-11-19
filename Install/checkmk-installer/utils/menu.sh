#!/usr/bin/env bash
# menu.sh - Complete working version

[[ -z "$GREEN" ]] && source "$(dirname "${BASH_SOURCE[0]}")/colors.sh"

show_menu() {
  echo ""
  echo "=========================================="
  echo "  $1"
  echo "=========================================="
  shift
  local i=1
  for item in "$@"; do
    echo "  $i) $item"
    ((i++))
  done
  echo "=========================================="
}

get_selection() {
  local max=$1
  while true; do
    read -p "Select option (1-$max): " MENU_SELECTION
    if [[ "$MENU_SELECTION" =~ ^[0-9]+$ ]] && [ "$MENU_SELECTION" -ge 1 ] && [ "$MENU_SELECTION" -le "$max" ]; then
      export MENU_SELECTION
      return 0
    fi
    echo "Invalid selection. Try again."
  done
}

confirm() {
  local prompt="$1"
  local default="${2:-n}"
  
  while true; do
    if [[ "$default" == "y" ]]; then
      read -p "$prompt (Y/n): " -r response
      response=${response:-y}
    else
      read -p "$prompt (y/N): " -r response
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
        echo "Invalid response. Enter y or n"
        ;;
    esac
  done
}

multi_select() {
  local prompt="$1"
  shift
  local items=("$@")
  local selected=()
  
  echo ""
  echo "$prompt"
  echo "(Enter numbers separated by spaces, or 'all' for all)"
  echo ""
  
  for i in "${!items[@]}"; do
    local num=$((i + 1))
    echo "  $num) ${items[$i]}"
  done
  
  echo ""
  
  while true; do
    read -p "Selections: " -r -a selections
    
    if [[ "${selections[0],,}" == "all" ]]; then
      for i in "${!items[@]}"; do
        selected+=("$i")
      done
      break
    fi
    
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
    
    echo "Invalid selection"
  done
  
  echo "${selected[@]}"
}

display_box() {
  local title="$1"
  shift
  
  echo ""
  echo "=========================================="
  echo "  $title"
  echo "=========================================="
  for line in "$@"; do
    echo "  $line"
  done
  echo "=========================================="
  echo ""
}

input_text() {
  local prompt="$1"
  local default="$2"
  local result
  
  if [[ -n "$default" ]]; then
    read -p "$prompt [$default]: " result
    echo "${result:-$default}"
  else
    read -p "$prompt: " result
    echo "$result"
  fi
}

input_password() {
  local prompt="$1"
  local result
  
  read -s -p "$prompt: " result
  echo "" >&2
  echo "$result"
}

input_number() {
  local prompt="$1"
  local default="$2"
  local result
  
  while true; do
    if [[ -n "$default" ]]; then
      read -p "$prompt [$default]: " result
      result="${result:-$default}"
    else
      read -p "$prompt: " result
    fi
    
    if [[ "$result" =~ ^[0-9]+$ ]]; then
      echo "$result"
      return 0
    fi
    
    echo "Enter a valid number" >&2
  done
}

select_from_list() {
  local prompt="$1"
  shift
  local options=("$@")
  
  echo "" >&2
  echo "$prompt" >&2
  echo "" >&2
  
  for i in "${!options[@]}"; do
    local num=$((i + 1))
    echo "  $num) ${options[$i]}" >&2
  done
  
  echo "" >&2
  
  while true; do
    read -p "Select (1-${#options[@]}): " selection
    
    if [[ "$selection" =~ ^[0-9]+$ ]] && \
       [[ $selection -ge 1 ]] && \
       [[ $selection -le ${#options[@]} ]]; then
      echo "${options[$((selection - 1))]}"
      return 0
    fi
    
    echo "Invalid selection" >&2
  done
}

press_any_key() {
  read -n 1 -s -r -p "Press any key to continue..."
  echo ""
}

show_main_menu() {
  local options=(
    "Complete Server Installation (CheckMK + Scripts + Ydea + FRPC)"
    "Client Agent Installation (CheckMK Agent + FRPC)"
    "Deploy Monitoring Scripts (Scripts only)"
    "Install Ydea Toolkit (Toolkit only)"
    "Custom Installation (Choose modules)"
    "Update Scripts (from local)"
    "Update Scripts (from GitHub)"
    "Configuration Wizard"
    "Show Current Configuration"
    "Exit"
  )
  
  show_menu "CheckMK Installer v1.0 - Main Menu" "${options[@]}"
  get_selection "${#options[@]}"
}
