#!/bin/sh
set -eu

# install-checkmk-agent-debtools-frp-nsec8c-rocksolid.sh
# ROCKSOLID VERSION - Resiste ai major upgrade di NethSecurity/OpenWrt
# Install / uninstall Checkmk agent + (opzionale) FRP client su OpenWrt / NethSecurity (init: procd).
# Output semplice (ASCII-only).

# Modalità non-interattiva (es. boot automatico)
NON_INTERACTIVE="${NON_INTERACTIVE:-0}"

# Parsing parametri CLI
while [ $# -gt 0 ]; do
    case "$1" in
        --interactive|-i)
            NON_INTERACTIVE=0
            shift
            ;;
        --non-interactive)
            NON_INTERACTIVE=1
            shift
            ;;
        --frp-server)
            SERVER_ADDR="$2"
            shift 2
            ;;
        --frp-port)
            SERVER_PORT="$2"
            shift 2
            ;;
        --frp-token)
            FRP_TOKEN="$2"
            shift 2
            ;;
        --frp-proxy)
            PROXY_NAME="$2"
            shift 2
            ;;
        --frp-remote-port)
            REMOTE_PORT="$2"
            shift 2
            ;;
        --uninstall)
            UNINSTALL=1
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --interactive, -i           Forza modalità interattiva (chiede conferme)"
            echo "  --non-interactive           Forza modalità non-interattiva"
            echo "  --frp-server ADDR           Server FRP (es: monitor.nethlab.it)"
            echo "  --frp-port PORT             Porta FRP (default: 7000)"
            echo "  --frp-token TOKEN           Token autenticazione FRP"
            echo "  --frp-proxy NAME            Nome proxy FRP (es: nsec8-stable)"
            echo "  --frp-remote-port PORT      Porta remota tunnel FRP"
            echo "  --uninstall                 Disinstalla tutti i componenti"
            echo "  --help, -h                  Mostra questo help"
            exit 0
            ;;
        *)
            echo "Parametro sconosciuto: $1"
            echo "Usa --help per vedere le opzioni disponibili"
            exit 1
            ;;
    esac
done

CUSTOMFEEDS="${CUSTOMFEEDS:-/etc/opkg/customfeeds.conf}"
TMPDIR="${TMPDIR:-/tmp/checkmk-deb}"
SYSUPGRADE_CONF="${SYSUPGRADE_CONF:-/etc/sysupgrade.conf}"

# OpenWrt 23.05 x86_64 (come versione originale dello script)
REPO_BASE="${REPO_BASE:-https://downloads.openwrt.org/releases/23.05.0/packages/x86_64/base}"
REPO_PACKAGES="${REPO_PACKAGES:-https://downloads.openwrt.org/releases/23.05.0/packages/x86_64/packages}"

# Configurazione CheckMK Server
CMK_SERVER="${CMK_SERVER:-monitor.nethlab.it}"
CMK_SITE="${CMK_SITE:-monitoring}"
CMK_PROTOCOL="${CMK_PROTOCOL:-https}"

# URL del .deb dell'agente (rilevato automaticamente o override manuale)
DEB_URL="${DEB_URL:-}"

FRP_VER="${FRP_VER:-0.64.0}"
FRPC_BIN="${FRPC_BIN:-/usr/local/bin/frpc}"
FRPC_CONF="${FRPC_CONF:-/etc/frp/frpc.toml}"
FRPC_INIT="${FRPC_INIT:-/etc/init.d/frpc}"
FRPC_LOG="${FRPC_LOG:-/var/log/frpc.log}"

log() { echo "[INFO] $*"; }
warn() { echo "[WARN] $*"; }
die() { echo "[ERR] $*" >&2; exit 1; }

is_root() {
    [ "$(id -u 2>/dev/null || echo 1)" -eq 0 ]
}

need_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "comando mancante: $1"
}

# Controlla se siamo in modalità interattiva
is_interactive() {
    # Se --interactive esplicito, forza modalità interattiva anche senza TTY
    [ "$NON_INTERACTIVE" -eq 0 ]
}

add_repo() {
    name="$1"
    url="$2"
    grep -q "$url" "$CUSTOMFEEDS" 2>/dev/null || echo "src/gz $name $url" >>"$CUSTOMFEEDS"
}

cleanup_temp_repos() {
    # Rimuove i repository temporanei OpenWrt aggiunti per l'installazione
    if [ -f "$CUSTOMFEEDS" ]; then
        log "Rimozione repository temporanei..."
        sed -i '/^src\/gz openwrt_base/d' "$CUSTOMFEEDS" 2>/dev/null || true
        sed -i '/^src\/gz openwrt_packages/d' "$CUSTOMFEEDS" 2>/dev/null || true
        
        # CRITICO: Rimuovi anche CACHE opkg dei repository temporanei
        # Cache mantiene metadata pacchetti (incluso ns-ui 2.8.1 upstream)
        # Anche dopo rimozione repository, cache causa upgrade indesiderati
        log "Pulizia cache opkg repository temporanei..."
        rm -f /var/opkg-lists/openwrt_base* 2>/dev/null || true
        rm -f /var/opkg-lists/openwrt_packages* 2>/dev/null || true
    fi
}

# ============================================================================
# Rileva versione CheckMK e costruisce URL .deb dinamicamente
# ============================================================================
detect_checkmk_agent_url() {
    if [ -n "$DEB_URL" ]; then
        log "URL .deb specificato manualmente: $DEB_URL"
        return 0
    fi
    
    log "Rilevamento automatico versione CheckMK da $CMK_SERVER..."
    
    # Prova a rilevare la versione dall'API o dalla pagina agents
    local version=""
    local base_url="${CMK_PROTOCOL}://${CMK_SERVER}/${CMK_SITE}/check_mk/agents"
    
    # Metodo 1: Cerca la versione dalla pagina agents
    if command -v wget >/dev/null 2>&1; then
        version=$(wget -qO- --no-check-certificate "$base_url/" 2>/dev/null | grep -oP 'check-mk-agent_\K[0-9]+\.[0-9]+\.[0-9]+p[0-9]+' | head -1)
    elif command -v curl >/dev/null 2>&1; then
        version=$(curl -fsSL --insecure "$base_url/" 2>/dev/null | grep -oP 'check-mk-agent_\K[0-9]+\.[0-9]+\.[0-9]+p[0-9]+' | head -1)
    fi
    
    # Metodo 2: Prova URL diretto standard
    if [ -z "$version" ]; then
        warn "Impossibile rilevare versione automaticamente, provo versione di default"
        # Prova a scaricare dalla directory agents standard
        local test_url="${base_url}/check-mk-agent_2.4.0p14-1_all.deb"
        if command -v wget >/dev/null 2>&1; then
            if wget --spider --no-check-certificate "$test_url" 2>/dev/null; then
                version="2.4.0p14"
            fi
        elif command -v curl >/dev/null 2>&1; then
            if curl -fsSL -I --insecure "$test_url" >/dev/null 2>&1; then
                version="2.4.0p14"
            fi
        fi
    fi
    
    if [ -n "$version" ]; then
        DEB_URL="${base_url}/check-mk-agent_${version}-1_all.deb"
        log "Versione rilevata: $version"
        log "URL .deb: $DEB_URL"
    else
        # Fallback: usa URL di default
        DEB_URL="${CMK_PROTOCOL}://${CMK_SERVER}/${CMK_SITE}/check_mk/agents/check-mk-agent_2.4.0p14-1_all.deb"
        warn "Versione non rilevata, uso fallback: $DEB_URL"
    fi
}

