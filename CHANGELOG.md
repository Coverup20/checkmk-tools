# Changelog

All notable changes to the CheckMK Tools project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2024-10-12

### Added

#### Agent Plugins
- **nethserver_check**: Custom check plugin for Nethserver 7.9 and 8
  - Monitors services (httpd-admin, email, Samba)
  - Tracks backup status and age
  - Checks database configuration
  - Monitors disk usage and mail queue
  - RAID array status monitoring

- **nethsecurity_check**: Custom check plugin for Nethsecurity firewall 7.9 and 8
  - Firewall status (Shorewall, iptables)
  - Connection tracking metrics
  - VPN status and client count
  - IDS/IPS monitoring (Suricata)
  - Threat blocking (Fail2ban, Snort)
  - Network interface monitoring
  - DHCP/DNS service status

- **proxmox_check**: Custom check plugin for Proxmox VE
  - Cluster status and quorum monitoring
  - VM and container status
  - Storage monitoring (local, Ceph, ZFS, LVM)
  - Replication status
  - Backup job monitoring
  - Network bridge status
  - Resource usage (CPU, memory)

- **vmware_check**: Custom check plugin for VMware ESXi
  - Hardware information and health sensors
  - Datastore and storage monitoring
  - VM status tracking
  - Network adapter status
  - vSwitch configuration
  - Maintenance mode detection
  - License information
  - NTP synchronization status

- **linux_client_check**: Custom check plugin for Linux clients
  - System information and kernel version
  - Package updates (apt/yum/zypper)
  - Service status monitoring
  - Firewall status (UFW/firewalld/iptables)
  - Failed services detection
  - Security tools (Fail2ban, ClamAV)
  - Docker container monitoring
  - Temperature sensors
  - System load and logged users

- **windows_client_check.ps1**: PowerShell plugin for Windows clients
  - Windows Update status
  - Windows Defender monitoring
  - Firewall status per profile
  - Disk usage tracking
  - BitLocker encryption status
  - Security event monitoring
  - Pending reboot detection
  - Performance metrics
  - Event Log error tracking
  - Certificate expiration alerts
  - License activation status

- **managed_switch_check**: SNMP-based switch monitoring
  - System information via SNMP
  - Port status and statistics
  - Traffic metrics per port
  - VLAN configuration
  - CPU and memory usage (Cisco-specific)
  - Temperature sensors
  - Fan and power supply status
  - Spanning Tree Protocol
  - MAC address table size

#### Bootstrap Scripts
- **00_bootstrap.sh**: Main bootstrap orchestrator
  - Fixed path issue (removed incorrect scripts/ subdirectory reference)
  - Automated sequential execution of all bootstrap scripts

- **10-ssh.sh**: SSH server configuration
  - Configurable SSH port
  - Security hardening
  - Root login control
  - Keep-alive settings

- **15-ntp.sh**: Time synchronization
  - systemd-timesyncd configuration
  - Configurable NTP servers
  - Timezone setup

- **20-packages.sh**: Base package installation
  - Essential tools installation
  - Unattended upgrades setup

- **25-postfix.sh**: Email relay configuration
  - Smarthost setup
  - SMTP authentication
  - Interactive or environment-based configuration

- **30-firewall.sh**: UFW firewall setup
  - Default deny incoming policy
  - SSH port configuration
  - HTTP/HTTPS port management

- **40-fail2ban.sh**: Intrusion prevention
  - SSH jail configuration
  - Automatic ban for failed logins

- **50-certbot.sh**: SSL certificate management
  - Let's Encrypt integration
  - Apache/Nginx/Standalone modes
  - Automatic certificate renewal

- **60-checkmk.sh**: CheckMK Raw installation
  - Automated download and installation
  - Site creation and startup
  - Admin password configuration

- **70-backup-retention.sh**: Backup automation (NEW)
  - Automated daily backups
  - Configurable retention policy
  - Systemd timer configuration
  - Backup cleanup automation

#### Documentation
- **README.md**: Comprehensive project documentation
  - Project overview and contents
  - Bootstrap script usage
  - Plugin deployment instructions
  - Troubleshooting guide

- **docs/QUICKSTART.md**: Quick start guide
  - 10-minute setup instructions
  - Minimal configuration examples
  - Step-by-step deployment
  - Common troubleshooting

