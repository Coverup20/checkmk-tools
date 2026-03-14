#!/bin/bash
# diagnose-auto-git-sync.sh - Diagnostica servizio auto-git-sync
# Verifica stato servizio, logs, e configurazione

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RESET='\033[0m'

print_header() {
  echo -e "\n${CYAN}=== $1 ===${RESET}\n"
}

print_ok() {
  echo -e "${GREEN}✓${RESET} $1"
}

print_error() {
  echo -e "${RED}✗${RESET} $1"
}

print_warning() {
  echo -e "${YELLOW}⚠${RESET} $1"
}

print_header "AUTO-GIT-SYNC DIAGNOSTICS"

# Check if service exists
if systemctl list-unit-files | grep -q "auto-git-sync.service"; then
  print_ok "Service file exists"
else
  print_error "Service file NOT found"
  exit 1
fi

# Check service status
print_header "SERVICE STATUS"
if systemctl is-active --quiet auto-git-sync.service; then
  print_ok "Service is ACTIVE"
else
  print_error "Service is NOT ACTIVE"
  echo ""
  systemctl status auto-git-sync.service --no-pager
fi

# Check if enabled
if systemctl is-enabled --quiet auto-git-sync.service; then
  print_ok "Service is ENABLED (auto-start)"
else
  print_warning "Service is NOT enabled"
fi

# Show service configuration
print_header "SERVICE CONFIGURATION"
systemctl cat auto-git-sync.service

# Show recent logs
print_header "RECENT LOGS (last 50 lines)"
journalctl -u auto-git-sync.service -n 50 --no-pager

# Check repository
print_header "REPOSITORY STATUS"
if [[ -d "/opt/checkmk-tools" ]]; then
  print_ok "Repository directory exists"
  cd /opt/checkmk-tools
  
  echo ""
  git status --short
  echo ""
  
  print_header "LAST 5 COMMITS"
  git log --oneline -5
  
  print_header "LAST GIT PULL"
  git log --grep="Merge" -1 --format="%ci %s" || echo "No recent pulls found"
else
  print_error "Repository directory NOT found"
fi

print_header "DIAGNOSTICS COMPLETE"
