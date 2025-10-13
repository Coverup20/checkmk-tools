#!/bin/bash
# Smart Deploy per CheckMK Scripts - Sistema Ibrido
# Deploy iniziale + wrapper intelligenti per auto-update

set -euo pipefail

# =====================================================
# CONFIGURAZIONE
# =====================================================
GITHUB_REPO="Coverup20/checkmk-tools"
BASE_URL="https://raw.githubusercontent.com/$GITHUB_REPO/main"

# Auto-detection environment CheckMK
if [ -d "/omd/sites" ]; then
    # Ambiente CheckMK Server (OMD)
    SITE_NAME=$(ls /omd/sites/ 2>/dev/null | head -n1)
    OMD_ROOT="/omd/sites/${SITE_NAME:-monitoring}"
    CHECKMK_LOCAL_DIR="/usr/lib/check_mk_agent/local"
    CHECKMK_SPOOL_DIR="/usr/lib/check_mk_agent/spool"
    CHECKMK_PLUGIN_DIR="/usr/lib/check_mk_agent/plugins"
    CHECKMK_NOTIFICATION_DIR="$OMD_ROOT/local/share/check_mk/notifications"
    CACHE_DIR="$OMD_ROOT/var/cache/checkmk-scripts"
    ENV_TYPE="OMD Server"
else
    # Ambiente CheckMK Agent (client)
    CHECKMK_LOCAL_DIR="/usr/lib/check_mk_agent/local"
    CHECKMK_SPOOL_DIR="/usr/lib/check_mk_agent/spool"
    CHECKMK_PLUGIN_DIR="/usr/lib/check_mk_agent/plugins"
    CACHE_DIR="/var/cache/checkmk-scripts"
    ENV_TYPE="Agent Client"
fi

# Lista script da deployare con i loro tipi
declare -A SCRIPTS=(
    ["check_cockpit_sessions"]="script-check-ns7/check_cockpit_sessions.sh:local"
    ["check_dovecot_status"]="script-check-ns7/check_dovecot_status.sh:local"
    ["check_ssh_root_sessions"]="script-check-ns7/check_ssh_root_sessions.sh:local"
    ["check_postfix_status"]="script-check-ns7/check_postfix_status.sh:local"
    ["telegram_realip"]="script-notify-checkmk/telegram_realip:notification"
)

# =====================================================
# FUNZIONI
# =====================================================

log() {
    echo "[$(date '+%H:%M:%S')] $1"
}

create_smart_wrapper() {
    local script_name="$1"
    local github_path="$2"
    local script_type="$3"
    
    # Determina directory target in base al tipo
    local target_dir
    case "$script_type" in
        "local")        target_dir="$CHECKMK_LOCAL_DIR" ;;
        "spool")        target_dir="$CHECKMK_SPOOL_DIR" ;;
        "plugin")       target_dir="$CHECKMK_PLUGIN_DIR" ;;
        "notification") target_dir="$CHECKMK_NOTIFICATION_DIR" ;;
        *)              target_dir="$CHECKMK_LOCAL_DIR" ;;
    esac
    
    local wrapper_file="$target_dir/${script_name}"
    
    log "📝 Creando wrapper smart per $script_name ($script_type) in $target_dir..."
    
    # Crea directory se non esiste
    mkdir -p "$target_dir" 2>/dev/null || true
    
    cat > "$wrapper_file" << EOF
#!/bin/bash
# Smart CheckMK Script Wrapper - $script_name
# Auto-aggiorna da GitHub con fallback locale

SCRIPT_NAME="$script_name"
SCRIPT_TYPE="$script_type"
GITHUB_URL="$BASE_URL/$github_path"
CACHE_DIR="$CACHE_DIR"
CACHE_FILE="\$CACHE_DIR/\$SCRIPT_NAME.sh"
TIMEOUT=5

# Setup cache directory
mkdir -p "\$CACHE_DIR" 2>/dev/null || true

# Funzione di update
update_script() {
    local temp_file="\$CACHE_FILE.tmp"
    
    if curl -s --max-time "\$TIMEOUT" --fail "\$GITHUB_URL" -o "\$temp_file" 2>/dev/null; then
        if head -n 1 "\$temp_file" | grep -q "^#!/.*bash"; then
            mv "\$temp_file" "\$CACHE_FILE"
            chmod +x "\$CACHE_FILE"
            echo "# Updated from GitHub \$(date)" > "\$CACHE_FILE.info"
            return 0
        else
            rm -f "\$temp_file"
            return 1
        fi
    else
        rm -f "\$temp_file" 2>/dev/null
        return 1
    fi
}

