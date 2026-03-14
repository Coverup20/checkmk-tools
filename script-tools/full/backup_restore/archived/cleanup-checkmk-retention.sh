#!/bin/bash
# cleanup-checkmk-retention.sh - Gestione retention dati CheckMK
# Mantiene 180 giorni per RRD/Nagios, 30 giorni per notify-backup

set -euo pipefail

# ================================================================
# CONFIGURAZIONE
# ================================================================

OMD_SITE="${OMD_SITE:-monitoring}"
SITE_PATH="/omd/sites/${OMD_SITE}"

# Retention in giorni
RETENTION_RRD=180           # File RRD (metriche performance)
RETENTION_NAGIOS=180        # Archivi Nagios
RETENTION_NOTIFY=30         # Backup notifiche
COMPRESS_AFTER=30           # Comprimi file più vecchi di 30 giorni

# Log
LOG_FILE="${SITE_PATH}/var/log/cleanup-retention.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# Dry-run mode (test senza eliminare)
DRY_RUN="${DRY_RUN:-false}"

# Email report
EMAIL_TO="${EMAIL_TO:-}"  # Indirizzo email per report (opzionale)
EMAIL_FROM="checkmk-retention@$(hostname -f 2>/dev/null || echo 'localhost')"
EMAIL_SUBJECT="CheckMK Retention Cleanup Report - $(date '+%Y-%m-%d')"

# Email report
EMAIL_TO="${EMAIL_TO:-}"  # Indirizzo email per report (opzionale)
EMAIL_FROM="checkmk-retention@$(hostname -f 2>/dev/null || echo 'localhost')"
EMAIL_SUBJECT="CheckMK Retention Cleanup Report - $(date '+%Y-%m-%d')"

# ================================================================
# FUNZIONI
# ================================================================

log_info() {
    echo "[${TIMESTAMP}] [INFO] $*" | tee -a "$LOG_FILE"
}

log_warn() {
    echo "[${TIMESTAMP}] [WARN] $*" | tee -a "$LOG_FILE"
}

log_error() {
    echo "[${TIMESTAMP}] [ERROR] $*" | tee -a "$LOG_FILE"
}

log_success() {
    echo "[${TIMESTAMP}] [OK] $*" | tee -a "$LOG_FILE"
}

human_size() {
    local bytes=$1
    if [ "$bytes" -lt 1024 ]; then
        echo "${bytes}B"
    elif [ "$bytes" -lt 1048576 ]; then
        echo "$(( bytes / 1024 ))KB"
    elif [ "$bytes" -lt 1073741824 ]; then
        echo "$(( bytes / 1048576 ))MB"
    else
        echo "$(( bytes / 1073741824 ))GB"
    fi
}

send_email_report() {
    if [ -z "$EMAIL_TO" ]; then
        return 0
    fi
    
    log_info "Invio report via email a: $EMAIL_TO"
    
    # Verifica che mail/sendmail sia disponibile
    if ! command -v mail >/dev/null 2>&1 && ! command -v sendmail >/dev/null 2>&1; then
        log_warn "Comando mail/sendmail non trovato. Report non inviato."
        log_warn "Installa mailutils: apt install mailutils"
        return 1
    fi
    
    # Crea report email
    local email_body
    email_body=$(cat <<EOF
CheckMK Retention Cleanup Report
================================

Data esecuzione: $(date '+%Y-%m-%d %H:%M:%S')
Hostname: $(hostname -f 2>/dev/null || hostname)
Site CheckMK: $OMD_SITE
Modalità: $([ "$DRY_RUN" = "true" ] && echo "DRY-RUN (simulazione)" || echo "PRODUZIONE")

--------------------------------
CONFIGURAZIONE RETENTION
--------------------------------
RRD files: $RETENTION_RRD giorni
Nagios archives: $RETENTION_NAGIOS giorni
Notify backups: $RETENTION_NOTIFY giorni
Compressione automatica dopo: $COMPRESS_AFTER giorni

--------------------------------
RISULTATI CLEANUP
--------------------------------

$(tail -n 200 "$LOG_FILE" | grep -A 5 "CLEANUP FILE RRD\|CLEANUP ARCHIVI NAGIOS\|CLEANUP BACKUP NOTIFICHE\|REPORT FINALE" || echo "Nessun dato disponibile")

--------------------------------
LOG COMPLETO
--------------------------------
Vedi log completo: $LOG_FILE

Questo è un messaggio automatico generato da cleanup-checkmk-retention.sh
EOF
)
    
    # Invia email
    if command -v mail >/dev/null 2>&1; then
        echo "$email_body" | mail -s "$EMAIL_SUBJECT" -r "$EMAIL_FROM" "$EMAIL_TO" 2>&1 | tee -a "$LOG_FILE"
        if [ $? -eq 0 ]; then
            log_success "Report inviato con successo a $EMAIL_TO"
        else
            log_error "Errore nell'invio del report a $EMAIL_TO"
        fi
    elif command -v sendmail >/dev/null 2>&1; then
        {
            echo "From: $EMAIL_FROM"
            echo "To: $EMAIL_TO"
            echo "Subject: $EMAIL_SUBJECT"
            echo ""
            echo "$email_body"
        } | sendmail -t 2>&1 | tee -a "$LOG_FILE"
        if [ $? -eq 0 ]; then
            log_success "Report inviato con successo a $EMAIL_TO"
        else
            log_error "Errore nell'invio del report a $EMAIL_TO"
        fi
    fi
}

