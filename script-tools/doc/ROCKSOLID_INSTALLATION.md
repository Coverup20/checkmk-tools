# CheckMK Agent - ROCKSOLID Installation Guide
> **Category:** Operational

## Problem Solved

During a **major upgrade** of NethSecurity/OpenWrt (e.g. 8.7.0 → .8.7.1), the system restores the firmware and:
- **Losses** unprotected files in `/usr/bin`, `/etc/init.d`
- **Delete** unlisted configurations in `/etc/sysupgrade.conf`
- **Remove** manually installed binaries

**Result**: CheckMK Agent stops working after the upgrade.

## ROCKSOLID solution

The `install-checkmk-agent-debtools-frp-nsec8c-rocksolid.sh` script implements automatic protections:

### 1⃣ Critical File Protection

Automatically adds to `/etc/sysupgrade.conf`:
```
# CheckMK Agent - Binary
/usr/bin/check_mk_agent

# CheckMK Agent - Init Script
/etc/init.d/check_mk_agent

# CheckMK Agent - Configuration
/etc/check_mk/

# FRP Client - Binary
/usr/local/bin/frpc

# FRP Client - Configuration
/etc/frp/

# FRP Client - Init Script
/etc/init.d/frpc

# Post-upgrade verification script
/etc/checkmk-post-upgrade.sh

# Custom package repositories
/etc/opkg/customfeeds.conf
```

### 2⃣ Automatic Post-Upgrade Script

Create `/etc/checkmk-post-upgrade.sh` that:
- Check for critical files after upgrade
- Reactivate CheckMK and FRP services
- Check that socat is listening on port 6556

### 3⃣ Autocheck at Startup (NEW!)

The `rocksolid-startup-check.sh` script runs **automatically on every reboot**:
- Check and restart CheckMK Agent if not active
- Check and restart FRP Client if not active
- **Reinstall Git automatically** if missing (after upgrade)
- Check and restore git-sync cron jobs
- Repository sync test
- Full log in `/var/log/rocksolid-startup.log`

**Configuration**: Run automatically by `/etc/rc.local` in the background.
- Log all events in syslog

### 3⃣ Differences vs Original Script

| Features | Original | ROCKSOLID |
|---------|----------|----------|
| Install agent |  |  |
| Configure socat |  |  |
| Install FRP (optional) |  |  |
| Protects from upgrades |  |  |
| Post-upgrade script |  |  |
| Adds to sysupgrade.conf |  |  Automatic |
| Logging upgrade |  |  Syslog |

## Installation

### About NethSecurity/OpenWrt - Interactive Mode

```bash
# From local repository (if available)
bash /opt/checkmk-tools/script-tools/full/installation/install-checkmk-agent-persistent-nsec8.sh

# From GitHub
curl -fsSL https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/full/installation/install-checkmk-agent-persistent-nsec8.sh | bash
```

### Non-Interactive Mode (Automatic Boot)

For automatic executions (e.g. boot, cron, automation):

```bash
# Automatically maintains existing FRP configuration (if any)
# Skip interactive prompts
NON_INTERACTIVE=1 bash /opt/checkmk-tools/script-tools/full/installation/install-checkmk-agent-persistent-nsec8.sh
```

**Non-interactive mode behavior:**
- If `/etc/frp/frpc.toml` exists → **automatically** maintains the configuration
- Does not ask for confirmation to maintain FRP config
- If FRP not configured → skip FRP installation
- Ideal for startup scripts, autocheck, automation

### Installation Output

