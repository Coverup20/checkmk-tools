#!/usr/bin/env bash
# test-vm.sh - Automated testing suite for CheckMK Installer
# Tests all installation scenarios in VM environment

set -euo pipefail

TEST_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALLER_ROOT="$(dirname "$TEST_ROOT")"

# Source utilities
source "${INSTALLER_ROOT}/utils/colors.sh"
source "${INSTALLER_ROOT}/utils/logger.sh"

# Test configuration
TEST_LOG="/tmp/checkmk-installer-test.log"
TEST_RESULTS="/tmp/test-results.json"
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

# Initialize logging
init_logging
LOG_FILE="$TEST_LOG"

#############################################
# Test framework functions
#############################################
test_start() {
  local test_name="$1"
  ((TOTAL_TESTS++))
  log_info "TEST START: $test_name"
  echo -n "  Testing: $test_name... "
}

test_pass() {
  ((PASSED_TESTS++))
  print_success "PASS"
  log_success "TEST PASS"
}

test_fail() {
  local reason="$1"
  ((FAILED_TESTS++))
  print_error "FAIL"
  log_error "TEST FAIL: $reason"
}

test_skip() {
  local reason="$1"
  print_warning "SKIP: $reason"
  log_warning "TEST SKIP: $reason"
}

#############################################
# Pre-flight checks
#############################################
test_preflight() {
  print_header "Pre-flight Checks"
  
  test_start "Running as root"
  if [[ $EUID -eq 0 ]]; then
    test_pass
  else
    test_fail "Not running as root"
    return 1
  fi
  
  test_start "Installer directory exists"
  if [[ -d "$INSTALLER_ROOT" ]]; then
    test_pass
  else
    test_fail "Installer directory not found"
    return 1
  fi
  
  test_start "Scripts are executable"
  if [[ -x "${INSTALLER_ROOT}/installer.sh" ]]; then
    test_pass
  else
    test_fail "installer.sh not executable"
    return 1
  fi
  
  test_start "Minimum disk space (5GB)"
  local available=$(df / | awk 'NR==2 {print $4}')
  if [[ $available -gt 5000000 ]]; then
    test_pass
  else
    test_fail "Insufficient disk space"
  fi
  
  test_start "Minimum memory (1.5GB)"
  local mem_kb=$(grep MemTotal /proc/meminfo | awk '{print $2}')
  if [[ $mem_kb -gt 1500000 ]]; then
    test_pass
  else
    test_fail "Insufficient memory"
  fi
}

#############################################
# Test configuration wizard
#############################################
test_config_wizard() {
  print_header "Configuration Wizard Tests"
  
  test_start "Config wizard exists"
  if [[ -f "${INSTALLER_ROOT}/config-wizard.sh" ]]; then
    test_pass
  else
    test_fail "config-wizard.sh not found"
    return 1
  fi
  
  test_start "Config template exists"
  if [[ -f "${INSTALLER_ROOT}/.env.template" ]]; then
    test_pass
  else
    test_fail ".env.template not found"
  fi
  
  test_start "Create test configuration"
  if cp "${INSTALLER_ROOT}/.env.template" "${INSTALLER_ROOT}/.env"; then
    test_pass
  else
    test_fail "Failed to create .env"
    return 1
  fi
  
  test_start "Load configuration"
  if source "${INSTALLER_ROOT}/.env" 2>/dev/null; then
    test_pass
  else
    test_fail "Failed to load .env"
  fi
}

#############################################
# Test system base module
#############################################
test_system_base() {
  print_header "System Base Module Tests"
  
  test_start "System base module exists"
  if [[ -f "${INSTALLER_ROOT}/modules/01-system-base.sh" ]]; then
    test_pass
  else
    test_fail "Module not found"
    return 1
  fi
  
  test_start "Execute system base module"
  if bash "${INSTALLER_ROOT}/modules/01-system-base.sh" >> "$TEST_LOG" 2>&1; then
    test_pass
  else
    test_fail "Module execution failed"
    return 1
  fi
  
  test_start "SSH service running"
  if systemctl is-active --quiet sshd || systemctl is-active --quiet ssh; then
    test_pass
  else
    test_fail "SSH not running"
  fi
  
  test_start "UFW firewall active"
  if systemctl is-active --quiet ufw; then
    test_pass
  else
    test_fail "UFW not active"
  fi
  
  test_start "Fail2Ban running"
  if systemctl is-active --quiet fail2ban; then
    test_pass
  else
    test_fail "Fail2Ban not running"
  fi
}

