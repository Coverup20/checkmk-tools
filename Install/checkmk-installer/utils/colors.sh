#!/usr/bin/env bash
# colors.sh - Color definitions and symbols for terminal output

# Color codes
export RED='\033[0;31m'
export GREEN='\033[0;32m'
export YELLOW='\033[1;33m'
export BLUE='\033[0;34m'
export MAGENTA='\033[0;35m'
export CYAN='\033[0;36m'
export WHITE='\033[1;37m'
export GRAY='\033[0;90m'
export NC='\033[0m' # No Color

# Background colors
export BG_RED='\033[41m'
export BG_GREEN='\033[42m'
export BG_YELLOW='\033[43m'
export BG_BLUE='\033[44m'
export BG_MAGENTA='\033[45m'
export BG_CYAN='\033[46m'
export BG_WHITE='\033[47m'

# Text styles
export BOLD='\033[1m'
export DIM='\033[2m'
export UNDERLINE='\033[4m'
export BLINK='\033[5m'
export REVERSE='\033[7m'
export HIDDEN='\033[8m'

# Symbols
export SYMBOL_SUCCESS="✅"
export SYMBOL_ERROR="❌"
export SYMBOL_WARNING="⚠️ "
export SYMBOL_INFO="ℹ️ "
export SYMBOL_QUESTION="❓"
export SYMBOL_ARROW="➜"
export SYMBOL_BULLET="•"
export SYMBOL_CHECK="✓"
export SYMBOL_CROSS="✗"
export SYMBOL_STAR="★"
export SYMBOL_HEART="♥"
export SYMBOL_GEAR="⚙️ "
export SYMBOL_ROCKET="🚀"
export SYMBOL_PACKAGE="📦"
export SYMBOL_FOLDER="📁"
export SYMBOL_FILE="📄"
export SYMBOL_LOCK="🔒"
export SYMBOL_KEY="🔑"
export SYMBOL_CLOUD="☁️ "
export SYMBOL_SERVER="🖥️ "
export SYMBOL_CLIENT="💻"
export SYMBOL_NETWORK="🌐"
export SYMBOL_DOWNLOAD="⬇️ "
export SYMBOL_UPLOAD="⬆️ "
export SYMBOL_REFRESH="🔄"
export SYMBOL_CLOCK="🕐"
export SYMBOL_FIRE="🔥"
export SYMBOL_WRENCH="🔧"
export SYMBOL_HAMMER="🔨"
export SYMBOL_SCRIPT="📜"
export SYMBOL_TICKET="🎫"

# Box drawing characters
export BOX_TL="╔"  # Top Left
export BOX_TR="╗"  # Top Right
export BOX_BL="╚"  # Bottom Left
export BOX_BR="╝"  # Bottom Right
export BOX_H="═"   # Horizontal
export BOX_V="║"   # Vertical
export BOX_VL="╣"  # Vertical Left
export BOX_VR="╠"  # Vertical Right
export BOX_HT="╦"  # Horizontal Top
export BOX_HB="╩"  # Horizontal Bottom
export BOX_C="╬"   # Cross

# Helper functions
print_color() {
  local color="$1"
  shift
  echo -e "${color}$*${NC}"
}

print_success() { echo -e "${GREEN}${SYMBOL_SUCCESS} $*${NC}"; }
print_error() { echo -e "${RED}${SYMBOL_ERROR} $*${NC}" >&2; }
print_warning() { echo -e "${YELLOW}${SYMBOL_WARNING}$*${NC}"; }
print_info() { echo -e "${CYAN}${SYMBOL_INFO}$*${NC}"; }
print_question() { echo -e "${MAGENTA}${SYMBOL_QUESTION} $*${NC}"; }

print_header() {
  local text="$1"
  local width=60
  local padding=$(( (width - ${#text} - 2) / 2 ))
  
  echo ""
  echo -e "${CYAN}${BOX_TL}$(printf "${BOX_H}%.0s" $(seq 1 $width))${BOX_TR}${NC}"
  printf "${CYAN}${BOX_V}${NC}%${padding}s${BOLD}${WHITE} %s ${NC}%${padding}s${CYAN}${BOX_V}${NC}\n" "" "$text" ""
  echo -e "${CYAN}${BOX_BL}$(printf "${BOX_H}%.0s" $(seq 1 $width))${BOX_BR}${NC}"
  echo ""
}

print_box() {
  local text="$1"
  local width=60
  
  echo -e "${CYAN}${BOX_TL}$(printf "${BOX_H}%.0s" $(seq 1 $width))${BOX_TR}${NC}"
  echo -e "${CYAN}${BOX_V}${NC} ${WHITE}$text${NC}$(printf ' %.0s' $(seq 1 $((width - ${#text} - 1))))${CYAN}${BOX_V}${NC}"
  echo -e "${CYAN}${BOX_BL}$(printf "${BOX_H}%.0s" $(seq 1 $width))${BOX_BR}${NC}"
}

print_separator() {
  local char="${1:-=}"
  local width="${2:-60}"
  printf "${GRAY}%${width}s${NC}\n" | tr ' ' "$char"
}

print_step() {
  local step="$1"
  local total="$2"
  local description="$3"
  echo -e "${BOLD}${BLUE}[${step}/${total}]${NC} ${WHITE}${description}${NC}"
}

# Progress bar
print_progress() {
  local current="$1"
  local total="$2"
  local width=40
  local percentage=$((current * 100 / total))
  local completed=$((current * width / total))
  local remaining=$((width - completed))
  
  printf "\r${CYAN}["
  printf "${GREEN}%${completed}s" | tr ' ' '█'
  printf "${GRAY}%${remaining}s" | tr ' ' '░'
  printf "${CYAN}] ${WHITE}%3d%%${NC}" "$percentage"
  
  [[ $current -eq $total ]] && echo ""
}

# Spinner animation
spinner() {
  local pid=$1
  local delay=0.1
  local spinstr='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
  
  while ps -p $pid > /dev/null 2>&1; do
    local temp=${spinstr#?}
    printf " ${CYAN}%c${NC} " "$spinstr"
    spinstr=$temp${spinstr%"$temp"}
    sleep $delay
    printf "\b\b\b\b"
  done
  printf "    \b\b\b\b"
}