# ============================================================================
# ROCKSOLID: Funzione per aggiungere file a sysupgrade.conf
# ============================================================================
add_to_sysupgrade() {
    local file_path="$1"
    local comment="${2:-}"
    
    # Crea il file se non esiste
    if [ ! -f "$SYSUPGRADE_CONF" ]; then
        log "Creo $SYSUPGRADE_CONF"
        cat > "$SYSUPGRADE_CONF" <<'EOF'
## This file contains files and directories that should
## be preserved during an upgrade.

EOF
    fi
    
    # Controlla se il file è già presente
    if grep -qxF "$file_path" "$SYSUPGRADE_CONF" 2>/dev/null; then
        return 0
    fi
    
    # Aggiungi commento se fornito
    if [ -n "$comment" ]; then
        echo "" >> "$SYSUPGRADE_CONF"
        echo "# $comment" >> "$SYSUPGRADE_CONF"
    fi
    
    # Aggiungi il file
    echo "$file_path" >> "$SYSUPGRADE_CONF"
    log "Aggiunto a sysupgrade.conf: $file_path"
}

# ============================================================================
# ROCKSOLID: Proteggi installazione CheckMK Agent
# ============================================================================
protect_checkmk_installation() {
    log "ROCKSOLID: Proteggo installazione CheckMK da major upgrade"
    
    # File critici CheckMK Agent
    add_to_sysupgrade "/usr/bin/check_mk_agent" "CheckMK Agent - Binary"
    add_to_sysupgrade "/etc/init.d/check_mk_agent" "CheckMK Agent - Init Script"
    add_to_sysupgrade "/etc/check_mk/" "CheckMK Agent - Configuration"
    
    # Directory critiche
    add_to_sysupgrade "/usr/local/bin/" "Script Custom Directory (preserva tutti gli script)"
    add_to_sysupgrade "/usr/lib/check_mk_agent/local/" "CheckMK Agent Local Checks (eseguiti ad ogni check)"
    add_to_sysupgrade "/usr/lib/check_mk_agent/plugins/" "CheckMK Agent Plugins (eseguiti ad intervalli)"
    
    # Repository checkmk-tools (script persistenti)
    add_to_sysupgrade "/opt/checkmk-tools/" "Repository checkmk-tools (git + script)"
    
    # Backup binari critici (separato da repo)
    add_to_sysupgrade "/opt/checkmk-backups/" "Backup binari critici (tar, ar, gzip)"
    
    # NGINX - Configurazione Web UI (porta 9090)
    add_to_sysupgrade "/etc/nginx/" "NGINX configuration (Web UI NethSecurity)"
    
    # Cron jobs
    add_to_sysupgrade "/etc/cron.d/" "Cron Jobs Directory"
    add_to_sysupgrade "/var/spool/cron/crontabs/" "User Crontabs"
    
    # Package dependencies (se installati via opkg, sono già protetti)
    # Ma aggiungiamo customfeeds per sicurezza
    add_to_sysupgrade "/etc/opkg/customfeeds.conf" "Custom package repositories"
    
    log "Installazione CheckMK protetta contro major upgrade"
}

# ============================================================================
# ROCKSOLID: Backup Binari Critici
# Backup di tar/ar/gzip che si corrompono durante major upgrade
# ============================================================================
backup_critical_binaries() {
    local backup_dir="/opt/checkmk-backups/binaries"
    local bins="/usr/libexec/tar-gnu /usr/bin/ar /usr/libexec/gzip-gnu /usr/libexec/gunzip-gnu /usr/lib/libbfd-2.40.so"
    
    log "ROCKSOLID: Backup binari critici (protegge da corruzione durante upgrade)..."
    mkdir -p "$backup_dir" 2>/dev/null || true
    
    for bin in $bins; do
        if [ -f "$bin" ] && file "$bin" 2>/dev/null | grep -q "ELF"; then
            local backup_file="$backup_dir/$(basename "$bin").backup"
            cp -p "$bin" "$backup_file" 2>/dev/null && \
                log "  ✓ Backup: $bin" || \
                warn "  ✗ Backup fallito: $bin"
        fi
    done
    
    # Proteggi backup in sysupgrade
    if ! grep -q "$backup_dir" "$SYSUPGRADE_CONF" 2>/dev/null; then
        {
            echo ""
            echo "# ROCKSOLID: Backup binari critici (tar, ar, gzip)"
            echo "$backup_dir/"
        } >> "$SYSUPGRADE_CONF"
        log "  ✓ Backup protetto in sysupgrade.conf"
    fi
    
    log "Binari critici backuppati in: $backup_dir"
}

# ============================================================================
# ROCKSOLID: Proteggi installazione FRP Client
# ============================================================================
protect_frp_installation() {
    log "ROCKSOLID: Proteggo installazione FRP da major upgrade"
    
    # Crea marker file per autocheck detection
    mkdir -p /opt/checkmk-tools
    echo "FRP installed on $(date '+%Y-%m-%d %H:%M:%S')" > /etc/.frp-installed
    log "Marker FRP creato: /etc/.frp-installed"
    
    add_to_sysupgrade "/usr/local/bin/frpc" "FRP Client - Binary"
    add_to_sysupgrade "/etc/frp/frpc.toml" "FRP Client - Configuration (CRITICO: contiene token)"
    add_to_sysupgrade "/etc/init.d/frpc" "FRP Client - Init Script"
    add_to_sysupgrade "/etc/.frp-installed" "FRP Client - Marker file (autocheck detection)"
    
    log "Installazione FRP protetta contro major upgrade"
}