# Log function (debug)
log_info() {
    [ "\${DEBUG:-0}" = "1" ] && echo "# CheckMK Wrapper [\$SCRIPT_NAME]: \$1" >&2
}

# Prova aggiornamento (silenzioso)
update_script >/dev/null 2>&1

# Esegui script cached
if [ -f "\$CACHE_FILE" ] && [ -x "\$CACHE_FILE" ]; then
    log_info "Executing cached script (type: $script_type)"
    "\$CACHE_FILE"
else
    echo "2 \${SCRIPT_NAME} - CRITICAL: No script available (GitHub unreachable, no cache)"
    log_info "CRITICAL: No cached script available"
    exit 2
fi
EOF
    
    chmod +x "$wrapper_file"
    log "✅ Wrapper $script_name creato in $target_dir"
}

# =====================================================
# SETUP INIZIALE
# =====================================================

log "🚀 CheckMK Smart Deploy - Sistema Ibrido"
log "🏗️  Environment: $ENV_TYPE"
log "📁 Cache: $CACHE_DIR"

# Verifica permessi base
if [ ! -w "/usr/lib/check_mk_agent" ] 2>/dev/null; then
    log "❌ Errore: Non hai permessi di scrittura su /usr/lib/check_mk_agent"
    log "💡 Esegui come root o con sudo"
    exit 1
fi

# Crea directory cache
mkdir -p "$CACHE_DIR"
log "📂 Cache directory: $CACHE_DIR"

# =====================================================
# DEPLOY SCRIPTS
# =====================================================

log "📥 Deploying scripts..."

for script_entry in "${!SCRIPTS[@]}"; do
    # Parse entry: "path:type"
    IFS=':' read -r github_path script_type <<< "${SCRIPTS[$script_entry]}"
    
    log "🔄 Processing $script_entry (type: $script_type)..."
    
    # Download iniziale per popolare la cache
    cache_file="$CACHE_DIR/${script_entry}.sh"
    if curl -s --max-time 10 --fail "$BASE_URL/$github_path" -o "$cache_file"; then
        chmod +x "$cache_file"
        log "✅ Cache iniziale per $script_entry creata"
    else
        log "⚠️  Warning: Impossibile scaricare $script_entry (continuo comunque)"
    fi
    
    # Crea wrapper smart
    create_smart_wrapper "$script_entry" "$github_path" "$script_type"
done

# =====================================================
# SCRIPT DI MANUTENZIONE
# =====================================================

log "🔧 Creando script di manutenzione..."

cat > "$CACHE_DIR/update-all.sh" << 'EOF'
#!/bin/bash
# Aggiorna manualmente tutti gli script CheckMK

CACHE_DIR="/var/cache/checkmk-scripts"
cd "$CACHE_DIR"

echo "🔄 Aggiornamento manuale script CheckMK..."

for info_file in *.info; do
    [ -f "$info_file" ] || continue
    script_name=$(basename "$info_file" .info)
    echo "📥 Aggiornando $script_name..."
    
    # Forza update eseguendo il wrapper
    if /usr/lib/check_mk_agent/local/"$script_name" >/dev/null 2>&1; then
        echo "✅ $script_name aggiornato"
    else
        echo "⚠️  $script_name: problema nell'aggiornamento"
    fi
done

echo "🎉 Aggiornamento completato!"
EOF

chmod +x "$CACHE_DIR/update-all.sh"

# =====================================================
# RIEPILOGO
# =====================================================

log "🎉 Deploy completato!"
log ""
log "📊 RIEPILOGO:"
log "   • Environment: $ENV_TYPE"
log "   • Script deployati: ${#SCRIPTS[@]}"
log "   • Cache directory: $CACHE_DIR"
log "   • Directories usate:"
log "     - Local checks: $CHECKMK_LOCAL_DIR"
if [ "$ENV_TYPE" = "OMD Server" ]; then
    log "     - Notifications: $CHECKMK_NOTIFICATION_DIR"
fi
log ""
log "💡 FUNZIONAMENTO:"
log "   • Gli script si auto-aggiornano da GitHub ad ogni esecuzione"
log "   • In caso di problemi di rete, usano la cache locale"
log "   • Aggiornamento manuale: $CACHE_DIR/update-all.sh"
log ""
log "🧪 TEST:"
log "   ls -la $CHECKMK_LOCAL_DIR/"
if [ -f "$CHECKMK_LOCAL_DIR/check_cockpit_sessions" ]; then
    log "   $CHECKMK_LOCAL_DIR/check_cockpit_sessions"
fi
log "   DEBUG=1 $CHECKMK_LOCAL_DIR/check_cockpit_sessions  # debug mode"