send_email_report() {
    if [ -z "$EMAIL_TO" ]; then
        return 0
    fi
    
    log_info "Invio report via email a: $EMAIL_TO"
    
    # Verifica che mail/sendmail sia disponibile
    if ! command -v mail >/dev/null 2>&1 && ! command -v sendmail >/dev/null 2>&1; then
        log_warn "Comando mail/sendmail non trovato. Report non inviato."
        log_warn "Installa mailutils: apt install mailutils"
        return 1
    fi
    
    # Crea report email
    local email_body
    email_body=$(cat <<EOF
CheckMK Retention Cleanup Report
================================

Data esecuzione: $(date '+%Y-%m-%d %H:%M:%S')
Hostname: $(hostname -f 2>/dev/null || hostname)
Site CheckMK: $OMD_SITE
Modalità: $([ "$DRY_RUN" = "true" ] && echo "DRY-RUN (simulazione)" || echo "PRODUZIONE")

--------------------------------
CONFIGURAZIONE RETENTION
--------------------------------
RRD files: $RETENTION_RRD giorni
Nagios archives: $RETENTION_NAGIOS giorni
Notify backups: $RETENTION_NOTIFY giorni
Compressione automatica dopo: $COMPRESS_AFTER giorni

--------------------------------
RISULTATI CLEANUP
--------------------------------

$(tail -n 200 "$LOG_FILE" | grep -A 5 "CLEANUP FILE RRD\|CLEANUP ARCHIVI NAGIOS\|CLEANUP BACKUP NOTIFICHE\|REPORT FINALE" || echo "Nessun dato disponibile")

--------------------------------
LOG COMPLETO
--------------------------------
Vedi log completo: $LOG_FILE

Questo è un messaggio automatico generato da cleanup-checkmk-retention.sh
EOF
)
    
    # Invia email
    if command -v mail >/dev/null 2>&1; then
        echo "$email_body" | mail -s "$EMAIL_SUBJECT" -r "$EMAIL_FROM" "$EMAIL_TO" 2>&1 | tee -a "$LOG_FILE"
        if [ $? -eq 0 ]; then
            log_success "Report inviato con successo a $EMAIL_TO"
        else
            log_error "Errore nell'invio del report a $EMAIL_TO"
        fi
    elif command -v sendmail >/dev/null 2>&1; then
        {
            echo "From: $EMAIL_FROM"
            echo "To: $EMAIL_TO"
            echo "Subject: $EMAIL_SUBJECT"
            echo ""
            echo "$email_body"
        } | sendmail -t 2>&1 | tee -a "$LOG_FILE"
        if [ $? -eq 0 ]; then
            log_success "Report inviato con successo a $EMAIL_TO"
        else
            log_error "Errore nell'invio del report a $EMAIL_TO"
        fi
    fi
}

# ================================================================
# CLEANUP FILE RRD (PNP4NAGIOS)
# ================================================================

