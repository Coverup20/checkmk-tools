#!/bin/bash
# pre-upgrade-nsec8.sh
# Esegui PRIMA di ogni major upgrade di NethSecurity 8
# Crea snapshot, verifica configurazioni critiche, backup

set -e

LOG_FILE="/var/log/pre-upgrade-nsec8.log"
BACKUP_DIR="/root/pre-upgrade-backup-$(date +%Y%m%d-%H%M%S)"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

die() {
    log "ERRORE: $*"
    exit 1
}

log "========================================="
log "PRE-UPGRADE CHECKLIST - NethSecurity 8"
log "========================================="

# ============================================================================
# 1. VERIFICA ROOT
# ============================================================================
if [ "$(id -u)" -ne 0 ]; then
    die "Eseguire come root"
fi

# ============================================================================
# 2. CREA DIRECTORY BACKUP
# ============================================================================
log "[Backup] Creazione directory: $BACKUP_DIR"
mkdir -p "$BACKUP_DIR"

# ============================================================================
# 3. BACKUP FILE CRITICI
# ============================================================================
log "[Backup] Salvataggio configurazioni critiche..."

# rc.local
if [ -f /etc/rc.local ]; then
    cp -a /etc/rc.local "$BACKUP_DIR/"
    log "[Backup] ✓ rc.local salvato"
fi

# sysupgrade.conf
if [ -f /etc/sysupgrade.conf ]; then
    cp -a /etc/sysupgrade.conf "$BACKUP_DIR/"
    log "[Backup] ✓ sysupgrade.conf salvato"
fi

