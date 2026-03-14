#!/bin/sh
# ==========================================================
# ROCKSOLID Startup Check & Remediation
# Verifica e ripristina servizi critici ad ogni avvio
# ==========================================================

LOG_FILE="/var/log/rocksolid-startup.log"
SYSUPGRADE_CONF="/etc/sysupgrade.conf"

# Repository OpenWrt per download dinamico
REPO_PACKAGES="${REPO_PACKAGES:-https://downloads.openwrt.org/releases/23.05.0/packages/x86_64/packages}"

# Versione FRP (configurabile)
FRP_VER="${FRP_VER:-0.64.0}"

# Funzione log con timestamp
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"
    logger -t rocksolid-startup "$*"
}

# Download dinamico pacchetti OpenWrt (evita URL statici fragili)
download_openwrt_package() {
    local package_name="$1"
    local repo_url="$2"
    local output_file="$3"
    
    log "[Download] Ricerca dinamica pacchetto: $package_name"
    
    # Scarica lista pacchetti OpenWrt
    if ! wget -q -O /tmp/Packages.gz "${repo_url}/Packages.gz" 2>/dev/null; then
        log "[Download] WARN: Download Packages.gz fallito"
        return 1
    fi
    
    # Verifica gzip/gunzip disponibile
    if ! command -v gunzip >/dev/null 2>&1 && ! command -v gzip >/dev/null 2>&1; then
        log "[Download] WARN: gzip/gunzip non disponibile"
        rm -f /tmp/Packages.gz
        return 1
    fi
    
    # Estrai filename del pacchetto dall'index
    # Pattern: "Filename: package_name_version_arch.ipk" (no slash before package name)
    local package_file=$(gunzip -c /tmp/Packages.gz 2>/dev/null | grep "^Filename:" | grep "${package_name}_" | head -1 | awk '{print $2}')
    rm -f /tmp/Packages.gz
    
    if [ -z "$package_file" ]; then
        log "[Download] WARN: Pacchetto $package_name non trovato nell'index"
        return 1
    fi
    
    log "[Download] Trovato: $package_file"
    
    # Download pacchetto
    if wget -q -O "$output_file" "${repo_url}/${package_file}" 2>/dev/null; then
        log "[Download] Completato: $package_file"
        return 0
    else
        log "[Download] ERRORE: Download fallito"
        return 1
    fi
}

log "========================================="
log "ROCKSOLID Startup Check - AVVIO"
log "========================================="

# ============================================================================
# 0. RIPRISTINA BINARI CRITICI (se backup disponibile)
# ============================================================================
BACKUP_DIR="/opt/checkmk-backups/binaries"

