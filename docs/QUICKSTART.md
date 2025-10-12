# Quick Start Guide

This guide will help you get started with CheckMK Tools in 10 minutes.

## What You'll Get

- CheckMK Raw monitoring server fully configured
- Custom check plugins for 9+ system types
- Automated backups
- SSL certificates (optional)
- Email notifications (optional)

## Prerequisites

- **Server:** Ubuntu 20.04/22.04 or Debian 11/12
- **Resources:** 2GB RAM, 20GB disk, 2 CPU cores
- **Access:** Root or sudo access
- **Network:** Internet connectivity

## Step 1: Clone Repository

```bash
git clone https://github.com/Coverup20/checkmk-tools.git
cd checkmk-tools/bootstrap
```

## Step 2: Configure Environment

```bash
# Copy example configuration
cp .env.example .env

# Edit configuration
nano .env
```

**Minimal configuration** (edit these values):

```bash
# Your timezone
TIMEZONE="Europe/Rome"

# Open web ports
OPEN_HTTP_HTTPS=true

# CheckMK download URL (get latest from https://checkmk.com/download)
CHECKMK_DEB_URL="https://download.checkmk.com/checkmk/2.2.0p15/check-mk-raw-2.2.0p15_0.jammy_amd64.deb"

# Set admin password (optional but recommended)
CHECKMK_ADMIN_PASSWORD="YourSecurePassword123"
```

**Optional but recommended:**

```bash
# For SSL certificates
LETSENCRYPT_EMAIL="admin@yourdomain.com"
LETSENCRYPT_DOMAINS="monitoring.yourdomain.com"
WEBSERVER=apache
```

Save and exit (Ctrl+X, Y, Enter).

## Step 3: Run Bootstrap

```bash
# Make scripts executable
chmod +x *.sh

# Run installation
sudo ./00_bootstrap.sh
```

This will take 5-10 minutes and will:
- Configure SSH and firewall
- Install CheckMK Raw
- Set up automated backups
- Configure SSL (if domain provided)
- Set up email relay (if configured)

## Step 4: Access CheckMK

Once installation completes, you'll see:

```
✅ Checkmk installato e site avviato.
   Site: monitoring
   URL:  http://YOUR-SERVER-IP/monitoring/
```

**Log in:**
- URL: `http://YOUR-SERVER-IP/monitoring/`
- Username: `cmkadmin`
- Password: (from .env or default: `omd`)

**First login steps:**
1. Change password if you didn't set one
2. Complete setup wizard
3. Configure notification settings

## Step 5: Deploy Agent Plugins

Choose the plugin for your target system:

### For Nethserver

```bash
# On the Nethserver host
sudo wget -O /usr/lib/check_mk_agent/plugins/nethserver_check \
  https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/agents/plugins/nethserver_check
sudo chmod 755 /usr/lib/check_mk_agent/plugins/nethserver_check

# Test it
sudo /usr/lib/check_mk_agent/plugins/nethserver_check
```

### For Proxmox VE

```bash
# On the Proxmox host
sudo wget -O /usr/lib/check_mk_agent/plugins/proxmox_check \
  https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/agents/plugins/proxmox_check
sudo chmod 755 /usr/lib/check_mk_agent/plugins/proxmox_check
```

### For Linux Clients

```bash
# On any Linux client
sudo wget -O /usr/lib/check_mk_agent/plugins/linux_client_check \
  https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/agents/plugins/linux_client_check
sudo chmod 755 /usr/lib/check_mk_agent/plugins/linux_client_check
```

### For Windows Clients

```powershell
# On Windows (as Administrator)
$url = "https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/agents/windows/windows_client_check.ps1"
$dest = "C:\ProgramData\checkmk\agent\plugins\windows_client_check.ps1"
Invoke-WebRequest -Uri $url -OutFile $dest
```

**Note:** You need CheckMK agent installed on the target systems first.

## Step 6: Add Hosts to CheckMK

1. **Log into CheckMK web interface**

2. **Navigate to Setup → Hosts**

3. **Click "Add host"**
   - Hostname: `server-name`
   - IP address: `192.168.1.10`
   - CheckMK agent: select "Normal CheckMK Agent"
   - Save