cleanup_rrd_files() {
    local rrd_path="${SITE_PATH}/var/pnp4nagios/perfdata"
    
    log_info "============================================================"
    log_info "CLEANUP FILE RRD (retention: ${RETENTION_RRD} giorni)"
    log_info "============================================================"
    
    if [ ! -d "$rrd_path" ]; then
        log_warn "Cartella RRD non trovata: $rrd_path"
        return 0
    fi
    
    local count_before
    local size_before
    count_before=$(find "$rrd_path" -name "*.rrd" -type f 2>/dev/null | wc -l)
    size_before=$(du -sb "$rrd_path" 2>/dev/null | cut -f1)
    
    log_info "File RRD trovati: $count_before"
    log_info "Dimensione totale: $(human_size "$size_before")"
    
    # Trova file RRD più vecchi di RETENTION_RRD giorni
    local deleted=0
    local freed_space=0
    
    while IFS= read -r file; do
        local file_size
        file_size=$(stat -c%s "$file" 2>/dev/null || echo 0)
        
        if [ "$DRY_RUN" = "true" ]; then
            log_info "[DRY-RUN] Eliminerei: $file ($(human_size "$file_size"))"
        else
            if rm -f "$file" 2>/dev/null; then
                deleted=$((deleted + 1))
                freed_space=$((freed_space + file_size))
            else
                log_error "Impossibile eliminare: $file"
            fi
        fi
    done < <(find "$rrd_path" -name "*.rrd" -type f -mtime +${RETENTION_RRD} 2>/dev/null)
    
    if [ "$deleted" -gt 0 ]; then
        log_success "RRD eliminati: $deleted file"
        log_success "Spazio liberato: $(human_size "$freed_space")"
    else
        log_info "Nessun file RRD da eliminare"
    fi
}

# ================================================================
# CLEANUP ARCHIVI NAGIOS
# ================================================================

cleanup_nagios_archives() {
    local nagios_path="${SITE_PATH}/var/nagios"
    
    log_info "============================================================"
    log_info "CLEANUP ARCHIVI NAGIOS (retention: ${RETENTION_NAGIOS} giorni)"
    log_info "============================================================"
    
    if [ ! -d "$nagios_path" ]; then
        log_warn "Cartella Nagios non trovata: $nagios_path"
        return 0
    fi
    
    local size_before
    size_before=$(du -sb "$nagios_path" 2>/dev/null | cut -f1)
    log_info "Dimensione totale: $(human_size "$size_before")"
    
    # FASE 1: Comprimi file >30 giorni e <180 giorni (se non già compressi)
    log_info "Fase 1: Compressione file 30-180 giorni..."
    local compressed=0
    local compress_saved=0
    
    while IFS= read -r file; do
        # Salta se già compresso
        if [[ "$file" =~ \.(gz|bz2|xz)$ ]]; then
            continue
        fi
        
        local file_size
        file_size=$(stat -c%s "$file" 2>/dev/null || echo 0)
        
        if [ "$DRY_RUN" = "true" ]; then
            log_info "[DRY-RUN] Comprimerei: $file ($(human_size "$file_size"))"
        else
            if gzip -9 "$file" 2>/dev/null; then
                local compressed_size
                compressed_size=$(stat -c%s "${file}.gz" 2>/dev/null || echo 0)
                compressed=$((compressed + 1))
                compress_saved=$((compress_saved + file_size - compressed_size))
                log_info "Compresso: $file → $(human_size "$compressed_size")"
            else
                log_error "Errore compressione: $file"
            fi
        fi
    done < <(find "$nagios_path" -type f -mtime +${COMPRESS_AFTER} -mtime -${RETENTION_NAGIOS} 2>/dev/null)
    
    if [ "$compressed" -gt 0 ]; then
        log_success "File compressi: $compressed"
        log_success "Spazio risparmiato: $(human_size "$compress_saved")"
    else
        log_info "Nessun file da comprimere"
    fi
    
    # FASE 2: Elimina file >180 giorni
    log_info "Fase 2: Eliminazione file >180 giorni..."
    local deleted=0
    local freed_space=0
    
    while IFS= read -r file; do
        local file_size
        file_size=$(stat -c%s "$file" 2>/dev/null || echo 0)
        
        if [ "$DRY_RUN" = "true" ]; then
            log_info "[DRY-RUN] Eliminerei: $file ($(human_size "$file_size"))"
        else
            if rm -f "$file" 2>/dev/null; then
                deleted=$((deleted + 1))
                freed_space=$((freed_space + file_size))
            else
                log_error "Impossibile eliminare: $file"
            fi
        fi
    done < <(find "$nagios_path" -type f -mtime +${RETENTION_NAGIOS} 2>/dev/null)
    
    if [ "$deleted" -gt 0 ]; then
        log_success "File eliminati: $deleted"
        log_success "Spazio liberato: $(human_size "$freed_space")"
    else
        log_info "Nessun file da eliminare"
    fi
}