if [ -d "$BACKUP_DIR" ]; then
    log "[Binari Critici] Verifica e ripristino in corso..."
    
    # STEP 1: Ripristina backup binari se mancanti
    for backup in "$BACKUP_DIR"/*.backup; do
        [ -f "$backup" ] || continue
        
        basename_file=$(basename "$backup" .backup)
        
        case "$basename_file" in
            tar-gnu|gzip-gnu|gunzip-gnu|zcat-gnu)
                dest="/usr/libexec/$basename_file"
                ;;
            ar)
                dest="/usr/bin/$basename_file"
                ;;
            libbfd-*.so)
                dest="/usr/lib/$basename_file"
                ;;
            *)
                continue
                ;;
        esac
        
        # Ripristina se mancante o corrotto
        if [ ! -f "$dest" ]; then
            log "[Binari Critici] RIPRISTINO: $dest (mancante)"
            cp -p "$backup" "$dest" 2>/dev/null || true
        elif ! file "$dest" 2>/dev/null | grep -q "ELF"; then
            log "[Binari Critici] RIPRISTINO: $dest (corrotto)"
            cp -p "$backup" "$dest" 2>/dev/null || true
        fi
    done
    
    # STEP 2: Verifica se ar funziona DOPO ripristino backup
    BINARIES_CORRUPTED=0
    if [ -x /usr/bin/ar ]; then
        if ! /usr/bin/ar --version >/dev/null 2>&1; then
            log "[Binari Critici] ar corrotto dopo ripristino - mancano shared libraries"
            BINARIES_CORRUPTED=1
        fi
    else
        log "[Binari Critici] ar non eseguibile dopo ripristino"
        BINARIES_CORRUPTED=1
    fi
    
    # STEP 3: Se ancora corrotto, reinstalla dependencies chain (libbfd → ar)
    if [ $BINARIES_CORRUPTED -eq 1 ]; then
        if command -v opkg >/dev/null 2>&1 && command -v wget >/dev/null 2>&1; then
            log "[Binari Critici] Reinstallo dependencies chain (libbfd → ar)..."
            REPO_BASE="https://downloads.openwrt.org/releases/23.05.0/packages/x86_64/base"
            
            # Install libbfd (base library)
            if download_openwrt_package "libbfd" "$REPO_BASE" "/tmp/libbfd.ipk"; then
                opkg install --force-depends /tmp/libbfd.ipk >/dev/null 2>&1 || true
                rm -f /tmp/libbfd.ipk
            fi
            
            # Install ar (uses libbfd)
            if download_openwrt_package "ar" "$REPO_BASE" "/tmp/ar.ipk"; then
                opkg install --force-depends /tmp/ar.ipk >/dev/null 2>&1 || true
                rm -f /tmp/ar.ipk
                
                # Verifica finale
                if /usr/bin/ar --version >/dev/null 2>&1; then
                    log "[Binari Critici] ar reinstallato e funzionante"
                else
                    log "[Binari Critici] ERRORE: ar ancora non funzionante"
                fi
            fi
        fi
    else
        log "[Binari Critici] ar funzionante dopo ripristino backup"
    fi
    
    log "[Binari Critici] Verifica completata"
fi

# ============================================================================
# 0.5 VERIFICA E RIPRISTINA NODE.JS + NGINX (NethSecurity Web UI)
# ============================================================================
log "[Node.js] Verifica in corso..."

# Verifica se node.js è installato
if ! command -v node >/dev/null 2>&1; then
    log "[Node.js] MANCANTE - Reinstallazione automatica..."
    
    if command -v wget >/dev/null 2>&1; then
        # Verifica e installa libcares (dipendenza node.js)
        if ! opkg list-installed | grep -q "^libcares "; then
            log "[Node.js] Installazione dipendenza libcares..."
            opkg update >> "$LOG_FILE" 2>&1
            opkg install libcares >> "$LOG_FILE" 2>&1 || log "[Node.js] WARNING: Installazione libcares fallita"
        fi
        
        log "[Node.js] Download dinamico da OpenWrt..."
        cd /tmp || exit 1
        
        # Download dinamico node.js (trova versione corrente automaticamente)
        if download_openwrt_package "node" "$REPO_PACKAGES" "/tmp/node.ipk"; then
            log "[Node.js] Installazione pacchetto..."
            opkg install node.ipk >> "$LOG_FILE" 2>&1
            rm -f node.ipk
            
            if command -v node >/dev/null 2>&1; then
                log "[Node.js] RIPRISTINATO: $(node --version)"
            else
                log "[Node.js] ERRORE: Installazione fallita"
            fi
        else
            log "[Node.js] ERRORE: Download dinamico fallito"
        fi
    else
        log "[Node.js] ERRORE: wget non disponibile"
    fi
else
    log "[Node.js] OK - Presente: $(node --version 2>&1 | head -1)"
fi

# Verifica e riavvia servizi web
log "[Web UI] Verifica servizi..."
if command -v nginx >/dev/null 2>&1; then
    # Ripristina symlink uci.conf se mancante (cancellato durante upgrade)
    if [ ! -L /etc/nginx/uci.conf ] && [ -f /var/lib/nginx/uci.conf ]; then
        log "[Nginx] Ripristino symlink uci.conf..."
        ln -sf /var/lib/nginx/uci.conf /etc/nginx/uci.conf 2>/dev/null || true
    fi
    
    if ! pgrep -f "nginx.*master" >/dev/null 2>&1; then
        log "[Nginx] Servizio non attivo, avvio..."
        /etc/init.d/nginx enable 2>/dev/null || true
        /etc/init.d/nginx restart >> "$LOG_FILE" 2>&1 || true
        sleep 2
        
        if pgrep -f "nginx.*master" >/dev/null 2>&1; then
            log "[Nginx] Servizio riavviato"
        else
            log "[Nginx] ERRORE: Impossibile avviare nginx"
        fi
    else
        log "[Nginx] OK - Servizio attivo"
    fi
    
    # Verifica porta 9090 (Web UI NethSecurity)
    if ! netstat -tlnp 2>/dev/null | grep -q ":9090.*LISTEN"; then
        log "[Web UI] Porta 9090 non attiva, riconfigurazione..."
        
        # Esegui script ns-ui per riconfigurare nginx
        if [ -x /usr/sbin/ns-ui ]; then
            /usr/sbin/ns-ui >> "$LOG_FILE" 2>&1 || true
            /etc/init.d/nginx restart >> "$LOG_FILE" 2>&1 || true
            sleep 2
            
            if netstat -tlnp 2>/dev/null | grep -q ":9090.*LISTEN"; then
                log "[Web UI] Porta 9090 attiva dopo riconfigurazione"
            else
                log "[Web UI] ERRORE: Porta 9090 non disponibile"
            fi
        else
            log "[Web UI] ERRORE: /usr/sbin/ns-ui non disponibile"
        fi
    else
        log "[Web UI] OK - Porta 9090 attiva"
    fi
fi

# ============================================================================
# 1. VERIFICA E RIPRISTINA CHECKMK AGENT
# ============================================================================
log "[CheckMK Agent] Verifica in corso..."

if [ ! -x /usr/bin/check_mk_agent ]; then
    log "[CheckMK Agent] ERRORE: Binary mancante!"
    log "[CheckMK Agent] Eseguo script post-upgrade..."
    if [ -x /etc/checkmk-post-upgrade.sh ]; then
        /etc/checkmk-post-upgrade.sh >> "$LOG_FILE" 2>&1
    else
        log "[CheckMK Agent] CRITICO: Script post-upgrade mancante!"
    fi
else
    # Binary presente, verifica servizio
    if ! pgrep -f "socat TCP-LISTEN:6556" >/dev/null 2>&1; then
        log "[CheckMK Agent] Servizio non attivo, avvio..."
        /etc/init.d/check_mk_agent enable 2>/dev/null || true
        /etc/init.d/check_mk_agent restart 2>/dev/null || true
        sleep 2
        if pgrep -f "socat TCP-LISTEN:6556" >/dev/null 2>&1; then
            log "[CheckMK Agent] Servizio riavviato con successo"
        else
            log "[CheckMK Agent] ERRORE: Impossibile avviare servizio"
        fi
    else
        log "[CheckMK Agent] OK - Servizio attivo"
    fi
fi

# ============================================================================
# 2. VERIFICA E RIPRISTINA FRP CLIENT
# ============================================================================
log "[FRP Client] Verifica in corso..."

FRP_MARKER="/etc/.frp-installed"

if [ -f "$FRP_MARKER" ]; then
    # FRP era installato, deve funzionare
    
    # Verifica corruzione binario frpc (problema comune dopo upgrade)
    FRPC_CORRUPTED=0
    if [ -x /usr/local/bin/frpc ]; then
        if ! /usr/local/bin/frpc -v >/dev/null 2>&1; then
            log "[FRP Client] CRITICO: Binario corrotto (upgrade ha danneggiato file)"
            FRPC_CORRUPTED=1
        fi
    fi
    
    if [ ! -x /usr/local/bin/frpc ] || [ ! -f /etc/frp/frpc.toml ] || [ ! -f /etc/init.d/frpc ] || [ $FRPC_CORRUPTED -eq 1 ]; then
        log "[FRP Client] Reinstallazione automatica..."
        
        # Download e reinstalla frpc da GitHub (versione configurabile)
        cd /tmp || true
        if command -v wget >/dev/null 2>&1; then
            FRP_TGZ="frp_${FRP_VER}_linux_amd64.tar.gz"
            FRP_URL="https://github.com/fatedier/frp/releases/download/v${FRP_VER}/${FRP_TGZ}"
            
            log "[FRP Client] Download v${FRP_VER} da GitHub..."
            wget -q "$FRP_URL" 2>/dev/null || true
            
            if [ -f "$FRP_TGZ" ]; then
                tar -xzf "$FRP_TGZ" 2>/dev/null || true
                FRP_DIR="frp_${FRP_VER}_linux_amd64"
                
                if [ -f "$FRP_DIR/frpc" ]; then
                    cp -f "$FRP_DIR/frpc" /usr/local/bin/frpc 2>/dev/null || true
                    chmod +x /usr/local/bin/frpc 2>/dev/null || true
                    rm -rf frp_* 2>/dev/null || true
                    log "[FRP Client] Binario reinstallato v${FRP_VER}"
                fi
            else
                log "[FRP Client] ERRORE: Download v${FRP_VER} fallito"
            fi
        fi
    fi
    
    if ! pgrep -f frpc >/dev/null 2>&1; then
        log "[FRP Client] Servizio non attivo, avvio..."
        /etc/init.d/frpc enable 2>/dev/null || true
        /etc/init.d/frpc restart 2>/dev/null || true
        sleep 2
        if pgrep -f frpc >/dev/null 2>&1; then
            log "[FRP Client] Servizio riavviato con successo"
        else
            log "[FRP Client] ERRORE: Impossibile avviare servizio"
        fi
    else
        log "[FRP Client] OK - Servizio attivo"
    fi
else
    # FRP non era mai stato installato, ├¿ opzionale
    if [ -x /usr/local/bin/frpc ] && [ -f /etc/frp/frpc.toml ]; then
        log "[FRP Client] Trovato ma senza marker (installazione manuale?)"
        if ! pgrep -f frpc >/dev/null 2>&1; then
            log "[FRP Client] Avvio servizio..."
            /etc/init.d/frpc enable 2>/dev/null || true
            /etc/init.d/frpc restart 2>/dev/null || true
        fi
    else
        log "[FRP Client] Non installato (opzionale)"
    fi
fi

# ============================================================================
# 2.5 VERIFICA E RIPRISTINA QEMU GUEST AGENT (VM ONLY)
# ============================================================================
if [ -f "/usr/bin/qemu-ga" ]; then
    log "[QEMU-GA] Verifica in corso..."
    
    # Self-healing: riconfigura init script in base a device disponibile
    if [ -e "/dev/virtio-ports/org.qemu.guest_agent.0" ]; then
        # Proxmox con virtio-serial disponibile
        EXPECTED_MODE="virtio-serial"
        EXPECTED_PATH="/dev/virtio-ports/org.qemu.guest_agent.0"
    elif [ -e "/dev/vport2p1" ]; then
        # Proxmox con device vportXpY diretto
        EXPECTED_MODE="virtio-serial"
        EXPECTED_PATH="/dev/vport2p1"
    else
        # Fallback isa-serial
        EXPECTED_MODE="isa-serial"
        EXPECTED_PATH="/dev/ttyS0"
    fi
    
    # Verifica se init script ha configurazione corretta
    if ! grep -q "$EXPECTED_MODE" /etc/init.d/qemu-ga 2>/dev/null; then
        log "[QEMU-GA] Riconfigurazione init script per $EXPECTED_MODE..."
        cat > /etc/init.d/qemu-ga <<QEMU_INIT
#!/bin/sh /etc/rc.common
START=99
USE_PROCD=1

start_service() {
    procd_open_instance
    procd_set_param command /usr/bin/qemu-ga -m $EXPECTED_MODE -p $EXPECTED_PATH
    procd_set_param respawn
    procd_set_param stdout 1
    procd_set_param stderr 1
    procd_close_instance
}
QEMU_INIT
        chmod +x /etc/init.d/qemu-ga
        log "[QEMU-GA] Init script aggiornato per $EXPECTED_MODE"
    fi
    
    if ! pgrep qemu-ga >/dev/null 2>&1; then
        log "[QEMU-GA] Servizio non attivo, avvio..."
        /etc/init.d/qemu-ga enable 2>/dev/null || true
        /etc/init.d/qemu-ga restart 2>/dev/null || true
        sleep 2
        
        if pgrep qemu-ga >/dev/null 2>&1; then
            log "[QEMU-GA] Servizio riavviato con successo ($EXPECTED_MODE)"
        else
            log "[QEMU-GA] ERRORE: Impossibile avviare servizio"
        fi
    else
        log "[QEMU-GA] OK - Servizio attivo"
    fi
else
    log "[QEMU-GA] Non installato (opzionale, solo per VM)"
fi

# ============================================================================
# 2.7 VERIFICA E RIPRISTINA GIT (per Auto-Sync Repository)
# ============================================================================
log "[Git] Verifica in corso..."

if ! command -v git >/dev/null 2>&1; then
    log "[Git] Non trovato - installazione automatica per Auto-Sync..."
    
    if command -v opkg >/dev/null 2>&1 && command -v wget >/dev/null 2>&1; then
        # Download dinamico git e git-http da OpenWrt
        if download_openwrt_package "git" "$REPO_PACKAGES" "/tmp/git.ipk"; then
            if download_openwrt_package "git-http" "$REPO_PACKAGES" "/tmp/git-http.ipk"; then
                opkg install /tmp/git.ipk /tmp/git-http.ipk >/dev/null 2>&1
                rm -f /tmp/git.ipk /tmp/git-http.ipk
                
                if command -v git >/dev/null 2>&1; then
                    log "[Git] Installato con successo: $(git --version 2>&1 | head -1)"
                else
                    log "[Git] ERRORE: Installazione fallita"
                fi
            else
                log "[Git] ERRORE: Download git-http fallito"
            fi
        else
            log "[Git] ERRORE: Download git fallito"
        fi
    else
        log "[Git] ERRORE: opkg o wget non disponibili"
    fi
else
    log "[Git] OK - Presente: $(git --version 2>&1 | head -1)"
fi

# ============================================================================
# 2.8 AUTO-DEPLOY LOCAL CHECKS E PLUGIN DA REPOSITORY
# ============================================================================
if [ -d "/opt/checkmk-tools/script-check-nsec8/full" ]; then
    log "[Auto-Deploy] Verifica nuovi script locali..."
    
    # Deploy local checks (check_*.sh)
    DEPLOYED_CHECKS=0
    for script in /opt/checkmk-tools/script-check-nsec8/full/check_*.sh; do
        [ -f "$script" ] || continue
        basename_script=$(basename "$script")
        dest="/usr/lib/check_mk_agent/local/$basename_script"
        
        # Copia se mancante o se repository ha versione più recente
        if [ ! -f "$dest" ] || [ "$script" -nt "$dest" ]; then
            log "[Auto-Deploy] Deploy: $basename_script"
            cp -p "$script" "$dest" 2>/dev/null && \
                chmod +x "$dest" && \
                DEPLOYED_CHECKS=$((DEPLOYED_CHECKS + 1))
        fi
    done
    
    if [ "$DEPLOYED_CHECKS" -gt 0 ]; then
        log "[Auto-Deploy] Deployed $DEPLOYED_CHECKS local check(s)"
    else
        log "[Auto-Deploy] Local checks già aggiornati"
    fi
fi

# Deploy plugins (se directory esiste)
if [ -d "/opt/checkmk-tools/script-check-nsec8/plugins" ]; then
    log "[Auto-Deploy] Verifica nuovi plugin..."
    
    DEPLOYED_PLUGINS=0
    for plugin in /opt/checkmk-tools/script-check-nsec8/plugins/*; do
        [ -f "$plugin" ] || continue
        basename_plugin=$(basename "$plugin")
        dest="/usr/lib/check_mk_agent/plugins/$basename_plugin"
        
        # Copia se mancante o se repository ha versione più recente
        if [ ! -f "$dest" ] || [ "$plugin" -nt "$dest" ]; then
            log "[Auto-Deploy] Deploy: $basename_plugin (plugin)"
            cp -p "$plugin" "$dest" 2>/dev/null && \
                chmod +x "$dest" && \
                DEPLOYED_PLUGINS=$((DEPLOYED_PLUGINS + 1))
        fi
    done
    
    if [ "$DEPLOYED_PLUGINS" -gt 0 ]; then
        log "[Auto-Deploy] Deployed $DEPLOYED_PLUGINS plugin(s)"
    else
        log "[Auto-Deploy] Plugin già aggiornati"
    fi
else
    log "[Auto-Deploy] Nessuna directory plugin nel repository"
fi

# ============================================================================
# 3. VERIFICA PROTEZIONI SYSUPGRADE.CONF
# ============================================================================
log "[Protezioni] Verifica sysupgrade.conf..."

# Conta tutte le righe non-commento non-vuote che iniziano con / (protezioni totali)
# -a forza trattamento come testo (alcuni sistemi vedono sysupgrade.conf come binario)
PROTECTED_COUNT=$(grep -a -v '^#' "$SYSUPGRADE_CONF" 2>/dev/null | grep -a -v '^$' | grep -a -E '^/' | wc -l)
PROTECTED_COUNT=$(echo "$PROTECTED_COUNT" | tr -d ' \n')
log "[Protezioni] File protetti: $PROTECTED_COUNT"

if [ "$PROTECTED_COUNT" -lt 5 ] 2>/dev/null; then
    log "[Protezioni] WARN: Poche protezioni attive (attese almeno 5)"
fi

# ============================================================================
# 4. RIEPILOGO FINALE
# ============================================================================
log "========================================="
log "RIEPILOGO STATO SERVIZI:"
log "========================================="

# CheckMK Agent
if pgrep -f "socat TCP-LISTEN:6556" >/dev/null 2>&1; then
    log "  CheckMK Agent:  [OK]"
else
    log "  CheckMK Agent:  [FAIL]"
fi

# FRP Client
if pgrep -f frpc >/dev/null 2>&1; then
    log "  FRP Client:     [OK]"
else
    log "  FRP Client:     [N/A]"
fi

# QEMU Guest Agent
if [ -f "/usr/bin/qemu-ga" ]; then
    if pgrep qemu-ga >/dev/null 2>&1; then
        log "  QEMU-GA:        [OK]"
    else
        log "  QEMU-GA:        [FAIL]"
    fi
fi

# Auto Git Sync (controlla sia script wrapper che comando diretto)
if [ -f "/etc/crontabs/root" ]; then
    if grep -qE "git-auto-sync\.sh|git.*checkmk-tools.*pull" /etc/crontabs/root 2>/dev/null; then
        log "  Auto Git Sync:  [OK]"
    else
        log "  Auto Git Sync:  [N/A]"
    fi
else
    log "  Auto Git Sync:  [N/A]"
fi

# Local Check Scripts
LOCAL_CHECK_COUNT=$(find /usr/lib/check_mk_agent/local/ -type f -name "check_*.sh" 2>/dev/null | wc -l)
LOCAL_CHECK_COUNT=$(echo "$LOCAL_CHECK_COUNT" | tr -d ' \n')
if [ "$LOCAL_CHECK_COUNT" -gt 0 ] 2>/dev/null; then
    log "  Local Checks:   [OK] ($LOCAL_CHECK_COUNT scripts)"
else
    log "  Local Checks:   [N/A]"
fi

# Plugin CheckMK
PLUGIN_COUNT=$(find /usr/lib/check_mk_agent/plugins/ -type f 2>/dev/null | wc -l)
PLUGIN_COUNT=$(echo "$PLUGIN_COUNT" | tr -d ' \n')
if [ "$PLUGIN_COUNT" -gt 0 ] 2>/dev/null; then
    log "  Plugins:        [OK] ($PLUGIN_COUNT plugins)"
else
    log "  Plugins:        [N/A]"
fi

log "========================================="
log "ROCKSOLID Startup Check - COMPLETATO"
log "========================================="

exit 0
