# CheckMK Plugin Reference

This document provides a comprehensive reference of all custom plugins, their sections, and collected metrics.

## Table of Contents

1. [Nethserver Check](#nethserver-check)
2. [Nethsecurity Check](#nethsecurity-check)
3. [Proxmox VE Check](#proxmox-ve-check)
4. [VMWare ESXi Check](#vmware-esxi-check)
5. [Linux Client Check](#linux-client-check)
6. [Windows Client Check](#windows-client-check)
7. [Managed Switch Check](#managed-switch-check)

---

## Nethserver Check

**File:** `nethserver_check`  
**Path:** `/usr/lib/check_mk_agent/plugins/nethserver_check`  
**Supported Versions:** Nethserver 7.9, 8.x

### Sections and Metrics

#### `<<<nethserver_info>>>`
Basic system information
- `version`: Nethserver version (7 or 8)
- `hostname`: Fully qualified domain name
- `uptime`: System uptime in human-readable format

#### `<<<nethserver_services>>>`
Service status monitoring
- `httpd-admin`: Admin panel status (active/inactive)
- `rsyslog`: System logging service
- `cockpit.socket`: Web admin interface
- For Nethserver 7.x:
  - `smb`: Samba file sharing
  - `nmb`: NetBIOS name service
  - `clamd`: Antivirus scanner
  - `amavisd`: Email content filter
  - `postfix`: Mail transfer agent
  - `dovecot`: IMAP/POP3 server

#### `<<<nethserver_database>>>`
Configuration database status
- `config_entries`: Number of entries in e-smith database

#### `<<<nethserver_backup>>>`
Backup monitoring
- `last_backup_age_seconds`: Age of last backup in seconds (-1 if none found)

#### `<<<nethserver_disk>>>`
Disk usage for critical partitions
- Output: Filesystem usage for `/`, `/var`, `/home`

#### `<<<nethserver_mailqueue>>>`
Email queue monitoring (if Postfix is installed)
- `queue_count`: Number of messages in mail queue

#### `<<<nethserver_raid>>>`
RAID array status (if mdadm is installed)
- `device_name`: RAID device status (clean, degraded, etc.)

### Use Cases
- Monitor email server health
- Track backup status
- Alert on service failures
- Monitor file sharing services
- Track configuration changes

---

## Nethsecurity Check

**File:** `nethsecurity_check`  
**Path:** `/usr/lib/check_mk_agent/plugins/nethsecurity_check`  
**Supported Versions:** Nethsecurity 7.9, 8.x

### Sections and Metrics

#### `<<<nethsecurity_info>>>`
System information
- `version`: Nethsecurity version
- `hostname`: System hostname
- `uptime`: System uptime

#### `<<<nethsecurity_firewall>>>`
Firewall status and metrics
- `shorewall`: Firewall service status
- `conntrack_entries`: Number of active connection tracking entries

#### `<<<nethsecurity_iptables>>>`
Firewall rules metrics
- `rules_count`: Total number of iptables rules
- `nat_rules_count`: Number of NAT rules

#### `<<<nethsecurity_vpn>>>`
VPN status monitoring
- `vpn_name`: OpenVPN connection status per configured VPN
- `vpn_name_clients`: Number of connected VPN clients

#### `<<<nethsecurity_ids>>>`
Intrusion Detection System status
- `suricata`: IDS/IPS service status
- `recent_alerts_1h`: Number of alerts in last hour

#### `<<<nethsecurity_threats>>>`
Threat blocking services
- `fail2ban`: Intrusion prevention status
- `fail2ban_jails`: Number of active fail2ban jails
- `snort`: IDS service status

#### `<<<nethsecurity_interfaces>>>`
Network interface status
- Per interface: operational state (up/down)

#### `<<<nethsecurity_dhcp>>>`
DHCP service monitoring
- `dhcp`: Service status
- `dhcp_leases`: Number of active DHCP leases

#### `<<<nethsecurity_dns>>>`
DNS service monitoring
- `dns`: Service status (named or dnsmasq)

#### `<<<nethsecurity_logs>>>`
Log analysis
- `firewall_drops_recent`: Number of recent firewall DROP events

### Use Cases
- Monitor firewall health
- Track VPN connections
- Alert on security threats
- Monitor network services
- Track intrusion attempts

---

## Proxmox VE Check

**File:** `proxmox_check`  
**Path:** `/usr/lib/check_mk_agent/plugins/proxmox_check`  
**Supported Versions:** Proxmox VE 6.x, 7.x, 8.x

### Sections and Metrics

#### `<<<proxmox_info>>>`
System information
- `version`: Proxmox VE version
- `hostname`: System hostname
- `uptime`: System uptime

#### `<<<proxmox_cluster>>>`
Cluster status (if clustered)
- `cluster_name`: Name of Proxmox cluster
- `cluster_nodes`: Number of cluster nodes
- `quorum`: Cluster quorum status
- `cluster_status`: standalone (if not clustered)

#### `<<<proxmox_services>>>`
Proxmox service status
- `pve-cluster`: Cluster communication
- `pvedaemon`: Main Proxmox daemon
- `pveproxy`: Web proxy service
- `pvestatd`: Statistics daemon
- `pvescheduler`: Task scheduler

#### `<<<proxmox_vms>>>`
Virtual machine status
- Per VM: `VM {id}: {status} - {name}`

#### `<<<proxmox_containers>>>`
LXC container status
- Per container: `CT {id}: {status} - {name}`

#### `<<<proxmox_storage>>>`
Storage configuration
- Per storage: name, type, enabled status

#### `<<<proxmox_replication>>>`
Replication status
- Replication job details and status

#### `<<<proxmox_backup>>>`
Backup configuration
- `vzdump_configured`: Whether backup is configured
- `recent_backup_jobs_24h`: Number of backup jobs in last 24 hours

#### `<<<proxmox_ceph>>>`
Ceph storage status (if configured)
- `ceph`: Service status
- `ceph_health`: Ceph cluster health (HEALTH_OK, HEALTH_WARN, etc.)

#### `<<<proxmox_zfs>>>`
ZFS pool status (if ZFS is used)
- Per pool: name, health, capacity

#### `<<<proxmox_lvm>>>`
LVM volume group status
- Per VG: name, size, free space

#### `<<<proxmox_bridges>>>`
Network bridge status
- Per bridge: operational state

#### `<<<proxmox_subscription>>>`
Subscription status
- `subscription`: active/inactive status

#### `<<<proxmox_resources>>>`
Host resource usage
- `cpu_usage_percent`: CPU utilization
- `memory_usage_percent`: Memory utilization

### Use Cases
- Monitor virtualization infrastructure
- Track VM/container health
- Alert on storage issues
- Monitor cluster health
- Track backup jobs
- Monitor Ceph/ZFS status

---

## VMWare ESXi Check

**File:** `vmware_check`  
**Path:** `/usr/lib/check_mk_agent/plugins/vmware_check`  
**Supported Versions:** ESXi 6.x, 7.x, 8.x

### Sections and Metrics

#### `<<<vmware_info>>>`
ESXi information
- `version`: ESXi version string
- `hostname`: System hostname

#### `<<<vmware_services>>>`
ESXi service status
- `hostd`: Host daemon status

#### `<<<vmware_hardware>>>`
Hardware information
- Product name, vendor, serial number
- `cpu_count`: Number of CPUs
- `memory_mb`: Total memory in MB

#### `<<<vmware_storage>>>`
Storage information
- Per datastore: mount point, size, free space, type

#### `<<<vmware_network>>>`
Network adapter status
- Per vmnic: adapter information and status

#### `<<<vmware_vms>>>`
Virtual machine status
- Per VM: ID, power state, name

#### `<<<vmware_vswitches>>>`
Virtual switch configuration
- vSwitch information including uplinks and portgroups

#### `<<<vmware_resources>>>`
Resource usage
- CPU and memory usage statistics

#### `<<<vmware_health>>>`
Hardware health status
- Overall health status
- Sensor information

#### `<<<vmware_maintenance>>>`
Maintenance mode status
- `maintenance_mode`: true/false

#### `<<<vmware_license>>>`
License information
- Product name and license key

#### `<<<vmware_ntp>>>`
NTP synchronization
- NTP configuration and status

### Use Cases
- Monitor ESXi host health
- Track VM status
- Alert on storage capacity
- Monitor hardware health
- Track resource usage

**Note:** For comprehensive vCenter monitoring, use CheckMK's built-in VMware special agent.

---

## Linux Client Check

**File:** `linux_client_check`  
**Path:** `/usr/lib/check_mk_agent/plugins/linux_client_check`  
**Supported Distributions:** Ubuntu, Debian, RHEL, CentOS, SUSE

### Sections and Metrics

#### `<<<linux_client_info>>>`
System information
- `hostname`: System FQDN
- `distribution`: Linux distribution
- `kernel`: Kernel version
- `uptime`: System uptime

#### `<<<linux_client_updates>>>`
Package updates
- `updates_available`: Number of available updates
- `security_updates`: Number of security updates

#### `<<<linux_client_services>>>`
Critical service status
- `ssh/sshd`: SSH service
- `NetworkManager`: Network management
- `systemd-resolved`: DNS resolution

#### `<<<linux_client_firewall>>>`
Firewall status
- Firewall type (ufw/firewalld/iptables) and status

#### `<<<linux_client_disk>>>`
Disk usage
- Usage statistics for `/` and `/home`

#### `<<<linux_client_failed_services>>>`
Failed services
- `failed_services_count`: Number of failed systemd services
- List of failed service names

#### `<<<linux_client_login>>>`
Last login information
- `last_login`: Last successful login details

#### `<<<linux_client_security>>>`
Security tools status
- `fail2ban`: Status and banned IPs count
- `antivirus`: ClamAV status and signature age

#### `<<<linux_client_auto_updates>>>`
Automatic updates configuration
- `unattended_upgrades`: Installation status
- `unattended_upgrades_enabled`: Enabled status

#### `<<<linux_client_load>>>`
System load
- `load_average`: 1, 5, and 15-minute load averages

#### `<<<linux_client_users>>>`
Logged in users
- `logged_in_users`: Number of currently logged-in users

#### `<<<linux_client_sensors>>>`
Temperature sensors (if lm-sensors installed)
- Temperature readings from hardware sensors

#### `<<<linux_client_docker>>>`
Docker status (if installed)
- `docker`: Service status
- `running_containers`: Number of running containers

### Use Cases
- Monitor desktop/server health
- Track security updates
- Alert on service failures
- Monitor resource usage
- Track security tools status

---

## Windows Client Check

**File:** `windows_client_check.ps1`  
**Path:** `C:\ProgramData\checkmk\agent\plugins\windows_client_check.ps1`  
**Supported Versions:** Windows 10, 11, Server 2016+

### Sections and Metrics

#### `<<<windows_client_info>>>`
System information
- `hostname`: Computer name
- `os_version`: Windows version
- `os_build`: Build number
- `uptime_hours`: System uptime in hours
- `domain`: Domain name

#### `<<<windows_client_updates>>>`
Windows Update status
- `updates_available`: Total updates available
- `security_updates`: Security updates available

#### `<<<windows_client_services>>>`
Critical service status
- `WinDefend`: Windows Defender
- `BITS`: Background Intelligent Transfer Service
- `wuauserv`: Windows Update service
- `EventLog`: Event logging
- `Dhcp`: DHCP client
- `Dnscache`: DNS cache

#### `<<<windows_client_defender>>>`
Windows Defender status
- `defender_enabled`: Antivirus enabled
- `realtime_protection`: Real-time protection status
- `signature_age_days`: Signature database age
- `last_scan`: Last full scan date
- `quick_scan_age_days`: Days since last quick scan

#### `<<<windows_client_firewall>>>`
Windows Firewall status
- Per profile (Domain, Private, Public): enabled status

#### `<<<windows_client_disk>>>`
Disk usage
- Per drive: used percentage, free space, total space

#### `<<<windows_client_bitlocker>>>`
BitLocker encryption status
- Per volume: protection status, encryption percentage

#### `<<<windows_client_security_events>>>`
Security events
- `failed_logins_24h`: Failed login attempts in last 24 hours

#### `<<<windows_client_reboot>>>`
Pending reboot status
- `reboot_pending`: true/false

#### `<<<windows_client_performance>>>`
Performance metrics
- `cpu_load_percent`: CPU utilization
- `memory_used_percent`: Memory utilization

#### `<<<windows_client_applications>>>`
Installed applications
- `installed_applications`: Count of installed apps

#### `<<<windows_client_eventlog>>>`
Event Log errors
- `system_errors_24h`: System errors in last 24 hours
- `application_errors_24h`: Application errors in last 24 hours

#### `<<<windows_client_network>>>`
Network adapters
- Per adapter: name, status, link speed

#### `<<<windows_client_certificates>>>`
Certificate expiration
- `expiring_certificates_30d`: Certificates expiring in 30 days

#### `<<<windows_client_license>>>`
Windows license status
- `license_status`: Activation status

#### `<<<windows_client_last_update>>>`
Last update installation
- `last_update_date`: Date of last update

### Use Cases
- Monitor Windows workstations
- Track Windows updates
- Alert on security issues
- Monitor disk encryption
- Track failed logins
- Monitor system health

---

## Managed Switch Check

**File:** `managed_switch_check`  
**Path:** `/usr/lib/check_mk_agent/plugins/managed_switch_check`  
**Protocol:** SNMP v2c/v3  
**Supported:** Cisco, HP, Dell, Netgear, any SNMP-enabled switch

### Configuration Required

File: `/etc/check_mk/switch_config.conf`
```bash
SWITCH_IP="192.168.1.1"
SNMP_COMMUNITY="public"
SNMP_VERSION="2c"
```

### Sections and Metrics

#### `<<<managed_switch_info>>>`
System information
- `switch_ip`: Switch IP address
- `system_name`: System name (sysName)
- `description`: System description (sysDescr)
- `uptime`: System uptime

#### `<<<managed_switch_ports>>>`
Port/interface information
- `total_ports`: Number of ports
- Per port: description, admin status, operational status

#### `<<<managed_switch_traffic>>>`
Traffic statistics
- Per port:
  - `in_bytes`: Inbound octets
  - `out_bytes`: Outbound octets
  - `in_errors`: Input errors
  - `out_errors`: Output errors

#### `<<<managed_switch_vlans>>>`
VLAN configuration
- `vlan_count`: Number of configured VLANs

#### `<<<managed_switch_cpu>>>`
CPU utilization (Cisco-specific MIBs)
- `cpu_5sec`: CPU usage last 5 seconds
- `cpu_1min`: CPU usage last 1 minute
- `cpu_5min`: CPU usage last 5 minutes

#### `<<<managed_switch_memory>>>`
Memory utilization (Cisco-specific MIBs)
- `memory_used`: Memory in use
- `memory_free`: Free memory

#### `<<<managed_switch_temperature>>>`
Temperature sensors
- Temperature readings in Celsius

#### `<<<managed_switch_fans>>>`
Fan status
- Per fan: operational status

#### `<<<managed_switch_power>>>`
Power supply status
- Per PSU: operational status

#### `<<<managed_switch_stp>>>`
Spanning Tree Protocol
- `stp_root`: STP root bridge

#### `<<<managed_switch_mac_table>>>`
MAC address table
- `mac_addresses`: Number of learned MAC addresses

### Use Cases
- Monitor switch health
- Track port utilization
- Alert on port errors
- Monitor temperature
- Track MAC address table size
- Alert on power/fan failures

### SNMP OIDs Used

- **System:** `SNMPv2-MIB::sys*`
- **Interfaces:** `IF-MIB::if*`
- **Bridge:** `BRIDGE-MIB::dot1d*`
- **VLANs:** `Q-BRIDGE-MIB::dot1q*`
- **Cisco specific:** `.1.3.6.1.4.1.9.9.*`

---

## Plugin Performance

### Execution Time Guidelines

- **Fast (<1s):** nethserver_check, linux_client_check
- **Medium (1-3s):** nethsecurity_check, windows_client_check
- **Slow (3-5s):** proxmox_check, vmware_check
- **Variable:** managed_switch_check (depends on port count)

### Optimization Tips

1. **Cache slow checks:**
   ```bash
   echo "<<<section:cached(300,120)>>>"
   # Cache for 5 minutes, update every 2 minutes
   ```

2. **Adjust check interval in CheckMK:**
   - Setup → Service monitoring rules
   - "Normal check interval for service checks"
   - Set to 5, 10, or 15 minutes for heavy checks

3. **Run expensive checks async:**
   - Use CheckMK's async execution for long-running checks

---

## Support Matrix

| Plugin | Ubuntu | Debian | RHEL/CentOS | Windows | VMWare | Proxmox | Switches |
|--------|--------|--------|-------------|---------|--------|---------|----------|
| nethserver_check | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| nethsecurity_check | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| proxmox_check | ❌ | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ |
| vmware_check | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ |
| linux_client_check | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| windows_client_check | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ |
| managed_switch_check | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |

---

## Common Integration Patterns

### Example: Complete Server Monitoring

```bash
# Install CheckMK agent
apt-get install check-mk-agent

# Deploy multiple plugins for comprehensive monitoring
cp linux_client_check /usr/lib/check_mk_agent/plugins/
cp nethserver_check /usr/lib/check_mk_agent/plugins/  # if Nethserver

# Make executable
chmod 755 /usr/lib/check_mk_agent/plugins/*

# Test
check_mk_agent | head -100
```

### Example: Infrastructure Dashboard

Combine multiple plugins to create comprehensive dashboards:
- Proxmox hosts + Proxmox VMs
- VMWare hosts + Guest OS monitoring
- Network infrastructure (switches) + Firewall (Nethsecurity)
- Application servers (Linux) + Email (Nethserver)

---

## Troubleshooting

### Plugin Not Producing Output

1. **Check execution:**
   ```bash
   sudo /usr/lib/check_mk_agent/plugins/plugin_name
   ```

2. **Check permissions:**
   ```bash
   ls -la /usr/lib/check_mk_agent/plugins/
   # Should be: -rwxr-xr-x
   ```

3. **Check dependencies:**
   - Bash scripts: ensure bash is available
   - PowerShell: ensure PS 5.1+
   - SNMP: ensure snmp tools installed

### No Services Discovered

1. Run service discovery in CheckMK GUI
2. Check agent output includes plugin sections
3. Verify plugin is executable
4. Check CheckMK service rules

---

## Future Enhancements

Potential additions:
- PostgreSQL/MySQL database monitoring
- Docker container monitoring (enhanced)
- Kubernetes cluster monitoring
- Cloud provider integration (AWS, Azure)
- Custom application monitoring
- Log analysis plugins

---

## Version History

- **v1.0.0** (2024) - Initial release
  - All 7 plugins implemented
  - Full documentation
  - Deployment automation

---

For deployment instructions, see [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)  
For quick setup, see [QUICKSTART.md](QUICKSTART.md)  
For development, see [CONTRIBUTING.md](CONTRIBUTING.md)