# ================================================================
# CLEANUP NOTIFY BACKUP
# ================================================================

cleanup_notify_backup() {
    local notify_path="${SITE_PATH}/var/notify-backup"
    
    log_info "============================================================"
    log_info "CLEANUP NOTIFY BACKUP (retention: ${RETENTION_NOTIFY} giorni)"
    log_info "============================================================"
    
    if [ ! -d "$notify_path" ]; then
        log_warn "Cartella notify-backup non trovata: $notify_path"
        return 0
    fi
    
    local size_before
    size_before=$(du -sb "$notify_path" 2>/dev/null | cut -f1)
    log_info "Dimensione totale: $(human_size "$size_before")"
    
    # FASE 1: Comprimi file >1 giorno e <30 giorni
    log_info "Fase 1: Compressione file 1-30 giorni..."
    local compressed=0
    local compress_saved=0
    
    while IFS= read -r file; do
        # Salta se già compresso
        if [[ "$file" =~ \.(gz|bz2|xz)$ ]]; then
            continue
        fi
        
        local file_size
        file_size=$(stat -c%s "$file" 2>/dev/null || echo 0)
        
        if [ "$DRY_RUN" = "true" ]; then
            log_info "[DRY-RUN] Comprimerei: $file ($(human_size "$file_size"))"
        else
            if gzip -9 "$file" 2>/dev/null; then
                local compressed_size
                compressed_size=$(stat -c%s "${file}.gz" 2>/dev/null || echo 0)
                compressed=$((compressed + 1))
                compress_saved=$((compress_saved + file_size - compressed_size))
            else
                log_error "Errore compressione: $file"
            fi
        fi
    done < <(find "$notify_path" -type f -mtime +1 -mtime -${RETENTION_NOTIFY} 2>/dev/null)
    
    if [ "$compressed" -gt 0 ]; then
        log_success "File compressi: $compressed"
        log_success "Spazio risparmiato: $(human_size "$compress_saved")"
    else
        log_info "Nessun file da comprimere"
    fi
    
    # FASE 2: Elimina file >30 giorni
    log_info "Fase 2: Eliminazione file >30 giorni..."
    local deleted=0
    local freed_space=0
    
    while IFS= read -r file; do
        local file_size
        file_size=$(stat -c%s "$file" 2>/dev/null || echo 0)
        
        if [ "$DRY_RUN" = "true" ]; then
            log_info "[DRY-RUN] Eliminerei: $file ($(human_size "$file_size"))"
        else
            if rm -f "$file" 2>/dev/null; then
                deleted=$((deleted + 1))
                freed_space=$((freed_space + file_size))
            else
                log_error "Impossibile eliminare: $file"
            fi
        fi
    done < <(find "$notify_path" -type f -mtime +${RETENTION_NOTIFY} 2>/dev/null)
    
    if [ "$deleted" -gt 0 ]; then
        log_success "File eliminati: $deleted"
        log_success "Spazio liberato: $(human_size "$freed_space")"
    else
        log_info "Nessun file da eliminare"
    fi
}

# ================================================================
# CLEANUP CARTELLE VUOTE
# ================================================================

cleanup_empty_dirs() {
    log_info "============================================================"
    log_info "CLEANUP CARTELLE VUOTE"
    log_info "============================================================"
    
    local paths=(
        "${SITE_PATH}/var/pnp4nagios/perfdata"
        "${SITE_PATH}/var/nagios"
        "${SITE_PATH}/var/notify-backup"
    )
    
    local removed=0
    
    for path in "${paths[@]}"; do
        if [ ! -d "$path" ]; then
            continue
        fi
        
        while IFS= read -r dir; do
            if [ "$DRY_RUN" = "true" ]; then
                log_info "[DRY-RUN] Eliminerei cartella vuota: $dir"
            else
                if rmdir "$dir" 2>/dev/null; then
                    removed=$((removed + 1))
                    log_info "Eliminata cartella vuota: $dir"
                fi
            fi
        done < <(find "$path" -type d -empty 2>/dev/null)
    done
    
    if [ "$removed" -gt 0 ]; then
        log_success "Cartelle vuote eliminate: $removed"
    else
        log_info "Nessuna cartella vuota da eliminare"
    fi
}

