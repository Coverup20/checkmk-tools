# FRPC Installation Fix - Before/After Code Comparison

## 1. FRPC Download Directory Fix

### BEFORE (Broken - Line 570)
```bash
install_frpc() {
    echo -e "\n${BLUE}═══ INSTALLAZIONE FRPC CLIENT ═══${NC}"
    
    echo -e "${YELLOW}📦 Download FRPC v${FRP_VERSION}...${NC}"
    cd /usr/local/src || exit 1  # ❌ FAILS ON OPENWRT - Directory doesn't exist!
    rm -f frp.tar.gz 2>/dev/null
    
    # Download con output visibile
    echo -e "${CYAN}   Downloading from GitHub...${NC}"
    if wget "$FRP_URL" -O frp.tar.gz 2>&1; then
        echo -e "${GREEN}   ✓ Download completato${NC}"
    else
        echo -e "${RED}✗ Errore durante il download di FRPC${NC}"
        exit 1
    fi
```

### AFTER (Fixed - Platform-Aware)
```bash
install_frpc() {
    echo -e "\n${BLUE}═══ INSTALLAZIONE FRPC CLIENT ═══${NC}"
    
    echo -e "${YELLOW}📦 Download FRPC v${FRP_VERSION}...${NC}"
    
    # ✅ Per OpenWrt usa /tmp, per Linux usa /usr/local/src
    local FRP_DIR="/tmp"
    if [ "$PKG_TYPE" != "openwrt" ] && [ -d /usr/local/src ]; then
        FRP_DIR="/usr/local/src"
    fi
    
    cd "$FRP_DIR" || exit 1  # ✅ Uses variable - works on all platforms
    rm -f "frp_${FRP_VERSION}_linux_amd64.tar.gz" 2>/dev/null
    
    # Download
    echo -e "${CYAN}   Downloading from GitHub...${NC}"
    if wget "$FRP_URL" -O "frp_${FRP_VERSION}_linux_amd64.tar.gz" 2>&1; then
        echo -e "${GREEN}   ✓ Download completato${NC}"
    else
        echo -e "${RED}✗ Errore durante il download di FRPC${NC}"
        exit 1
    fi
```

**Improvements**:
- ✅ Dynamic directory selection based on platform
- ✅ Fallback to `/usr/local/src` on Linux if available
- ✅ Always works with `/tmp` fallback
- ✅ No hard-coded paths that fail on some systems

---

## 2. FRPC Directory Extraction Fix

### BEFORE (Fixed Assumption - Line 585)
```bash
    echo -e "${YELLOW}📦 Estrazione...${NC}"
    tar xzf frp.tar.gz
    cd "frp_${FRP_VERSION}_linux_amd64" || exit 1  # ❌ ASSUMES fixed directory name
    
    systemctl stop frpc 2>/dev/null || true
    cp frpc /usr/local/bin/frpc
    chmod +x /usr/local/bin/frpc
    
    rm -f /usr/local/src/frp.tar.gz
```

### AFTER (Dynamic Detection)
```bash
    echo -e "${YELLOW}📦 Estrazione...${NC}"
    tar -xzf "frp_${FRP_VERSION}_linux_amd64.tar.gz"
    FRP_EXTRACTED=$(tar -tzf "frp_${FRP_VERSION}_linux_amd64.tar.gz" | head -1 | cut -f1 -d"/")
    # ✅ Dynamically determines directory name from archive
    
    mkdir -p /usr/local/bin
    cp -f "$FRP_EXTRACTED/frpc" /usr/local/bin/frpc
    # ✅ Uses variable - works even if directory name changes
    
    chmod +x /usr/local/bin/frpc
    
    rm -rf "$FRP_EXTRACTED" "frp_${FRP_VERSION}_linux_amd64.tar.gz"
    # ✅ Removes extracted directory
```

**Improvements**:
- ✅ Detects actual directory name from tar archive
- ✅ Works even if upstream changes directory naming
- ✅ Cleaner extraction (uses `-x` flag)
- ✅ Proper cleanup of extracted directory

**How the detection works**:
```bash
# Example: tar -tzf frp_0.64.0_linux_amd64.tar.gz
# Output:
#   frp_0.64.0_linux_amd64/
#   frp_0.64.0_linux_amd64/frpc
#   frp_0.64.0_linux_amd64/frpd
#   ...
#
# Extract first line: "frp_0.64.0_linux_amd64/"
# Cut first field (/) : "frp_0.64.0_linux_amd64"
```

