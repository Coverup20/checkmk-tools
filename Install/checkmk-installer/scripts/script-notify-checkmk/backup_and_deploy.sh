#!/bin/bash
# ==================================================================
# 🔒 CheckMK Notification Script - Safe Deployment Utility
# ==================================================================
# Backup automatico delle configurazioni esistenti prima del deploy
# di mail_realip_hybrid per garantire rollback sicuro.
#
# Uso: ./backup_and_deploy.sh [--dry-run]
# ==================================================================

set -euo pipefail

# ==================== CONFIGURAZIONE ====================
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
CMK_NOTIFY_DIR="/omd/sites/$(cat /etc/omd/site)/local/share/check_mk/notifications"
BACKUP_DIR="$CMK_NOTIFY_DIR/backup_$(date +%Y%m%d_%H%M%S)"
SCRIPT_NAME="mail_realip_hybrid"
DRY_RUN=false

# ==================== FUNZIONI UTILITY ====================
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >&2
}

error() {
    log "ERROR: $*"
    exit 1
}

check_root() {
    if [[ $EUID -ne 0 ]] && [[ -z "${OMD_SITE:-}" ]]; then
        error "Script deve essere eseguito come root o dentro ambiente OMD"
    fi
}

detect_checkmk_site() {
    if [[ -n "${OMD_SITE:-}" ]]; then
        echo "$OMD_SITE"
        return
    fi
    
    if [[ -f /etc/omd/site ]]; then
        cat /etc/omd/site
        return
    fi
    
    error "Impossibile rilevare sito CheckMK"
}

# ==================== BACKUP FUNCTIONS ====================
create_backup_dir() {
    local backup_dir="$1"
    
    log "Creazione directory backup: $backup_dir"
    mkdir -p "$backup_dir"
    
    # Metadata backup
    cat > "$backup_dir/backup_info.txt" << EOF
Backup CheckMK Notifications - $(date)
==========================================
Site: $(detect_checkmk_site)
User: $(whoami)
Script: $SCRIPT_NAME
Source: $SCRIPT_DIR
Target: $CMK_NOTIFY_DIR
==========================================
EOF
}