# ================================================================
# REPORT FINALE
# ================================================================

generate_report() {
    log_info "============================================================"
    log_info "REPORT FINALE"
    log_info "============================================================"
    
    log_info "Dimensioni attuali:"
    du -sh "${SITE_PATH}/var/pnp4nagios/perfdata" 2>/dev/null | awk '{print "  - RRD: " $1}'
    du -sh "${SITE_PATH}/var/nagios" 2>/dev/null | awk '{print "  - Nagios: " $1}'
    if [ -d "${SITE_PATH}/var/notify-backup" ]; then
        du -sh "${SITE_PATH}/var/notify-backup" 2>/dev/null | awk '{print "  - Notify: " $1}'
    else
        echo "  - Notify: N/A (directory non presente)"
    fi
    
    log_info ""
    log_info "Conta file:"
    find "${SITE_PATH}/var/pnp4nagios/perfdata" -name "*.rrd" 2>/dev/null | wc -l | awk '{print "  - File RRD: " $1}'
    find "${SITE_PATH}/var/nagios" -type f 2>/dev/null | wc -l | awk '{print "  - File Nagios: " $1}'
    if [ -d "${SITE_PATH}/var/notify-backup" ]; then
        find "${SITE_PATH}/var/notify-backup" -type f 2>/dev/null | wc -l | awk '{print "  - File Notify: " $1}'
    else
        echo "  - File Notify: 0 (directory non presente)"
    fi
}

# ================================================================
# MAIN
# ================================================================

main() {
    # Parse parametri
    while [[ $# -gt 0 ]]; do
        case $1 in
            --dry-run)
                DRY_RUN="true"
                shift
                ;;
            --email)
                EMAIL_TO="$2"
                shift 2
                ;;
            --help|-h)
                echo "Usage: $0 [OPTIONS]"
                echo ""
                echo "Options:"
                echo "  --dry-run          Esegui in modalità test (non elimina file)"
                echo "  --email ADDRESS    Invia report via email all'indirizzo specificato"
                echo "  --help, -h         Mostra questo help"
                echo ""
                echo "Environment variables:"
                echo "  OMD_SITE           Nome del site CheckMK (default: monitoring)"
                echo "  DRY_RUN            true per modalità test (default: false)"
                echo "  EMAIL_TO           Indirizzo email per report (opzionale)"
                echo ""
                echo "Examples:"
                echo "  $0 --dry-run"
                echo "  $0 --email admin@example.com"
                echo "  $0 --dry-run --email admin@example.com"
                echo "  EMAIL_TO=admin@example.com $0"
                echo ""
                exit 0
                ;;
            *)
                echo "Unknown option: $1"
                echo "Use --help for usage information"
                exit 1
                ;;
        esac
    done
    
    log_info "============================================================"
    log_info "CLEANUP RETENTION CHECKMK - START"
    log_info "============================================================"
    log_info "Site: $OMD_SITE"
    log_info "Path: $SITE_PATH"
    log_info "Retention RRD: ${RETENTION_RRD} giorni"
    log_info "Retention Nagios: ${RETENTION_NAGIOS} giorni"
    log_info "Retention Notify: ${RETENTION_NOTIFY} giorni"
    log_info "Compressione dopo: ${COMPRESS_AFTER} giorni"
    
    if [ "$DRY_RUN" = "true" ]; then
        log_warn "!!! DRY-RUN MODE - Nessuna modifica effettiva !!!"
    fi
    
    log_info ""
    
    # Verifica che il site esista
    if [ ! -d "$SITE_PATH" ]; then
        log_error "Site non trovato: $SITE_PATH"
        exit 1
    fi
    
    # Esegui cleanup
    cleanup_rrd_files
    echo ""
    cleanup_nagios_archives
    echo ""
    cleanup_notify_backup
    echo ""
    cleanup_empty_dirs
    echo ""
    generate_report
    echo ""
    send_email_report
    
    log_info ""
    log_info "============================================================"
    log_info "CLEANUP RETENTION CHECKMK - COMPLETATO"
    log_info "============================================================"
}

# Esegui
main "$@"
