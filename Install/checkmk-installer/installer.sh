#!/usr/bin/env bash
# installer.sh - CheckMK Installer Main Menu
# Interactive installation system for CheckMK and monitoring tools

set -euo pipefail

# Script directory
INSTALLER_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source utilities
source "${INSTALLER_ROOT}/utils/colors.sh"
source "${INSTALLER_ROOT}/utils/logger.sh"
source "${INSTALLER_ROOT}/utils/menu.sh"
source "${INSTALLER_ROOT}/utils/validate.sh"

# Initialize logging
init_logging

# Check if running as root
if [[ $EUID -ne 0 ]]; then
  print_error "This installer must be run as root"
  echo "Please run: sudo $0"
  exit 1
fi

#############################################
# Load configuration
#############################################
load_configuration() {
  if [[ -f "${INSTALLER_ROOT}/.env" ]]; then
    set -a
    source "${INSTALLER_ROOT}/.env"
    set +a
    log_debug "Configuration loaded from .env"
    return 0
  else
    log_warning "Configuration file not found"
    return 1
  fi
}

#############################################
# Installation profiles
#############################################
install_full_server() {
  log_info "Starting FULL SERVER installation..."
  
  print_header "Full Server Installation"
  echo "This will install:"
  echo "  • System Base (SSH, Firewall, NTP, etc.)"
  echo "  • CheckMK Server"
  echo "  • Monitoring Scripts"
  echo "  • Ydea Toolkit"
  echo "  • FRPC Client"
  echo ""
  
  if ! confirm "Proceed with full server installation?" "n"; then
    log_info "Installation cancelled by user"
    return 0
  fi
  
  # Execute modules in order
  bash "${INSTALLER_ROOT}/modules/01-system-base.sh" || { log_error "System base failed"; return 1; }
  bash "${INSTALLER_ROOT}/modules/02-checkmk-server.sh" || { log_error "CheckMK server failed"; return 1; }
  bash "${INSTALLER_ROOT}/modules/04-scripts-deploy.sh" || { log_error "Scripts deployment failed"; return 1; }
  bash "${INSTALLER_ROOT}/modules/05-ydea-toolkit.sh" || { log_error "Ydea toolkit failed"; return 1; }
  bash "${INSTALLER_ROOT}/modules/06-frps-setup.sh" || { log_error "FRPS setup failed"; return 1; }
  
  print_separator "="
  print_success "FULL SERVER INSTALLATION COMPLETED!"
  print_separator "="
  
  press_any_key
}

install_client_agent() {
  log_info "Starting CLIENT AGENT installation..."
  
  print_header "Client Agent Installation"
  echo "This will install:"
  echo "  • System Base (SSH, Firewall, NTP, etc.)"
  echo "  • CheckMK Agent"
  echo "  • Monitoring Scripts (local checks)"
  echo "  • FRPC Client"
  echo ""
  
  if ! confirm "Proceed with client agent installation?" "n"; then
    log_info "Installation cancelled by user"
    return 0
  fi
  
  # Execute modules
  bash "${INSTALLER_ROOT}/modules/01-system-base.sh" || { log_error "System base failed"; return 1; }
  bash "${INSTALLER_ROOT}/modules/03-checkmk-agent.sh" || { log_error "CheckMK agent failed"; return 1; }
  bash "${INSTALLER_ROOT}/modules/04-scripts-deploy.sh" || { log_error "Scripts deployment failed"; return 1; }
  bash "${INSTALLER_ROOT}/modules/06-frpc-setup.sh" || { log_error "FRPC client setup failed"; return 1; }
  
  print_separator "="
  print_success "CLIENT AGENT INSTALLATION COMPLETED!"
  print_separator "="
  
  press_any_key
}

install_scripts_only() {
  log_info "Starting SCRIPTS ONLY deployment..."
  
  print_header "Scripts Deployment"
  echo "This will deploy all monitoring scripts without installing CheckMK"
  echo ""
  
  if ! confirm "Proceed with scripts deployment?" "y"; then
    log_info "Deployment cancelled by user"
    return 0
  fi
  
  bash "${INSTALLER_ROOT}/modules/04-scripts-deploy.sh" || { log_error "Scripts deployment failed"; return 1; }
  
  print_success "SCRIPTS DEPLOYMENT COMPLETED!"
  press_any_key
}

install_ydea_only() {
  log_info "Starting YDEA TOOLKIT installation..."
  
  print_header "Ydea Toolkit Installation"
  echo "This will install and configure the Ydea Cloud API toolkit"
  echo ""
  
  if ! confirm "Proceed with Ydea toolkit installation?" "y"; then
    log_info "Installation cancelled by user"
    return 0
  fi
  
  bash "${INSTALLER_ROOT}/modules/05-ydea-toolkit.sh" || { log_error "Ydea toolkit failed"; return 1; }
  
  print_success "YDEA TOOLKIT INSTALLATION COMPLETED!"
  press_any_key
}