```
╔════════════════════════════════ ════════════════════════════════╗
║ CheckMK Agent Installer - ROCKSOLID Edition ║
║ Version resistant to NethSecurity/OpenWrt major upgrades ║
╚════════════════════════════════ ════════════════════════════════╝

[INFO] I configure repository (customfeeds)
[INFO] opkg update
[INFO] Installing necessary tools (binutils/tar/gzip/wget/socat/ca-certificates)
[INFO] Checkmk agent installation
[INFO] Download .deb agent
[INFO] Extracting .deb (ar + tar)
[INFO] Copy agent binary
[INFO] Agent installed: /usr/bin/check_mk_agent
[INFO] I create procd service (socat listener on 6556)
[INFO] Checkmk agent listening on TCP 6556 (socat)
[INFO] ROCKSOLID: Protecting CheckMK installation from major upgrades
[INFO] Added to sysupgrade.conf: /usr/bin/check_mk_agent
[INFO] Added to sysupgrade.conf: /etc/init.d/check_mk_agent
[INFO] Added to sysupgrade.conf: /etc/check_mk/
[INFO] I create post-upgrade recovery script: /etc/checkmk-post-upgrade.sh
[INFO] Post-upgrade script created and secured

╔════════════════════════════════ ════════════════════════════════╗
║ INSTALLATION COMPLETE - ROCKSOLID MODE ACTIVATED ║
╚════════════════════════════════ ════════════════════════════════╝

Protections activated:
   Critical files added to /etc/sysupgrade.conf
Created post-upgrade script: /etc/checkmk-post-upgrade.sh
   Installation resistant to major upgrades

Local test agent: nc 127.0.0.1 6556 | head
```

## Major Upgrade Procedure

### Before Upgrading

1. Check protected files:
```bash
cat /etc/sysupgrade.conf | grep -E 'check_mk|frpc'
```

2. Manual backup (optional):
```bash
tar czf /tmp/checkmk-backup.tar.gz \
  /usr/bin/check_mk_agent \
  /etc/init.d/check_mk_agent \
  /etc/check_mk/ \
  /usr/local/bin/frpc \
  /etc/frp/ \
  /etc/init.d/frpc
```

### After the Upgrade

1. **AUTOMATIC**: The `rocksolid-startup-check.sh` script starts automatically at boot and:
   - Reactivate CheckMK Agent and FRP Client
   - Reinstall Git if missing
   - Reset git-sync cron jobs
   - Log everything to `/var/log/rocksolid-startup.log`

2. **MANUAL (if needed)**: Run post-upgrade script:
```bash
/etc/checkmk-post-upgrade.sh
/etc/git-sync-post-upgrade.sh
```

3. **CHECK Git**: If git is missing, it will be automatically reinstalled at boot:
```bash
# The script automatically runs:
opkg update
opkg install git git-http
```

4. Check active services:
```bash
ps | grep -It's socat|frpc'
netstat -tlnp | grep 6556
```

5. Test agents:
```bash
nc 127.0.0.1 6556 | head -20
```

6. Check autocheck log:
```bash
tail -50 /var/log/rocksolid-startup.log
```

## Pre-Upgrade Test (Simulation)

Before a major upgrade, test persistence:

```bash
#1. Simulate file loss
mv /usr/bin/check_mk_agent /tmp/
/etc/init.d/check_mk_agent stop

#2. Run post-upgrade scripts
/etc/checkmk-post-upgrade.sh

#3. It should detect the problem
# Expected output: "ERROR: /usr/bin/check_mk_agent missing after upgrade!"

#4. Reset to continue testing
mv /tmp/check_mk_agent /usr/bin/
/etc/checkmk-post-upgrade.sh
```

## Check ROCKSOLID Installation

### Method 1: Automatic Script (Recommended)

```bash
# Performs full verification with autocheck
/usr/local/bin/rocksolid-startup-check.sh

# View log
tail -50 /var/log/rocksolid-startup.log
```

### Method 2: Manual Verification Script