#############################################
# Test CheckMK agent module
#############################################
test_checkmk_agent() {
  print_header "CheckMK Agent Module Tests"
  
  test_start "Agent module exists"
  if [[ -f "${INSTALLER_ROOT}/modules/03-checkmk-agent.sh" ]]; then
    test_pass
  else
    test_fail "Module not found"
    return 1
  fi
  
  # Skip if no agent available
  if [[ ! -f "${INSTALLER_ROOT}/scripts/Install/Agent-FRPC/check-mk-agent.deb" ]]; then
    test_skip "Agent package not available"
    return 0
  fi
  
  test_start "Execute agent module"
  if bash "${INSTALLER_ROOT}/modules/03-checkmk-agent.sh" >> "$TEST_LOG" 2>&1; then
    test_pass
  else
    test_fail "Module execution failed"
    return 1
  fi
  
  test_start "Agent binary installed"
  if [[ -f "/usr/bin/check_mk_agent" ]]; then
    test_pass
  else
    test_fail "Agent binary not found"
  fi
  
  test_start "Agent socket listening"
  if ss -tlnp | grep -q ":6556"; then
    test_pass
  else
    test_fail "Agent not listening on port 6556"
  fi
  
  test_start "Agent responds to queries"
  if timeout 5 telnet localhost 6556 </dev/null 2>/dev/null | grep -q "<<<check_mk>>>"; then
    test_pass
  else
    test_fail "Agent not responding"
  fi
}

#############################################
# Test scripts deployment module
#############################################
test_scripts_deploy() {
  print_header "Scripts Deployment Module Tests"
  
  test_start "Scripts deploy module exists"
  if [[ -f "${INSTALLER_ROOT}/modules/04-scripts-deploy.sh" ]]; then
    test_pass
  else
    test_fail "Module not found"
    return 1
  fi
  
  test_start "Scripts source directory exists"
  if [[ -d "${INSTALLER_ROOT}/scripts" ]]; then
    test_pass
  else
    test_fail "Scripts directory not found"
    return 1
  fi
  
  test_start "Execute scripts deploy module"
  if bash "${INSTALLER_ROOT}/modules/04-scripts-deploy.sh" >> "$TEST_LOG" 2>&1; then
    test_pass
  else
    test_fail "Module execution failed"
    return 1
  fi
  
  test_start "Notification scripts deployed"
  if [[ -d "/opt/script-notify-checkmk" ]]; then
    test_pass
  else
    test_fail "Notification scripts not deployed"
  fi
  
  test_start "Tool scripts deployed"
  if [[ -d "/opt/script-tools" ]]; then
    test_pass
  else
    test_fail "Tool scripts not deployed"
  fi
  
  test_start "Update script created"
  if [[ -f "/usr/local/bin/update-checkmk-scripts" ]]; then
    test_pass
  else
    test_fail "Update script not found"
  fi
}

#############################################
# Test Ydea toolkit module
#############################################
test_ydea_toolkit() {
  print_header "Ydea Toolkit Module Tests"
  
  test_start "Ydea module exists"
  if [[ -f "${INSTALLER_ROOT}/modules/05-ydea-toolkit.sh" ]]; then
    test_pass
  else
    test_fail "Module not found"
    return 1
  fi
  
  test_start "Execute Ydea module"
  if bash "${INSTALLER_ROOT}/modules/05-ydea-toolkit.sh" >> "$TEST_LOG" 2>&1; then
    test_pass
  else
    test_fail "Module execution failed"
    return 1
  fi
  
  test_start "Ydea toolkit installed"
  if [[ -f "/usr/local/bin/ydea-toolkit" ]]; then
    test_pass
  else
    test_fail "Toolkit not installed"
  fi
  
  test_start "Ydea toolkit executable"
  if [[ -x "/opt/ydea-toolkit/ydea-toolkit.sh" ]]; then
    test_pass
  else
    test_fail "Toolkit not executable"
  fi
  
  test_start "Tracking file initialized"
  if [[ -f "/var/log/ydea-tickets-tracking.json" ]]; then
    test_pass
  else
    test_fail "Tracking file not created"
  fi
}

#############################################
# Generate test report
#############################################
generate_report() {
  print_header "Test Results Summary"
  
  local pass_rate=0
  if [[ $TOTAL_TESTS -gt 0 ]]; then
    pass_rate=$((PASSED_TESTS * 100 / TOTAL_TESTS))
  fi
  
  echo ""
  echo "Total Tests: $TOTAL_TESTS"
  echo ""
  print_success "Passed: $PASSED_TESTS"
  print_error "Failed: $FAILED_TESTS"
  echo ""
  echo "Pass Rate: ${pass_rate}%"
  echo ""
  
  # Generate JSON report
  cat > "$TEST_RESULTS" <<EOF
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "total_tests": $TOTAL_TESTS,
  "passed": $PASSED_TESTS,
  "failed": $FAILED_TESTS,
  "pass_rate": $pass_rate,
  "log_file": "$TEST_LOG"
}
EOF
  
  print_info "Detailed log: $TEST_LOG"
  print_info "JSON report: $TEST_RESULTS"
  echo ""
  
  # Exit code
  if [[ $FAILED_TESTS -eq 0 ]]; then
    print_success "ALL TESTS PASSED! ✅"
    return 0
  else
    print_error "SOME TESTS FAILED ❌"
    return 1
  fi
}

#############################################
# Main test execution
#############################################
main() {
  clear
  print_header "CheckMK Installer Test Suite"
  echo ""
  print_info "Starting automated tests..."
  echo ""
  
  # Run test suites
  test_preflight || { print_error "Pre-flight checks failed"; exit 1; }
  test_config_wizard
  test_system_base
  test_checkmk_agent
  test_scripts_deploy
  test_ydea_toolkit
  
  # Generate report
  echo ""
  generate_report
}

# Run tests
main "$@"