- **docs/DEPLOYMENT_GUIDE.md**: Detailed deployment guide
  - System-specific configurations
  - Prerequisites and requirements
  - Deployment procedures
  - Service discovery instructions
  - Advanced troubleshooting
  - Best practices

- **docs/PLUGIN_REFERENCE.md**: Complete plugin reference
  - All plugin sections documented
  - Metrics and outputs explained
  - Performance considerations
  - Support matrix
  - Integration patterns

- **docs/CONTRIBUTING.md**: Contribution guidelines
  - Coding standards
  - Plugin development guidelines
  - Testing procedures
  - Pull request process
  - Community guidelines

#### Configuration
- **bootstrap/.env.example**: Environment configuration template
  - All configurable options documented
  - Example configurations for common scenarios
  - Security best practices

- **.gitignore**: Git ignore configuration
  - Sensitive files excluded (.env, secrets)
  - Build artifacts excluded
  - OS-specific files excluded

- **LICENSE**: MIT License
  - Open source license for the project

### Changed
- Fixed bootstrap script path from `$SCRIPT_DIR/scripts/$1` to `$SCRIPT_DIR/$1`
- Made all scripts executable by default
- Updated documentation to reflect current repository structure

### Security
- All bootstrap scripts include `set -euo pipefail` for safety
- Sensitive configuration stored in .env (not committed)
- SSH hardening in bootstrap
- Firewall rules configured by default
- Fail2ban enabled for intrusion prevention

### Technical Details

#### Repository Structure
```
checkmk-tools/
├── agents/
│   ├── plugins/          # Linux agent plugins
│   └── windows/          # Windows agent plugins
├── bootstrap/            # Server setup scripts
├── custom_checks/        # Additional custom checks
├── docs/                 # Documentation
└── [configuration files]
```

#### Code Statistics
- **Agent Plugins**: 969 lines across 7 plugins
- **Bootstrap Scripts**: 412 lines across 10 scripts
- **Documentation**: 2,216 lines across 5 documents
- **Total**: ~3,600 lines of code and documentation

#### Supported Systems
- Nethserver 7.9, 8.x
- Nethsecurity 7.9, 8.x
- Proxmox VE 6.x, 7.x, 8.x
- VMware ESXi 6.x, 7.x, 8.x
- Linux: Ubuntu, Debian, RHEL, CentOS, SUSE
- Windows: 10, 11, Server 2016+
- Managed Switches: Cisco, HP, Dell, Netgear (SNMP-enabled)

#### Monitoring Capabilities
- **250+ metrics** collected across all plugins
- **Real-time monitoring** of services and resources
- **Security monitoring** (IDS/IPS, Defender, Fail2ban)
- **Infrastructure monitoring** (VMs, containers, storage)
- **Network monitoring** (switches, VPNs, interfaces)
- **System health** (CPU, memory, disk, temperature)

### Dependencies
- Bash 4.0+ for shell scripts
- PowerShell 5.1+ for Windows plugin
- CheckMK Raw Edition 2.1.0+ recommended
- SNMP tools for switch monitoring
- Python 3 for Proxmox JSON parsing

### Installation
See [QUICKSTART.md](docs/QUICKSTART.md) for installation instructions.

### Upgrade Notes
This is the initial release. No upgrade path required.

## [Unreleased]

### Planned Features
- PostgreSQL/MySQL database monitoring plugins
- Enhanced Docker/Kubernetes monitoring
- Cloud provider integration (AWS, Azure, GCP)
- Custom application monitoring templates
- Log analysis plugins
- Backup verification tools
- Performance optimization tools
- Web-based configuration interface

---

## Release Notes

### Version 1.0.0 - Initial Release

This is the first stable release of CheckMK Tools, providing a complete solution for monitoring various IT infrastructure components with CheckMK Raw Edition.

**Highlights:**
- 7 custom agent plugins for diverse system types
- Automated CheckMK server bootstrap
- Comprehensive documentation
- Production-ready monitoring templates
- Security-focused implementation

**Getting Started:**
1. Clone the repository
2. Follow the [QUICKSTART.md](docs/QUICKSTART.md) guide
3. Deploy plugins to target systems
4. Configure monitoring in CheckMK GUI

**Support:**
- GitHub Issues: https://github.com/Coverup20/checkmk-tools/issues
- CheckMK Forum: https://forum.checkmk.com/
- Documentation: See docs/ directory

---

[1.0.0]: https://github.com/Coverup20/checkmk-tools/releases/tag/v1.0.0