```bash
#!/bin/sh
echo "=== CHECK ROCKSOLID INSTALLATION ==="
echo ""

echo "1. CheckMK Agent Binary:"
ls -lh /usr/bin/check_mk_agent && echo " OK" || echo "MISSING"

echo "2. Init script CheckMK:"
ls -lh /etc/init.d/check_mk_agent && echo " OK" || echo "MISSING"

echo "3. CheckMK Configuration:"
ls -ld /etc/check_mk && echo " OK" || echo "MISSING"

echo "4. FRP client binary:"
ls -lh /usr/local/bin/frpc 2>/dev/null && echo " OK" || echo "Not installed"

echo "5. FRP configuration:"
ls -ld /etc/frp 2>/dev/null && echo " OK" || echo "Not installed"

echo "6. Post-upgrade script:"
ls -lh /etc/checkmk-post-upgrade.sh && echo " OK" || echo "MISSING"

echo "7. Startup autocheck script:"
ls -lh /usr/local/bin/rocksolid-startup-check.sh && echo " OK" || echo "MISSING"

echo "8. rc.local configuration:"
grep -q rocksolid-startup-check.sh /etc/rc.local && echo " Autocheck active" || echo "Autocheck not configured"

echo "9. Security sysupgrade.conf:"
if grep -q check_mk_agent /etc/sysupgrade.conf; then
    echo "CheckMK protected"
else
    echo "CheckMK NOT protected"
fi

echo "10. Active socat process:"
if pgrep -f "socat TCP-LISTEN:6556" >/dev/null; then
    echo "Agent listening"
else
    echo "Agent down"
fi

echo "11. Listening on port 6556:"
netstat -tlnp | grep -q 6556 && echo " Door open" || echo "Door closed"

echo "12. Git installed:"
command -v git >/dev/null && echo " Git present: $(git --version)" || echo "Git missing"

echo ""
echo "=== CONTENTS sysupgrade.conf (ROCKSOLID) ==="
grep -E 'check_mk|frpc|frp/|git-sync|rocksolid|rc.local' /etc/sysupgrade.conf || echo "No entries found"
```

## Troubleshooting

### Agent not working after upgrade

```bash
# 1. Check existing files
ls -la /usr/bin/check_mk_agent /etc/init.d/check_mk_agent

#2. Run post-upgrade scripts
/etc/checkmk-post-upgrade.sh

#3. Reboot manually
/etc/init.d/check_mk_agent enable
/etc/init.d/check_mk_agent restart

#4. Check logs
logread | tail -50
```

### Files lost after upgrade

If the files were still lost:
1. Re-run the ROCKSOLID installation script
2. The files will be recreated and protected
3. FRP configuration will be preserved if in `/etc/frp/`

### FRP does not reconnect

```bash
# Check preserved configuration
cat /etc/frp/frpc.toml

# Restart service
/etc/init.d/frpc restart

# Check log
tail -f /var/log/frpc.log
```

## Protection Statistics

| Component | Size | Protected | Critical |
|------------|-----------|----------|---------|
| check_mk_agent | ~74 KB |  | High |
| check_mk_agent init | ~552 B |  | High |
| /etc/check_mk/ | ~8 KB |  | Average |
| frpc binary | ~14.8 MB |  | Average |
| frpc.toml | ~389 B |  | High |
| frpc init | ~283 B |  | Average |
| post-upgrade.sh | ~1.2 KB |  | High |

**Total protected space**: ~15 MB

## Best Practices

1. **Always use ROCKSOLID version** for new installations on NethSecurity/OpenWrt
2. **Test post-upgrade scripts** before real major upgrades
3. **Check sysupgrade.conf** periodically with `cat /etc/sysupgrade.conf`
4. **Manual backup** before critical upgrades (even if protected)
5. **Monitor syslog logs** after upgrade: `logread | grep checkmk`

## References

- Original script: `install-checkmk-agent-debtools-frp-nsec8c.sh`
- ROCKSOLID script: `install-checkmk-agent-debtools-frp-nsec8c-rocksolid.sh`
- OpenWrt sysupgrade: https://openwrt.org/docs/guide-user/installation/sysupgrade
- NethSecurity Upgrade: https://github.com/nethserver/nethsecurity

---

**Last update**: 2026-01-29  
**Version**: 1.0 ROCKSOLID  
**Tested on**: NethSecurity 8.7.1 (OpenWrt 24.10.3)