# ============================================================================
# ROCKSOLID: Crea script di ripristino post-upgrade
# ============================================================================
create_post_upgrade_script() {
    local script_path="/etc/checkmk-post-upgrade.sh"
    
    log "Creo script di ripristino post-upgrade: $script_path"
    
    cat > "$script_path" <<'POSTSCRIPT'
#!/bin/sh
# Script eseguito automaticamente dopo major upgrade
# Ripristina binari corrotti e servizi CheckMK

log() { logger -t checkmk-post-upgrade "$*"; echo "[POST-UPGRADE] $*"; }

log "=== POST-UPGRADE: Inizio ripristino ==="

# ==========================================================
# FASE 1: RIPRISTINA BINARI CRITICI (tar, ar, gzip)
# Major upgrade spesso corrompe questi binari
# ==========================================================
BACKUP_DIR="/opt/checkmk-backups/binaries"

if [ -d "$BACKUP_DIR" ]; then
    log "Ripristino binari critici da backup..."
    
    for backup in "$BACKUP_DIR"/*.backup; do
        [ -f "$backup" ] || continue
        
        # Estrai nome originale
        basename_file=$(basename "$backup" .backup)
        
        # Determina path destinazione
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
                log "  ? SKIP: $basename_file (path sconosciuto)"
                continue
                ;;
        esac
        
        # Verifica se destinazione è corrotta (non-ELF)
        if [ -f "$dest" ]; then
            if ! file "$dest" 2>/dev/null | grep -q "ELF"; then
                log "  ⚠ CORROTTO: $dest - ripristino da backup"
                cp -p "$backup" "$dest" 2>/dev/null && \
                    log "  ✓ RIPRISTINATO: $dest" || \
                    log "  ✗ ERRORE ripristino: $dest"
            else
                log "  ✓ OK: $dest (già valido)"
            fi
        else
            # File mancante, ripristina
            log "  ⚠ MANCANTE: $dest - ripristino da backup"
            cp -p "$backup" "$dest" 2>/dev/null && \
                log "  ✓ RIPRISTINATO: $dest" || \
                log "  ✗ ERRORE ripristino: $dest"
        fi
    done
else
    log "⚠ Backup binari non trovato in $BACKUP_DIR"
fi

# ==========================================================
# FASE 2: VERIFICA E RIPRISTINA CHECKMK AGENT
# ==========================================================
log "Verifica installazione CheckMK Agent post-upgrade"

# Verifica binario
if [ ! -x /usr/bin/check_mk_agent ]; then
    log "ERRORE: /usr/bin/check_mk_agent mancante dopo upgrade!"
    exit 1
fi

# Verifica init script
if [ ! -x /etc/init.d/check_mk_agent ]; then
    log "ERRORE: /etc/init.d/check_mk_agent mancante dopo upgrade!"
    exit 1
fi

# Riattiva servizio
/etc/init.d/check_mk_agent enable 2>/dev/null || true
/etc/init.d/check_mk_agent restart 2>/dev/null || true

# Verifica FRP se presente
if [ -x /etc/init.d/frpc ]; then
    log "Riattivo FRP client"
    /etc/init.d/frpc enable 2>/dev/null || true
    /etc/init.d/frpc restart 2>/dev/null || true
fi

# Verifica processo socat
sleep 2
if pgrep -f "socat TCP-LISTEN:6556" >/dev/null 2>&1; then
    log "CheckMK Agent attivo su porta 6556"
else
    log "WARN: socat non in esecuzione, riavvio servizio"
    /etc/init.d/check_mk_agent restart
fi

log "Verifica completata"
POSTSCRIPT

    chmod +x "$script_path"
    
    # Proteggi anche lo script stesso
    add_to_sysupgrade "$script_path" "Post-upgrade verification script"
    
    log "Script post-upgrade creato e protetto"
}

# ============================================================================
# ROCKSOLID: Installa script autocheck all'avvio
# ============================================================================
install_autocheck() {
    log "Installazione script autocheck all'avvio"
    
    # IMPORTANTE: Scarica da GitHub e copia in /opt/checkmk-backups/ (protetto, no git dependency)
    local autocheck_script="/opt/checkmk-backups/rocksolid-startup-check.sh"
    local autocheck_url="https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/full/upgrade_maintenance/rocksolid-startup-check.sh"
    local autocheck_log="/var/log/rocksolid-startup.log"
    local rc_local="/etc/rc.local"
    
    # Download da GitHub (sempre ultima versione, no git dependency)
    log "Download rocksolid da GitHub (ultima versione)..."
    mkdir -p "$(dirname "$autocheck_script")" 2>/dev/null || true
    
    if command -v wget >/dev/null 2>&1; then
        wget -q -O "$autocheck_script" "$autocheck_url" 2>/dev/null || {
            warn "Download da GitHub fallito, provo repository locale"
            if [ -f "/opt/checkmk-tools/script-tools/full/upgrade_maintenance/rocksolid-startup-check.sh" ]; then
                cp -f "/opt/checkmk-tools/script-tools/full/upgrade_maintenance/rocksolid-startup-check.sh" "$autocheck_script"
            fi
        }
        chmod +x "$autocheck_script" 2>/dev/null || true
        log "Script rocksolid installato: $autocheck_script"
    else
        warn "wget non disponibile - fallback a repository locale"
        if [ -f "/opt/checkmk-tools/script-tools/full/upgrade_maintenance/rocksolid-startup-check.sh" ]; then
            cp -f "/opt/checkmk-tools/script-tools/full/upgrade_maintenance/rocksolid-startup-check.sh" "$autocheck_script"
            chmod +x "$autocheck_script"
            log "Script rocksolid copiato da repository locale"
        else
            warn "ATTENZIONE: Script rocksolid non disponibile"
        fi
    fi
    
    # Configura rc.local per esecuzione all'avvio
    # Configura rc.local per esecuzione all'avvio
    if [ ! -f "$rc_local" ]; then
        log "Creo $rc_local"
        cat > "$rc_local" <<'RCLOCAL'
#!/bin/sh
# Put your custom commands here that should be executed once
# the system init finished. By default this file does nothing.

exit 0
RCLOCAL
        chmod +x "$rc_local"
    fi
    
    # Aggiungi autocheck a rc.local - FORZA aggiornamento (rimuovi vecchie entry)
    # Esegue da /opt/checkmk-backups/ (upgrade-resistant, no git dependency)
    log "Configuro autocheck in rc.local (esecuzione da $autocheck_script)"
    # Rimuovi vecchie entry rocksolid (qualsiasi path)
    sed -i '/rocksolid-startup-check/d' "$rc_local"
    sed -i '/^exit 0/d' "$rc_local"
    # Aggiungi esecuzione da /opt/checkmk-backups/ (non dipende da git)
    echo "# ROCKSOLID Autocheck - esecuzione da /opt/checkmk-backups/ (upgrade-resistant, no git)" >> "$rc_local"
    echo "[ -x $autocheck_script ] && bash $autocheck_script >> /var/log/rocksolid-startup.log 2>&1 &" >> "$rc_local"
    echo "exit 0" >> "$rc_local"
    log "Autocheck configurato per esecuzione da $autocheck_script all'avvio"
    
    # Proteggi rc.local e directory checkmk-backups (script già dentro)
    add_to_sysupgrade "$rc_local" "Boot Script (rc.local)"
    
    log "Autocheck installato e protetto"
    
    # Test immediato
    log "Test esecuzione autocheck..."
    if "$autocheck_script"; then
        log "Test autocheck completato - verifica log in $autocheck_log"
    else
        warn "Test autocheck fallito"
    fi
}

uninstall_all() {
    log "Disinstallazione Checkmk Agent + FRP client"

    if [ -x "$FRPC_INIT" ]; then
        /etc/init.d/frpc stop >/dev/null 2>&1 || true
        /etc/init.d/frpc disable >/dev/null 2>&1 || true
    fi

    if [ -x /etc/init.d/check_mk_agent ]; then
        /etc/init.d/check_mk_agent stop >/dev/null 2>&1 || true
        /etc/init.d/check_mk_agent disable >/dev/null 2>&1 || true
        rm -f /etc/init.d/check_mk_agent
    fi

    killall frpc socat >/dev/null 2>&1 || true

    rm -rf /etc/frp >/dev/null 2>&1 || true
    rm -f "$FRPC_BIN" "$FRPC_INIT" "$FRPC_LOG" >/dev/null 2>&1 || true

    rm -f /usr/bin/check_mk_agent >/dev/null 2>&1 || true
    rm -rf /etc/check_mk /etc/xinetd.d/check_mk >/dev/null 2>&1 || true
    
    # Rimuovi anche script post-upgrade
    rm -f /etc/checkmk-post-upgrade.sh >/dev/null 2>&1 || true

    log "Disinstallazione completata"
    warn "NOTA: le entry in $SYSUPGRADE_CONF non sono state rimosse"
    warn "Per rimuoverle manualmente, modifica $SYSUPGRADE_CONF"
}

# ============================================================================
# Download dinamico pacchetti OpenWrt (evita URL statici fragili)
# ============================================================================
download_openwrt_package() {
    local package_name="$1"
    local repo_url="$2"  # es. https://downloads.openwrt.org/releases/23.05.0/packages/x86_64/base
    local output_file="$3"
    
    log "Download dinamico pacchetto: $package_name"
    
    # Scarica lista pacchetti OpenWrt
    if ! wget -q -O /tmp/Packages.gz "${repo_url}/Packages.gz"; then
        warn "Download Packages.gz fallito - impossibile rilevare versione dinamica"
        return 1
    fi
    
    # Verifica gzip disponibile per decompressione
    if ! command -v gunzip >/dev/null 2>&1 && ! command -v gzip >/dev/null 2>&1; then
        warn "gzip/gunzip non disponibile - fallback a ricerca diretta"
        rm -f /tmp/Packages.gz
        return 1
    fi
    
    # Estrai filename del pacchetto dall'index
    # Pattern: "Filename: package_name_version_arch.ipk" (no slash before package name)
    local package_file=$(gunzip -c /tmp/Packages.gz | grep "^Filename:" | grep "${package_name}_" | head -1 | awk '{print $2}')
    rm -f /tmp/Packages.gz
    
    if [ -z "$package_file" ]; then
        warn "Pacchetto $package_name non trovato nell'index OpenWrt"
        return 1
    fi
    
    log "Trovato nell'index: $package_file"
    
    # Download pacchetto
    if wget -O "$output_file" "${repo_url}/${package_file}" 2>/dev/null; then
        log "Download completato: $package_file"
        return 0
    else
        warn "Download fallito: ${repo_url}/${package_file}"
        return 1
    fi
}

install_prereqs() {
    need_cmd opkg

    # CRITICO: NON usare repository OpenWrt - causano conflitti di dipendenze
    # e rimozione di pacchetti critici (node.js, nginx-ssl-util, etc.)
    
    log "Installo tool necessari da repository NethSecurity"
    # Solo wget/socat/ca-certificates sono nei repo NethSecurity - installarli senza conflitti
    opkg update
    opkg install wget socat ca-certificates 2>/dev/null || \
        log "Alcuni pacchetti già installati (continuo comunque)"

    need_cmd wget
    need_cmd socat

    # Per ar/tar/gzip: usa opkg install (robusto, gestisce dipendenze)
    if ! command -v ar >/dev/null 2>&1 || ! command -v tar >/dev/null 2>&1 || ! command -v gzip >/dev/null 2>&1; then
        log "Binari ar/tar/gzip mancanti - installazione via opkg"
        
        # Download binutils (ar) - dinamico con catena dipendenze
        if ! command -v ar >/dev/null 2>&1; then
            log "Installazione binutils dependencies chain (libbfd → ar → objdump → binutils)..."
            
            # STEP 1: Install libbfd (base library)
            if download_openwrt_package "libbfd" "$REPO_BASE" "/tmp/libbfd.ipk"; then
                opkg install --force-depends /tmp/libbfd.ipk 2>/dev/null || warn "libbfd install fallito (ignoro)"
                rm -f /tmp/libbfd.ipk
            fi
            
            # STEP 2: Install ar (uses libbfd)
            if download_openwrt_package "ar" "$REPO_BASE" "/tmp/ar.ipk"; then
                opkg install --force-depends /tmp/ar.ipk 2>/dev/null || warn "ar install fallito (ignoro)"
                rm -f /tmp/ar.ipk
            fi
            
            # STEP 3: Install objdump (uses libbfd)
            if download_openwrt_package "objdump" "$REPO_BASE" "/tmp/objdump.ipk"; then
                opkg install --force-depends /tmp/objdump.ipk 2>/dev/null || warn "objdump install fallito (ignoro)"
                rm -f /tmp/objdump.ipk
            fi
            
            # STEP 4: Install binutils (meta-package, should work now)
            if download_openwrt_package "binutils" "$REPO_BASE" "/tmp/binutils.ipk"; then
                if opkg install --force-depends /tmp/binutils.ipk 2>/dev/null; then
                    log "binutils installato con successo via opkg"
                    rm -f /tmp/binutils.ipk
                else
                    warn "binutils opkg install fallito - verifica manuale ar"
                    rm -f /tmp/binutils.ipk
                    # Verifica se ar funziona comunque dopo install dependencies
                    if ! command -v ar >/dev/null 2>&1; then
                        die "ar non disponibile dopo install dependencies chain"
                    fi
                fi
            else
                die "Download binutils fallito - impossibile proseguire senza ar"
            fi
        fi
        
        # Download tar - dinamico
        if ! command -v tar >/dev/null 2>&1; then
            log "Installazione tar via opkg..."
            
            if download_openwrt_package "tar" "$REPO_BASE" "/tmp/tar.ipk"; then
                if opkg install --force-depends /tmp/tar.ipk 2>/dev/null; then
                    log "tar installato con successo via opkg"
                    rm -f /tmp/tar.ipk
                else
                    warn "opkg install fallito, provo estrazione manuale..."
                    ( cd /tmp && ar x tar.ipk && tar -xzf data.tar.gz && cp -f ./usr/libexec/tar-gnu /usr/local/bin/tar ) || die "Estrazione tar fallita"
                    chmod +x /usr/local/bin/tar
                    export PATH="/usr/local/bin:$PATH"
                    rm -f /tmp/tar.ipk /tmp/data.tar.gz /tmp/control.tar.gz /tmp/debian-binary
                    log "tar installato con successo (estrazione manuale)"
                fi
            else
                die "Download tar fallito - impossibile proseguire senza tar"
            fi
        fi
        
        # Download gzip - dinamico
        if ! command -v gzip >/dev/null 2>&1; then
            log "Installazione gzip via opkg..."
            
            if download_openwrt_package "gzip" "$REPO_BASE" "/tmp/gzip.ipk"; then
                if opkg install --force-depends /tmp/gzip.ipk 2>/dev/null; then
                    log "gzip installato con successo via opkg"
                    rm -f /tmp/gzip.ipk
                else
                    warn "opkg install fallito, provo estrazione manuale..."
                    ( cd /tmp && ar x gzip.ipk && tar -xzf data.tar.gz && cp -f ./usr/libexec/gzip-gnu /usr/local/bin/gzip ) || die "Estrazione gzip fallita"
                    chmod +x /usr/local/bin/gzip
                    export PATH="/usr/local/bin:$PATH"
                    rm -f /tmp/gzip.ipk /tmp/data.tar.gz /tmp/control.tar.gz /tmp/debian-binary
                    log "gzip installato con successo (estrazione manuale)"
                fi
            else
                die "Download gzip fallito - impossibile proseguire senza gzip"
            fi
        fi
    fi

    need_cmd ar
    need_cmd tar
}

install_agent() {
    log "Installazione Checkmk agent"

    rm -rf "$TMPDIR" >/dev/null 2>&1 || true
    mkdir -p "$TMPDIR/data"
    cd "$TMPDIR" || die "cd fallito: $TMPDIR"

    log "Download .deb agente"
    wget -O check-mk-agent.deb "$DEB_URL" || die "download fallito: $DEB_URL"

    log "Estrazione .deb (ar + tar)"
    ar x check-mk-agent.deb || die "ar x fallito"

    # Debian packages: data.tar.gz or data.tar.xz
    if [ -f data.tar.gz ]; then
        tar -xzf data.tar.gz -C data || die "tar -xzf fallito"
    elif [ -f data.tar.xz ]; then
        tar -xJf data.tar.xz -C data || die "tar -xJf fallito"
    else
        die "data.tar.* non trovato nel .deb"
    fi

    if [ ! -f data/usr/bin/check_mk_agent ]; then
        die "file mancante dopo estrazione: data/usr/bin/check_mk_agent"
    fi

    log "Copia binario agente"
    mkdir -p /usr/bin
    cp -f data/usr/bin/check_mk_agent /usr/bin/check_mk_agent
    chmod +x /usr/bin/check_mk_agent

    log "Copia configurazione (best effort)"
    mkdir -p /etc/check_mk
    if [ -d data/etc/check_mk ]; then
        cp -rf data/etc/check_mk/* /etc/check_mk/ 2>/dev/null || true
    fi

    log "Crea directory local checks e plugins"
    mkdir -p /usr/lib/check_mk_agent/local
    mkdir -p /usr/lib/check_mk_agent/plugins

    cd / || true
    rm -rf "$TMPDIR" >/dev/null 2>&1 || true

    log "Agente installato: /usr/bin/check_mk_agent"
}

install_agent_service() {
    log "Creo servizio procd (socat listener su 6556)"

    cat >/etc/init.d/check_mk_agent <<'EOF'
#!/bin/sh /etc/rc.common
START=98
STOP=10
USE_PROCD=1

PROG=/usr/bin/check_mk_agent

start_service() {
    procd_open_instance
    procd_set_param respawn
    procd_set_param command socat TCP-LISTEN:6556,reuseaddr,fork,keepalive EXEC:$PROG
    procd_set_param stdout 1
    procd_set_param stderr 1
    procd_close_instance
}

stop_service() {
    killall socat >/dev/null 2>&1 || true
}
EOF

    chmod +x /etc/init.d/check_mk_agent
    /etc/init.d/check_mk_agent enable >/dev/null 2>&1 || true
    /etc/init.d/check_mk_agent restart >/dev/null 2>&1 || /etc/init.d/check_mk_agent start >/dev/null 2>&1 || true

    # Best effort check
    if pgrep -f "socat TCP-LISTEN:6556" >/dev/null 2>&1; then
        log "Checkmk agent in ascolto su TCP 6556 (socat)"
    else
        warn "socat non risulta in esecuzione: verificare /etc/init.d/check_mk_agent e log di sistema"
    fi
}

# ============================================================================
# QEMU Guest Agent Installation (per VM Proxmox/KVM)
# ============================================================================
install_qemu_ga() {
    log "Installazione QEMU Guest Agent (opzionale per VM)"
    
    # Rileva se siamo su una VM
    PRODUCT_NAME=$(cat /sys/class/dmi/id/product_name 2>/dev/null || echo "")
    
    # Verifica se è una VM (Proxmox usa "Standard PC" o contiene "QEMU")
    if ! echo "$PRODUCT_NAME" | grep -qi "qemu\|standard pc\|virtual\|kvm"; then
        log "Sistema non identificato come VM - skip qemu-guest-agent"
        return 0
    fi
    
    log "VM rilevata: $PRODUCT_NAME - procedo con installazione qemu-guest-agent"
    
    # Installa qemu-guest-agent (pacchetto: qemu-ga)
    log "Installazione pacchetto qemu-ga..."
    opkg update >/dev/null 2>&1 || log "Warning: opkg update fallito (continuo comunque)"
    opkg install qemu-ga 2>/dev/null || {
        log "Warning: pacchetto qemu-ga non disponibile o già installato"
    }
    
    # Verifica binario
    if [ ! -f "/usr/bin/qemu-ga" ]; then
        log "Warning: /usr/bin/qemu-ga non trovato - qemu-guest-agent potrebbe non essere disponibile"
        return 0
    fi
    
    # Rileva device disponibile e configura di conseguenza
    if [ -e "/dev/virtio-ports/org.qemu.guest_agent.0" ]; then
        # Proxmox con QEMU Guest Agent abilitato → virtio-serial (integrazione completa)
        log "Rilevato virtio-serial device - configurazione per piena integrazione Proxmox..."
        QEMU_MODE="virtio-serial"
        QEMU_PATH="/dev/virtio-ports/org.qemu.guest_agent.0"
    elif [ -e "/dev/vport2p1" ]; then
        # Proxmox senza directory virtio-ports ma con device vportXpY diretto
        log "Rilevato device /dev/vport2p1 - configurazione virtio-serial diretta..."
        QEMU_MODE="virtio-serial"
        QEMU_PATH="/dev/vport2p1"
    else
        # Fallback a isa-serial (funzionamento base, compatibile senza config Proxmox)
        log "Configurazione init script per isa-serial (fallback)..."
        QEMU_MODE="isa-serial"
        QEMU_PATH="/dev/ttyS0"
    fi
    
    log "Modalità: $QEMU_MODE su $QEMU_PATH"
    cat > /etc/init.d/qemu-ga <<QEMU_INIT
#!/bin/sh /etc/rc.common
# Copyright (C) 2016 OpenWrt.org

START=99
USE_PROCD=1

start_service() {
        procd_open_instance
        procd_set_param command /usr/bin/qemu-ga -m $QEMU_MODE -p $QEMU_PATH
        procd_set_param respawn
        procd_set_param stdout 1
        procd_set_param stderr 1
        procd_close_instance
}
QEMU_INIT
    
    chmod +x /etc/init.d/qemu-ga
    
    # Avvia servizio
    log "Avvio servizio qemu-guest-agent..."
    /etc/init.d/qemu-ga enable 2>/dev/null || log "Warning: enable qemu-ga fallito"
    /etc/init.d/qemu-ga start 2>/dev/null || log "Warning: start qemu-ga fallito"
    
    # Verifica servizio attivo
    sleep 2
    if pgrep qemu-ga >/dev/null 2>&1; then
        log "QEMU Guest Agent installato e attivo ($QEMU_MODE)"
    else
        log "Warning: QEMU Guest Agent non risulta in esecuzione"
    fi
    
    # ROCKSOLID: Proteggi installazione
    log "ROCKSOLID: Proteggo installazione QEMU Guest Agent da major upgrade"
    add_to_sysupgrade "/usr/bin/qemu-ga" "QEMU Guest Agent - Binary"
    add_to_sysupgrade "/etc/init.d/qemu-ga" "QEMU Guest Agent - Init Script"
    
    # Proteggi librerie glib2 critiche (dipendenza qemu-ga)
    add_to_sysupgrade "/usr/lib/libglib-2.0.so*" "QEMU Guest Agent - glib2 library dependency"
    
    # Se esiste config proteggi anche quello
    if [ -f "/etc/config/qemu-ga" ]; then
        add_to_sysupgrade "/etc/config/qemu-ga" "QEMU Guest Agent - Configuration"
    fi
    
    log "Installazione QEMU Guest Agent protetta contro major upgrade"
}

install_frp() {
    echo ""
    echo "Installazione FRP client (opzionale)"
    echo "Server remoto: monitor.nethlab.it:7000"
    echo ""
    
    # Controlla se esiste già una configurazione FRP
    EXISTING_CONFIG=""
    if [ -f "$FRPC_CONF" ]; then
        log "Configurazione FRP esistente trovata: $FRPC_CONF"
        
        # Estrai parametri dalla configurazione esistente (supporta v0.x e v1.x)
        # v1.x usa serverAddr/serverPort, v0.x usa server_addr/server_port
        SERVER_ADDR=$(grep -E '^(serverAddr|server_addr)' "$FRPC_CONF" | sed 's/.*= *"\([^"]*\)".*/\1/' | grep -v '^$' | head -1)
        SERVER_PORT=$(grep -E '^(serverPort|server_port)' "$FRPC_CONF" | sed 's/.*= *\([0-9][0-9]*\).*/\1/' | head -1)
        FRP_TOKEN=$(grep 'auth.token' "$FRPC_CONF" | sed 's/.*= *"\([^"]*\)".*/\1/' | grep -v '^$' | head -1)
        
        # v1.x: [[proxies]] con name=, v0.x: [proxy-name] come sezione
        if grep -q '^\[\[proxies\]\]' "$FRPC_CONF"; then
            # Formato v1.x
            PROXY_NAME=$(grep '^\[\[proxies\]\]' -A 10 "$FRPC_CONF" | grep '^name' | sed 's/.*= *"\([^"]*\)".*/\1/' | grep -v '^$' | head -1)
            REMOTE_PORT=$(grep '^\[\[proxies\]\]' -A 10 "$FRPC_CONF" | grep -E '^(remotePort|remote_port)' | sed 's/.*= *\([0-9][0-9]*\).*/\1/' | head -1)
        else
            # Formato v0.x: cerca prima sezione dopo [common]
            PROXY_NAME=$(grep -E '^\[[a-zA-Z0-9_-]+\]' "$FRPC_CONF" | grep -v '\[common\]' | head -1 | tr -d '[]')
            REMOTE_PORT=$(grep -E '^(remotePort|remote_port)' "$FRPC_CONF" | sed 's/.*= *\([0-9][0-9]*\).*/\1/' | head -1)
        fi
        
        # Valida configurazione estratta - tutti i valori devono essere non-vuoti
        if [ -n "$SERVER_ADDR" ] && [ -n "$SERVER_PORT" ] && [ -n "$FRP_TOKEN" ] && [ -n "$PROXY_NAME" ] && [ -n "$REMOTE_PORT" ]; then
            EXISTING_CONFIG="yes"
            log "Configurazione recuperata:"
            log "  Server: $SERVER_ADDR:$SERVER_PORT"
            log "  Proxy: $PROXY_NAME (porta remota: $REMOTE_PORT)"
            echo ""
        else
            warn "Configurazione FRP esistente incompleta o invalida"
            warn "  serverAddr: ${SERVER_ADDR:-VUOTO}"
            warn "  serverPort: ${SERVER_PORT:-VUOTO}"
            warn "  token: ${FRP_TOKEN:+PRESENTE}${FRP_TOKEN:-VUOTO}"
            warn "  proxy name: ${PROXY_NAME:-VUOTO}"
            warn "  remotePort: ${REMOTE_PORT:-VUOTO}"
            warn "Richiesta nuova configurazione"
            echo ""
        fi
        
        # Se non-interattivo (boot/auto), mantieni sempre config esistente
        if ! is_interactive; then
            log "Modalita non-interattiva: mantengo configurazione esistente"
        else
            printf "Vuoi mantenere questa configurazione? [Y/n]: "
            read ans || ans=""
            ans_lc=$(printf "%s" "$ans" | tr '[:upper:]' '[:lower:]')
            case "$ans_lc" in
                n|no) EXISTING_CONFIG="" ;;
                *) ;;
            esac
        fi
        
        # Se mantiene config esistente, proteggi subito e esci
        if [ -n "$EXISTING_CONFIG" ]; then
            log "Configurazione FRP esistente mantenuta - proteggo installazione"
            protect_frp_installation
            return 0
        fi
    fi
    
    # Se non c'è configurazione esistente o l'utente vuole cambiarla
    if [ -z "$EXISTING_CONFIG" ]; then
        # Se non-interattivo senza config esistente, salta FRP
        if ! is_interactive; then
            log "Modalita non-interattiva: nessuna config FRP esistente, salto installazione"
            return 0
        fi
        
        printf "Vuoi installare e configurare il client FRP? [y/N]: "
        read ans || ans=""
        ans_lc=$(printf "%s" "$ans" | tr '[:upper:]' '[:lower:]')
        case "$ans_lc" in
            y|yes|s|si) ;;
            *) return 0 ;;
        esac

        SERVER_ADDR="monitor.nethlab.it"
        SERVER_PORT="7000"

        while :; do
            printf "Inserisci la remote_port da assegnare (es. 6020): "
            read REMOTE_PORT || REMOTE_PORT=""
            echo "$REMOTE_PORT" | grep -Eq '^[0-9]+$' && break
            echo "Valore non valido"
        done

        printf "Inserisci la chiave/token FRP: "
        read FRP_TOKEN || FRP_TOKEN=""
        [ -n "$FRP_TOKEN" ] || die "token FRP vuoto"

        DEFAULT_NAME="$(hostname 2>/dev/null || echo openwrt-host)"
        printf "Nome proxy FRP (default: %s): " "$DEFAULT_NAME"
        read PROXY_NAME || PROXY_NAME=""
        [ -n "$PROXY_NAME" ] || PROXY_NAME="$DEFAULT_NAME"
    fi

    cd /tmp || die "cd /tmp fallito"
    FRP_TGZ="frp_${FRP_VER}_linux_amd64.tar.gz"
    FRP_DL="https://github.com/fatedier/frp/releases/download/v${FRP_VER}/${FRP_TGZ}"

    # Verifica se binario esistente è corrotto o versione vecchia
    SKIP_DOWNLOAD=0
    if [ -f "$FRPC_BIN" ]; then
        log "Verifica integrità binario FRP esistente..."
        if ! "$FRPC_BIN" -v >/dev/null 2>&1; then
            log "WARN: Binario FRP esistente corrotto - rimuovo e ri-scarico"
            rm -f "$FRPC_BIN"
        else
            CURRENT_VER=$("$FRPC_BIN" -v 2>/dev/null | head -n1 || echo "unknown")
            log "Versione FRP esistente: $CURRENT_VER (target: $FRP_VER)"
            if echo "$CURRENT_VER" | grep -q "$FRP_VER"; then
                log "Versione corretta già installata - skip download"
                SKIP_DOWNLOAD=1
            else
                log "Versione obsoleta - aggiorno a $FRP_VER"
                rm -f "$FRPC_BIN"
            fi
        fi
    fi

    # Download e installazione binario (solo se necessario)
    if [ "$SKIP_DOWNLOAD" -eq 0 ]; then
        log "Download FRP v$FRP_VER"
        wget -O "$FRP_TGZ" "$FRP_DL" || die "download FRP fallito"

        log "Estrazione FRP"
        tar -xzf "$FRP_TGZ" || die "tar frp fallito"
        FRP_DIR="$(tar -tzf "$FRP_TGZ" | head -n1 | cut -d/ -f1)"

        [ -n "$FRP_DIR" ] || die "impossibile determinare directory estratta"
        [ -f "$FRP_DIR/frpc" ] || die "frpc non trovato nel tarball"

        mkdir -p "$(dirname "$FRPC_BIN")" /etc/frp /var/log
        cp -f "$FRP_DIR/frpc" "$FRPC_BIN"
        chmod +x "$FRPC_BIN"

        # Verifica integrità binario installato
        if ! "$FRPC_BIN" -v >/dev/null 2>&1; then
            die "CRITICO: Binario FRP installato risulta corrotto"
        fi
        
        INSTALLED_VER=$("$FRPC_BIN" -v 2>/dev/null | head -n1)
        log "FRP installato con successo: $INSTALLED_VER"

        rm -f "$FRP_TGZ"
        rm -rf "$FRP_DIR"
    fi

    log "Scrivo configurazione TOML: $FRPC_CONF"
    cat >"$FRPC_CONF" <<EOF
