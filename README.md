# CheckMK Tools Collection

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CheckMK](https://img.shields.io/badge/CheckMK-Compatible-green.svg)](https://checkmk.com/)
[![Python](https://img.shields.io/badge/Python-3.6+-blue.svg)](https://www.python.org/)

Complete collection of scripts for monitoring and managing infrastructures with CheckMK. Includes local check scripts for multiple platforms, custom notification systems, deployment tools, cloud backup, and Ydea ticketing integration.

---

## Index

- [Repository Structure](#repository-structure)
- [Check Scripts](#check-scripts)
  - [NethServer 7](#nethserver-7)
  - [NethServer 8](#nethserver-8)
  - [NethSecurity 8](#nethsecurity-8)
  - [Ubuntu/Linux](#ubuntulinux)
  - [Proxmox](#proxmox)
  - [tmate Server](#tmate-server)
  - [Windows](#windows)
- [Notification Scripts](#notification-scripts)
- [Deployment Tools](#deployment-tools)
- [Ydea Toolkit](#ydea-toolkit)
- [Nethesis Branding](#nethesis-branding)
- [Installation](#installation)
- [Contributing](#contributing)
- [License](#license)

---

## Main Features

### Multi-Platform

- **Windows**: PowerShell scripts for Windows Server (AD, IIS, Ransomware Detection)
- **Linux**: Python scripts for NethServer, NethSecurity, Ubuntu, Proxmox
- **Container**: Podman/Docker monitoring on NethServer 8

### ROCKSOLID Mode - Upgrade Resistant Agent

- **NethSecurity 8**: CheckMK + FRP agent installation resistant to major upgrades
- **Auto-Recovery**: Startup script that restores services automatically
- **Binary Backup**: Protect `tar`, `ar`, `gzip` from corruption
- **FRP Dual-Format**: Support FRP v0.x and v1.x with auto detection
- **Dynamic packages**: Download from OpenWrt upstream repositories at runtime

### Automated Deployment

- **Smart Deploy**: Hybrid system for multi-host deployment
- **Interactive Menu**: Interactive deployment with script selection for OS
- **Agent Installer**: Unified agent installation script for multiple platforms

### Nethesis Branding for CheckMK

- **CSS override**: Logo, colors and CSS for CheckMK Facelift theme
- **Multi-server**: Deploy to all servers with a single script
- **Static assets**: SVG files in `nethesis-brand/`

### Automated Cloud Backup

- **rclone Integration**: Backup CheckMK to cloud storage (S3, DigitalOcean Spaces, etc.)
- **Intelligent Retention**: Automatic local and remote retention management
- **Monitoring Timer**: Systemd timer for periodic backup checks

### Advanced Notifications

- **Email Real IP**: Notifications with real IP even behind FRP proxy
- **Telegram Integration**: Telegram notifications with scenario detection
- **Ydea Ticketing**: Automatic ticket creation from CheckMK events

---

## Repository Structure

```text
checkmk-tools/
├── script-check-ns7/           # NethServer 7 check scripts
│   ├── full/                   # Python check scripts
│   └── doc/
├── script-check-ns8/           # NethServer 8 check scripts
│   ├── full/                   # Python check scripts
│   └── doc/
├── script-check-nsec8/         # NethSecurity 8 check scripts
│   ├── full/                   # Python check scripts
│   └── doc/
├── script-check-ubuntu/        # Ubuntu/Linux check scripts
│   ├── full/                   # Python check scripts
│   └── doc/
├── script-check-proxmox/       # Proxmox VE check scripts
│   ├── full/                   # Python check scripts
│   └── doc/
├── script-check-tmate-server/  # tmate server check scripts
│   └── full/
├── script-check-windows/       # Windows check scripts (PowerShell)
│   ├── full/
│   └── doc/
├── script-notify-checkmk/      # CheckMK notification scripts
│   ├── full/                   # Email, Telegram, Ydea
│   └── doc/
├── script-tools/               # Deployment and management tools
│   ├── full/
│   │   └── installation/       # Agent and service installers
│   └── doc/
├── script-checkmk/             # CheckMK server-side scripts
│   ├── full/
│   └── doc/
├── ydea-Toolkit/               # Ydea ticketing integration
│   ├── full/
│   ├── config/
│   └── doc/
├── nethesis-brand/             # CheckMK Nethesis branding assets
│   ├── theme.css
│   └── *.svg
├── script-ps-tools/            # PowerShell maintenance tools (Windows)
└── deploy-nethesis-brand.sh    # Deploy branding on CheckMK servers
```

---

## Check Scripts

All check scripts follow the CheckMK local check output format:

```text
<STATE> <SERVICE_NAME> - <message>
```

States: `0`=OK, `1`=WARNING, `2`=CRITICAL, `3`=UNKNOWN.

Scripts are deployed to `/usr/lib/check_mk_agent/local/` on the monitored host, **without the `.py` extension**.

### NethServer 7

**Directory**: `script-check-ns7/full/`

Complete monitoring for NethServer 7 (CentOS 7 based).

| Script | Description |
|--------|-------------|
| `check_cockpit_sessions.py` | Active Cockpit sessions |
| `check_dovecot_sessions.py` | IMAP/POP3 active sessions |
| `check_dovecot_maxuserconn.py` | Max connections per user |
| `check_dovecot_status.py` | Dovecot service status |
| `check_dovecot_vsz.py` | Dovecot memory usage (VSZ) |
| `check_postfix_status.py` | Postfix service status |
| `check_postfix_process.py` | Active Postfix processes |
| `check_postfix_queue.py` | Email queue length |
| `check_webtop_status.py` | Webtop5 service status |
| `check_webtop_maxmemory.py` | Webtop memory allocation |
| `check_webtop_https.py` | Webtop HTTPS / certificate expiry |
| `check_ssh_root_logins.py` | SSH root login attempts |
| `check_ssh_root_sessions.py` | Active root SSH sessions |
| `check_ssh_all_sessions.py` | All SSH sessions |
| `check-ssh-failures.py` | SSH failed attempts |
| `check_fail2ban_status.py` | Fail2ban service status |
| `check_ransomware_ns7.py` | Ransomware detection |
| `check-sos-ns7.py` | SOS report generation |
| `check-sosid-ns7.py` | SOS report case ID tracking |
| `check-pkg-install.py` | Installed package count |

---

### NethServer 8

**Directory**: `script-check-ns8/full/`

Monitoring for NethServer 8 (Podman/Container based).

| Script | Description |
|--------|-------------|
| `check_ns8_containers.py` | Container status overview |
| `check_ns8_container_status.py` | Individual container status |
| `check_ns8_container_health.py` | Container health checks |
| `check_ns8_container_resources.py` | Container CPU/memory usage |
| `check_ns8_container_inventory.py` | Container inventory |
| `check_ns8_services.py` | NS8 service status |
| `check_ns8_webtop.py` | Webtop service monitoring |
| `check_ns8_tomcat8.py` | Tomcat8 status |
| `check_ns8_smoke_test.py` | Smoke test for NS8 modules |
| `check_nv8_status_trunk.py` | NethVoice trunk status |
| `check_nv8_status_extensions.py` | NethVoice extensions status |
| `check-sos.py` | SOS report generation |
| `acl-viewer.py` | ACL permissions viewer |
| `monitor_podman_events.py` | Real-time Podman event monitor |

---

### NethSecurity 8

**Directory**: `script-check-nsec8/full/`

Monitoring for NethSecurity 8 (OpenWrt-based firewall).

| Script | Description |
|--------|-------------|
| `check_wan_status.py` | WAN interface status |
| `check_wan_throughput.py` | WAN bandwidth utilization |
| `check_vpn_tunnels.py` | VPN tunnel status |
| `check_ovpn_host2net.py` | OpenVPN host-to-net connections |
| `check_firewall_rules.py` | Firewall rule count and status |
| `check_firewall_connections.py` | Active firewall connections |
| `check_firewall_traffic.py` | Firewall traffic statistics |
| `check_dhcp_leases.py` | DHCP lease usage |
| `check_dns_resolution.py` | DNS resolution check |
| `check_martian_packets.py` | Martian packet detection |
| `check_root_access.py` | Root access attempts |
| `check_uptime.py` | System uptime |
| `check_opkg_packages.py` | OpenWrt package status |

---

### Ubuntu/Linux

**Directory**: `script-check-ubuntu/full/`

Generic check scripts for Ubuntu/Debian distributions.

| Script | Description |
|--------|-------------|
| `check_disk_space.py` | Disk space usage |
| `check_fail2ban_status.py` | Fail2ban status and ban count |
| `check_ssh_root_logins.py` | SSH root login attempts |
| `check_ssh_root_sessions.py` | Active root SSH sessions |
| `check_ssh_all_sessions.py` | All SSH sessions |
| `check_arp_watch.py` | ARP watch / MAC address changes |
| `check_tmate_session.py` | tmate session status |
| `check_efivars.py` | EFI variables check |

---

### Proxmox

**Directory**: `script-check-proxmox/full/`

Proxmox Virtual Environment monitoring via API.

| Script | Description |
|--------|-------------|
| `check-proxmox-vm-status.py` | VM running/stopped status |
| `check-proxmox_qemu_status.py` | QEMU VM status |
| `check-proxmox_qemu_runtime.py` | QEMU VM runtime |
| `check-proxmox_qemu_guest_agent_status.py` | QEMU Guest Agent status |
| `check-proxmox_lxc_status.py` | LXC container status |
| `check-proxmox_lxc_runtime.py` | LXC container runtime |
| `check-proxmox_storage_status.py` | Storage pool status |
| `check-proxmox_backup_status.py` | Backup job status |
| `check-proxmox_services_status.py` | Proxmox service status |
| `check-proxmox_vm_monitor.py` | General VM monitor (CPU, RAM, Disk) |

**Requirements**: Proxmox API token with read permissions, `curl`, `jq`.

---

### tmate Server

**Directory**: `script-check-tmate-server/full/`

| Script | Description |
|--------|-------------|
| `check_tmate_server.py` | tmate-ssh-server connectivity and status |

---

### Windows

**Directory**: `script-check-windows/`

PowerShell scripts for Windows Server monitoring including ransomware detection on network shares.

**Features**:

- Multi-pattern detection (suspicious extensions, known ransomware patterns, I/O speed)
- Canary file monitoring
- Timeout protection for slow/blocked shares
- Detailed metrics per share

**Quick Start**:

```powershell
# Deploy on Windows Server
Copy-Item check_ransomware_activity.ps1, ransomware_config.json `
    -Destination "C:\ProgramData\checkmk\agent\local\"

# Manual test
.\check_ransomware_activity.ps1 -VerboseLog
```

**Documentation**: [script-check-windows/README.md](script-check-windows/README.md)

---

## Notification Scripts

**Directory**: `script-notify-checkmk/full/`

Custom CheckMK notification scripts with real IP detection (for hosts behind FRP proxy), HTML email with graphs, and Telegram integration.

### Real IP Detection

Extracts the real client IP even when hosts are behind an FRP proxy:

```python
if 'NOTIFY_HOSTLABEL_real_ip' in os.environ:
    real_ip = os.environ['NOTIFY_HOSTLABEL_real_ip']
```

### Email

| Script | Description |
|--------|-------------|
| `mail_realip` | Email with real IP extraction (FRP-aware) |

### Telegram

| Script | Description |
|--------|-------------|
| `telegram_realip` | Telegram notification with real IP |
| `telegram_selfmon` | Telegram self-monitoring alert |
| `telegram_c01` | Telegram channel C01 |
| `telegram_c01_selfmon` | Telegram C01 self-monitoring |
| `telegram_cl00` | Telegram CL00 notifications |
| `telegram_tmate.py` | Telegram tmate session notifications |

### Ydea Integration

| Script | Description |
|--------|-------------|
| `ydea_la` | Ydea LA ticketing notification |
| `ydea_ag` | Ydea AG ticketing notification |
| `ydea_cache_validator.py` | Ticket cache validator |
| `notify_ticket_watcher.py` | Monitor open notification tickets |

### Deployment

```bash
# On CheckMK server (as site user)
cp mail_realip /omd/sites/SITENAME/local/share/check_mk/notifications/
chmod +x /omd/sites/SITENAME/local/share/check_mk/notifications/mail_realip

# Configure in Web GUI:
# Setup -> Notifications -> New Rule -> Notification Method: mail_realip
```

**Documentation**: [script-notify-checkmk/TESTING_GUIDE.md](script-notify-checkmk/TESTING_GUIDE.md)

---

## Deployment Tools

**Directory**: `script-tools/full/`

Python tools for CheckMK agent deployment, infrastructure management, backup, and tuning.

### Agent Installation

| Script | Description |
|--------|-------------|
| `installation/install-checkmk-agent-persistent-nsec8.*` | ROCKSOLID installer for NethSecurity 8 |
| `install_frpc.py` | FRP client installation |
| `deploy-plain-agent.py` | Deploy agent to a single host |
| `deploy-plain-agent-multi.py` | Multi-host deployment from list |

#### ROCKSOLID Mode - Upgrade Resistant Installation

Advanced protection system for **NethSecurity 8** that keeps CheckMK Agent and FRP Client operational across major system upgrades.

**Features**:

- Adds critical files to `/etc/sysupgrade.conf` (survive upgrades)
- Binary backup for `tar`, `ar`, `gzip` (protects against corruption)
- Startup auto-recovery script
- FRP v0.x and v1.x support with auto-detection
- Dynamic package download from OpenWrt repositories

**Installation**:

```bash
curl -fsSL https://raw.githubusercontent.com/nethesis/checkmk-tools/main/script-tools/full/installation/install-checkmk-agent-persistent-nsec8.sh | bash
```

**Validated on**: NethSecurity 8.7.1 (OpenWrt 23.05.0), CheckMK Agent 2.4.0p20.

### tmate Integration

| Script | Description |
|--------|-------------|
| `installation/install-tmate-server.py` | Install and configure tmate-ssh-server |
| `installation/install-tmate-client.py` | Install and configure tmate client |
| `installation/setup-tmate-token-push.py` | Configure token push to server |
| `installation/tmate-receive-token.py` | Receive and store tmate tokens (forced command) |

### Backup and Recovery

| Script | Description |
|--------|-------------|
| `backup_restore/checkmk_rclone_space_dyn.py` | Cloud backup with rclone (S3/Spaces) |
| `backup_restore/checkmk_backup.py` | Local CheckMK backup |
| `backup_restore/checkmk_restore.py` | CheckMK restore |
| `backup_restore/checkmk_disaster_recovery.py` | Disaster recovery workflow |
| `cleanup-checkmk-retention.py` | Backup retention cleanup |

### CheckMK Tuning and Upgrade

| Script | Description |
|--------|-------------|
| `checkmk-tuning-interactive-v5.py` | Interactive CheckMK tuning wizard |
| `checkmk_optimize.py` | Automated CheckMK optimization |
| `upgrade-checkmk.py` | Automated CheckMK upgrade |
| `setup-auto-upgrade-checkmk.py` | Setup auto-upgrade via crontab |

### Monitoring Script Deployment

| Script | Description |
|--------|-------------|
| `deploy-monitoring-scripts.py` | OS-aware interactive script deployment |
| `smart-deploy-hybrid.py` | Multi-host deployment with cache |
| `deploy_monitoring.py` | Batch monitoring deployment |

### Repository Sync

```bash
# Install auto-sync as systemd service or cron
python3 /opt/checkmk-tools/script-tools/full/install-auto-git-sync.py
```

The repository is automatically synchronized on CheckMK servers. After cloning to `/opt/checkmk-tools/`, the sync service runs `git pull` periodically. Never edit files directly in `/opt/checkmk-tools/` — changes will be overwritten.

---

## Ydea Toolkit

**Directory**: `ydea-Toolkit/`

Complete integration between CheckMK and the Ydea helpdesk system for automatic ticket creation from monitoring events.

**Structure**:

- `full/` — Integration scripts
- `config/` — Configuration files
- `doc/` — Documentation

### Main Features

- Automatic ticket creation from CheckMK PROBLEM/RECOVERY events
- SLA discovery from customer contracts
- Ticket deduplication and state tracking
- Health monitor for integration status

### Key Scripts

| Script | Description |
|--------|-------------|
| `ydea_monitoring_integration.py` | Core CheckMK-Ydea integration |
| `install_ydea_checkmk_integration.py` | Automated installation |
| `ydea_health_monitor.py` | Integration health monitoring |
| `ydea_ticket_monitor.py` | Open ticket monitor |
| `ydea_discover_sla_ids.py` | Automatic SLA discovery from contracts |
| `ydea-toolkit.py` | Ydea API master toolkit |

### Configuration

```bash
# Required: .env file with credentials
YDEA_ID="your_company_id"
YDEA_API_KEY="YOUR_API_KEY_HERE"
YDEA_CONTRATTO_ID="your_contract_id"
```

### Quick Start

```bash
# 1. Installation
cd ydea-Toolkit/full
python3 install_ydea_checkmk_integration.py

# 2. Configure credentials
cp .env.example .env
vim .env

# 3. Automatic SLA discovery
python3 ydea_discover_sla_ids.py

# 4. Monitor health
python3 ydea_health_monitor.py
```

**Documentation**: [ydea-Toolkit/README.md](ydea-Toolkit/README.md)

---

## Nethesis Branding

**Directory**: `nethesis-brand/`

CSS and SVG assets to apply Nethesis visual identity to the CheckMK web interface (Facelift theme).

**Files**:

- `theme.css` — CSS overrides for colors and fonts
- `checkmk_logo.svg` — Login page logo (290px)
- `icon_checkmk_logo.svg` — Sidebar icon (40px)
- `icon_checkmk_logo_min.svg` — Sidebar icon (28px)

**Deploy**:

```bash
./deploy-nethesis-brand.sh
```

---

## Installation

### Requirements

**Linux (all platforms)**:

- Python 3.6+
- CheckMK Agent installed
- `curl` (for some tools)

**Windows**:

- PowerShell 5.1+
- CheckMK Agent for Windows

### Deploy a Check Script

```bash
# Clone the repository
git clone https://github.com/nethesis/checkmk-tools.git /opt/checkmk-tools

# Copy the desired script to the local checks directory (no extension)
cp /opt/checkmk-tools/script-check-ns7/full/check_dovecot_status.py \
   /usr/lib/check_mk_agent/local/check_dovecot_status
chmod +x /usr/lib/check_mk_agent/local/check_dovecot_status

# Verify output
/usr/lib/check_mk_agent/local/check_dovecot_status
```

Scripts are deployed **without the `.py` extension** so CheckMK executes them directly.

### Auto-Sync Setup

To keep scripts automatically updated on a server:

```bash
python3 /opt/checkmk-tools/script-tools/full/install-auto-git-sync.py
```

### Notification Script Installation

```bash
# On CheckMK server (as root)
git clone https://github.com/nethesis/checkmk-tools.git /tmp/checkmk-tools
cp /tmp/checkmk-tools/script-notify-checkmk/full/mail_realip \
   /omd/sites/SITENAME/local/share/check_mk/notifications/
chmod +x /omd/sites/SITENAME/local/share/check_mk/notifications/mail_realip
```

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/check-name`
3. Write the script following the Python style below
4. Commit: `git commit -m 'feat(platform): add check_name v1.0.0'`
5. Open a Pull Request

### Python Style

All scripts follow the Nethesis Python style (reference: `NethServer/nethsecurity`):

```python
#!/usr/bin/python3
#
# Copyright (C) 2025 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

# Check <service> status

import subprocess

SERVICE = "ServiceName"

## Utils

def run(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return p.returncode, p.stdout, p.stderr
    except Exception as e:
        return 1, "", str(e)

## Check

def check():
    rc, out, err = run(["systemctl", "is-active", "myservice"])
    if rc != 0:
        print(f"2 {SERVICE} - CRITICAL: service not running")
        return
    print(f"0 {SERVICE} - OK: running")

check()
```

**Rules**:

- No classes, no `if __name__ == "__main__"` — call the function directly at module level
- No type hints, no docstrings on obvious functions
- `subprocess.run` with `capture_output=True, text=True` — never `shell=True`
- CheckMK output format: `<STATE> <SERVICE> - <message>`
- Script version in `VERSION = "x.y.z"` variable at module level

### Naming Convention

- Check scripts: `check_<name>.py`
- Deployed name (no extension): `check_<name>`
- CheckMK service name: `ServiceName` (matches the `SERVICE` constant)

---

## Auto-Sync System

The repository uses an automatic synchronization system on CheckMK servers:

```text
GitHub (nethesis/checkmk-tools)
    ↓ [auto-git-sync - every 1-5 minutes]
/opt/checkmk-tools/ (on servers)
    ↓ [execute scripts from local repo]
Production
```

### Check Sync Status

```bash
# Service status
systemctl status auto-git-sync.service

# Force manual sync
cd /opt/checkmk-tools && git pull

# Recent logs
journalctl -u auto-git-sync.service -n 50
```

---

## CheckMK Cloud Backup

Complete script for automated CheckMK backup to cloud storage via rclone.

**File**: `script-tools/full/backup_restore/checkmk_rclone_space_dyn.py`

**Features**:

- Multi-cloud: S3, DigitalOcean Spaces, Google Drive, etc.
- Automatic local and remote retention management
- Systemd timer for periodic backup checks
- S3-compatible API (no mkdir required)

**Quick Start**:

```bash
cd /opt/checkmk-tools/script-tools/full
python3 checkmk_rclone_space_dyn.py setup
```

---

## Security

- Do not commit credentials in config files — use environment variables
- Limit file permissions: `600` for sensitive configs (`.env`, key files)
- Use HTTPS for API communications
- Set timeouts for all network operations

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

## Platform Coverage

| Platform | Check Scripts | Description |
|----------|--------------|-------------|
| NethServer 7 | 20 | CentOS 7 based server |
| NethServer 8 | 14 | Container/Podman based server |
| NethSecurity 8 | 13 | OpenWrt-based firewall |
| Ubuntu/Linux | 8 | Generic Debian/Ubuntu |
| Proxmox VE | 10 | Virtualization platform |
| tmate Server | 1 | SSH session sharing |
| Windows | - | PowerShell scripts |

---

*Developed for the CheckMK community.*
