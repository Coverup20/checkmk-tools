#!/usr/bin/env bash
# validate.sh - Input validation functions

# Source dependencies
UTILS_DIR="$(dirname "${BASH_SOURCE[0]}")"
source "${UTILS_DIR}/colors.sh"

# Validate IP address
validate_ip() {
  local ip="$1"
  
  if [[ "$ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
    local IFS='.'
    local -a octets=($ip)
    for octet in "${octets[@]}"; do
      [[ $octet -gt 255 ]] && return 1
    done
    return 0
  fi
  
  return 1
}

# Validate port number
validate_port() {
  local port="$1"
  
  if [[ "$port" =~ ^[0-9]+$ ]] && [[ $port -ge 1 ]] && [[ $port -le 65535 ]]; then
    return 0
  fi
  
  return 1
}

# Validate email address
validate_email() {
  local email="$1"
  
  if [[ "$email" =~ ^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]]; then
    return 0
  fi
  
  return 1
}

# Validate hostname
validate_hostname() {
  local hostname="$1"
  
  if [[ "$hostname" =~ ^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$ ]]; then
    return 0
  fi
  
  return 1
}

# Validate URL
validate_url() {
  local url="$1"
  
  if [[ "$url" =~ ^https?://[a-zA-Z0-9.-]+(:[0-9]+)?(/.*)?$ ]]; then
    return 0
  fi
  
  return 1
}

# Validate domain
validate_domain() {
  local domain="$1"
  
  if [[ "$domain" =~ ^([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$ ]]; then
    return 0
  fi
  
  return 1
}

# Validate path exists
validate_path_exists() {
  local path="$1"
  [[ -e "$path" ]]
}

# Validate directory exists
validate_dir_exists() {
  local dir="$1"
  [[ -d "$dir" ]]
}

# Validate file exists
validate_file_exists() {
  local file="$1"
  [[ -f "$file" ]]
}

# Validate not empty
validate_not_empty() {
  local value="$1"
  [[ -n "$value" ]]
}

# Validate number
validate_number() {
  local num="$1"
  [[ "$num" =~ ^[0-9]+$ ]]
}

# Validate number in range
validate_number_range() {
  local num="$1"
  local min="$2"
  local max="$3"
  
  if validate_number "$num"; then
    [[ $num -ge $min ]] && [[ $num -le $max ]]
  else
    return 1
  fi
}

# Validate password strength
validate_password() {
  local password="$1"
  local min_length="${2:-8}"
  
  # Check minimum length
  [[ ${#password} -ge $min_length ]] || return 1
  
  # Check for at least one letter
  [[ "$password" =~ [a-zA-Z] ]] || return 1
  
  # Check for at least one number
  [[ "$password" =~ [0-9] ]] || return 1
  
  return 0
}

# Validate username
validate_username() {
  local username="$1"
  
  # Must start with letter, contain only alphanumeric and underscore
  if [[ "$username" =~ ^[a-z][a-z0-9_-]{2,31}$ ]]; then
    return 0
  fi
  
  return 1
}

# Validate disk space available (in MB)
validate_disk_space() {
  local path="$1"
  local required_mb="$2"
  
  local available_mb=$(df -BM "$path" | awk 'NR==2 {print $4}' | sed 's/M//')
  
  [[ $available_mb -ge $required_mb ]]
}

# Validate system requirements
validate_system_requirements() {
  local errors=0
  
  print_info "Verifica requisiti sistema..."
  
  # Check if running as root
  if [[ $EUID -ne 0 ]]; then
    print_error "Questo script deve essere eseguito come root"
    ((errors++))
  else
    print_success "Permessi root: OK"
  fi
  
  # Check disk space (at least 5GB)
  if validate_disk_space "/" 5000; then
    print_success "Spazio disco: OK"
  else
    print_error "Spazio disco insufficiente (minimo 5GB richiesti)"
    ((errors++))
  fi
  
  # Check memory (at least 2GB)
  local mem_mb=$(free -m | awk 'NR==2 {print $2}')
  if [[ $mem_mb -ge 2000 ]]; then
    print_success "Memoria RAM: OK (${mem_mb}MB)"
  else
    print_warning "Memoria RAM bassa (${mem_mb}MB, consigliati almeno 2GB)"
  fi
  
  # Check internet connection (optional)
  if ping -c 1 8.8.8.8 &>/dev/null; then
    print_success "Connessione internet: OK"
  else
    print_warning "Connessione internet non disponibile (modalità offline)"
  fi
  
  # Check required commands
  local required_commands=("curl" "wget" "jq" "systemctl" "apt-get")
  for cmd in "${required_commands[@]}"; do
    if command -v "$cmd" &>/dev/null; then
      print_success "Comando '$cmd': OK"
    else
      print_warning "Comando '$cmd': NON TROVATO (verrà installato)"
    fi
  done
  
  return $errors
}

# Input validation wrappers
input_ip() {
  local prompt="$1"
  local default="$2"
  
  while true; do
    local ip=$(input_text "$prompt" "$default")
    if validate_ip "$ip"; then
      echo "$ip"
      return 0
    else
      print_error "Indirizzo IP non valido"
    fi
  done
}

input_port() {
  local prompt="$1"
  local default="$2"
  
  while true; do
    local port=$(input_text "$prompt" "$default" "^[0-9]+$")
    if validate_port "$port"; then
      echo "$port"
      return 0
    else
      print_error "Porta non valida (1-65535)"
    fi
  done
}

input_email() {
  local prompt="$1"
  local default="$2"
  
  while true; do
    local email=$(input_text "$prompt" "$default")
    if validate_email "$email"; then
      echo "$email"
      return 0
    else
      print_error "Email non valida"
    fi
  done
}

input_url() {
  local prompt="$1"
  local default="$2"
  
  while true; do
    local url=$(input_text "$prompt" "$default")
    if validate_url "$url"; then
      echo "$url"
      return 0
    else
      print_error "URL non valido (deve iniziare con http:// o https://)"
    fi
  done
}

input_hostname() {
  local prompt="$1"
  local default="$2"
  
  while true; do
    local hostname=$(input_text "$prompt" "$default")
    if validate_hostname "$hostname"; then
      echo "$hostname"
      return 0
    else
      print_error "Hostname non valido"
    fi
  done
}
