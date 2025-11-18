# 🚀 CheckMK Installer - Complete Installation System

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Ubuntu](https://img.shields.io/badge/Ubuntu-24.04%20LTS-orange.svg)](https://ubuntu.com/)
[![CheckMK](https://img.shields.io/badge/CheckMK-2.4.0p15-green.svg)](https://checkmk.com/)

**Comprehensive, offline-capable installer for CheckMK monitoring infrastructure**

Deploy complete monitoring systems from USB or ISO with interactive menus, automated configuration, and bundled scripts. Supports full server installations, client-only agents, standalone script deployment, and Ydea Cloud integration.

---

## 📋 Table of Contents

- [Features](#-features)
- [Quick Start](#-quick-start)
- [Installation Profiles](#-installation-profiles)
- [System Requirements](#-system-requirements)
- [Usage](#-usage)
- [Configuration](#-configuration)
- [Creating Bootable Media](#-creating-bootable-media)
- [Testing](#-testing)
- [Architecture](#-architecture)
- [Troubleshooting](#-troubleshooting)
- [Contributing](#-contributing)

---

## ✨ Features

### 🎯 Core Capabilities
- **Interactive Installation**: Menu-driven interface with guided wizards
- **Offline Operation**: All scripts and packages bundled locally
- **Multiple Profiles**: Full server, client-only, scripts-only, custom
- **Bootable Media**: Generate bootable USB/ISO for bare-metal deployment
- **Automated Testing**: Complete test suite with VM validation

### 📦 Components Included
- **CheckMK 2.4.0p15**: Monitoring server and agent
- **Ydea Cloud Integration**: Ticket management and automation
- **FRPC Client**: Secure reverse proxy tunneling (v0.52.3)
- **Monitoring Scripts**: 
  - NethServer 7/8 monitoring
  - Ubuntu/Debian monitoring
  - Windows monitoring
  - Proxmox monitoring
  - Notification handlers
  - Automation tools

### 🛡️ Security & Reliability
- SSH hardening and key-based authentication
- UFW firewall with sensible defaults
- Fail2Ban intrusion prevention
- Comprehensive logging with rotation
- Input validation and error handling
- Systemd service management

---

## 🚀 Quick Start

### Option 1: Direct Installation

```bash
# Clone repository
git clone https://github.com/yourusername/checkmk-installer.git
cd checkmk-installer/Install/checkmk-installer/

# Run configuration wizard
sudo ./config-wizard.sh

# Start installation
sudo ./installer.sh
```

### Option 2: USB Installation

```bash
# Create bootable USB
sudo ./make-iso.sh
sudo dd if=checkmk-installer.iso of=/dev/sdX bs=4M status=progress
# Or use: Rufus (Windows), Etcher (macOS/Linux)

# Boot from USB and follow on-screen instructions
```

### Option 3: ISO Installation

```bash
# Generate ISO
sudo ./make-iso.sh

# Burn to CD/DVD or use in VM
# ISO supports both UEFI and Legacy BIOS
```

---

## 📊 Installation Profiles

### 1️⃣ Full Server (`install_full_server`)
Complete CheckMK monitoring server with all components:
- ✅ System base configuration (SSH, NTP, UFW, Fail2Ban)
- ✅ CheckMK server installation and site creation
- ✅ Local agent installation
- ✅ All monitoring scripts deployment
- ✅ Ydea Cloud integration
- ✅ FRPC reverse proxy client

**Use case**: New monitoring server deployment

**Time**: ~15-20 minutes

### 2️⃣ Client Agent (`install_client_agent`)
CheckMK agent-only for monitored hosts:
- ✅ System base configuration
- ✅ CheckMK agent installation
- ✅ Basic monitoring scripts
- ✅ Systemd socket configuration

**Use case**: Adding hosts to existing CheckMK server

**Time**: ~5-8 minutes

### 3️⃣ Scripts Only (`install_scripts_only`)
Deploy monitoring scripts without CheckMK:
- ✅ All monitoring script collections
- ✅ Update automation script
- ✅ Notification handlers

**Use case**: Standalone script deployment for custom monitoring

**Time**: ~2-3 minutes

### 4️⃣ Ydea Only (`install_ydea_only`)
Ydea Cloud toolkit standalone:
- ✅ System base configuration
- ✅ Ydea toolkit installation
- ✅ Ticket tracking automation
- ✅ Systemd timer setup

**Use case**: Ydea Cloud integration without monitoring

**Time**: ~3-5 minutes

### 5️⃣ Custom (`install_custom`)
Mix and match components:
- Interactive module selection
- Flexible configuration
- Minimal to maximum installation

**Use case**: Specific deployment requirements

**Time**: Varies by selection

---

## 💻 System Requirements

### Minimum Requirements
| Component | Requirement |
|-----------|-------------|
| **OS** | Ubuntu 24.04 LTS (Jammy) |
| **CPU** | 2 cores (1 core minimum) |
| **RAM** | 2 GB (1.5 GB minimum) |
| **Disk** | 10 GB (5 GB minimum) |
| **Network** | Internet (for package downloads) |

### Recommended Requirements
| Component | Recommendation |
|-----------|----------------|
| **CPU** | 4+ cores |
| **RAM** | 4+ GB |
| **Disk** | 20+ GB SSD |
| **Network** | 100+ Mbps |

### Software Dependencies
Automatically installed by installer:
- `curl`, `wget`, `git`
- `jq` (JSON processing)
- `apache2` (for CheckMK server)
- `xinetd` or systemd sockets
- `openssh-server`
- `ufw`, `fail2ban`
- `ntp` or `systemd-timesyncd`

---

## 📖 Usage

### Main Menu Options

After running `sudo ./installer.sh`, you'll see:

```
╔══════════════════════════════════════════════════════════╗
║          CheckMK Complete Installation System            ║
║                     Version 1.0.0                        ║
╚══════════════════════════════════════════════════════════╝

MAIN MENU:

  1) Install Full Server (CheckMK + Agent + Scripts + Ydea)
  2) Install Client Agent Only
  3) Install Scripts Only
  4) Install Ydea Toolkit Only
  5) Custom Installation
  6) Configuration Wizard
  7) System Information
  8) Test Installation
  9) Update Components
  0) Exit

Enter your choice [0-9]:
```

### Module-by-Module Installation

Install specific components:

```bash
# System base only
sudo modules/01-system-base.sh

# CheckMK server
sudo modules/02-checkmk-server.sh

# CheckMK agent
sudo modules/03-checkmk-agent.sh

# Scripts deployment
sudo modules/04-scripts-deploy.sh

# Ydea toolkit
sudo modules/05-ydea-toolkit.sh

# FRPC setup
sudo modules/06-frpc-setup.sh
```

### Unattended Installation

Use environment variables for automation:

```bash
# Set configuration
export ENV_FILE="/path/to/.env"
export CHECKMK_ADMIN_PASSWORD="secure123"
export YDEA_API_KEY="your-api-key"

# Run installation
sudo -E ./installer.sh --profile full-server --unattended
```

---

## ⚙️ Configuration

### Configuration Wizard

Interactive configuration:
```bash
sudo ./config-wizard.sh
```

Creates `.env` file with all settings.

### Manual Configuration

Copy and edit template:
```bash
cp .env.template .env
nano .env
```

### Key Configuration Sections

#### System Base
```bash
TIMEZONE="Europe/Rome"
SSH_PORT="22"
PERMIT_ROOT_LOGIN="no"
NTP_SERVERS="0.pool.ntp.org 1.pool.ntp.org"
OPEN_HTTP_HTTPS="yes"
FAIL2BAN_EMAIL="admin@example.com"
```

#### CheckMK Server
```bash
INSTALL_CHECKMK_SERVER="yes"
CHECKMK_DEB_URL="https://download.checkmk.com/checkmk/2.4.0p15/check-mk-raw-2.4.0p15_0.jammy_amd64.deb"
CHECKMK_SITE_NAME="monitoring"
CHECKMK_HTTP_PORT="5000"
CHECKMK_ADMIN_PASSWORD="yourpassword"
```

#### Ydea Cloud
```bash
YDEA_ID="your-ydea-id"
YDEA_API_KEY="your-api-key"
YDEA_USER_ID_CREATE_TICKET="4675"
YDEA_TRACKING_RETENTION_DAYS="30"
YDEA_MONITOR_INTERVAL="30"
```

#### FRPC Client
```bash
FRPC_SERVER_ADDR="your-frps-server.com"
FRPC_SERVER_PORT="7000"
FRPC_TOKEN="your-token"
FRPC_REMOTE_PORT="6000"
FRPC_DOMAIN="monitoring.example.com"
```

---

## 💿 Creating Bootable Media

### Generate ISO

```bash
# Create bootable ISO
sudo ./make-iso.sh

# ISO will be created as: checkmk-installer.iso
# Hybrid mode: Works as ISO and USB image
```

### Create Bootable USB (Linux)

```bash
# Find USB device
lsblk

# Write ISO to USB (replace /dev/sdX with your device)
sudo dd if=checkmk-installer.iso of=/dev/sdX bs=4M status=progress conv=fsync

# Or use more advanced tool
sudo ddrescue -D --force checkmk-installer.iso /dev/sdX
```

### Create Bootable USB (Windows)

Use **Rufus**:
1. Download [Rufus](https://rufus.ie/)
2. Select ISO file
3. Select USB device
4. Partition scheme: GPT (UEFI) or MBR (Legacy)
5. Click Start

Use **Etcher**:
1. Download [Etcher](https://www.balena.io/etcher/)
2. Select ISO file
3. Select USB device
4. Click Flash

### Create Bootable USB (macOS)

```bash
# Find USB device
diskutil list

# Unmount device
diskutil unmountDisk /dev/diskX

# Write ISO
sudo dd if=checkmk-installer.iso of=/dev/rdiskX bs=4m

# Or use Etcher (GUI)
```

### ISO Features

- ✅ **UEFI and Legacy BIOS support**
- ✅ **Preseed automation** (unattended installation)
- ✅ **Offline installation** (all packages bundled)
- ✅ **Persistent storage** (save configurations)
- ✅ **Rescue mode** (system recovery)

---

## 🧪 Testing

### Automated Testing

```bash
cd testing/

# Start test VM
vagrant up

# Run all tests
vagrant ssh -c 'sudo /root/checkmk-installer/testing/test-vm.sh'

# Clean up
vagrant destroy -f
```

### Test Scenarios

```bash
# Full server installation
sudo testing/test-scenarios/full-server.sh

# Client-only installation
sudo testing/test-scenarios/client-only.sh

# Scripts-only deployment
sudo testing/test-scenarios/scripts-only.sh

# Ydea-only installation
sudo testing/test-scenarios/ydea-only.sh
```

### Manual Testing

```bash
# Test CheckMK agent
telnet localhost 6556

# Test CheckMK web UI
curl http://localhost:5000/monitoring/

# Test Ydea toolkit
ydea-toolkit status
ydea-toolkit tickets list

# Test FRPC
systemctl status frpc
curl http://localhost:7400/api/proxy/tcp
```

See [TESTING_GUIDE.md](testing/TESTING_GUIDE.md) for detailed information.

---

## 🏗️ Architecture

### Directory Structure

```
checkmk-installer/
├── installer.sh              # Main menu system
├── config-wizard.sh          # Interactive configuration
├── make-iso.sh              # ISO generation script
├── .env.template            # Configuration template
│
├── modules/                 # Installation modules
│   ├── 01-system-base.sh
│   ├── 02-checkmk-server.sh
│   ├── 03-checkmk-agent.sh
│   ├── 04-scripts-deploy.sh
│   ├── 05-ydea-toolkit.sh
│   └── 06-frpc-setup.sh
│
├── utils/                   # Helper libraries
│   ├── colors.sh           # Colors and symbols
│   ├── logger.sh           # Logging system
│   ├── menu.sh             # Interactive menus
│   └── validate.sh         # Input validation
│
├── templates/              # Configuration templates
│   ├── frpc.ini.template
│   ├── systemd/
│   ├── cron/
│   └── checkmk/
│
├── scripts/                # Bundled scripts (offline)
│   ├── script-check-ns7/
│   ├── script-check-ns8/
│   ├── script-check-ubuntu/
│   ├── script-check-windows/
│   ├── script-notify-checkmk/
│   ├── script-tools/
│   ├── Ydea-Toolkit/
│   ├── Proxmox/
│   └── Fix/
│
└── testing/                # Test suite
    ├── Vagrantfile
    ├── test-vm.sh
    ├── test-config.env
    ├── test-scenarios/
    └── TESTING_GUIDE.md
```

### Module Flow

```
installer.sh (Main Menu)
    ↓
config-wizard.sh (Configuration)
    ↓
modules/ (Sequential Installation)
    ↓
01-system-base.sh
    ├── SSH hardening
    ├── NTP sync
    ├── UFW firewall
    ├── Fail2Ban
    └── Base packages
    ↓
02-checkmk-server.sh
    ├── Download CheckMK
    ├── Install packages
    ├── Create site
    ├── Configure Apache
    └── Set admin password
    ↓
03-checkmk-agent.sh
    ├── Install agent
    ├── Configure socket
    ├── Deploy plugins
    └── Test connectivity
    ↓
04-scripts-deploy.sh
    ├── Copy all scripts
    ├── Set permissions
    ├── Create symlinks
    └── Setup update automation
    ↓
05-ydea-toolkit.sh
    ├── Install toolkit
    ├── Configure API
    ├── Setup monitoring
    └── Create systemd timer
    ↓
06-frpc-setup.sh
    ├── Download FRPC
    ├── Configure client
    ├── Create service
    └── Setup monitoring
```

### Utility Libraries

#### colors.sh
- Color codes and formatting
- Progress bars and spinners
- Box drawing characters
- Status symbols

#### logger.sh
- Centralized logging
- Log rotation
- Multiple log levels (DEBUG→CRITICAL)
- PID tracking
- Command logging

#### menu.sh
- Interactive menus
- Input validation
- Confirmation dialogs
- Multi-select options

#### validate.sh
- IP address validation
- Port validation
- Email validation
- URL validation
- Hostname validation
- System requirements check

---

## 🔧 Troubleshooting

### Installation Issues

#### CheckMK download fails
```bash
# Check internet connectivity
ping -c 3 download.checkmk.com

# Manual download
wget https://download.checkmk.com/checkmk/2.4.0p15/check-mk-raw-2.4.0p15_0.jammy_amd64.deb

# Place in: scripts/Install/Agent-FRPC/
```

#### Permission denied errors
```bash
# Ensure running as root
sudo su -

# Fix script permissions
chmod +x *.sh modules/*.sh utils/*.sh
```

#### Port already in use
```bash
# Check what's using the port
sudo netstat -tulpn | grep :5000

# Kill process or change port in .env
CHECKMK_HTTP_PORT="5001"
```

### CheckMK Issues

#### Site won't start
```bash
# Check site status
omd status

# Start services
omd start

# Check logs
tail -f /omd/sites/monitoring/var/log/web.log
```

#### Agent not responding
```bash
# Check agent service
systemctl status check-mk-agent.socket

# Test agent locally
echo | nc localhost 6556

# Check firewall
sudo ufw status
sudo ufw allow 6556/tcp
```

#### Web UI not accessible
```bash
# Check Apache
systemctl status apache2

# Check site
omd status

# Check logs
journalctl -u apache2 -f
```

### Ydea Toolkit Issues

#### API authentication fails
```bash
# Verify credentials
cat /opt/ydea-toolkit/.env

# Test API manually
ydea-toolkit api GET /tickets

# Check logs
journalctl -u ydea-ticket-monitor -f
```

#### Tracking not updating
```bash
# Force update
ydea-toolkit update-tracking

# Check tracking file
cat /var/log/ydea-tickets-tracking.json

# Verify API response
ydea-toolkit api GET "/tickets?limit=100"
```

### FRPC Issues

#### Can't connect to server
```bash
# Check service
systemctl status frpc

# Test connection
telnet your-frps-server.com 7000

# Check logs
journalctl -u frpc -f
```

#### Invalid token
```bash
# Verify token in config
cat /opt/frpc/frpc.ini

# Update token
nano /opt/frpc/frpc.ini
systemctl restart frpc
```

### System Issues

#### Firewall blocking connections
```bash
# Check rules
sudo ufw status verbose

# Allow specific port
sudo ufw allow 5000/tcp

# Disable temporarily for testing
sudo ufw disable
```

#### Out of disk space
```bash
# Check usage
df -h

# Clean package cache
apt-get clean
apt-get autoclean

# Remove old logs
journalctl --vacuum-time=7d
```

### Log Locations

| Component | Log Location |
|-----------|--------------|
| **Installer** | `/var/log/checkmk-installer.log` |
| **CheckMK Site** | `/omd/sites/monitoring/var/log/` |
| **Apache** | `/var/log/apache2/` |
| **Ydea Toolkit** | `/var/log/ydea-toolkit.log` |
| **FRPC** | `journalctl -u frpc` |
| **System** | `/var/log/syslog` |

---

## 🤝 Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

### Development Workflow

```bash
# Clone repo
git clone https://github.com/yourusername/checkmk-installer.git
cd checkmk-installer/

# Create branch
git checkout -b feature/my-feature

# Make changes
# ...

# Test changes
cd Install/checkmk-installer/testing/
vagrant up
vagrant ssh -c 'sudo /root/checkmk-installer/testing/test-vm.sh'

# Commit and push
git add .
git commit -m "Description of changes"
git push origin feature/my-feature
```

### Coding Standards

- Use `shellcheck` for bash scripts
- Follow existing code style
- Add comments for complex logic
- Update documentation
- Add tests for new features

---

## 📄 License

This project is licensed under the MIT License - see [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- [CheckMK](https://checkmk.com/) - Comprehensive IT monitoring
- [Ydea Cloud](https://www.ydea.it/) - Ticketing and cloud services
- [FRP](https://github.com/fatedier/frp) - Fast reverse proxy
- Ubuntu Community

---

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/yourusername/checkmk-installer/issues)
- **Documentation**: See `docs/` directory
- **Testing**: See [TESTING_GUIDE.md](testing/TESTING_GUIDE.md)

---

## 🗺️ Roadmap

### Version 1.1 (Planned)
- [ ] Debian 12 support
- [ ] Ubuntu 22.04 LTS support
- [ ] Multi-site CheckMK configuration
- [ ] Automated backup/restore
- [ ] Web-based configuration interface

### Version 1.2 (Future)
- [ ] Kubernetes deployment
- [ ] Docker container support
- [ ] Cloud provider images (AWS, Azure, GCP)
- [ ] Distributed monitoring setup
- [ ] High availability configuration

---

## 📊 Project Stats

- **Total Files**: 20+ configuration and script files
- **Lines of Code**: ~3500+ lines
- **Modules**: 6 installation modules
- **Test Scenarios**: 4 automated test scenarios
- **Supported OS**: Ubuntu 24.04 LTS (more planned)

---

<div align="center">

**Made with ❤️ for the CheckMK community**

⭐ Star this repo if you find it useful!

[Report Bug](https://github.com/yourusername/checkmk-installer/issues) · [Request Feature](https://github.com/yourusername/checkmk-installer/issues)

</div>