4. **Run service discovery**
   - Click "Save & run service discovery"
   - Review discovered services
   - Click "Accept all"
   - Click "Activate on selected sites"

5. **View monitoring**
   - Navigate to "Monitor → All hosts"
   - Check your host status

## Step 7: Configure Notifications (Optional)

Set up email alerts:

1. **Setup → Users → Notification rules**
2. **Click "Add rule"**
3. Configure:
   - Method: Email
   - From: `checkmk@yourdomain.com`
   - To: `admin@yourdomain.com`
   - When: Host or service down
4. **Save and activate**

## Troubleshooting

### Can't access CheckMK web interface

**Check firewall:**
```bash
sudo ufw status
# Should show: 80/tcp ALLOW and 443/tcp ALLOW
```

**Check CheckMK service:**
```bash
omd status monitoring
# All services should show: running
```

**Restart if needed:**
```bash
sudo omd restart monitoring
```

### Plugin not showing data

**Check plugin execution:**
```bash
# On the monitored host
sudo check_mk_agent | grep "<<<section_name>>>"
```

**Run service discovery:**
- In CheckMK GUI: Setup → Hosts → [Select host] → "Save & run service discovery"

### Agent not connecting

**Test agent on monitored host:**
```bash
sudo check_mk_agent
# Should output lots of monitoring data
```

**Check from CheckMK server:**
```bash
# Replace HOST with target IP
telnet HOST 6556
# Should connect and show agent output
```

**Check firewall on monitored host:**
```bash
# Allow CheckMK server IP
sudo ufw allow from CHECKMK-SERVER-IP to any port 6556
```

## What's Next?

### Essential Configuration

1. **Set up backups** (already configured, verify):
   ```bash
   sudo systemctl status checkmk-backup.timer
   ls -lh /var/lib/checkmk_backups/
   ```

2. **Create dashboards**
   - Customize → Dashboards → Add dashboard
   - Add widgets for your most important metrics

3. **Set up alerting rules**
   - Setup → Events → Event rules
   - Configure thresholds and notifications

### Advanced Configuration

4. **Configure business intelligence**
   - Monitor → Business Intelligence
   - Create BI aggregations

5. **Set up distributed monitoring**
   - For multiple locations
   - Setup → General → Distributed monitoring

6. **Create custom graphs**
   - Customize → Custom graphs
   - Combine multiple metrics

## Useful Commands

### CheckMK Management

```bash
# Check site status
omd status monitoring

# Start/stop site
omd start monitoring
omd stop monitoring
omd restart monitoring

# Manual backup
/usr/local/bin/checkmk_backup.sh

# View logs
omd tail monitoring
```

### Bootstrap Re-run

If you need to reconfigure:

```bash
cd checkmk-tools/bootstrap

# Edit .env as needed
nano .env

# Re-run specific script
sudo ./XX-script-name.sh

# Or re-run entire bootstrap
sudo ./00_bootstrap.sh
```

## Getting Help

- **Documentation:** [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)
- **CheckMK Docs:** https://docs.checkmk.com/
- **CheckMK Forum:** https://forum.checkmk.com/
- **GitHub Issues:** https://github.com/Coverup20/checkmk-tools/issues

## Available Plugins

- ✅ **Nethserver 7.9/8** - Full service monitoring
- ✅ **Nethsecurity 7.9/8** - Firewall and security monitoring
- ✅ **Proxmox VE** - Virtualization platform monitoring
- ✅ **VMWare ESXi** - VMware host monitoring
- ✅ **Linux Clients** - Desktop/server monitoring
- ✅ **Windows Clients** - Windows workstation monitoring
- ✅ **Managed Switches** - SNMP-based switch monitoring

## Success Checklist

- [ ] CheckMK server installed and accessible
- [ ] Admin password set
- [ ] At least one host added
- [ ] Services discovered and monitored
- [ ] Email notifications configured
- [ ] Backup timer running
- [ ] Custom plugins deployed to target systems

**Congratulations!** You now have a fully functional CheckMK monitoring system.

For detailed information, see:
- [README.md](../README.md) - Full documentation
- [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) - Detailed deployment instructions
- [CONTRIBUTING.md](CONTRIBUTING.md) - Development guidelines