---

## 3. FRPC Uninstall - Process Cleanup Added

### BEFORE (Missing Process Cleanup)
```bash
uninstall_frpc() {
    echo -e "\n${RED}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║           DISINSTALLAZIONE FRPC CLIENT                    ║${NC}"
    echo -e "${RED}╚════════════════════════════════════════════════════════════╝${NC}"
    
    echo -e "\n${YELLOW}🗑️  Rimozione FRPC in corso...${NC}\n"
    
    # ❌ MISSING: Process termination!
    
    # Stop e disable servizio
    if systemctl is-active --quiet frpc 2>/dev/null; then
        echo -e "${YELLOW}⏹️  Arresto servizio FRPC...${NC}"
        systemctl stop frpc
    fi
```

### AFTER (Platform-Aware + Process Cleanup)
```bash
uninstall_frpc() {
    echo -e "\n${RED}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║           DISINSTALLAZIONE FRPC CLIENT                    ║${NC}"
    echo -e "${RED}╚════════════════════════════════════════════════════════════╝${NC}"
    
    echo -e "\n${YELLOW}🗑️  Rimozione FRPC in corso...${NC}\n"
    
    # ✅ Kill processi FRPC
    killall frpc 2>/dev/null || true
    
    # ✅ Gestisci servizi per il tipo di sistema
    if [ "$PKG_TYPE" = "openwrt" ]; then
        # OpenWrt: init.d
        if [ -f /etc/init.d/frpc ]; then
            echo -e "${YELLOW}⏹️  Arresto servizio FRPC...${NC}"
            /etc/init.d/frpc stop 2>/dev/null || true
            /etc/init.d/frpc disable 2>/dev/null || true
            rm -f /etc/init.d/frpc
        fi
    else
        # Linux: systemd
        if systemctl is-active --quiet frpc 2>/dev/null; then
            echo -e "${YELLOW}⏹️  Arresto servizio FRPC...${NC}"
            systemctl stop frpc 2>/dev/null || true
        fi
        
        if systemctl is-enabled --quiet frpc 2>/dev/null; then
            echo -e "${YELLOW}⏹️  Disabilito servizio FRPC...${NC}"
            systemctl disable frpc 2>/dev/null || true
        fi
```

**Improvements**:
- ✅ Terminates running processes immediately
- ✅ Handles both systemd (Linux) and init.d (OpenWrt)
- ✅ Removes service files for both platforms
- ✅ Robust error handling with `2>/dev/null || true`

---

## 4. Agent Uninstall - Complete Rewrite for Cross-Platform

### BEFORE (Systemd Only - Fails on OpenWrt)
```bash
uninstall_agent() {
    # ... header ...
    
    # ❌ Only handles systemd, not init.d
    # ❌ Only handles DEB/RPM packages, not manual extraction
    # ❌ Doesn't kill socat process
    
    # Stop e disable socket plain
    if systemctl is-active --quiet check-mk-agent-plain.socket 2>/dev/null; then
        echo -e "${YELLOW}⏹️  Arresto socket plain...${NC}"
        systemctl stop check-mk-agent-plain.socket
    fi
    
    # Disinstalla pacchetto
    echo -e "${YELLOW}📦 Disinstallazione pacchetto CheckMK Agent...${NC}"
    if [ "$PKG_TYPE" = "deb" ]; then
        if dpkg -l | grep -q check-mk-agent; then
            apt-get remove -y check-mk-agent 2>/dev/null || dpkg --purge check-mk-agent
        fi
    fi
```