[common]
server_addr = "$SERVER_ADDR"
server_port = $SERVER_PORT

auth.method = "token"
auth.token = "$FRP_TOKEN"

tls.enable = true

log.to = "$FRPC_LOG"
log.level = "info"

[$PROXY_NAME]
type = "tcp"
local_ip = "127.0.0.1"
local_port = 6556
remote_port = $REMOTE_PORT
EOF

    log "Creo servizio procd FRP: $FRPC_INIT"
    cat >"$FRPC_INIT" <<'EOF'
#!/bin/sh /etc/rc.common
START=99
STOP=10

USE_PROCD=1

start_service() {
    procd_open_instance
    procd_set_param command /usr/local/bin/frpc -c /etc/frp/frpc.toml
    procd_set_param respawn
    procd_set_param stdout 1
    procd_set_param stderr 1
    procd_close_instance
}
EOF

    chmod +x "$FRPC_INIT"
    /etc/init.d/frpc enable >/dev/null 2>&1 || true
    /etc/init.d/frpc restart >/dev/null 2>&1 || /etc/init.d/frpc start >/dev/null 2>&1 || true

    if pgrep -f frpc >/dev/null 2>&1; then
        log "FRP attivo: proxy=$PROXY_NAME remote_port=$REMOTE_PORT"
    else
        warn "FRP non risulta in esecuzione: controllare log $FRPC_LOG"
    fi
    
    # ROCKSOLID: Proteggi installazione FRP
    protect_frp_installation
}

