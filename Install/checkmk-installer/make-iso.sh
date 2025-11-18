#!/usr/bin/env bash
# make-iso.sh - Create bootable ISO with CheckMK installer
# Generates a custom Ubuntu 24.04 ISO with the installer pre-loaded

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source utilities
source "${SCRIPT_DIR}/utils/colors.sh"
source "${SCRIPT_DIR}/utils/logger.sh"

# Configuration
ISO_NAME="checkmk-installer-v1.0-amd64.iso"
ISO_OUTPUT_DIR="${SCRIPT_DIR}/iso-output"
WORK_DIR="/tmp/checkmk-iso-build"
UBUNTU_VERSION="24.04"
UBUNTU_ISO_URL="https://releases.ubuntu.com/${UBUNTU_VERSION}/ubuntu-${UBUNTU_VERSION}-live-server-amd64.iso"
UBUNTU_ISO_NAME="ubuntu-${UBUNTU_VERSION}-live-server-amd64.iso"

init_logging

print_header "CheckMK Installer ISO Builder"

#############################################
# Check dependencies
#############################################
check_dependencies() {
  log_info "Checking dependencies..."
  
  local deps=("wget" "xorriso" "isolinux" "squashfs-tools" "genisoimage")
  local missing=()
  
  for dep in "${deps[@]}"; do
    if ! command -v "$dep" &>/dev/null; then
      missing+=("$dep")
    fi
  done
  
  if [[ ${#missing[@]} -gt 0 ]]; then
    log_error "Missing dependencies: ${missing[*]}"
    log_info "Install with: sudo apt-get install xorriso isolinux squashfs-tools genisoimage wget"
    return 1
  fi
  
  log_success "All dependencies installed"
}

#############################################
# Download Ubuntu ISO
#############################################
download_ubuntu_iso() {
  local iso_cache="${SCRIPT_DIR}/${UBUNTU_ISO_NAME}"
  
  if [[ -f "$iso_cache" ]]; then
    log_info "Using cached Ubuntu ISO"
    echo "$iso_cache"
    return 0
  fi
  
  log_info "Downloading Ubuntu ${UBUNTU_VERSION} ISO..."
  log_warning "This may take several minutes (~2.5GB download)"
  
  if ! wget -O "$iso_cache" "$UBUNTU_ISO_URL"; then
    log_error "Failed to download Ubuntu ISO"
    return 1
  fi
  
  log_success "Ubuntu ISO downloaded"
  echo "$iso_cache"
}

#############################################
# Extract Ubuntu ISO
#############################################
extract_iso() {
  local iso_file="$1"
  local extract_dir="$2"
  
  log_info "Extracting Ubuntu ISO..."
  
  mkdir -p "$extract_dir"
  
  # Mount ISO
  local mount_point="${WORK_DIR}/mnt"
  mkdir -p "$mount_point"
  
  if ! mount -o loop "$iso_file" "$mount_point" 2>/dev/null; then
    log_error "Failed to mount ISO (need root privileges)"
    return 1
  fi
  
  # Copy contents
  log_info "Copying ISO contents..."
  rsync -a "$mount_point/" "$extract_dir/"
  
  # Unmount
  umount "$mount_point"
  rmdir "$mount_point"
  
  log_success "ISO extracted"
}

#############################################
# Add installer to ISO
#############################################
add_installer_to_iso() {
  local iso_root="$1"
  
  log_info "Adding CheckMK installer to ISO..."
  
  # Create installer directory
  local installer_dir="${iso_root}/checkmk-installer"
  mkdir -p "$installer_dir"
  
  # Copy installer files
  log_info "Copying installer files..."
  rsync -a --exclude='iso-output' --exclude='.git' --exclude='*.iso' \
    "${SCRIPT_DIR}/" "$installer_dir/"
  
  # Make scripts executable
  find "$installer_dir" -type f -name "*.sh" -exec chmod +x {} \;
  
  log_success "Installer added to ISO"
}

#############################################
# Create autostart script
#############################################
create_autostart() {
  local iso_root="$1"
  
  log_info "Creating autostart configuration..."
  
  # Create autostart script
  cat > "${iso_root}/autostart.sh" <<'EOF'
#!/bin/bash
# CheckMK Installer Autostart

clear
echo "=========================================="
echo "  CheckMK Installer"
echo "  Bootable Installation System"
echo "=========================================="
echo ""
echo "The installer is located at:"
echo "  /cdrom/checkmk-installer/"
echo ""
echo "To start the installation, run:"
echo "  cd /cdrom/checkmk-installer"
echo "  sudo ./installer.sh"
echo ""
echo "Or copy to local system:"
echo "  cp -r /cdrom/checkmk-installer ~/"
echo "  cd ~/checkmk-installer"
echo "  sudo ./installer.sh"
echo ""
EOF
  
  chmod +x "${iso_root}/autostart.sh"
  
  # Add to boot message
  if [[ -f "${iso_root}/isolinux/txt.cfg" ]]; then
    sed -i '1i default live\nlabel live\n  menu label ^Start Ubuntu with CheckMK Installer\n  kernel /casper/vmlinuz\n  append  file=/cdrom/preseed/ubuntu.seed boot=casper initrd=/casper/initrd quiet splash ---\n' \
      "${iso_root}/isolinux/txt.cfg"
  fi
  
  log_success "Autostart configured"
}

#############################################
# Create preseed for automation
#############################################
create_preseed() {
  local iso_root="$1"
  
  log_info "Creating preseed configuration..."
  
  mkdir -p "${iso_root}/preseed"
  
  cat > "${iso_root}/preseed/checkmk-installer.seed" <<'EOF'
# CheckMK Installer Preseed
# Minimal automated installation

# Locale
d-i debian-installer/locale string en_US.UTF-8
d-i keyboard-configuration/xkb-keymap select us

# Network
d-i netcfg/choose_interface select auto
d-i netcfg/get_hostname string checkmk-installer

# User
d-i passwd/user-fullname string CheckMK Admin
d-i passwd/username string admin
d-i passwd/user-password password installer
d-i passwd/user-password-again password installer

# Partitioning
d-i partman-auto/method string regular
d-i partman-auto/choose_recipe select atomic

# Package selection
tasksel tasksel/first multiselect standard
d-i pkgsel/include string openssh-server

# Boot loader
d-i grub-installer/only_debian boolean true

# Finish
d-i finish-install/reboot_in_progress note

# Late command - copy installer
d-i preseed/late_command string \
  cp -r /cdrom/checkmk-installer /target/root/; \
  in-target chown -R root:root /root/checkmk-installer; \
  in-target chmod +x /root/checkmk-installer/*.sh; \
  echo "CheckMK Installer copied to /root/checkmk-installer" > /target/root/INSTALLER_README.txt
EOF
  
  log_success "Preseed created"
}

#############################################
# Update boot menu
#############################################
update_boot_menu() {
  local iso_root="$1"
  
  log_info "Updating boot menu..."
  
  # Update grub.cfg for UEFI
  if [[ -f "${iso_root}/boot/grub/grub.cfg" ]]; then
    cat > "${iso_root}/boot/grub/grub.cfg" <<'EOF'
set timeout=10
set default=0

menuentry "Install Ubuntu with CheckMK Installer" {
    set gfxpayload=keep
    linux   /casper/vmlinuz file=/cdrom/preseed/checkmk-installer.seed boot=casper automatic-ubiquity quiet splash ---
    initrd  /casper/initrd
}

menuentry "Try Ubuntu (with installer available)" {
    set gfxpayload=keep
    linux   /casper/vmlinuz boot=casper quiet splash ---
    initrd  /casper/initrd
}

menuentry "Boot from local disk" {
    exit
}
EOF
  fi
  
  log_success "Boot menu updated"
}

#############################################
# Build ISO
#############################################
build_iso() {
  local iso_root="$1"
  local output_iso="$2"
  
  log_info "Building ISO image..."
  log_info "This may take several minutes..."
  
  # Create output directory
  mkdir -p "$(dirname "$output_iso")"
  
  # Build ISO with xorriso
  if ! xorriso -as mkisofs \
    -r -V "CheckMK Installer" \
    -o "$output_iso" \
    -J -joliet-long \
    -b isolinux/isolinux.bin \
    -c isolinux/boot.cat \
    -no-emul-boot \
    -boot-load-size 4 \
    -boot-info-table \
    -eltorito-alt-boot \
    -e boot/grub/efi.img \
    -no-emul-boot \
    -isohybrid-gpt-basdat \
    -isohybrid-apm-hfsplus \
    "$iso_root" 2>&1 | tee -a "$LOG_FILE"; then
    log_error "Failed to build ISO"
    return 1
  fi
  
  log_success "ISO built successfully"
}

#############################################
# Make ISO hybrid (USB bootable)
#############################################
make_hybrid() {
  local iso_file="$1"
  
  log_info "Making ISO hybrid (USB bootable)..."
  
  if command -v isohybrid &>/dev/null; then
    isohybrid --uefi "$iso_file" 2>&1 | tee -a "$LOG_FILE" || true
    log_success "ISO is now hybrid (can boot from USB)"
  else
    log_warning "isohybrid not found, ISO may not boot from USB"
  fi
}

#############################################
# Calculate checksums
#############################################
calculate_checksums() {
  local iso_file="$1"
  
  log_info "Calculating checksums..."
  
  local md5sum_file="${iso_file}.md5"
  local sha256sum_file="${iso_file}.sha256"
  
  md5sum "$iso_file" > "$md5sum_file"
  sha256sum "$iso_file" > "$sha256sum_file"
  
  log_success "Checksums calculated"
  echo "  MD5: $(cat "$md5sum_file")"
  echo "  SHA256: $(cat "$sha256sum_file")"
}

#############################################
# Display final information
#############################################
display_final_info() {
  local iso_file="$1"
  local iso_size=$(du -h "$iso_file" | cut -f1)
  
  print_separator "="
  echo ""
  display_box "ISO Build Complete!" \
    "" \
    "ISO File: $iso_file" \
    "Size: $iso_size" \
    "" \
    "Write to USB:" \
    "  Linux: sudo dd if=$iso_file of=/dev/sdX bs=4M status=progress" \
    "  Windows: Use Rufus or Etcher" \
    "  Mac: sudo dd if=$iso_file of=/dev/diskX bs=4m" \
    "" \
    "Boot from USB and run:" \
    "  cd /cdrom/checkmk-installer" \
    "  sudo ./installer.sh" \
    "" \
    "Or copy to installed system:" \
    "  cp -r /cdrom/checkmk-installer ~/" \
    "  cd ~/checkmk-installer && sudo ./installer.sh"
  echo ""
  print_separator "="
}

#############################################
# Cleanup
#############################################
cleanup() {
  log_info "Cleaning up temporary files..."
  
  if [[ -d "$WORK_DIR" ]]; then
    rm -rf "$WORK_DIR"
  fi
  
  log_success "Cleanup complete"
}

#############################################
# Main execution
#############################################
main() {
  log_module_start "ISO Builder"
  
  # Check if running as root
  if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root"
    echo "Please run: sudo $0"
    exit 1
  fi
  
  # Check dependencies
  if ! check_dependencies; then
    exit 1
  fi
  
  # Confirm action
  echo ""
  log_warning "This will create a ~3GB bootable ISO file"
  log_info "The process will take 10-20 minutes"
  echo ""
  
  read -p "Continue? (y/n) " -n 1 -r
  echo ""
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    log_info "Aborted by user"
    exit 0
  fi
  
  # Create work directory
  mkdir -p "$WORK_DIR"
  
  # Download Ubuntu ISO
  local ubuntu_iso=$(download_ubuntu_iso)
  
  # Extract ISO
  local iso_root="${WORK_DIR}/iso"
  extract_iso "$ubuntu_iso" "$iso_root"
  
  # Customize ISO
  add_installer_to_iso "$iso_root"
  create_autostart "$iso_root"
  create_preseed "$iso_root"
  update_boot_menu "$iso_root"
  
  # Build final ISO
  local output_iso="${ISO_OUTPUT_DIR}/${ISO_NAME}"
  build_iso "$iso_root" "$output_iso"
  
  # Make hybrid
  make_hybrid "$output_iso"
  
  # Calculate checksums
  calculate_checksums "$output_iso"
  
  # Cleanup
  cleanup
  
  # Display info
  display_final_info "$output_iso"
  
  log_module_end "ISO Builder" "success"
}

# Handle interrupts
trap 'echo ""; log_warning "Build interrupted"; cleanup; exit 130' INT TERM

# Run main
main "$@"