### AFTER (Cross-Platform)
```bash
uninstall_agent() {
    # ... header ...
    
    echo -e "\n${YELLOW}🗑️  Rimozione CheckMK Agent in corso...${NC}\n"
    
    # ✅ Kill processi
    killall check_mk_agent 2>/dev/null || true
    killall socat 2>/dev/null || true
    
    # ✅ Gestisci servizi per il tipo di sistema
    if [ "$PKG_TYPE" = "openwrt" ]; then
        # OpenWrt: init.d
        if [ -f /etc/init.d/check_mk_agent ]; then
            echo -e "${YELLOW}⏹️  Arresto servizio agent...${NC}"
            /etc/init.d/check_mk_agent stop 2>/dev/null || true
            /etc/init.d/check_mk_agent disable 2>/dev/null || true
            rm -f /etc/init.d/check_mk_agent
        fi
    else
        # Linux: systemd socket
        if systemctl is-active --quiet check-mk-agent-plain.socket 2>/dev/null; then
            echo -e "${YELLOW}⏹️  Arresto socket plain...${NC}"
            systemctl stop check-mk-agent-plain.socket 2>/dev/null || true
        fi
        
        if systemctl is-enabled --quiet check-mk-agent-plain.socket 2>/dev/null; then
            echo -e "${YELLOW}⏹️  Disabilito socket plain...${NC}"
            systemctl disable check-mk-agent-plain.socket 2>/dev/null || true
        fi
        
        if [ -f /etc/systemd/system/check-mk-agent-plain.socket ]; then
            echo -e "${YELLOW}🗑️  Rimozione socket systemd plain...${NC}"
            rm -f /etc/systemd/system/check-mk-agent-plain.socket
        fi
        
        if [ -f /etc/systemd/system/check-mk-agent-plain@.service ]; then
            echo -e "${YELLOW}🗑️  Rimozione service systemd plain...${NC}"
            rm -f /etc/systemd/system/check-mk-agent-plain@.service
        fi
        
        systemctl daemon-reload 2>/dev/null || true
    fi
    
    # ✅ Rimuovi eseguibile
    if [ -f /usr/bin/check_mk_agent ]; then
        echo -e "${YELLOW}🗑️  Rimozione eseguibile agent...${NC}"
        rm -f /usr/bin/check_mk_agent
    fi
    
    # ✅ Rimuovi configurazione
    if [ -d /etc/check_mk ]; then
        echo -e "${YELLOW}🗑️  Rimozione directory configurazione...${NC}"
        rm -rf /etc/check_mk
    fi
    
    # ✅ Rimuovi xinetd config (se presente)
    if [ -f /etc/xinetd.d/check_mk ]; then
        echo -e "${YELLOW}🗑️  Rimozione configurazione xinetd...${NC}"
        rm -f /etc/xinetd.d/check_mk
        systemctl reload xinetd 2>/dev/null || true
    fi
```

**Improvements**:
- ✅ Terminates both agent and socat processes
- ✅ Handles init.d (OpenWrt) service removal
- ✅ Handles systemd (Linux) socket/service removal
- ✅ Works with manually extracted agents (not just packages)
- ✅ Complete configuration and xinetd cleanup
- ✅ Robust error handling throughout

---

## Key Metrics

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Lines in `install_frpc()` | 30 | 40 | +33% (better structure) |
| Lines in `uninstall_frpc()` | 50 | 65 | +30% (added platform support) |
| Lines in `uninstall_agent()` | 60 | 91 | +52% (added platform support) |
| Platform support | 2 | 3 | OpenWrt added |
| Process cleanup | None | 3 types | ✅ Complete |
| Directory handling | Fixed | Dynamic | ✅ Flexible |
| Error handling | Basic | Robust | ✅ Enhanced |

---

## Testing Commands

### Fresh Installation Test
```bash
./install-agent-interactive.sh
# Enters: yes for FRPC
# Verify: FRPC binary at /usr/local/bin/frpc
# Verify: Config at /etc/frp/frpc.toml
# Verify: Service running (systemctl status or /etc/init.d/frpc)
```

### Uninstall Test
```bash
./install-agent-interactive.sh --uninstall-frpc
# Verify: /usr/local/bin/frpc gone
# Verify: /etc/frp/ removed
# Verify: Service files removed
# Verify: No frpc process running: pgrep frpc (should return nothing)
```

### Log Verification
```bash
# On Linux (systemd):
journalctl -u frpc -f

# On OpenWrt (init.d):
tail -f /var/log/frpc.log
```

---

## Summary

✅ **All issues resolved** by porting proven code from `install-checkmk-agent-debtools-frp-nsec8c.sh`  
✅ **Complete platform support** for OpenWrt and Linux systems  
✅ **Dynamic directory detection** handles future version changes  
✅ **Proper process cleanup** using `killall` before service removal  
✅ **Comprehensive file cleanup** removes all traces of installations  
✅ **Backward compatible** - no command-line interface changes

