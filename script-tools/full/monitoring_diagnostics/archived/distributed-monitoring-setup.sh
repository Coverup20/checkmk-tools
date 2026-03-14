#!/bin/bash
# distributed-monitoring-setup.sh - Setup distributed monitoring CheckMK
# Configura un sito CheckMK come distributed monitoring slave

set -euo pipefail

# Colori
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

# Configurazione
SITE="${1:-monitoring}"
MASTER_URL="${2:-}"
MASTER_USER="${3:-automation}"
MASTER_SECRET="${4:-}"

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

print_info() {
  echo -e "${CYAN}ℹ${RESET} $1"
}

# Usage
if [[ -z "$MASTER_URL" ]]; then
  echo "Usage: $0 <site_name> <master_url> <automation_user> <automation_secret>"
  echo ""
  echo "Example:"
  echo "  $0 monitoring https://master.example.com/monitoring automation SECRET123"
  exit 1
fi

print_header "DISTRIBUTED MONITORING SETUP"

# Check if site exists
print_step "Checking site '$SITE'..."

if ! omd sites | grep -q "^$SITE"; then
  print_error "Site '$SITE' not found"
  exit 1
fi

print_success "Site found"

# Configure distributed monitoring
print_step "Configuring distributed monitoring..."

# Create automation user configuration
MULTISITE_CONFIG="/omd/sites/$SITE/etc/check_mk/multisite.d/distributed.mk"

sudo -u "$SITE" bash -c "cat > '$MULTISITE_CONFIG' <<'EOF'
# Distributed Monitoring Configuration
sites.update({
    'master': {
        'alias': 'Master Site',
        'socket': ('tcp', {
            'address': ('$MASTER_URL', 6557),
            'tls': ('encrypted', {
                'verify': True
            }),
        }),
        'url_prefix': '/$SITE/',
        'status_host': None,
        'user_sync': 'all',
        'replication': 'slave',
        'multisiteurl': '$MASTER_URL',
        'user_login': True,
        'secret': '$MASTER_SECRET',
        'customer': None,
        'proxy': None,
    }
})
EOF
"

print_success "Configuration created"

# Reload CheckMK
print_step "Reloading CheckMK configuration..."

if sudo -u "$SITE" bash -c "omd reload"; then
  print_success "CheckMK reloaded"
else
  print_error "Failed to reload CheckMK"
  exit 1
fi

# Test connection
print_step "Testing connection to master..."

if sudo -u "$SITE" bash -c "cmk --automation get-agent-output $MASTER_USER" >/dev/null 2>&1; then
  print_success "Connection successful"
else
  print_error "Connection failed - check URL, user and secret"
  exit 1
fi

print_header "✓ SETUP COMPLETE"

echo "Next steps:"
echo "1. Add this site as slave on master"
echo "2. Configure replication rules on master"
echo "3. Push configuration from master"
