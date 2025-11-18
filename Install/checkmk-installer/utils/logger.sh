#!/usr/bin/env bash
# logger.sh - Centralized logging system

# Source colors if not already loaded
[[ -z "$GREEN" ]] && source "$(dirname "${BASH_SOURCE[0]}")/colors.sh"

# Log configuration
export LOG_DIR="${LOG_DIR:-/var/log/checkmk-installer}"
export LOG_FILE="${LOG_FILE:-${LOG_DIR}/installer.log}"
export LOG_LEVEL="${LOG_LEVEL:-INFO}"
export LOG_MAX_SIZE="${LOG_MAX_SIZE:-10485760}"  # 10MB
export LOG_MAX_FILES="${LOG_MAX_FILES:-5}"

# Log levels (numeric for comparison)
declare -A LOG_LEVELS=(
  [DEBUG]=0
  [INFO]=1
  [SUCCESS]=2
  [WARNING]=3
  [ERROR]=4
  [CRITICAL]=5
)

# Initialize logging
init_logging() {
  # Create log directory
  if [[ ! -d "$LOG_DIR" ]]; then
    mkdir -p "$LOG_DIR" 2>/dev/null || {
      LOG_DIR="/tmp/checkmk-installer"
      mkdir -p "$LOG_DIR"
    }
  fi
  
  # Create log file if not exists
  touch "$LOG_FILE" 2>/dev/null || {
    LOG_FILE="/tmp/checkmk-installer/installer.log"
    mkdir -p "$(dirname "$LOG_FILE")"
    touch "$LOG_FILE"
  }
  
  # Log session start
  log_write "INFO" "=========================================="
  log_write "INFO" "Logging session started: $(date '+%Y-%m-%d %H:%M:%S')"
  log_write "INFO" "PID: $$"
  log_write "INFO" "User: $(whoami)"
  log_write "INFO" "Hostname: $(hostname)"
  log_write "INFO" "=========================================="
}

# Rotate log if needed
log_rotate() {
  [[ ! -f "$LOG_FILE" ]] && return 0
  
  local size=$(stat -f%z "$LOG_FILE" 2>/dev/null || stat -c%s "$LOG_FILE" 2>/dev/null || echo 0)
  
  if [[ $size -gt $LOG_MAX_SIZE ]]; then
    # Rotate existing logs
    for i in $(seq $((LOG_MAX_FILES - 1)) -1 1); do
      [[ -f "${LOG_FILE}.$i" ]] && mv "${LOG_FILE}.$i" "${LOG_FILE}.$((i + 1))"
    done
    
    # Move current log to .1
    mv "$LOG_FILE" "${LOG_FILE}.1"
    touch "$LOG_FILE"
    
    log_write "INFO" "Log rotated (size: ${size} bytes)"
  fi
}

# Write to log file
log_write() {
  local level="$1"
  shift
  local message="$*"
  local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
  
  # Check if we should log this level
  local current_level=${LOG_LEVELS[$LOG_LEVEL]:-1}
  local msg_level=${LOG_LEVELS[$level]:-1}
  
  [[ $msg_level -lt $current_level ]] && return 0
  
  # Rotate if needed
  log_rotate
  
  # Write to file
  echo "[$timestamp] [$level] [PID:$$] $message" >> "$LOG_FILE" 2>/dev/null || true
}

# Log functions
log_debug() {
  log_write "DEBUG" "$*"
  [[ "${VERBOSE:-0}" == "1" ]] && print_color "$GRAY" "🔍 DEBUG: $*"
}

log_info() {
  log_write "INFO" "$*"
  print_info "$*"
}

log_success() {
  log_write "SUCCESS" "$*"
  print_success "$*"
}

log_warning() {
  log_write "WARNING" "$*"
  print_warning "$*"
}

log_error() {
  log_write "ERROR" "$*"
  print_error "$*"
}

log_critical() {
  log_write "CRITICAL" "$*"
  print_error "CRITICAL: $*"
}

# Log command execution
log_command() {
  local cmd="$*"
  log_debug "Executing: $cmd"
  
  if [[ "${VERBOSE:-0}" == "1" ]]; then
    eval "$cmd" 2>&1 | tee -a "$LOG_FILE"
    local ret=${PIPESTATUS[0]}
  else
    eval "$cmd" >> "$LOG_FILE" 2>&1
    local ret=$?
  fi
  
  if [[ $ret -eq 0 ]]; then
    log_debug "Command succeeded: $cmd"
  else
    log_error "Command failed (exit code $ret): $cmd"
  fi
  
  return $ret
}

# Log module start/end
log_module_start() {
  local module="$1"
  log_write "INFO" "========== MODULE START: $module =========="
  print_header "$module"
}

log_module_end() {
  local module="$1"
  local status="${2:-success}"
  
  if [[ "$status" == "success" ]]; then
    log_write "INFO" "========== MODULE END: $module (SUCCESS) =========="
    log_success "Module $module completed successfully"
  else
    log_write "ERROR" "========== MODULE END: $module (FAILED) =========="
    log_error "Module $module failed"
  fi
}

# Show last N lines of log
log_tail() {
  local lines="${1:-50}"
  [[ -f "$LOG_FILE" ]] && tail -n "$lines" "$LOG_FILE"
}

# Show errors from log
log_errors() {
  [[ -f "$LOG_FILE" ]] && grep -E "\[ERROR\]|\[CRITICAL\]" "$LOG_FILE"
}

# Clear log
log_clear() {
  if [[ -f "$LOG_FILE" ]]; then
    > "$LOG_FILE"
    log_success "Log file cleared"
  fi
}

# Export log location
log_location() {
  echo "$LOG_FILE"
}
