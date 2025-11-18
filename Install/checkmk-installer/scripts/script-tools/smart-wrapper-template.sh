#!/bin/bash
# Smart CheckMK Script Wrapper - TEMPLATE
# Questo file è il template base per creare wrapper ibridi
# NON usare direttamente - usa smart-deploy-hybrid.sh per l'installazione
#
# Logica: Prova a scaricare la versione fresca, usa cache locale come fallback
# Gestisce automaticamente i path CheckMK corretti

# =====================================================
# CONFIGURAZIONE
# =====================================================
SCRIPT_NAME="check_cockpit_sessions"
SCRIPT_TYPE="local"  # local, spool, plugin, notification
GITHUB_URL="https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-check-ns7/check_cockpit_sessions.sh"
TIMEOUT=5

# =====================================================
# CONFIGURAZIONE PATH CHECKMK
# =====================================================
# Auto-detection del tipo di environment CheckMK
if [ -d "/omd/sites" ]; then
    # Ambiente CheckMK Server (OMD)
    SITE_NAME=$(ls /omd/sites/ 2>/dev/null | head -n1)
    OMD_ROOT="/omd/sites/${SITE_NAME:-monitoring}"
    
    case "$SCRIPT_TYPE" in
        "local")        TARGET_DIR="/usr/lib/check_mk_agent/local" ;;
        "spool")        TARGET_DIR="/usr/lib/check_mk_agent/spool" ;;
        "plugin")       TARGET_DIR="/usr/lib/check_mk_agent/plugins" ;;
        "notification") TARGET_DIR="$OMD_ROOT/local/share/check_mk/notifications" ;;
        "bin")          TARGET_DIR="$OMD_ROOT/local/bin" ;;
        *)              TARGET_DIR="/usr/lib/check_mk_agent/local" ;;
    esac
    CACHE_DIR="$OMD_ROOT/var/cache/checkmk-scripts"
else
    # Ambiente CheckMK Agent (client)
    case "$SCRIPT_TYPE" in
        "local")        TARGET_DIR="/usr/lib/check_mk_agent/local" ;;
        "spool")        TARGET_DIR="/usr/lib/check_mk_agent/spool" ;;
        "plugin")       TARGET_DIR="/usr/lib/check_mk_agent/plugins" ;;
        *)              TARGET_DIR="/usr/lib/check_mk_agent/local" ;;
    esac
    CACHE_DIR="/var/cache/checkmk-scripts"
fi

CACHE_FILE="$CACHE_DIR/$SCRIPT_NAME.sh"

# =====================================================
# SETUP CACHE DIRECTORY
# =====================================================
mkdir -p "$CACHE_DIR" 2>/dev/null || true

# =====================================================
# FUNZIONE DI UPDATE
# =====================================================
update_script() {
    local temp_file="$CACHE_FILE.tmp"
    
    # Prova download con timeout
    if curl -s --max-time "$TIMEOUT" --fail "$GITHUB_URL" -o "$temp_file" 2>/dev/null; then
        # Verifica che il file sia valido (contiene shebang bash)
        if head -n 1 "$temp_file" | grep -q "^#!/.*bash"; then
            mv "$temp_file" "$CACHE_FILE"
            chmod +x "$CACHE_FILE"
            echo "# Script updated from GitHub $(date)" > "$CACHE_FILE.info"
            return 0
        else
            rm -f "$temp_file"
            return 1
        fi
    else
        rm -f "$temp_file" 2>/dev/null
        return 1
    fi
}

# =====================================================
# LOGICA PRINCIPALE
# =====================================================

# Verifica environment CheckMK
log_info() {
    # Log solo se DEBUG è abilitato
    [ "${DEBUG:-0}" = "1" ] && echo "# CheckMK Wrapper [$SCRIPT_NAME]: $1" >&2
}

log_info "Environment: $([ -d "/omd/sites" ] && echo "OMD Server" || echo "Agent Client")"
log_info "Script Type: $SCRIPT_TYPE"
log_info "Target Dir: $TARGET_DIR" 
log_info "Cache Dir: $CACHE_DIR"

# Prova aggiornamento (silenzioso)
update_script >/dev/null 2>&1

# Esegui script cached
if [ -f "$CACHE_FILE" ] && [ -x "$CACHE_FILE" ]; then
    log_info "Executing cached script"
    "$CACHE_FILE"
else
    # Fallback: nessun script disponibile
    echo "2 ${SCRIPT_NAME} - CRITICAL: No script available (cache miss, GitHub unreachable)"
    log_info "CRITICAL: No cached script available"
    exit 2
fi