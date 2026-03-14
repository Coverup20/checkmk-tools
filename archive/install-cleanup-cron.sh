#!/usr/bin/env bash
set -euo pipefail

# install-cleanup-cron.sh
# Interactive installer for cleanup-checkmk-retention.sh cron job
#
# Usage:
#   ./install-cleanup-cron.sh              # Interactive mode
#   ./install-cleanup-cron.sh --yes        # Auto-confirm (default time 03:00)
#   ./install-cleanup-cron.sh --time "0 2 * * *"  # Specific time

SCRIPT_URL="https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/full/backup_restore/cleanup-checkmk-retention.sh"
LOG_FILE="/var/log/cleanup-checkmk-retention.log"
CRON_TIME="0 3 * * *"  # Default: 03:00 every day
AUTO_YES=false
EMAIL_REPORT=""  # Email address for reports

log() { echo -e "\n\033[1;34m[INFO]\033[0m $*"; }
success() { echo -e "\033[1;32m[OK]\033[0m $*"; }
warn() { echo -e "\033[1;33m[WARN]\033[0m $*"; }
err() { echo -e "\033[1;31m[ERROR]\033[0m $*" >&2; }
die() { err "$*"; exit 1; }

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y)
      AUTO_YES=true
      shift
      ;;
    --time|-t)
      CRON_TIME="$2"
      shift 2
      ;;
    --email|-e)
      EMAIL_REPORT="$2"
      shift 2
      ;;
    --help|-h)
      cat <<EOF
Usage: $0 [OPTIONS]

Options:
  --yes, -y           Auto-confirm installation (non-interactive)
  --time, -t TIME     Set cron schedule (format: "MIN HOUR DAY MONTH WEEKDAY")
  --email, -e EMAIL   Email address for cleanup reports
  --help, -h          Show this help

Examples:
  $0                           # Interactive mode
  $0 --yes                     # Install with default time (03:00)
  $0 --yes --time "0 2 * * *"  # Install at 02:00 AM
  $0 --yes --email admin@example.com  # Install with email reports

When piped from curl:
  curl -fsSL https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/install-cleanup-cron.sh | sudo bash -s -- --yes --email admin@example.com
EOF
      exit 0
      ;;
    *)
      err "Unknown option: $1"
      exit 1
      ;;
  esac
done

# Redirect stdin from /dev/tty for interactive input when piped (only if not auto-yes)
if [[ "$AUTO_YES" == false ]] && [[ -t 0 ]]; then
  exec < /dev/tty
fi

# Check root
if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  die "This script must be run as root. Use: sudo $0"
fi

# Banner
clear
cat << "EOF"
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║      CLEANUP CHECKMK RETENTION - CRON INSTALLER              ║
║                                                              ║
║  Automated cleanup for CheckMK data retention:              ║
║  • RRD files: 180 days                                       ║
║  • Nagios archives: 180 days (compressed after 30 days)     ║
║  • Notify backups: 30 days (compressed after 1 day)         ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
EOF

log "Script URL: $SCRIPT_URL"
log "Log file: $LOG_FILE"
echo ""

# Check if curl is available
if ! command -v curl >/dev/null 2>&1; then
  die "curl is not installed. Please install it first: apt install curl"
fi

# Test script accessibility
log "Testing script accessibility from GitHub..."
if ! curl -fsSL --connect-timeout 5 "$SCRIPT_URL" >/dev/null 2>&1; then
  die "Cannot access script from GitHub. Check your internet connection or URL."
fi
success "Script is accessible from GitHub"

# Check if cron job already exists
CRON_PATTERN="cleanup-checkmk-retention.sh"
if crontab -l 2>/dev/null | grep -q "$CRON_PATTERN"; then
  warn "Cron job already exists!"
  echo ""
  echo "Current cron configuration:"
  echo "─────────────────────────────────────────────────────────────"
  crontab -l 2>/dev/null | grep "$CRON_PATTERN"
  echo "─────────────────────────────────────────────────────────────"
  echo ""
  
  if [[ "$AUTO_YES" == false ]]; then
    read -p "Do you want to REPLACE it? [y/N]: " answer
    if [[ ! "$answer" =~ ^[Yy]$ ]]; then
      log "Installation cancelled."
      exit 0
    fi
  else
    log "Auto-confirm enabled - replacing existing cron job"
  fi
  
  # Remove existing cron
  log "Removing existing cron job..."
  crontab -l 2>/dev/null | grep -v "$CRON_PATTERN" | crontab - || true
  success "Existing cron job removed"
fi

# Ask for schedule (only if not auto-yes)
if [[ "$AUTO_YES" == false ]]; then
  echo ""
  log "Configure execution schedule"
  echo ""
  echo "Default schedule: 03:00 AM every day (0 3 * * *)"
  echo ""
  echo "Common schedules:"
  echo "  1) 03:00 AM daily (recommended)"
  echo "  2) 02:00 AM daily"
  echo "  3) 04:00 AM daily"
  echo "  4) Custom time"
  echo ""

  read -p "Select schedule [1-4, default: 1]: " schedule_choice

  case "${schedule_choice:-1}" in
    1)
      CRON_TIME="0 3 * * *"
      CRON_DESC="03:00 AM daily"
      ;;
    2)
      CRON_TIME="0 2 * * *"
      CRON_DESC="02:00 AM daily"
      ;;
    3)
      CRON_TIME="0 4 * * *"
      CRON_DESC="04:00 AM daily"
      ;;
    4)
      echo ""
      echo "Enter cron schedule (format: MIN HOUR DAY MONTH WEEKDAY)"
      echo "Examples:"
      echo "  0 3 * * *     = 03:00 every day"
      echo "  30 2 * * *    = 02:30 every day"
      echo "  0 3 * * 0     = 03:00 every Sunday"
      echo ""
      read -p "Custom schedule: " CRON_TIME
      CRON_DESC="custom: $CRON_TIME"
      
      # Validate cron syntax (basic)
      if [[ ! "$CRON_TIME" =~ ^[0-9*,/-]+[[:space:]][0-9*,/-]+[[:space:]][0-9*,/-]+[[:space:]][0-9*,/-]+[[:space:]][0-9*,/-]+$ ]]; then
        die "Invalid cron syntax. Please use format: MIN HOUR DAY MONTH WEEKDAY"
      fi
      ;;
    *)
      CRON_TIME="0 3 * * *"
      CRON_DESC="03:00 AM daily (default)"
      ;;
  esac