install_custom() {
  log_info "Starting CUSTOM installation..."
  
  print_header "Custom Installation"
  echo "Select the modules you want to install:"
  echo ""
  
  local modules=(
    "System Base (SSH, Firewall, NTP)"
    "CheckMK Server"
    "CheckMK Agent (Client)"
    "Monitoring Scripts"
    "Ydea Toolkit"
    "FRPS Server"
  )
  
  local selected=$(multi_select "Select modules to install" "${modules[@]}")
  
  if [[ -z "$selected" ]]; then
    log_info "No modules selected"
    return 0
  fi
  
  echo ""
  if ! confirm "Install selected modules?" "n"; then
    log_info "Installation cancelled by user"
    return 0
  fi
  
  # Install selected modules
  for idx in $selected; do
    local module_num=$((idx + 1))
    local module_script=""
    
    case $module_num in
      1) module_script="01-system-base.sh" ;;
      2) module_script="02-checkmk-server.sh" ;;
      3) module_script="03-checkmk-agent.sh" ;;
      4) module_script="04-scripts-deploy.sh" ;;
      5) module_script="05-ydea-toolkit.sh" ;;
      6) module_script="06-frps-setup.sh" ;;
    esac
    
    if [[ -n "$module_script" ]]; then
      log_info "Installing module: $module_script"
      bash "${INSTALLER_ROOT}/modules/$module_script" || log_error "Module $module_script failed"
    fi
  done
  
  print_success "CUSTOM INSTALLATION COMPLETED!"
  press_any_key
}

update_scripts_local() {
  log_info "Updating scripts from local repository..."
  
  print_header "Update Scripts (Local)"
  echo "This will update all scripts from the local repository"
  echo ""
  
  if ! confirm "Proceed with update?" "y"; then
    return 0
  fi
  
  bash "${INSTALLER_ROOT}/modules/04-scripts-deploy.sh" || { log_error "Update failed"; return 1; }
  
  print_success "Scripts updated successfully!"
  press_any_key
}