# ========================================================================
# ROCKSOLID: Auto Git Sync Installation
# ========================================================================
install_auto_git_sync() {
    local repo_dir="/opt/checkmk-tools"
    local repo_url="https://github.com/Coverup20/checkmk-tools.git"
    local sync_script="/usr/local/bin/git-auto-sync.sh"
    local cron_file="/etc/crontabs/root"
    
    echo ""
    echo "Installazione Auto Git Sync Service"
    echo ""
    
    # Installa git se non presente
    if ! command -v git >/dev/null 2>&1; then
        log "Download git standalone (dinamico da OpenWrt repo)..."
        
        # Download dinamico git e git-http
        if download_openwrt_package "git" "$REPO_PACKAGES" "/tmp/git.ipk"; then
            log "Download git-http..."
            if download_openwrt_package "git-http" "$REPO_PACKAGES" "/tmp/git-http.ipk"; then
                # Installa .ipk direttamente (senza aggiungere repo)
                opkg install /tmp/git.ipk /tmp/git-http.ipk || die "Installazione git fallita"
                rm -f /tmp/git.ipk /tmp/git-http.ipk
                log "Git installato: $(git --version 2>&1 | head -1)"
            else
                rm -f /tmp/git.ipk
                die "Download git-http fallito - impossibile proseguire"
            fi
        else
            die "Download git fallito - impossibile proseguire"
        fi
    else
        log "Git già presente: $(git --version)"
    fi
    
    # Clona o aggiorna repository
    if [ -d "$repo_dir/.git" ]; then
        log "Repository già presente in $repo_dir"
        cd "$repo_dir" || die "cd $repo_dir fallito"
        log "Aggiornamento repository..."
        git pull >/dev/null 2>&1 || warn "Git pull fallito"
    else
        log "Clonazione repository in $repo_dir..."
        mkdir -p "$(dirname "$repo_dir")"
        git clone "$repo_url" "$repo_dir" >/dev/null 2>&1 || die "Clonazione repository fallita"
        log "Repository clonato con successo"
    fi
    
    # Crea script di sync
    log "Creazione script di sync: $sync_script"
    cat > "$sync_script" <<'SYNCSCRIPT'
#!/bin/sh
# Auto Git Sync Worker Script

REPO_DIR="/opt/checkmk-tools"
LOG_FILE="/var/log/auto-git-sync.log"
MAX_LOG_SIZE=1048576  # 1MB

# Rotazione log se troppo grande
if [ -f "$LOG_FILE" ] && [ "$(stat -c%s "$LOG_FILE" 2>/dev/null || echo 0)" -gt "$MAX_LOG_SIZE" ]; then
    mv "$LOG_FILE" "$LOG_FILE.old" 2>/dev/null || true
fi

# Timestamp
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Auto sync started" >> "$LOG_FILE"

# Verifica repository
if [ ! -d "$REPO_DIR/.git" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: Repository not found" >> "$LOG_FILE"
    exit 1
fi

cd "$REPO_DIR" || exit 1

# Git pull
if git pull origin main >> "$LOG_FILE" 2>&1; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Sync completed" >> "$LOG_FILE"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Git pull failed" >> "$LOG_FILE"
fi
SYNCSCRIPT
    
    chmod +x "$sync_script"
    log "Script di sync creato"
    
    # Configura cron
    log "Configurazione cron job (ogni minuto)..."
    if [ -f "$cron_file" ]; then
        sed -i '/git-auto-sync\.sh/d' "$cron_file" 2>/dev/null || true
    fi
    echo "* * * * * $sync_script" >> "$cron_file"
    
    # Riavvia cron
    /etc/init.d/cron restart >/dev/null 2>&1 || true
    log "Cron job configurato"
    
    # ROCKSOLID: Proteggi installazione
    log "ROCKSOLID: Proteggo installazione Auto Git Sync da major upgrade"
    add_to_sysupgrade "$repo_dir/" "CheckMK Tools Repository (Git Sync)"
    add_to_sysupgrade "$sync_script" "Git Auto Sync Script"
    add_to_sysupgrade "$cron_file" "Cron Jobs (include git sync)"
    add_to_sysupgrade "/var/log/auto-git-sync.log" "Git Sync Log File"
    log "Installazione Auto Git Sync protetta contro major upgrade"
    echo ""
}

main() {
    if [ "${1:-}" = "--uninstall" ]; then
        is_root || die "eseguire come root"
        uninstall_all
        exit 0
    fi

    is_root || die "eseguire come root"

    echo ""
    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║  CheckMK Agent Installer - ROCKSOLID Edition                  ║"
    echo "║  Versione resistente ai major upgrade NethSecurity/OpenWrt    ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo ""
    log "Configurazione:"
    log "  CheckMK Server: $CMK_SERVER"
    log "  Site: $CMK_SITE"
    log "  Protocol: $CMK_PROTOCOL"
    echo ""

    install_prereqs
    detect_checkmk_agent_url
    install_agent
    install_agent_service
    
    # ROCKSOLID: Proteggi installazione
    protect_checkmk_installation
    backup_critical_binaries
    create_post_upgrade_script
    
    # QEMU Guest Agent (per VM Proxmox/KVM)
    install_qemu_ga
    
    install_frp
    
    # ROCKSOLID: Auto Git Sync
    install_auto_git_sync
    
    # ROCKSOLID: Installa autocheck all'avvio
    install_autocheck

    echo ""
    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║  INSTALLAZIONE COMPLETATA - ROCKSOLID MODE ATTIVO             ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo ""
    echo "Protezioni attivate:"
    echo "  ✓ File critici aggiunti a $SYSUPGRADE_CONF"
    echo "  ✓ Binari critici backuppati (tar/ar/gzip protetti da corruzione)"
    echo "  ✓ Script post-upgrade: /etc/checkmk-post-upgrade.sh"
    echo "  ✓ Script autocheck avvio: /usr/local/bin/rocksolid-startup-check.sh"
    echo "  ✓ Installazione resistente ai major upgrade"
    echo ""
    echo "Autocheck all'avvio:"
    echo "  ✓ Verifica e riavvia CheckMK Agent automaticamente"
    echo "  ✓ Verifica e riavvia FRP Client automaticamente"
    echo "  ✓ Log: /var/log/rocksolid-startup.log"
    echo ""
    echo "Auto Git Sync:"
    echo "  ✓ Repository: /opt/checkmk-tools"
    echo "  ✓ Sync automatico ogni minuto"
    echo "  ✓ Log: /var/log/auto-git-sync.log"
    echo ""
    echo "Test agent locale: nc 127.0.0.1 6556 | head"
    echo "Config FRP: $FRPC_CONF"
    echo "Disinstallazione: sh $0 --uninstall"
    echo ""
    echo "IMPORTANTE: Dopo un major upgrade, esegui /etc/checkmk-post-upgrade.sh"
    echo "            per verificare e ripristinare i servizi"
}

main "$@"
