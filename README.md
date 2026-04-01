# CheckMK Tools Collection

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CheckMK](https://img.shields.io/badge/CheckMK-Compatible-green.svg)](https://checkmk.com/)
[![PowerShell](https://img.shields.io/badge/PowerShell-5.1+-blue.svg)](https://github.com/PowerShell/PowerShell)
[![Bash](https://img.shields.io/badge/Bash-4.0+-green.svg)](https://www.gnu.org/software/bash/)
[![Language](https://img.shields.io/badge/Lingua-Italiano%20-green.svg)](https://github.com/nethesis/checkmk-tools)

Complete collection of scripts for monitoring and managing infrastructures with CheckMK. Includes check scripts for multiple platforms, custom notification systems, automated deployment tools, cloud backup, and full automation.

> **Note**: This repository is mainly in Italian. Documentation and comments are in Italian.

---

## Index

- **Main Features**
- **Repository Structure**
- **Check Script**
  - Windows
  - NethServer 7
  - NethServer 8
  - Ubuntu/Linux
  - Proxmox
- **Notification Script**
- **Deploy Tools**
- **Automation and Backup**
- **Installation**
- **Documentation**
- **Contributions**

---

## Main Features

### Multi-Platform

- **Windows**: PowerShell scripts for Windows Server (AD, IIS, Ransomware Detection)
- **Linux**: Bash scripts for NethServer, Ubuntu, Proxmox
- **Container**: Podman/Docker monitoring on NethServer 8

### Auto-Update Pattern

- **Remote Wrappers**: Scripts that self-update from GitHub
- **Smart Cache**: Caching system with configurable timeout (60s default)
- **Resilient Fallback**: Use stale cache if GitHub is unreachable

### � ROCKSOLID Mode - Upgrade Resistant Agent

- **NethSecurity 8**: CheckMK + FRP agent installation resistant to major upgrades
- **Auto-Recovery**: Startup script that restores services automatically
- **Binary Backup**: Protect `tar`, `ar`, `gzip` from corruption
- **FRP Dual-Format**: Support FRP v0.x and v1.x with auto detection
- **Total Protections**: 13 critical files protected in `/etc/sysupgrade.conf`
- **Full Validation**: Tested on NethSecurity 8.7.1 + CheckMK 2.4.0p20

### � Automated Deployment

- **Smart Deploy**: Hybrid system for multi-host deployment
- **Automatic Backup**: Pre-deployment snapshot with rollback
- **Validation**: Pre-deployment syntax and functionality testing
- **Interactive Menu**: Interactive deployment with script selection for OS

### Nethesis Branding for CheckMK

- **Complete rebranding**: Logo, colors and CSS for CheckMK facelift theme
- **Multi-server**: Deploy to all servers with a single script
- **Static assets**: SVG with logo embedded in `nethesis-brand/`
- **Idempotent**: Safe to rerun, does not break existing configuration

### Automated Cloud Backup

- **rclone Integration**: Backup CheckMK to cloud storage (S3, DigitalOcean Spaces, etc.)
- **Intelligent Retention**: Automatic local and remote retention management
- **Automatic Rename**: Automatic timestamp for completed backups
- **Monitoring Timer**: Check every minute for new backups
- **Auto-Install Dependencies**: Automatic installation of rclone and dependencies

### Auto-Upgrade CheckMK

- **Automatic Upgrade**: Setup wizard for CheckMK upgrade via crontab
- **Always Latest**: Always download latest script version from GitHub
- **Universal Compatibility**: Bash 3.2+ support with download-to-temp method
- **Interactive Configuration**: Step-by-step wizard for complete configuration

### Advanced Notifications

- **Email Real IP**: Notifications with real IP even behind FRP proxy
- **Telegram Integration**: Telegram notifications with automatic scenario detection
- **HTML + Charts**: HTML emails with performance charts included

---

## Repository structure

```text

checkmk-tools/
├── script-check-windows/ # Script check for Windows
│ ├── nopolling/
│ │ └── ransomware_detection/ # Real-time ransomware detection
│ └── polling/
│
├── script-check-ns7/ # Script check for NethServer 7
│ ├── doc/ # Documentation
│ ├── full/ # Complete standalone scripts
│ └── (remote removed) # Full script only (remote launchers decommissioned)
│
├── script-check-ns8/ # Script check for NethServer 8
│ ├── doc/ # Documentation
│ ├── full/ # Full scripts (Podman, Webtop, Tomcat)
│ └── (remote removed) # Full script only
│
├── script-check-nsec8/ # Script check for NethSecurity 8
│ ├── doc/ # Documentation
│ ├── full/ # Complete scripts
│ └── (remote removed) # Check pure Python in full/
│
├── script-check-ubuntu/ # Script check for Ubuntu/Linux
│ ├── doc/ # Documentation
│ ├── full/ # Full scripts (SSH, Fail2ban, Disk)
│ ├── (remote removed) # Full script only
│ └── deploy-ssh-checks.sh # Deploy automatic SSH check
│
├── script-check-proxmox/ # Script check for Proxmox VE
│ ├── doc/ # Documentation
│ ├── full/ # Complete Proxmox API scripts
│ └── (remote removed) # Full script only
│
├── script-notify-checkmk/ # Custom notification script
│ ├── doc/ # Documentation
│ ├── full/ # Complete notification scripts
│ │ ├── mail_realip* # Email with real IP + graphs
│ │ ├── telegram_* # Telegram Notifications
│ │ ├── ydea_* # Ydea ticketing integration
│ │ └── dump_env # Utility debug environment
│ └── (remote removed) # Full script only
│
├── script-tools/ # Tool deployment and utilities
│ ├── doc/ # Documentation
│ ├── full/ # Complete tools
│ │ ├── smart-deploy-hybrid.sh # Multi-host smart deployment
│ │ ├── deploy-monitoring-scripts.sh # OS-aware interactive deployment
│ │ ├── deploy-plain-agent*.sh # Deploy agent CheckMK
│ │ ├── install-frpc*.sh # Install FRP client
│ │ ├── install-agent-interactive.sh # Interactive agent installation
│ │ ├── checkmk-tuning-interactive*.sh # Tuning CheckMK
│ │ ├── checkmk-optimize.sh # CheckMK optimization
│ │ ├── scan-nmap*.sh # Interactive network scanner
│ │ ├── auto-git-sync.sh # Auto sync repository
│ │ ├── checkmk_rclone_space_dyn.sh # Cloud backup with rclone
│ │ ├── setup-auto-upgrade-checkmk.sh # Setup auto-upgrade CheckMK
│ │ ├── upgrade-checkmk.sh # Upgrade CheckMK
│ │ └── increase-swap.sh # Swap management
│ ├── (remote removed) # Discontinued remote launchers
│ ├── auto-git-sync.service # Systemd service for sync
│ └── install-auto-git-sync.sh # Automatic sync installation
│
├── install/ # Installation and bootstrap
│ ├── bootstrap-installer.sh # Bootstrap installer CheckMK
│ ├── make-bootstrap-iso.sh # Creating bootstrap ISO
│ ├── install-cmk8/ # CheckMK 8 Installation Guides
│ ├── checkmk-installer/ # Custom CheckMK Installer
│ └── Agent-FRPC/ # Installer Agent + FRPC combined
│
├── fix/ # Script fixes and corrections
│ ├── full/ # Complete fix scripts
│ └── (remote removed) # Full script only
│
├── Ydea-Toolkit/ # Ydea Ticketing integration
│ ├── doc/ # Complete documentation
│ ├── full/ # Complete integration scripts
│ │ ├── ydea-toolkit.sh # Main toolkit
│ │ ├── ydea-monitoring-integration.sh # CheckMK integration
│ │ ├── create-monitoring-ticket.sh # Ticket creation
│ │ ├── ydea-discover-sla-ids.sh # Discovery SLA
│ │ ├── install-ydea-checkmk-integration.sh # Installation
│ │ └── test-*.sh # Test script
│ ├── (remote removed) # Full script only
│ ├── config/ # Configuration file
│ ├── README.md # Main guide
│ └── README-*.md # Specific guides
│
├── nethesis-brand/ # Nethesis branding asset for CheckMK
│ ├── checkmk_logo.svg # Login logo (290px, green border)
│ ├── icon_checkmk_logo.svg # N sidebar icon 40px
│ ├── icon_checkmk_logo_min.svg # N sidebar icon 28px
│ ├── nethesis_color.png # Original logo color (source)
│ ├── nethesis_n_icon.png # Original Favicon N (source)
│ └── theme.css # CSS override Nethesis colors
│
├── deploy-nethesis-brand.sh # Deploy branding on all CheckMK servers
│
├── tools/ # Python utilities
│ ├── fix_bash_syntax_corruption.py # Fix syntax corruption
│ └── fix_mojibake_cp437.py # Fix CP437 encoding
│
├── test script/ # Test and verification script
│
├── *.ps1 # PowerShell automation script
│ ├── backup-*.ps1 # Automatic backup system
│ ├── setup-*.ps1 # Automation setup and configuration
│ └── quick-*.ps1 # Quick-access utility
│
└── Root Scripts/ # Bash script root directory
    ├── launcher.sh # Main launcher
    ├── deploy-from-repo.sh # Deploy from repository
    ├── diagnose-auto-git-sync.sh # Auto sync diagnostics
    ├── debug-monitor.sh # Debug monitoring
    ├── update-deployed-launchers.sh # Update deployed launchers
    ├── distributed-monitoring-setup.sh # Distributed monitoring setup
    └── .copilot-context.md # Context file for AI (auto-sync, preferences)

```text

> **Important Note**: The `.copilot-context.md` file contains critical information about the auto-sync system architecture and preferences for AI assistants. Read it before editing files or running commands.

---

## Check script

### Windows

**Directory**: `script-check-windows/`

#### Ransomware Detection

Advanced script for timely detection of ransomware activity on network shares.

**Features**:
- Multi-pattern detection (suspicious extensions, known ransoms, I/O speed)
- Canary files monitoring
- Timeout protection for slow/blocked shares
- Auto-update from GitHub
- Detailed metrics per share

**Files**:
- `check_ransomware_activity.ps1` - Main script (737 lines)
- `rcheck_ransomware_activity.ps1` - Remote wrapper with auto-update
- `ransomware_config.json` - Configuration
- `test_ransomware_detection.ps1` - Full test suite

**Documentation**: [README-Ransomware-Detection.md](script-check-windows/README-Ransomware-Detection.md)

**Quick Start**:

```powershell
# Deploy on Windows Server
Copy-Item check_ransomware_activity.ps1, ransomware_config.json `
    -Destination "C:\ProgramData\checkmk\agent\local\"

# Configuration
notepad C:\ProgramData\checkmk\agent\local\ransomware_config.json

# Manual testing
.\check_ransomware_activity.ps1 -VerboseLog

```text

---

### NethServer 7

**Directory**: `script-check-ns7/`

Complete monitoring for NethServer 7 (CentOS 7 based).

**Structure**:
- `full/` - Complete standalone scripts
- `doc/` - Specific documentation

#### Scripts Available

| Scripts | Description | Metrics |
|--------|-------------|----------|
| `check_cockpit_sessions.sh` | Active sessions Cockpit | Sessions, warning/crit |
| `check_dovecot_sessions.sh` | IMAP/POP3 sessions | Active Connections |
| `check_dovecot_maxuserconn.sh` | Max conn per user | Peak connections |
| `check_dovecot_status.sh` | Dovecot Service Status | Service status |
| `check_dovecot_vsz.sh` | VSZ Dovecot memory | MB used |
| `check_postfix_status.sh` | Postfix Service Status | Service status |
| `check_postfix_process.sh` | Active Postfix processes | Process count |
| `check_postfix_queue.sh` | Email Queue | Queued Messages |
| `check_webtop_status.sh` | Webtop5 Status | Service status |
| `check_webtop_maxmemory.sh` | Maximum Webtop Memory | MB allocated |
| `check_webtop_https.sh` | Webtop HTTPS Status | Certificate expiry |
| `check_ssh_root_logins.sh` | SSH Root Login | Failed attempts |
| `check_ssh_root_sessions.sh` | Active root sessions | Active sessions |
| `check_ssh_failures.sh` | SSH attempts failed | Failed count |
| `check-sos-ns7.sh` | Report sosreport NS7 | Report generation |
| `check-sosid-ns7.sh` | sosreport case ID | Case tracking |
| `check-pkg-install.sh` | Installed Packages | Package count |
| `check_ransomware_ns7.sh` | NS7 ransomware detection | Suspicious files |
| `check_fail2ban_status.sh` | Fail2ban Status | Service status |
| `check_ssh_all_sessions.sh` | All SSH sessions | Session count |

**Current pattern**: Full scripts in `full/` only (discontinued remote launchers).

---

### NethServer 8

**Directory**: `script-check-ns8/`

Monitoring for NethServer 8 (Podman/Container based).

**Structure**:
- `full/` - Complete scripts for monitoring containers and services
- `doc/` - Documentation

#### Scripts Available

| Scripts | Description | Features |
|--------|-------------|-------------|
| `monitor_podman_events.sh` | Podman real-time event monitor | Container start/stop/die |
| `check_podman_events.sh` | Check Podman events | Event detection |
| `check_ns8_containers.sh` | NS8 Container Status | Container health |
| `check_ns8_services.sh` | NS8 Services Status | Service monitoring |
| `check_ns8_webtop.sh` | NS8 Webtop Monitoring | Webtop status |
| `check_ns8_tomcat8.sh` | Tomcat8 NS8 Monitoring | Tomcat status |
| `check-sos.sh` | NS8 SOS Report Generation | Diagnostic reports |

**Note**: NethServer 8 uses container-based architecture, scripts are optimized for Podman.

---

### Ubuntu/Linux

**Directory**: `script-check-ubuntu/`

Generic script checks for Ubuntu/Debian distributions.

**Structure**:
- `full/` - Complete scripts for Ubuntu/Debian
- `doc/` - Documentation
- `deploy-ssh-checks.sh` - Deploy automatic SSH checks

#### Scripts Available

| Scripts | Description | Metrics |
|--------|-------------|----------|
| `check_ssh_root_logins.sh` | SSH Root Login | Failed attempts |
| `check_ssh_root_sessions.sh` | Active root sessions | Active sessions |
| `check_ssh_all_sessions.sh` | All SSH sessions | Total sessions |
| `check_fail2ban_status.sh` | Fail2ban Status | Ban count, status |
| `check_disk_space.sh` | Disk Space | Disk usage |
| `mk_logwatch` | Log monitoring | Log parsing |

**Deploy Quick Start**:

```bash
# Automatic SSH check deployment
./deploy-ssh-checks.sh

```text

---

### NethSecurity 8

**Directory**: `script-check-nsec8/`

Monitoring for NethSecurity 8 (NethServer 8 based Firewall).

**Structure**:
- `full/` - Complete scripts for NethSecurity
- `doc/` - Specific documentation

**Note**: NethSecurity 8 is the firewall distribution based on NethServer 8, includes specific monitoring for firewall services.

---

### Proxmox

**Directory**: `script-check-proxmox/`

Proxmox Virtual Environment monitoring via API.

#### Scripts Available

| Scripts | Description | API Endpoint |
|--------|-------------|--------------|
| `check-proxmox-vm-status.sh` | VM status (running/stopped) | `/api2/json/nodes/*/qemu` |
| `check-proxmox-vm-snapshot-status.sh` | VM Snapshot Status | `/api2/json/nodes/*/qemu/*/snapshot` |
| `proxmox_vm_api.sh` | Proxmox API connection test | API authentication |
| `proxmox_vm_disks.sh` | VM Disk Monitoring | Disk usage |
| `proxmox_vm_monitor.sh` | General VM Monitor | CPU, RAM, Disk |

**Execution**: Use the scripts in `full/` directly.

**Requirements**:
- Proxmox API token configured
- `curl` and `jq` installed
- Read permissions on Proxmox API

---

## Notification Script

**Directory**: `script-notify-checkmk/`

Advanced CheckMK notification system with FRP (Fast Reverse Proxy) support and Ydea ticketing integration.

**Structure**:
- `full/` - Complete notification scripts
- `doc/` - Documentation and test guides

### Main Features

#### Real IP Detection

Extracts real IP even behind FRP proxy for accurate notifications:

```python
# Automatic scenario detection
if 'NOTIFY_HOSTLABEL_real_ip' in os.environ:
    real_ip = os.environ['NOTIFY_HOSTLABEL_real_ip']
    # Use real_ip instead of HOSTADDRESS

```text

#### Integrated Charts

HTML email with performance graphs automatically included:
- CPU usage
- Memory utilization  
- Disk I/O
- Network traffic

#### Multi-Channel

- **Email**: `mail_realip*` - Various versions (HTML, hybrid, safe)
- **Telegram**: `telegram_realip` - Telegram bot with formatting

### Scripts Available

| Scripts | Description | Features |
|--------|-------------|----------|
| `mail_realip_hybrid` | Email HTML + Real IP + Charts |  Recommended |
| `mail_realip_hybrid_v24` | CheckMK version 2.4+ | Latest version |
| `mail_realip_hybrid_safe` | Version with fallback | Extra safety |
| `mail_realip` | Email base Real IP | Minimal |
| `mail_realip_html` | Email HTML Real IP | No graphs |
| `telegram_realip` | Telegram Real IP | Bot integration |
| `telegram_selfmon` | Telegram self-monitoring | Self-check |
| `ydea_ag` | Ydea AG integration | Ticketing AG |
| `ydea_la` | Ydea LA integration | Ticketing LA |
| `mail_ydea_down` | Host down notification email Ydea | Host down |
| `dump_env` | Dump environment variables |  Debugging |

### Deployment

```bash
#1. Backup existing configuration
./backup_and_deploy.sh --backup-only

#2. Dry-run testing
./backup_and_deploy.sh --dry-run

#3. Actual deployment
./backup_and_deploy.sh

#4. Check
up - $(cat /etc/omd/site)
ls -la local/share/check_mk/notifications/

```text

**Documentation**: [TESTING_GUIDE.md](script-notify-checkmk/TESTING_GUIDE.md)

---

## Deployment tools

**Directory**: `script-tools/`

Utility for automated CheckMK Agent deployment, scripting and infrastructure management.

**Structure**:
- `full/` - Complete deployment and management tools
- `remote/` - Remote wrapper
- `doc/` - Tool documentation
- `auto-git-sync.service` - Systemd service for automatic sync
- `install-auto-git-sync.sh` - Installing automatic repository sync

### Deploy Monitoring Scripts

Interactive script for selective deployment of monitoring scripts on remote hosts.

**Features**:
- Auto-detect operating system (NS7/NS8/Proxmox/Ubuntu)
- Interactive menu with list of available scripts
- Selective deployment (single scripts or all)
- Automatic copy to `/usr/lib/check_mk_agent/local/`
- Use local repository `/opt/checkmk-tools`

**One-liner installation**:

```bash
# Download and run directly
curl -fsSL https://raw.githubusercontent.com/nethesis/checkmk-tools/main/script-tools/full/deploy/deploy-monitoring-scripts.sh -o /tmp/deploy.sh && bash /tmp/deploy.sh

```text

**Manual use**:

```bash
# If you already have the repository cloned
cd /opt/checkmk-tools
./script-tools/full/deploy/deploy-monitoring-scripts.sh

```text

**Example output**:

```text

=========================================
  Deploy Monitoring Scripts
=========================================

 Repository found: /opt/checkmk-tools
System detected: NethServer 7

Available scripts:
  1) rcheck_cockpit_sessions.sh
  2) rcheck_dovecot_status.sh
  3) rcheck_postfix_queue.sh
  [...]
  
Selection (numbers separated by spaces, 'a' for all, 'q' for exit): 1 3 5

```text

---

### Smart Deploy Hybrid

Intelligent system for multi-host deployment with auto-update.

**Features**:
- Auto-download from GitHub with cache
- Fallback to cache in case of network issue
- Timeout protection (30s default)
- Detailed logging
- Pre-deploy syntax validation

**Files**:
- `smart-deploy-hybrid.sh` - Smart Deploy
- `README-Smart-Deploy.md` - Basic documentation
- `README-Smart-Deploy-Enhanced.md` - Enhanced features

**Example**:

```bash
# Deploy script on remote host
./smart-deploy-hybrid.sh \
    --host ns7-server.local \
    --scripts check_cockpit_sessions,check_dovecot_status \
    --github-repo nethesis/checkmk-tools

```text

### Deploy Agent CheckMK

Installation and configuration CheckMK Agent.

| Scripts | Description |
|--------|-------------|
| `deploy-plain-agent.sh` | Deploy agent single host |
| `deploy-plain-agent-multi.sh` | Multi-host deployment from list |
| `install-and-deploy-plain-agent.sh` | Install + deploy complete |

### FRP Client installation

| Scripts | Description |
|--------|-------------|
| `install-frpc.sh` | Basic client FRP installation |
| `install-frpc2.sh` | FRP v2 Installation |
| `install-frpc-dryrun.sh` | Test without modifications |

### CheckMK Optimization and Tuning

| Scripts | Description |
|--------|-------------|
| `checkmk-tuning-interactive-v5.sh` | Interactive Tuning CheckMK (latest) |
| `checkmk-tuning-interactive*.sh` | Previous versions tuning |
| `checkmk-optimize.sh` | CheckMK automatic optimization |
| `install-checkmk-log-optimizer.sh` | CheckMK Log Optimizer |
| `upgrade-checkmk.sh` | Automated CheckMK Upgrade |

### Agent Management

| Scripts | Description |
|--------|-------------|
| `install-agent-interactive.sh` | Interactive agent installation |
| `install-checkmk-agent-debtools-frp-nsec8c-rocksolid.sh` |  **ROCKSOLID Installer** for NethSecurity 8 |
| `rocksolid-startup-check.sh` | Autocheck boot for post-upgrade protection |
| `update-all-scripts.sh` | Updating script from repository |
| `update-scripts-from-repo.sh` | Update specific scripts |

#### ROCKSOLID Mode - Upgrade Resistant Installation

**Advanced protection system for NethSecurity 8** that guarantees the survival of CheckMK Agent and FRP Client during major system upgrades.

**Features**:
- **Total Protection**: Add critical files to `/etc/sysupgrade.conf` (survive upgrades)
- **Binary Backup**: Automatic backup of `tar`, `ar`, `gzip` (protects against corruption during upgrade)
- **Auto-Recovery**: Startup script that checks and restores services automatically
- **FRP Integration**: Support FRP v0.x and v1.x with existing configuration detection
- **Marker System**: Marker file for persistent FRP installation detection
- **Post-Upgrade Script**: Automatic post-upgrade verification and recovery script

**Validated on**:
- NethSecurity 8.7.1 (OpenWrt 23.05.0)
- FRP Client v0.64.0 and legacy v0.x
- CheckMK Agent 2.4.0p20

**Installation**:

```bash
# Download and run directly
curl -fsSL https://raw.githubusercontent.com/nethesis/checkmk-tools/main/script-tools/full/installation/install-checkmk-agent-persistent-nsec8.sh | bash

# Optional: interactive mode
bash install-checkmk-agent-debtools-frp-nsec8c-rocksolid.sh

```text

**Post-Upgrade** (after major manual upgrade):

```bash
/etc/checkmk-post-upgrade.sh

```text

**Full documentation**: [install-checkmk-agent-debtools-frp-nsec8c-rocksolid.md](script-tools/doc/install-checkmk-agent-debtools-frp-nsec8c-rocksolid.md)

### Repository automation

| Scripts | Description |
|--------|-------------|
| `auto-git-sync.sh` | Automatic repository sync |
| `install-auto-git-sync.sh` | Installing sync as a service |

### Network Scanner

| Scripts | Description |
|--------|-------------|
| `scan-nmap-interactive-verbose.sh` | Interactive Nmap Scanner |
| `scan-nmap-interactive-verbose-multi-options.sh` | Scanner with advanced options |

### System and Utilities

| Scripts | Description |
|--------|-------------|
| `increase-swap.sh` | Swap management and increase |
| `setup-auto-updates.sh` | Automatic updates setup |
| `setup-auto-upgrade-checkmk.sh` | CheckMK automatic upgrade setup |
| `smart-wrapper-template.sh` | Smart Wrapper Template |
| `smart-wrapper-example.sh` | Wrapper example with cache |

---

## Ydea Toolkit - Ticketing Integration

**Directory**: `Ydea-Toolkit/`

Complete integration between CheckMK and Ydea ticketing system for automatic creation of monitoring tickets.

**Structure**:
- `full/` - Complete integration scripts
- `remote/` - Remote wrapper
- `config/` - Configuration file
- `doc/` - Detailed documentation

### Main Features

#### Core features

- **Automatic ticket creation** from CheckMK events
- Automatic **SLA discovery** from contracts
- **Monitoring tickets** open and in progress
- **Health monitor** integration status
- **Complete toolkit** for Ydea API management

### Scripts Available

#### CheckMK integration

| Scripts | Description |
|--------|-------------|
| `ydea-monitoring-integration.sh` |  Full CheckMK-Ydea integration |
| `install-ydea-checkmk-integration.sh` | Automatic installation integration |
| `ydea-health-monitor.sh` | Integration Status Monitor |
| `ydea-ticket-monitor.sh` | Monitor open tickets |

#### Ticket Management

| Scripts | Description |
|--------|-------------|
| `create-monitoring-ticket.sh` | Creating tickets from events |
| `create-ticket-ita.sh` | Ticket creation in Italian |
| `get-ticket-by-id.sh` | Retrieve Tickets by ID |
| `get-full-ticket.sh` | Full ticket details |
| `search-ticket-by-code.sh` | Search ticket by code |

#### Discovery and Analysis

| Scripts | Description |
|--------|-------------|
| `ydea-discover-sla-ids.sh` | Automatic SLA discovery from contracts |
| `search-sla-in-contracts.sh` | Search SLA in contracts |
| `analyze-custom-attributes.sh` | Custom attribute analysis |
| `analyze-ticket-data.sh` | Ticket data analysis |

#### API and Testing

| Scripts | Description |
|--------|-------------|
| `ydea-toolkit.sh` |  Ydea API Master Toolkit |
| `explore-ydea-api.sh` | Explore Ydea API |
| `explore-anagrafica.sh` | Explore customer records |
| `quick-test-ydea-api.sh` | API Quick Test |
| `test-ydea-integration.sh` | Full integration test |
| `test-ticket-with-contract.sh` | Test ticket with contract |

### Quick Start

```bash
#1. Installation integration
cd Ydea-Toolkit/full
./install-ydea-checkmk-integration.sh

#2. Configuration (edit with your credentials)
cp .env.example .env
vim .env

#3. Automatic SLA Discovery
./ydea-discover-sla-ids.sh

#4. Test ticket creation
./create-monitoring-ticket.sh \
    --host "server01" \
    --service "CPU Load" \
    --state "CRITICAL" \
    --output "CPU at 95%"

#5. Monitor health integration
./ydea-health-monitor.sh

```text

### Documentation

- **[README.md](Ydea-Toolkit/README.md)** - Main Guide
- **[README-CHECKMK-INTEGRATION.md](Ydea-Toolkit/doc/README-CHECKMK-INTEGRATION.md)** - Complete CheckMK-Ydea integration guide
> **Note**: Documentation consolidated from 17 to 2 essential files for ease of navigation (February 2026)

### Configuration

**Required files**:
- `.env` - Ydea API credentials and SLA configuration
- `premium-mon-config.json` - Premium_Mon Mapping (contract + SLA)

**Environment variables**:

```bash
YDEA_ID="your_company_id"
YDEA_API_KEY="your_api_key"
YDEA_CONTRATTO_ID="171734" # Contract that applies SLA automatically

```text

**Contract-Based SLA**: As of February 2026, the system uses `contractId` to automatically apply Premium_Mon SLA. You no longer need to explicitly specify `serviceLevelAgreement` - the contract handles everything.

---

## Directory Utilities

### Install - Installation and Bootstrap

**Directory**: `install/`

Script for installing and bootstrapping CheckMK and components.

| Scripts/Directories | Description |
|------------------|-------------|
| `bootstrap-installer.sh` | Bootstrap installer CheckMK |
| `make-bootstrap-iso.sh` | Bootstrap ISO creation |
| `install-cmk8/` | CheckMK 8 Installation Guides |
| `checkmk-installer/` | CheckMK Custom Installer |
| `Agent-FRPC/` | Combined Installer Agent + FRPC |

### Fix - Corrections and Repairs

**Directory**: `fix/`

Script to fix common problems.

**Structure**:
- `full/` - Complete script fixes
- `remote/` - Remote wrapper

### Tools - Python utilities

**Directory**: `tools/`

Python utility for advanced fixes.

| Scripts | Description |
|--------|-------------|
| `fix_bash_syntax_corruption.py` | Fix bash syntax corruption |
| `fix_mojibake_cp437.py` | Fix CP437 encoding (mojibake) |

### Root Scripts

**Root Directory**

Bash script utility in the root of the repository.

| Scripts | Description |
|--------|-------------|
| `launcher.sh` | Main Launcher Script |
| `launcher_remote_script.sh` | Remote Script Launcher |
| `deploy-from-repo.sh` | Deploy from repository |
| `rdeploy-from-repo.sh` | Remote deployment |
| `diagnose-auto-git-sync.sh` | Automatic sync diagnostics |
| `rdiagnose-auto-git-sync.sh` | Remote diagnostics |
| `debug-monitor.sh` | Debug monitoring |
| `update-deployed-launchers.sh` | Update deployed launchers |
| `update-remote-urls.ps1` | Update Remote URLs |
| `distributed-monitoring-setup.sh` | Distributed setup monitoring |
| `check-distributed-monitoring-prerequisites.sh` | Check prerequisites |
| `update-crontab-frequency.sh` | Update crontab frequency |
| `test-log-events.sh` | Test log events |

---

## Automation and Backup

### Root Directory PowerShell Script

Automated system for repository backup and sync.

#### Automatic Backup

| Scripts | Description | Frequency |
|--------|-------------|-----------|
| `quick-backup.ps1` | Quick change backup | Hourly |
| `backup-sync.ps1` | Remote backup + sync | Daily |
| `backup-sync-complete.ps1` | Full + multi-remote backup | Weekly |
| `backup-existing-config.ps1` | Configuration backup | On-demand |

#### Automation Setup

| Scripts | Description |
|--------|-------------|
| `setup-automation.ps1` | Scheduled task setup wizard |
| `setup-backup-automation.ps1` | Automatic backup setup |
| `create_backup_task.ps1` | Windows task creation |
| `check_task.ps1` | Check existing tasks |

#### Git configuration

| Scripts | Description |
|--------|-------------|
| `setup-additional-remotes.ps1` | Add remote repository |
| `fix-gitlab-credentials.ps1` | Fix GitLab credentials |
| `git-credential-fix.ps1` | Fix generic Git credentials |

**Quick Start Automation**:

```powershell
#1. Automatic backup setup
.\setup-automation.ps1

# Choose option:
#1. Backup every hour (quick)
#2. Daily morning backup (9:00 am)
#3. Daily Evening Backup (10pm)
#4. Weekly Backup (Monday 8am)

#2. Check created task
.\check_task.ps1

#3. Manual testing
.\quick-backup.ps1

```text

---

## Installation

### Basic Requirements

#### Windows

- PowerShell 5.1 or higher
- CheckMK Agent Windows installed
- .NET Framework 4.5+

#### Linux

- Bash 4.0+
- CheckMK Agent installed
- `curl`, `jq` (for some scripts)
- Python 3 (for notification script)

### Installation Script Check

#### Windows

```powershell
#1. Clone repository
git clone https://github.com/nethesis/checkmk-tools.git
cd checkmk-tools

#2. Deploy desired script
$scriptPath = "script-check-windows\nopolling\ransomware_detection"
Copy-Item "$scriptPath\rcheck_ransomware_activity.ps1" `
    -Destination "C:\ProgramData\checkmk\agent\local\"
Copy-Item "$scriptPath\ransomware_config.json" `
    -Destination "C:\ProgramData\checkmk\agent\local\"

#3. Test
& "C:\Program Files (x86)\checkmk\service\check_mk_agent.exe" test | 
    Select-String -Pattern "Ransomware"

```text

#### Linux (NethServer / Ubuntu)

```bash
#1. Clone repository
git clone https://github.com/nethesis/checkmk-tools.git
cd checkmk-tools

#2. Deploy with smart-deploy
cd script-tools
./smart-deploy-hybrid.sh \
    --local \
    --script ../script-check-ns7/nopolling/check_cockpit_sessions.sh

# Or manual copy
sudo cp script-check-ns7/nopolling/rcheck_cockpit_sessions.sh \
    /usr/lib/check_mk_agent/local/

sudo chmod +x /usr/lib/check_mk_agent/local/rcheck_cockpit_sessions.sh

#3. Test
check_mk_agent | grep -A5 "cockpit"

```text

### Notification Script Installation

```bash
# On CheckMK server (as root)
cd /tmp
git clone https://github.com/nethesis/checkmk-tools.git
cd checkmk-tools/script-notify-checkmk

# Automatic Backup + Deploy
./backup_and_deploy.sh

# Or manual
omd stop
cp mail_realip_hybrid /omd/sites/SITENAME/local/share/check_mk/notifications/
chmod +x /omd/sites/SITENAME/local/share/check_mk/notifications/mail_realip_hybrid
omd start

# Configure in Web GUI
# Setup -> Notifications -> New Rule -> Notification Method: mail_realip_hybrid

```text

---

## Documentation

### README Specifics

Each category has its own detailed documentation:

- **Windows**: [script-check-windows/README.md](script-check-windows/README.md)
  - **Ransomware**: [README-Ransomware-Detection.md](script-check-windows/README-Ransomware-Detection.md)

- **Notifications**: [script-notify-checkmk/TESTING_GUIDE.md](script-notify-checkmk/TESTING_GUIDE.md)

- **Deploy Tools**: 
  - [script-tools/README-Smart-Deploy.md](script-tools/README-Smart-Deploy.md)
  - [script-tools/README-Smart-Deploy-Enhanced.md](script-tools/README-Smart-Deploy-Enhanced.md)

- **Complete Solutions**: [COMPLETE-SOLUTION.md](COMPLETE-SOLUTION.md)

### Installation Guides

- **CheckMK 8**: [script-tools/full/installation/install-cmk8/](script-tools/full/installation/install-cmk8/)

### Configurations

- **Host Labels**: [checkmk-host-labels-config.md](checkmk-host-labels-config.md)

---

## Testing

### Test Windows

```powershell
# Single script test
cd script-check-windows\nopolling\ransomware_detection
.\test_ransomware_detection.ps1 -TestScenario All

# Manual testing with debugging
.\check_ransomware_activity.ps1 -VerboseLog

# Test via CheckMK Agent
& "C:\Program Files (x86)\checkmk\service\check_mk_agent.exe" test

```text

### Linux tests

```bash
# Single script test
/usr/lib/check_mk_agent/local/check_cockpit_sessions

# CheckMK test output
check_mk_agent | head -50

# Test with debugging
bash -x /usr/lib/check_mk_agent/local/rcheck_cockpit_sessions.sh

```text

### Test Notifications

```bash
# FRP detection test
cd script-notify-checkmk
python3 -c "
import os
os.environ['NOTIFY_HOSTLABEL_real_ip'] = '192.168.1.100'
os.environ['NOTIFY_HOSTADDRESS'] = '127.0.0.1:5000'
exec(open('mail_realip_hybrid').read())
"

```text

---

## Contributions

### How to Contribute

1. **Fork** the repository
2. **Create branches** for your feature: `git checkout -b feature/AmazingFeature`
3. **Commit** changes: `git commit -m 'Add AmazingFeature'`
4. **Push** to branch: `git push origin feature/AmazingFeature`
5. **Open Pull Request**

### Standard Code

#### PowerShell

- Use `CmdletBinding()` for advanced scripting
- Parameter validation with `[Parameter()]`
- Help comments with `.SYNOPSIS`, `.DESCRIPTION`, `.EXAMPLE`
- Error handling with `try/catch`
- Output CheckMK format: `<<<local>>>` + status lines

#### Bash

- Use `#!/bin/bash` shebang
- Set `-euo pipefail` for error handling
- Functions with clear naming
- Comments for complex logic
- Standard CheckMK format output

#### Naming conventions

**Files**:
- Check scripts: `check_<name>.{ps1|sh}`
- Remote wrappers: `rcheck_<name>.{ps1|sh}`
- Test scripts: `test_<name>.{ps1|sh}`
- Config files: `<name>_config.json`

**CheckMK Services**:
- Format: `<Category>_<Name>`
- Examples: `Ransomware_Detection`, `Cockpit_Sessions`

**Metrics**:
- Snake case: `suspicious_files=10`
- Unit suffixes: `memory_mb=512`, `time_seconds=30`

---

## Repository statistics

### Script Count

| Category | Script Full | Remote Wrappers | Total |
|-----------|-------------|-----------------|-------|
| Windows | 2+ | 2+ | 4+ |
| NethServer 7 | 20 | 20+ | 40+ |
| NethServer 8 | 7 | 7+ | 14+ |
| NethSecurity 8 | 3+ | 3+ | 6+ |
| Ubuntu/Linux | 6 | 6+ | 12+ |
| Proxmox | 5 | 5+ | 10+ |
| **Total Check** | **43+** | **43+** | **86+** |

| Category | Scripts | Description |
|-----------|---------|-------------|
| Notifications | 11+ | Email + Telegram + Ydea |
| Deploy Tools | 28+ | Smart deployment, agent install, tuning |
| Ydea Toolkit | 30+ | Complete ticketing integration |
| Install/Bootstrap | 5+ | Installer and bootstrap |
| Fixes/Tools | 3+ | Fix Utility |
| Root Scripts | 12+ | Launcher, deployment, diagnostics |
| Tests | 10+ | Test suite and validation |

### Languages

- **PowerShell**: ~25% (Windows scripts, automation)
- **Bash**: ~65% (Linux scripts, deployment, tools)
- **Python**: ~10% (CheckMK Notifications, utilities)

### Platform Coverage

- **Windows Server** (PowerShell scripts)
- **NethServer 7** (CentOS 7 based)
- **NethServer 8** (Container/Podman based)
- **NethSecurity 8** (Firewall)
- **Ubuntu/Debian** (Generic Linux scripts)
- **Proxmox VE** (Virtualization)
- **CheckMK** (Notifications, tuning, deployment)
- **Ydea** (Ticketing system)

---

## Troubleshooting

### Windows

**Problem**: Script does not appear in CheckMK

```powershell
# Check permissions
Get-Acl "C:\ProgramData\checkmk\agent\local\*.ps1"

# Check execution policy
Get-ExecutionPolicy

# Manual testing
& "C:\Program Files (x86)\checkmk\service\check_mk_agent.exe" test

```text

**Problem**: Network share timeout error

```powershell
# Check ransomware_config.json
# Increase timeout if necessary (default 30s)

```text

### Linux

**Problem**: Script not executable

```bash
sudo chmod +x /usr/lib/check_mk_agent/local/*.sh

```text

**Problem**: Script cache not updating

```bash
# Remove manual cache
rm -f /var/cache/checkmk-scripts/*
rm -f /tmp/*_cache.sh

# Force re-download
/usr/lib/check_mk_agent/local/rcheck_script.sh

```text

**Problem**: Notification script not working

```bash
# Check permissions
ls -la /omd/sites/SITENAME/local/share/check_mk/notifications/

# Manual testing (as site user)
on - SITENAME
cd local/share/check_mk/notifications
python3 -c "exec(open('./mail_realip_hybrid').read())"

```text

---

## Security

### Best Practices

- Do not commit credentials in config files
- Use environment variables for token/password
- Limit file permissions (600 for sensitive configs)
- Validate user input
- Use HTTPS for API communications
- Timeout for network operations
- Log relevant security events

### Credentials

File `.gitignore` includes:

```text

*.json
*.config
*.key
*.token
*_password.txt

```text

Always use:

```bash
# Linux
export API_TOKEN="your-token"

#Windows
$env:API_TOKEN = "your-token"

```text

---

## � Auto-Sync system

The repository uses an **automatic synchronization** system on CheckMK servers:

### Architecture

```text

GitHub (nethesis/checkmk-tools)
    ↓ [auto-git-sync.service - every 5-15 minutes]
/opt/checkmk-tools/ (on servers)
    ↓ [execute script]
Production

```text

### Workflow Changes

1. **Local Edit** (Windows/Workstation)
2. **Commit + Push** to GitHub
3. **Wait for auto-sync** (5-15 minutes) or force it: `sudo bash /opt/checkmk-tools/script-tools/full/sync_update/auto-git-sync.sh`
4. **Updated scripts** in `/opt/checkmk-tools/`
5. **Test in production**

 **Important**: Never directly edit files in `/opt/checkmk-tools/` - they will be overwritten by sync!

### Check Sync

```bash
# Service status
sudo systemctl status auto-git-sync.service

# Recent logs
sudo journalctl -u auto-git-sync.service -n 50

# Force manual sync
sudo bash /opt/checkmk-tools/script-tools/full/sync_update/auto-git-sync.sh

```text

**Full documentation**: [.copilot-context.md](.copilot-context.md)

---

## CheckMK Cloud Backup

Complete script for automated CheckMK backup to cloud storage with rclone.

### Features

- **Multi-Cloud**: Support S3, DigitalOcean Spaces, Google Drive, Dropbox, etc.
- **Auto-Install**: Automatic installation of rclone and dependencies
- **Automatic Retention**: Local and remote management with configurable days
- **Smart Rename**: Automatic timestamp for `-complete` backups
- **Monitoring Timer**: Systemd timer (every 1 minute) for automatic checks
- **S3-Compatible**: Optimized for S3/Spaces (no mkdir, path auto-create)

### Quick Start

```bash
# Interactive setup
cd /opt/checkmk-tools/script-tools/full
./checkmk_rclone_space_dyn.sh setup

# Configuration:
# - Site CheckMK: monitoring
# - Remote rclone: do:testmonbck (DigitalOcean example)
# - Local retention: 30 days
# - Remote retention: 90 days

# Manual testing
./checkmk_rclone_space_dyn.sh run monitoring

# Check status
systemctl status checkmk-cloud-backup-push@monitoring.timer
journalctl -u checkmk-cloud-backup-push@monitoring.service -n 50

```text

### RClone configuration

The script requires rclone configured. Example for DigitalOcean Spaces:

```bash
rclone config
# Choose: s3
# Provider: DigitalOcean Spaces
# Endpoint: ams3.digitaloceanspaces.com
# Remote name: do

```text

**File**: `script-tools/full/backup_restore/checkmk_rclone_space_dyn.sh` (794 lines)

---

## Auto-Upgrade CheckMK

Interactive wizard to configure CheckMK automatic upgrade via crontab.

### Features

- **Always Latest**: Always download the latest upgrade script version from GitHub
- **Universal Compatibility**: Bash 3.2+ support (download-to-temp)
- **Interactive Wizard**: Guided step-by-step configuration
- **Crontab Safe**: Automatic crontab validation and backup
- **Multi-Site**: Single or all site upgrade support

### Quick Start

```bash
# Setup wizard
cd /opt/checkmk-tools/script-tools/full
./setup-auto-upgrade-checkmk.sh

# Follow wizard:
#1. Choose site (or “all”)
#2. Confirm CheckMK version
#3. Set time (ex: 03:00)
#4. Choose frequency (daily/weekly/monthly)
# 5. Confirm configuration

# Check history
crontab -l

```text

**File**: `script-tools/full/upgrade_maintenance/setup-auto-upgrade-checkmk.sh` (270 lines)

---

## � Support

### Issue Reporting

Open issue on GitHub with:
- Operating system and version
- CheckMK version
- Script involved
- Complete error message
- Debug logs (if available)

### Community

- GitHub Discussions

---

## License

MIT License - See [LICENSE](LICENSE) for details.

---

## Credits

Developed with for the CheckMK community.

### Main Authors

- 
### Contributors

Thanks to all the contributors who helped improve this collection!

### Acknowledgments

- [CheckMK](https://checkmk.com/) - Monitoring solution
- [NethServer](https://www.nethserver.org/) - Server platform
- CheckMK Community for patterns and best practices

---

## Roadmap

### Completed (v2.0)

- [x] **Ydea Toolkit**: Complete ticketing integration
- [x] **NethSecurity 8**: Firewall monitoring
- [x] **Ubuntu/Linux**: Full Scripts SSH, Fail2ban, Disk
- [x] **NS8 Enhanced**: Container monitoring, Webtop, Tomcat
- [x] **Deploy Tools**: Interactive tuning, optimization
- [x] **Automation**: Automatic Git sync

### In Development

- [ ] **Windows script**:
  - [ ] check_windows_updates.ps1
  - [ ] check_iis_sites.ps1
  - [ ] check_active_directory.ps1
  - [ ] check_windows_services_extended.ps1

- [ ] **Linux script**:
  - [ ] check_lvm_snapshots.sh
  - [ ] check_systemd_failed.sh
  - [ ] check_cert_expiry.sh
  - [ ] check_docker_compose.sh

- [ ] **Notifications**:
  - [ ] Slack integration
  - [ ] Microsoft Teams webhooks
  - [ ] Discord notifications
  - [ ] PagerDuty integration

- [ ] **Ydea Enhanced**:
  - [ ] Auto-close ticket resolved
  - [ ] SLA automatic tracking
  - [ ] Automatic monthly reports

### Planned

- [ ] Web dashboard for monitoring
- [ ] Ansible playbooks for deployment
- [ ] Container images for testing
- [ ] CI/CD pipeline for validation

---

## Changelog

### v2.2.0 (Current - February 2026)

- **Ydea Toolkit Enhanced**: Contract-based SLA system with `contractId` field
  - Automatic application of SLA "Premium_Mon" from contract 171734
  - Removed need to explicitly specify `serviceLevelAgreement`
  - Complete testing with 6 validated tickets (all with Premium_Mon SLA)
  - Multi-user configuration (Alessandro Gaggiano, Lorenzo Angelini)
- **Consolidated Documentation**: Ydea-Toolkit from 17 to 2 essential files
  - main README.md (overview and quick start)
  - README-CHECKMK-INTEGRATION.md (complete integration guide)
  - Removed redundant and fragmented files
  - Fix 61 markdownlint warnings for code quality
- **ROCKSOLID Mode Production**: System completed and validated
  - Tested on 2 production hosts (nsec8-stable, laboratory)
  - Dynamic package download from OpenWrt repository
  - Auto-recovery post major-upgrade working
  - Git auto-install if removed during upgrade
  - Zero static/hardcoded URLs in scripts
### v2.1.0 (January 2026)

- **ROCKSOLID Mode**: Complete protection system for NethSecurity 8 agent CheckMK
  - Major upgrade resistant installation with 13 critical files protected
  - Automatic auto-recovery at startup (CheckMK Agent + FRP Client)
  - Support FRP v0.x and v1.x with existing config detection
  - Critical binary backups (`tar`, `ar`, `gzip`) protected from corruption
  - Automatic post-upgrade script for verification and recovery
  - Fix grep binary file detection on OpenWrt
  - Marker system for persistent FRP detection
  - Validated on NethSecurity 8.7.1 + CheckMK 2.4.0p20

### v2.0.0 (January 2026)

- **Cloud Backup**: Complete CheckMK backup system on cloud with rclone (S3/Spaces)
- **Auto-Upgrade CheckMK**: Automatic upgrade setup wizard via crontab
- **Auto-Sync Enhanced**: Automatic synchronization system with .copilot-context.md
- **S3/Spaces Compatibility**: Fix compatibility for cloud storage without mkdir
- **Unified Search**: Backup unified file/directory selection by timestamp
- **Language Preferences**: Repository configured for Italian 
- **Full Ydea Toolkit**: Ticketing integration with 30+ scripts
- **NethSecurity 8**: Full NS8 firewall support
- **Ubuntu/Linux enhanced**: 6 monitoring scripts (SSH, Fail2ban, Disk)
- **NS8 extended monitoring**: Containers, Webtop, Tomcat, services
- **Advanced deployment tools**: 28+ deployment and optimization tools
- **CheckMK tuning**: Interactive scripts tuning v2-v5
- **Automatic Git sync**: Repository automation with systemd
- **Reorganized directories**: Standardized full/doc structure (remote decommissioned)
- **Full documentation**: 15+ specific READMEs

### v1.5.0

- Added ransomware detection for Windows
- Reduced wrapper cache timeout (60s)
- Improved error handling script notification
- Complete documentation updated

### v1.4.0

- Enhanced smart deployment system
- Built-in official CheckMK patterns
- Boot directly from full scripts in `full/`

### v1.3.0

- Notification script with Real IP + Charts
- Automatic pre-deployment backup
- Comprehensive testing guides

### v1.2.0

- NethServer 8 Monitoring (Podman)
- Proxmox VE script
- Deploy automated tools

### v1.1.0

- Complete NethServer 7 script collection
- Automatic backup system
- Windows automation setup

### v1.0.0

- Initial release
- Basic script for CheckMK

---

**If you find this repository useful, please leave a star on GitHub!**

** Problems? Open an issue!**

** Do you want to contribute? PR is welcome!**

---

*Last update: January 2026*