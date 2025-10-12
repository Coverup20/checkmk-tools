# CheckMK Tools Repository

This repository contains tools, scripts, and custom check plugins for CheckMK Raw monitoring system implementation.

## Contents

- **bootstrap/**: Bootstrap scripts for CheckMK server installation and configuration
- **agents/plugins/**: Custom check plugins for various systems
- **agents/windows/**: Windows-specific check plugins
- **custom_checks/**: Additional custom check scripts
- **docs/**: Documentation for deployment and usage

## Bootstrap Scripts

The bootstrap scripts automate the installation and configuration of a CheckMK monitoring server on Debian/Ubuntu systems.

### Prerequisites

- Debian 11/12 or Ubuntu 20.04/22.04 LTS
- Root access
- Internet connectivity

### Usage

1. Clone this repository
2. Copy `.env.example` to `.env` and configure your settings
3. Run the bootstrap script:

```bash
cd bootstrap
sudo ./00_bootstrap.sh
```

### Bootstrap Components

- **10-ssh.sh**: SSH configuration and hardening
- **15-ntp.sh**: Time synchronization setup
- **20-packages.sh**: Install base packages
- **25-postfix.sh**: Email relay configuration (smarthost)
- **30-firewall.sh**: UFW firewall setup
- **40-fail2ban.sh**: Intrusion prevention configuration
- **50-certbot.sh**: Let's Encrypt SSL certificate setup
- **60-checkmk.sh**: CheckMK Raw installation and site creation
- **70-backup-retention.sh**: Automatic backup configuration

## Custom Check Plugins

This repository includes custom agent plugins for monitoring various systems and platforms.

### Supported Systems

1. **Nethserver 7.9 / 8**
2. **Nethsecurity 7.9 / 8** (Firewall)
3. **Proxmox VE**
4. **VMWare ESXi**
5. **Linux Clients**
6. **Windows Clients**
7. **Managed Switches** (SNMP-based)

### Plugin Deployment

#### Linux Systems

Copy the plugin to the CheckMK agent plugins directory:

```bash
# For agent-based monitoring
sudo cp agents/plugins/<plugin_name> /usr/lib/check_mk_agent/plugins/
sudo chmod +x /usr/lib/check_mk_agent/plugins/<plugin_name>

# Test the plugin
sudo /usr/lib/check_mk_agent/plugins/<plugin_name>
```

#### Windows Systems

Copy the PowerShell plugin to the Windows agent plugins directory:

```powershell
# Copy to agent plugins directory
Copy-Item agents/windows/*.ps1 "C:\ProgramData\checkmk\agent\plugins\"

# Test the plugin
powershell -ExecutionPolicy Bypass -File "C:\ProgramData\checkmk\agent\plugins\windows_client_check.ps1"
```

## Plugin Details

### Nethserver Check (`nethserver_check`)

Monitors Nethserver 7.9 and 8 systems, collecting:
- Service status (httpd-admin, Samba, email services)
- Database configuration status
- Backup status and age
- Disk usage
- Email queue
- RAID status (if configured)

**Deployment:**
```bash
sudo cp agents/plugins/nethserver_check /usr/lib/check_mk_agent/plugins/
sudo chmod +x /usr/lib/check_mk_agent/plugins/nethserver_check
```

### Nethsecurity Check (`nethsecurity_check`)

Monitors Nethsecurity firewall systems (7.9/8), collecting:
- Firewall service status (Shorewall)
- Connection tracking
- VPN status (OpenVPN)
- IDS/IPS status (Suricata)
- Threat blocking services (Fail2ban)
- Network interfaces
- DHCP/DNS services

**Deployment:**
```bash
sudo cp agents/plugins/nethsecurity_check /usr/lib/check_mk_agent/plugins/
sudo chmod +x /usr/lib/check_mk_agent/plugins/nethsecurity_check
```

### Proxmox VE Check (`proxmox_check`)

Monitors Proxmox Virtual Environment, collecting:
- Cluster status and quorum
- Proxmox services status
- VM and Container status
- Storage status
- Replication status
- Backup configuration
- Ceph status (if configured)
- ZFS pool status
- Network bridges

**Deployment:**
```bash
sudo cp agents/plugins/proxmox_check /usr/lib/check_mk_agent/plugins/
sudo chmod +x /usr/lib/check_mk_agent/plugins/proxmox_check
```

### VMWare ESXi Check (`vmware_check`)

Monitors VMWare ESXi hosts via SSH, collecting:
- Hardware information
- Storage adapters and datastores
- Network adapters
- VM status
- vSwitch configuration
- Health sensors
- Maintenance mode status
- License information
- NTP synchronization

**Note:** For comprehensive VMware vCenter monitoring, use CheckMK's built-in VMware special agent.

**Deployment:**
```bash
sudo cp agents/plugins/vmware_check /usr/lib/check_mk_agent/plugins/
sudo chmod +x /usr/lib/check_mk_agent/plugins/vmware_check
```

### Linux Client Check (`linux_client_check`)

Monitors standard Linux client systems, collecting:
- System information and updates
- Service status
- Firewall status (UFW/firewalld/iptables)
- Disk usage
- Failed services
- Security tools (Fail2ban, ClamAV)
- Auto-update configuration
- System load and logged users
- Temperature sensors
- Docker containers (if installed)

**Deployment:**
```bash
sudo cp agents/plugins/linux_client_check /usr/lib/check_mk_agent/plugins/
sudo chmod +x /usr/lib/check_mk_agent/plugins/linux_client_check
```

### Windows Client Check (`windows_client_check.ps1`)

Monitors Windows client systems, collecting:
- System information and updates
- Windows Defender status
- Firewall status
- Disk usage
- BitLocker status
- Security events and failed logins
- Pending reboot status
- Performance metrics
- Event Log errors
- Network adapters
- Certificate expiration
- License activation

**Deployment:**
```powershell
# Copy to plugins directory
Copy-Item agents/windows/windows_client_check.ps1 "C:\ProgramData\checkmk\agent\plugins\"

# Or use CheckMK agent bakery to deploy
```

### Managed Switch Check (`managed_switch_check`)

Monitors managed switches via SNMP, collecting:
- System information
- Port status and statistics
- Traffic statistics per port
- VLAN configuration
- CPU and memory usage
- Temperature sensors
- Fan and power supply status
- Spanning Tree Protocol status
- MAC address table size

**Configuration:**

Create a configuration file at `/etc/check_mk/switch_config.conf`:

```bash
SWITCH_IP="192.168.1.1"
SNMP_COMMUNITY="public"
SNMP_VERSION="2c"
```

**Deployment:**
```bash
sudo cp agents/plugins/managed_switch_check /usr/lib/check_mk_agent/plugins/
sudo chmod +x /usr/lib/check_mk_agent/plugins/managed_switch_check

# Install SNMP tools
sudo apt-get install snmp snmp-mibs-downloader  # Debian/Ubuntu
sudo yum install net-snmp-utils                 # RHEL/CentOS
```

## CheckMK Configuration

After deploying agent plugins, configure CheckMK to discover and monitor the new services:

1. Log into CheckMK web interface
2. Navigate to **Setup → Hosts**
3. Select the host where you deployed the plugin
4. Click **Save & run service discovery**
5. Review discovered services and click **Accept all**
6. Activate changes

## Backup and Retention

The `70-backup-retention.sh` script sets up automatic daily backups of the CheckMK site:

- **Backup directory:** `/var/lib/checkmk_backups`
- **Schedule:** Daily at 2:00 AM
- **Retention:** 30 days (configurable)

### Manual Backup

```bash
sudo /usr/local/bin/checkmk_backup.sh
```

### Check Backup Status

```bash
# View timer status
sudo systemctl status checkmk-backup.timer

# List backups
ls -lh /var/lib/checkmk_backups/
```

### Restore from Backup

```bash
# Stop the site
sudo omd stop monitoring

# Restore backup
sudo omd restore monitoring /var/lib/checkmk_backups/monitoring_backup_YYYYMMDD_HHMMSS.tar.gz

# Start the site
sudo omd start monitoring
```

## Troubleshooting

### Plugin Not Showing Data

1. Verify plugin is executable:
   ```bash
   sudo ls -l /usr/lib/check_mk_agent/plugins/
   ```

2. Test plugin manually:
   ```bash
   sudo /usr/lib/check_mk_agent/plugins/<plugin_name>
   ```

3. Check CheckMK agent output:
   ```bash
   sudo check_mk_agent | grep "<<<plugin_section>>>"
   ```

4. Run service discovery in CheckMK GUI

### Permission Issues

Ensure plugins have correct permissions:
```bash
sudo chown root:root /usr/lib/check_mk_agent/plugins/*
sudo chmod 755 /usr/lib/check_mk_agent/plugins/*
```

### SNMP Issues (Switch Monitoring)

1. Verify SNMP is enabled on the switch
2. Test SNMP connectivity:
   ```bash
   snmpwalk -v 2c -c public <switch_ip> system
   ```
3. Check firewall rules allow SNMP (UDP port 161)

## Contributing

Contributions are welcome! Please submit pull requests or open issues for bugs and feature requests.

## License

This project is provided as-is for use with CheckMK monitoring systems.

## Support

For CheckMK-specific questions, refer to the [official CheckMK documentation](https://docs.checkmk.com/).

## Authors

- CheckMK Tools Contributors

## Version History

- **1.0.0** - Initial release with custom plugins for Nethserver, Nethsecurity, Proxmox, VMWare, Linux/Windows clients, and managed switches
