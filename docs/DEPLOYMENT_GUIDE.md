# CheckMK Custom Plugins - Deployment Guide

This guide provides detailed instructions for deploying and configuring custom CheckMK agent plugins for various systems.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [CheckMK Server Setup](#checkmk-server-setup)
3. [Agent Plugin Deployment](#agent-plugin-deployment)
4. [System-Specific Configurations](#system-specific-configurations)
5. [Service Discovery](#service-discovery)
6. [Troubleshooting](#troubleshooting)

## Prerequisites

### CheckMK Server

- CheckMK Raw Edition 2.1.0 or later
- Ubuntu 20.04/22.04 or Debian 11/12
- Minimum 2GB RAM, 20GB disk space
- Internet access for package downloads

### Monitored Hosts

- CheckMK agent installed
- SSH access for deployment
- Appropriate permissions for monitoring tasks

## CheckMK Server Setup

### Quick Setup with Bootstrap

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Coverup20/checkmk-tools.git
   cd checkmk-tools/bootstrap
   ```

2. **Create configuration file:**
   ```bash
   cp .env.example .env
   nano .env
   ```

3. **Configure essential settings in `.env`:**
   ```bash
   # System Configuration
   TIMEZONE="Europe/Rome"
   SSH_PORT=22
   PERMIT_ROOT_LOGIN=no
   
   # Network Configuration
   OPEN_HTTP_HTTPS=true
   
   # CheckMK Configuration
   CHECKMK_DEB_URL="https://download.checkmk.com/checkmk/2.2.0p15/check-mk-raw-2.2.0p15_0.jammy_amd64.deb"
   CHECKMK_ADMIN_PASSWORD="YourSecurePassword"
   
   # Email Configuration (optional)
   LETSENCRYPT_EMAIL="admin@yourdomain.com"
   LETSENCRYPT_DOMAINS="monitoring.yourdomain.com"
   ```

4. **Run bootstrap:**
   ```bash
   sudo ./00_bootstrap.sh
   ```

5. **Access CheckMK:**
   - URL: `https://your-server/monitoring/`
   - Username: `cmkadmin`
   - Password: (as configured in .env)

### Manual Setup

If you already have CheckMK installed, skip to [Agent Plugin Deployment](#agent-plugin-deployment).

## Agent Plugin Deployment

### General Deployment Steps

1. **Prepare the plugin:**
   ```bash
   cd checkmk-tools
   chmod +x agents/plugins/*
   ```

2. **Copy to remote host:**
   ```bash
   # Linux hosts
   scp agents/plugins/<plugin_name> user@remote-host:/tmp/
   
   # Then on remote host:
   sudo mv /tmp/<plugin_name> /usr/lib/check_mk_agent/plugins/
   sudo chmod 755 /usr/lib/check_mk_agent/plugins/<plugin_name>
   ```

3. **Verify plugin execution:**
   ```bash
   sudo check_mk_agent | grep "<<<plugin_section>>>"
   ```

### Using CheckMK Agent Bakery (Recommended)

For CheckMK Enterprise Edition:

1. Navigate to **Setup → Agents → Windows, Linux, Solaris, AIX**
2. Click **Agent rules**
3. Create rule: **Deploy custom files with agent**
4. Upload plugin files
5. Bake agents and deploy

## System-Specific Configurations

### Nethserver 7.9 / 8

**Plugin:** `nethserver_check`

**Deployment:**
```bash
# On Nethserver host
sudo wget -O /usr/lib/check_mk_agent/plugins/nethserver_check \
  https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/agents/plugins/nethserver_check
sudo chmod 755 /usr/lib/check_mk_agent/plugins/nethserver_check

# Test
sudo /usr/lib/check_mk_agent/plugins/nethserver_check
```

**Monitored Items:**
- Nethserver services (httpd-admin, rsyslog, cockpit)
- Email services (Postfix, Dovecot, Amavis)
- Samba services (smb, nmb)
- Database configuration entries
- Backup age and status
- RAID arrays

**Permissions Required:**
- Read access to `/var/lib/nethserver/backup`
- Execute systemctl commands
- Read access to configuration database

### Nethsecurity 7.9 / 8

**Plugin:** `nethsecurity_check`

**Deployment:**
```bash
# On Nethsecurity firewall
sudo wget -O /usr/lib/check_mk_agent/plugins/nethsecurity_check \
  https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/agents/plugins/nethsecurity_check
sudo chmod 755 /usr/lib/check_mk_agent/plugins/nethsecurity_check
```

**Monitored Items:**
- Firewall status (Shorewall, iptables)
- VPN connections (OpenVPN)
- IDS/IPS (Suricata)
- Threat blocking (Fail2ban, Snort)
- Network interfaces
- DHCP leases
- DNS service

**Permissions Required:**
- Execute shorewall commands
- Read `/proc/net/nf_conntrack`
- Execute iptables commands
- Read OpenVPN logs
- Execute fail2ban-client

### Proxmox VE

**Plugin:** `proxmox_check`

**Deployment:**
```bash
# On Proxmox host
sudo wget -O /usr/lib/check_mk_agent/plugins/proxmox_check \
  https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/agents/plugins/proxmox_check
sudo chmod 755 /usr/lib/check_mk_agent/plugins/proxmox_check

# Install dependencies
sudo apt-get install python3
```

**Monitored Items:**
- Cluster status and quorum
- Proxmox services
- VMs and containers
- Storage (local, Ceph, ZFS)
- Replication
- Backups
- Network bridges

**Permissions Required:**
- Execute pvecm, qm, pct, pvesh commands
- Read `/etc/pve/` configuration
- Execute zpool, ceph commands

### VMWare ESXi

**Plugin:** `vmware_check`

**Note:** This plugin works via SSH on ESXi hosts. For vCenter monitoring, use CheckMK's built-in VMware special agent.

**Deployment:**
```bash
# Enable SSH on ESXi host first (via vSphere client)
# Then copy plugin
scp agents/plugins/vmware_check root@esxi-host:/tmp/
ssh root@esxi-host "mv /tmp/vmware_check /usr/lib/check_mk_agent/plugins/ && chmod 755 /usr/lib/check_mk_agent/plugins/vmware_check"
```

**Monitored Items:**
- Hardware information
- Datastores and storage
- Network adapters
- VM status
- vSwitch configuration
- System resources
- Hardware health sensors
- Maintenance mode

**Permissions Required:**
- Root or administrator access
- SSH enabled on ESXi

### Linux Clients

**Plugin:** `linux_client_check`

**Deployment:**
```bash
# Copy to Linux client
sudo wget -O /usr/lib/check_mk_agent/plugins/linux_client_check \
  https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/agents/plugins/linux_client_check
sudo chmod 755 /usr/lib/check_mk_agent/plugins/linux_client_check

# Install optional dependencies
sudo apt-get install lm-sensors  # For temperature monitoring
```

**Monitored Items:**
- System information and kernel
- Available updates (apt/yum/zypper)
- Service status
- Firewall (UFW/firewalld/iptables)
- Failed services
- Security tools (Fail2ban, ClamAV)
- Docker containers
- Temperature sensors
- System load

**Supported Distributions:**
- Ubuntu 18.04+
- Debian 10+
- RHEL/CentOS 7+
- SUSE Linux

### Windows Clients

**Plugin:** `windows_client_check.ps1`

**Deployment:**

1. **Via CheckMK Agent:**
   ```powershell
   # On Windows client (as Administrator)
   $url = "https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/agents/windows/windows_client_check.ps1"
   $dest = "C:\ProgramData\checkmk\agent\plugins\windows_client_check.ps1"
   Invoke-WebRequest -Uri $url -OutFile $dest
   ```

2. **Test the plugin:**
   ```powershell
   powershell -ExecutionPolicy Bypass -File "C:\ProgramData\checkmk\agent\plugins\windows_client_check.ps1"
   ```

**Monitored Items:**
- Windows version and build
- Windows Updates
- Windows Defender status
- Firewall status
- Disk usage
- BitLocker encryption
- Security events
- Pending reboot
- Performance metrics
- Event Log errors
- Certificates expiration
- License activation

**Requirements:**
- PowerShell 5.1 or later
- CheckMK agent for Windows installed
- Administrator privileges for full monitoring

### Managed Switches

**Plugin:** `managed_switch_check`

**Note:** This plugin uses SNMP. Configure CheckMK's SNMP monitoring in the GUI for comprehensive switch monitoring.

**Deployment:**

1. **Enable SNMP on the switch** (example for Cisco):
   ```
   configure terminal
   snmp-server community public RO
   snmp-server enable traps
   ```

2. **Deploy plugin:**
   ```bash
   # On CheckMK server or monitoring proxy
   sudo cp agents/plugins/managed_switch_check /usr/lib/check_mk_agent/plugins/
   sudo chmod 755 /usr/lib/check_mk_agent/plugins/managed_switch_check
   
   # Install SNMP tools
   sudo apt-get install snmp snmp-mibs-downloader
   ```

3. **Configure switch details:**
   ```bash
   sudo nano /etc/check_mk/switch_config.conf
   ```
   
   Add:
   ```bash
   SWITCH_IP="192.168.1.1"
   SNMP_COMMUNITY="public"
   SNMP_VERSION="2c"
   ```

**Monitored Items:**
- System information
- Port status and traffic
- VLAN configuration
- CPU and memory
- Temperature sensors
- Fans and power supplies
- Spanning Tree Protocol
- MAC address table

**Supported Switches:**
- Cisco Catalyst series
- HP ProCurve/Aruba
- Dell PowerConnect
- Netgear managed switches
- Any SNMP-enabled switch

## Service Discovery

After deploying plugins:

1. **Log into CheckMK web interface**

2. **Navigate to host:**
   - Setup → Hosts
   - Select the host

3. **Run service discovery:**
   - Click "Save & run service discovery"
   - Wait for discovery to complete

4. **Review and accept services:**
   - Review discovered services
   - Click "Accept all" or selectively accept
   - Click "Activate on selected sites"

5. **Verify monitoring:**
   - Navigate to "Monitor → All hosts"
   - Check host status and services

## Troubleshooting

### Plugin Not Executing

**Check 1: File permissions**
```bash
ls -la /usr/lib/check_mk_agent/plugins/
# Should be: -rwxr-xr-x (755)
```

**Check 2: Script syntax**
```bash
bash -n /usr/lib/check_mk_agent/plugins/<plugin_name>
```

**Check 3: Dependencies**
```bash
# Test plugin manually
sudo /usr/lib/check_mk_agent/plugins/<plugin_name>
```

### No Data in CheckMK

**Check 1: Agent output**
```bash
sudo check_mk_agent | grep "<<<section_name>>>"
```

**Check 2: Service discovery**
- Run service discovery in CheckMK GUI
- Check if services are discovered but not monitored

**Check 3: Agent registration**
- Verify host is registered in CheckMK
- Check agent connection: `Setup → Hosts → Diagnostic`

### Permission Denied Errors

**Solution:** Ensure the CheckMK agent runs with sufficient privileges:

```bash
# Check agent configuration
sudo systemctl status check-mk-agent@*.service

# For xinetd-based agents
sudo cat /etc/xinetd.d/check-mk-agent
# Ensure user = root
```

### SNMP Timeout (Switches)

**Check 1: SNMP enabled**
```bash
snmpwalk -v 2c -c public <switch_ip> system
```

**Check 2: Firewall**
```bash
# Allow SNMP
sudo ufw allow from <checkmk_server_ip> to any port 161 proto udp
```

**Check 3: SNMP community string**
- Verify community string is correct
- Check read-only access is configured

## Performance Optimization

### Reduce Check Interval

For resource-intensive checks:

1. Navigate to **Setup → Service monitoring rules**
2. Search for "Normal check interval for service checks"
3. Create rule for specific services
4. Set interval to 5, 10, or 15 minutes

### Cache Results

For slow-running plugins:

Add cache header to plugin output:
```bash
#!/bin/bash
echo "<<<your_plugin:cached(300,120)>>>"
# 300 = cache for 5 minutes
# 120 = cache during check interval
```

## Maintenance

### Update Plugins

```bash
# Backup current plugin
sudo cp /usr/lib/check_mk_agent/plugins/<plugin_name> \
        /usr/lib/check_mk_agent/plugins/<plugin_name>.bak

# Download updated version
sudo wget -O /usr/lib/check_mk_agent/plugins/<plugin_name> \
  <url_to_new_version>

# Set permissions
sudo chmod 755 /usr/lib/check_mk_agent/plugins/<plugin_name>

# Test
sudo /usr/lib/check_mk_agent/plugins/<plugin_name>

# Run service discovery in CheckMK
```

### Backup Plugins

```bash
# Create backup
sudo tar czf checkmk-plugins-backup-$(date +%Y%m%d).tar.gz \
  /usr/lib/check_mk_agent/plugins/

# Restore
sudo tar xzf checkmk-plugins-backup-YYYYMMDD.tar.gz -C /
```

## Best Practices

1. **Test plugins** in development before production deployment
2. **Document customizations** for each monitored system
3. **Monitor plugin execution time** to avoid agent timeout
4. **Use agent bakery** (Enterprise) for centralized deployment
5. **Keep plugins updated** with system changes
6. **Set up alerts** for critical services
7. **Regular backup** of CheckMK configuration
8. **Review logs** regularly for errors

## Getting Help

- **CheckMK Forum:** https://forum.checkmk.com/
- **CheckMK Documentation:** https://docs.checkmk.com/
- **GitHub Issues:** https://github.com/Coverup20/checkmk-tools/issues

## Next Steps

After successful deployment:

1. Configure alerting rules in CheckMK
2. Set up notification channels (email, Slack, etc.)
3. Create custom dashboards
4. Configure SLA monitoring
5. Set up automated reports
6. Implement backup procedures