update_scripts_github() {
  log_info "Updating scripts from GitHub..."
  
  print_header "Update Scripts (GitHub)"
  
  local repo_url="https://github.com/Coverup20/checkmk-tools.git"
  local local_repo="/tmp/checkmk-tools"
  
  echo "This will:"
  echo "  1. Clone/pull repository from GitHub"
  echo "  2. Update all scripts to latest version"
  echo ""
  
  if ! confirm "Proceed with update from GitHub?" "y"; then
    return 0
  fi
  
  # Clone or update repository
  if [[ -d "$local_repo" ]]; then
    log_info "Updating existing repository..."
    cd "$local_repo"
    git pull origin main
  else
    log_info "Cloning repository..."
    git clone "$repo_url" "$local_repo"
  fi
  
  # Copy scripts
  log_info "Copying updated scripts..."
  cp -r "$local_repo"/* "${INSTALLER_ROOT}/scripts/" 2>/dev/null || true
  
  # Deploy
  bash "${INSTALLER_ROOT}/modules/04-scripts-deploy.sh" || { log_error "Deployment failed"; return 1; }
  
  print_success "Scripts updated from GitHub successfully!"
  press_any_key
}

run_config_wizard() {
  log_info "Running configuration wizard..."
  
  if [[ -f "${INSTALLER_ROOT}/config-wizard.sh" ]]; then
    bash "${INSTALLER_ROOT}/config-wizard.sh"
  else
    print_error "Configuration wizard not found"
  fi
  
  press_any_key
}

show_current_config() {
  print_header "Current Configuration"
  
  if load_configuration; then
    echo ""
    echo "${CYAN}System Configuration:${NC}"
    echo "  SSH Port: ${SSH_PORT:-22}"
    echo "  Timezone: ${TIMEZONE:-UTC}"
    echo "  Root Login: ${PERMIT_ROOT_LOGIN:-no}"
    echo ""
    
    if [[ -n "${CHECKMK_SITE_NAME:-}" ]]; then
      echo "${CYAN}CheckMK Configuration:${NC}"
      echo "  Site Name: ${CHECKMK_SITE_NAME}"
      echo "  HTTP Port: ${CHECKMK_HTTP_PORT:-5000}"
      echo "  Server: ${CHECKMK_SERVER:-N/A}"
      echo ""
    fi
    
    if [[ -n "${YDEA_ID:-}" ]]; then
      echo "${CYAN}Ydea Configuration:${NC}"
      echo "  Ydea ID: ${YDEA_ID}"
      echo "  User ID: ${YDEA_USER_ID_CREATE_TICKET:-N/A}"
      echo ""
    fi
    
    if [[ -n "${FRPC_SERVER_ADDR:-}" ]]; then
      echo "${CYAN}FRPC Configuration:${NC}"
      echo "  Server: ${FRPC_SERVER_ADDR}:${FRPC_SERVER_PORT:-7000}"
      echo "  Remote Port: ${FRPC_REMOTE_PORT:-N/A}"
      echo ""
    fi
  else
    echo ""
    print_warning "No configuration file found"
    echo ""
    echo "Run 'Configuration Guidata' to create configuration"
  fi
  
  echo ""
  press_any_key
}

run_complete_cleanup() {
  log_info "Running complete cleanup..."
  
  print_header "Complete Cleanup"
  
  print_color "$RED" "
╔════════════════════════════════════════════════════════════════╗
║                         WARNING!                               ║
║                                                                ║
║  This will COMPLETELY REMOVE all installed components:        ║
║    • CheckMK Server (site: monitoring)                        ║
║    • CheckMK Agent                                            ║
║    • FRPS/FRPC Server                                         ║
║    • All monitoring scripts                                   ║
║    • Ydea Toolkit                                             ║
║    • Configuration files                                      ║
║                                                                ║
║  Firewall rules will be preserved.                            ║
║                                                                ║
╚════════════════════════════════════════════════════════════════╝
"
  
  echo ""
  if ! confirm "Are you ABSOLUTELY SURE you want to remove everything?" "n"; then
    log_info "Cleanup cancelled by user"
    return 0
  fi
  
  echo ""
  print_warning "Last chance to cancel!"
  if ! confirm "Type YES to confirm complete removal" "n"; then
    log_info "Cleanup cancelled by user"
    return 0
  fi
  
  if [[ -f "${INSTALLER_ROOT}/testing/cleanup-full.sh" ]]; then
    bash "${INSTALLER_ROOT}/testing/cleanup-full.sh" || { log_error "Cleanup failed"; return 1; }
  else
    print_error "Cleanup script not found at ${INSTALLER_ROOT}/testing/cleanup-full.sh"
    return 1
  fi
  
  print_success "COMPLETE CLEANUP FINISHED!"
  press_any_key
}

#############################################
# Main menu loop
#############################################
main_menu() {
  while true; do
    show_main_menu
    
    case $MENU_SELECTION in
      1)
        install_full_server
        ;;
      2)
        install_client_agent
        ;;
      3)
        install_scripts_only
        ;;
      4)
        install_ydea_only
        ;;
      5)
        install_custom
        ;;
      6)
        update_scripts_local
        ;;
      7)
        update_scripts_github
        ;;
      8)
        run_config_wizard
        ;;
      9)
        show_current_config
        ;;
      10)
        run_complete_cleanup
        ;;
      11)
        log_info "Exiting installer"
        print_info "Goodbye!"
        exit 0
        ;;
      *)
        print_error "Invalid selection"
        sleep 1
        ;;
    esac
  done
}

#############################################
# Welcome screen
#############################################
show_welcome() {
  clear
  
  print_color "$CYAN" "
╔════════════════════════════════════════════════════════════════╗
║                                                                ║
║         ███████╗██╗  ██╗███████╗ ██████╗██╗  ██╗███╗   ███╗  ║
║         ██╔════╝██║  ██║██╔════╝██╔════╝██║ ██╔╝████╗ ████║  ║
║         ██║     ███████║█████╗  ██║     █████╔╝ ██╔████╔██║  ║
║         ██║     ██╔══██║██╔══╝  ██║     ██╔═██╗ ██║╚██╔╝██║  ║
║         ███████╗██║  ██║███████╗╚██████╗██║  ██╗██║ ╚═╝ ██║  ║
║         ╚══════╝╚═╝  ╚═╝╚══════╝ ╚═════╝╚═╝  ╚═╝╚═╝     ╚═╝  ║
║                                                                ║
║              CheckMK Installer & Toolkit v1.0                 ║
║                   Complete Installation Suite                 ║
║                                                                ║
╚════════════════════════════════════════════════════════════════╝
"
  
  echo ""
  print_info "Welcome to the CheckMK Installer!"
  echo ""
  echo "This installer will help you set up:"
  echo "  ${SYMBOL_SERVER} CheckMK Monitoring Server"
  echo "  ${SYMBOL_CLIENT} CheckMK Agent (Client)"
  echo "  ${SYMBOL_SCRIPT} Monitoring Scripts"
  echo "  ${SYMBOL_TICKET} Ydea Cloud Toolkit"
  echo "  ${SYMBOL_NETWORK} FRPC Client"
  echo ""
  
  # System requirements check
  if ! validate_system_requirements; then
    print_error "System requirements check failed"
    if ! confirm "Continue anyway?" "n"; then
      exit 1
    fi
  fi
  
  echo ""
  press_any_key "Press any key to continue..."
}

#############################################
# Main execution
#############################################
main() {
  # Show welcome screen
  show_welcome
  
  # Try to load configuration
  load_configuration || log_warning "No configuration loaded"
  
  # Start main menu loop
  main_menu
}

# Handle interrupts gracefully
trap 'echo ""; print_warning "Installation interrupted"; exit 130' INT TERM

# Run main function
main "$@"