else
  # Determine CRON_DESC for auto-yes mode
  case "$CRON_TIME" in
    "0 3 * * *")
      CRON_DESC="03:00 AM daily"
      ;;
    "0 2 * * *")
      CRON_DESC="02:00 AM daily"
      ;;
    "0 4 * * *")
      CRON_DESC="04:00 AM daily"
      ;;
    *)
      CRON_DESC="custom: $CRON_TIME"
      ;;
  esac
fi

# Ask for email address (only if not auto-yes and not specified)
if [[ "$AUTO_YES" == false ]] && [[ -z "$EMAIL_REPORT" ]]; then
  echo ""
  log "Configurazione email report (opzionale)"
  echo ""
  echo "Vuoi ricevere report via email dopo ogni cleanup?"
  echo ""
  read -p "Indirizzo email (lascia vuoto per saltare): " EMAIL_REPORT
  
  if [[ -n "$EMAIL_REPORT" ]]; then
    # Valida email (basic)
    if [[ ! "$EMAIL_REPORT" =~ ^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]]; then
      warn "Email non valida: $EMAIL_REPORT"
      read -p "Continuare comunque? [y/N]: " answer
      if [[ ! "$answer" =~ ^[Yy]$ ]]; then
        EMAIL_REPORT=""
      fi
    else
      success "Email configurata: $EMAIL_REPORT"
    fi
  fi
fi

# Build cron command
if [[ -n "$EMAIL_REPORT" ]]; then
  CRON_CMD="$CRON_TIME curl -fsSL $SCRIPT_URL | bash -s -- --email $EMAIL_REPORT >> $LOG_FILE 2>&1"
else
  CRON_CMD="$CRON_TIME curl -fsSL $SCRIPT_URL | bash >> $LOG_FILE 2>&1"
fi

# Show summary and confirm
echo ""
log "Installation summary:"
echo "─────────────────────────────────────────────────────────────"
echo "Schedule:    $CRON_DESC"
echo "Command:     curl -fsSL $SCRIPT_URL | bash$([ -n "$EMAIL_REPORT" ] && echo " --email $EMAIL_REPORT" || echo "")"
echo "Email report:$([ -n "$EMAIL_REPORT" ] && echo " $EMAIL_REPORT" || echo " disabled")"
echo "Log file:    $LOG_FILE"
echo "Cron entry:  $CRON_CMD"
echo "─────────────────────────────────────────────────────────────"
echo ""

if [[ "$AUTO_YES" == false ]]; then
  read -p "Proceed with installation? [y/N]: " answer
  if [[ ! "$answer" =~ ^[Yy]$ ]]; then
    log "Installation cancelled."
    exit 0
  fi
else
  log "Auto-confirm enabled - proceeding with installation"
fi

# Install cron job
log "Installing cron job..."

# Get current crontab, add new job
(crontab -l 2>/dev/null || true; echo "$CRON_CMD") | crontab -

success "Cron job installed successfully!"

# Verify installation
echo ""
log "Verifying installation..."
if crontab -l 2>/dev/null | grep -q "$CRON_PATTERN"; then
  success "Cron job verified in crontab"
  echo ""
  echo "Current cron configuration:"
  echo "─────────────────────────────────────────────────────────────"
  crontab -l 2>/dev/null | grep "$CRON_PATTERN"
  echo "─────────────────────────────────────────────────────────────"
else
  die "Cron job installation failed!"
fi

# Ask for test run (only if not auto-yes)
if [[ "$AUTO_YES" == false ]]; then
  echo ""
  read -p "Do you want to run the cleanup script now (test)? [y/N]: " answer
  if [[ "$answer" =~ ^[Yy]$ ]]; then
    log "Running cleanup script in dry-run mode..."
    echo ""
    echo "════════════════════════════════════════════════════════════"
    curl -fsSL "$SCRIPT_URL" | bash -s -- --dry-run
    echo "════════════════════════════════════════════════════════════"
    echo ""
    
    read -p "Run REAL cleanup now (not dry-run)? [y/N]: " answer
    if [[ "$answer" =~ ^[Yy]$ ]]; then
      log "Running REAL cleanup..."
      echo ""
      echo "════════════════════════════════════════════════════════════"
      curl -fsSL "$SCRIPT_URL" | bash | tee -a "$LOG_FILE"
      echo "════════════════════════════════════════════════════════════"
    fi
  fi
fi

# Final instructions
echo ""
success "Installation complete!"
echo ""
log "Next automatic execution: $CRON_DESC"
echo ""
echo "Useful commands:"
echo "  • View cron jobs:        crontab -l"
echo "  • Remove cron job:       crontab -e (delete the line)"
echo "  • View logs:             tail -f $LOG_FILE"
echo "  • Manual execution:      curl -fsSL $SCRIPT_URL | bash"
echo "  • Manual dry-run:        curl -fsSL $SCRIPT_URL | bash -s -- --dry-run"
echo ""