# nginx configs
if [ -d /etc/nginx ]; then
    mkdir -p "$BACKUP_DIR/nginx"
    cp -a /etc/nginx/* "$BACKUP_DIR/nginx/" 2>/dev/null || true
    log "[Backup] ✓ Configurazioni nginx salvate"
fi

# uhttpd configs
if [ -f /etc/config/uhttpd ]; then
    mkdir -p "$BACKUP_DIR/config"
    cp -a /etc/config/uhttpd "$BACKUP_DIR/config/"
    log "[Backup] ✓ Configurazione uhttpd salvata"
fi

# CheckMK agent e local checks
if [ -x /usr/bin/check_mk_agent ]; then
    cp -a /usr/bin/check_mk_agent "$BACKUP_DIR/"
    log "[Backup] ✓ CheckMK agent salvato"
fi

if [ -d /usr/lib/check_mk_agent/local ]; then
    mkdir -p "$BACKUP_DIR/local"
    cp -a /usr/lib/check_mk_agent/local/* "$BACKUP_DIR/local/" 2>/dev/null || true
    NUM_CHECKS=$(ls -1 "$BACKUP_DIR/local/"*.sh 2>/dev/null | wc -l)
    log "[Backup] ✓ $NUM_CHECKS local checks salvati"
fi

# FRP configs
if [ -f /etc/frp/frpc.toml ]; then
    mkdir -p "$BACKUP_DIR/frp"
    cp -a /etc/frp/frpc.toml "$BACKUP_DIR/frp/"
    log "[Backup] ✓ Configurazione FRP salvata"
fi

# Git sync scripts
if [ -f /usr/local/bin/git-auto-sync.sh ]; then
    mkdir -p "$BACKUP_DIR/usr-local-bin"
    cp -a /usr/local/bin/git-auto-sync.sh "$BACKUP_DIR/usr-local-bin/"
    cp -a /usr/local/bin/rocksolid-startup-check.sh "$BACKUP_DIR/usr-local-bin/" 2>/dev/null || true
    log "[Backup] ✓ Script git-sync salvati"
fi

# Crontab
if [ -f /etc/crontabs/root ]; then
    mkdir -p "$BACKUP_DIR/crontabs"
    cp -a /etc/crontabs/root "$BACKUP_DIR/crontabs/"
    log "[Backup] ✓ Crontab salvato"
fi

# ============================================================================
# 4. VERIFICA PROTEZIONI SYSUPGRADE
# ============================================================================
log "[Verifica] Controllo sysupgrade.conf..."

CRITICAL_PATHS=(
    "/etc/rc.local"
    "/usr/local/bin/"
    "/usr/lib/check_mk_agent/local/"
    "/opt/checkmk-tools/"
    "/usr/local/bin/git-auto-sync.sh"
    "/usr/local/bin/rocksolid-startup-check.sh"
)

MISSING=0
for path in "${CRITICAL_PATHS[@]}"; do
    if ! grep -q "^$path" /etc/sysupgrade.conf 2>/dev/null; then
        log "[Verifica] ⚠ MANCANTE in sysupgrade.conf: $path"
        MISSING=$((MISSING + 1))
    fi
done

if [ $MISSING -eq 0 ]; then
    log "[Verifica] ✓ Tutte le protezioni presenti in sysupgrade.conf"
else
    log "[Verifica] ⚠ WARNING: $MISSING path non protetti in sysupgrade.conf"
fi

# ============================================================================
# 5. VERIFICA RC.LOCAL ESEGUIBILE
# ============================================================================
if [ -f /etc/rc.local ]; then
    if [ -x /etc/rc.local ]; then
        log "[Verifica] ✓ rc.local eseguibile"
    else
        log "[Verifica] ⚠ WARNING: rc.local NON eseguibile (chmod +x necessario)"
        chmod +x /etc/rc.local
        log "[Fix] ✓ rc.local reso eseguibile"
    fi
else
    log "[Verifica] ⚠ WARNING: rc.local non trovato"
fi

# ============================================================================
# 6. VERIFICA SERVIZI ATTIVI
# ============================================================================
log "[Verifica] Controllo servizi critici..."

if pgrep -f "socat TCP-LISTEN:6556" >/dev/null 2>&1; then
    log "[Verifica] ✓ CheckMK agent attivo (porta 6556)"
else
    log "[Verifica] ⚠ CheckMK agent NON attivo"
fi

if [ -d /opt/checkmk-tools/.git ]; then
    log "[Verifica] ✓ Repository git presente"
else
    log "[Verifica] ⚠ Repository git NON presente"
fi

if crontab -l 2>/dev/null | grep -q git-auto-sync; then
    log "[Verifica] ✓ Cron git-sync configurato"
else
    log "[Verifica] ⚠ Cron git-sync NON configurato"
fi

# ============================================================================
# 7. CREA TARBALL BACKUP
# ============================================================================
log "[Backup] Creazione archivio compresso..."

cd /root || die "cd /root fallito"
TARBALL="pre-upgrade-backup-$(date +%Y%m%d-%H%M%S).tar.gz"
tar -czf "$TARBALL" "$(basename "$BACKUP_DIR")" || die "tar fallito"
log "[Backup] ✓ Archivio creato: /root/$TARBALL"

# ============================================================================
# 8. RIEPILOGO FINALE
# ============================================================================
log "========================================="
log "PRE-UPGRADE CHECKLIST COMPLETATA"
log "========================================="
log ""
log "Backup salvato in:"
log "  Directory:  $BACKUP_DIR"
log "  Archivio:   /root/$TARBALL"
log ""
log "IMPORTANTE:"
log "  1. Se l'upgrade fallisce, ripristina da snapshot"
log "  2. Dopo upgrade, verifica servizi con:"
log "     /usr/local/bin/rocksolid-startup-check.sh"
log "  3. Ripristino manuale da backup:"
log "     cd /root && tar -xzf $TARBALL"
log ""
log "Procedi con upgrade? [y/N]"
read -r CONFIRM

case "$CONFIRM" in
    y|Y|yes|YES)
        log "✓ Confermato - procedi con upgrade"
        exit 0
        ;;
    *)
        log "✗ Annullato dall'utente"
        exit 1
        ;;
esac