backup_existing_configs() {
    local backup_dir="$1"
    local found_configs=false
    
    log "🔍 Ricerca configurazioni esistenti..."
    
    # Backup script esistenti
    for script in mail mail_realip mail_realip_00; do
        if [[ -f "$CMK_NOTIFY_DIR/$script" ]]; then
            log "📋 Backup: $script"
            cp "$CMK_NOTIFY_DIR/$script" "$backup_dir/"
            found_configs=true
        fi
    done
    
    # Backup configurazioni wato
    if [[ -d "/omd/sites/$(detect_checkmk_site)/etc/check_mk/conf.d/wato" ]]; then
        local wato_dir="/omd/sites/$(detect_checkmk_site)/etc/check_mk/conf.d/wato"
        if ls "$wato_dir"/*notification* >/dev/null 2>&1; then
            log "📋 Backup configurazioni WATO"
            mkdir -p "$backup_dir/wato"
            cp "$wato_dir"/*notification* "$backup_dir/wato/" 2>/dev/null || true
            found_configs=true
        fi
    fi
    
    if $found_configs; then
        log "✅ Backup completato in: $backup_dir"
    else
        log "ℹ️  Nessuna configurazione esistente trovata"
    fi
}

# ==================== DEPLOYMENT FUNCTIONS ====================
validate_source_script() {
    local source_script="$SCRIPT_DIR/$SCRIPT_NAME"
    
    if [[ ! -f "$source_script" ]]; then
        error "Script sorgente non trovato: $source_script"
    fi
    
    # Validazione sintassi Python
    if ! python3 -m py_compile "$source_script" 2>/dev/null; then
        error "Script ha errori di sintassi Python"
    fi
    
    # Verifica funzioni chiave
    if ! grep -q "detect_frp_scenario" "$source_script"; then
        error "Script non contiene funzione detect_frp_scenario()"
    fi
    
    log "✅ Script sorgente validato"
}

deploy_script() {
    local source_script="$SCRIPT_DIR/$SCRIPT_NAME"
    local target_script="$CMK_NOTIFY_DIR/$SCRIPT_NAME"
    
    if $DRY_RUN; then
        log "🧪 DRY-RUN: Copia $source_script → $target_script"
        return
    fi
    
    log "📦 Deploy: $SCRIPT_NAME"
    cp "$source_script" "$target_script"
    chmod +x "$target_script"
    chown "$(detect_checkmk_site):$(detect_checkmk_site)" "$target_script"
    
    log "✅ Script deployato: $target_script"
}

# ==================== TESTING FUNCTIONS ====================
test_deployment() {
    local target_script="$CMK_NOTIFY_DIR/$SCRIPT_NAME"
    
    if $DRY_RUN; then
        log "🧪 DRY-RUN: Test deployment skipped"
        return
    fi
    
    log "🧪 Test deployment..."
    
    # Test sintassi
    if ! python3 -m py_compile "$target_script"; then
        error "Script deployato ha errori di sintassi"
    fi
    
    # Test import
    if ! python3 -c "import sys; sys.path.insert(0, '$CMK_NOTIFY_DIR'); exec(open('$target_script').read())" 2>/dev/null; then
        error "Script deployato ha errori di import"
    fi
    
    log "✅ Test deployment superati"
}

# ==================== ROLLBACK FUNCTIONS ====================
create_rollback_script() {
    local backup_dir="$1"
    
    cat > "$backup_dir/rollback.sh" << EOF
#!/bin/bash
# Rollback automatico per backup $(basename "$backup_dir")
set -euo pipefail

log() {
    echo "[\\$(date '+%Y-%m-%d %H:%M:%S')] \\$*" >&2
}

log "🔄 Esecuzione rollback da: $backup_dir"

# Rimuovi script hybrid
if [[ -f "$CMK_NOTIFY_DIR/$SCRIPT_NAME" ]]; then
    log "🗑️  Rimozione: $SCRIPT_NAME"
    rm -f "$CMK_NOTIFY_DIR/$SCRIPT_NAME"
fi

# Ripristina backup
for script in mail mail_realip mail_realip_00; do
    if [[ -f "$backup_dir/\\$script" ]]; then
        log "♻️  Ripristino: \\$script"
        cp "$backup_dir/\\$script" "$CMK_NOTIFY_DIR/"
        chmod +x "$CMK_NOTIFY_DIR/\\$script"
        chown "$(detect_checkmk_site):$(detect_checkmk_site)" "$CMK_NOTIFY_DIR/\\$script"
    fi
done

# Ripristina configurazioni WATO
if [[ -d "$backup_dir/wato" ]]; then
    local wato_dir="/omd/sites/$(detect_checkmk_site)/etc/check_mk/conf.d/wato"
    log "♻️  Ripristino configurazioni WATO"
    cp "$backup_dir/wato"/* "\\$wato_dir/" 2>/dev/null || true
fi

log "✅ Rollback completato"
log "ℹ️  Riavvia CheckMK per applicare le modifiche"
EOF
    
    chmod +x "$backup_dir/rollback.sh"
    log "🔄 Script rollback creato: $backup_dir/rollback.sh"
}

# ==================== MAIN DEPLOYMENT ====================
show_summary() {
    local backup_dir="$1"
    
    cat << EOF

🎯 ===== DEPLOYMENT SUMMARY =====
Sito CheckMK: $(detect_checkmk_site)
Script deployato: $SCRIPT_NAME
Directory backup: $backup_dir
Rollback: $backup_dir/rollback.sh

📋 NEXT STEPS:
1. Configura regola notifica per usare $SCRIPT_NAME
2. Aggiungi label 'real_ip' agli host FRP
3. Testa con notifica di prova
4. Se problemi: esegui $backup_dir/rollback.sh

🔧 TESTING COMMANDS:
# Test notifica
su - $(detect_checkmk_site) -c "echo 'Test notification' | $CMK_NOTIFY_DIR/$SCRIPT_NAME"

# Check logs
tail -f /omd/sites/$(detect_checkmk_site)/var/log/notify.log

===============================
EOF
}

# ==================== MAIN FUNCTION ====================
main() {
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            -h|--help)
                echo "Uso: $0 [--dry-run]"
                echo "  --dry-run  Simula deployment senza modifiche"
                exit 0
                ;;
            *)
                error "Argomento sconosciuto: $1"
                ;;
        esac
    done
    
    log "🚀 Avvio deployment CheckMK notification script"
    
    if $DRY_RUN; then
        log "🧪 MODALITÀ DRY-RUN - Nessuna modifica verrà applicata"
    fi
    
    # Pre-checks
    check_root
    validate_source_script
    
    # Backup
    create_backup_dir "$BACKUP_DIR"
    backup_existing_configs "$BACKUP_DIR"
    create_rollback_script "$BACKUP_DIR"
    
    # Deploy
    deploy_script
    test_deployment
    
    # Summary
    show_summary "$BACKUP_DIR"
    
    log "✅ Deployment completato con successo!"
}

# Esecuzione
main "$@"