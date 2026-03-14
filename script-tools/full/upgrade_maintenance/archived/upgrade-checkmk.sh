#!/usr/bin/env bash
set -euo pipefail

# upgrade-checkmk.sh
# Upgrade Checkmk RAW (CRE) su Debian/Ubuntu.
# Output semplice (ASCII-only).

SITE_NAME=""
DOWNLOAD_DIR="/tmp/checkmk-upgrade"
BACKUP_DIR="/opt/omd/backups"
REPORT_FILE="/tmp/checkmk-upgrade-report.txt"

die() { echo "[ERR] $*" >&2; echo "[ERR] $*" >> "$REPORT_FILE"; exit 1; }
log() { echo "[INFO] $*"; echo "[INFO] $*" >> "$REPORT_FILE"; }
warn() { echo "[WARN] $*"; echo "[WARN] $*" >> "$REPORT_FILE"; }

need_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "comando mancante: $1"
}

require_root() {
    [[ ${EUID:-$(id -u)} -eq 0 ]] || die "eseguire come root (sudo)"
}

get_current_version() {
    local v
    v="$(omd version "$SITE_NAME" 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+p[0-9]+' | head -n1 || true)"
    [[ -n "$v" ]] || die "impossibile rilevare versione corrente per sito: $SITE_NAME"
    printf '%s' "$v"
}

get_latest_version() {
    local page v
    page="$(curl -fsSL "https://checkmk.com/download" 2>/dev/null || true)"
    v="$(printf '%s' "$page" | grep -oE 'check-mk-raw-[0-9]+\.[0-9]+\.[0-9]+p[0-9]+' | head -n1 | sed 's/^check-mk-raw-//' || true)"
    [[ -n "$v" ]] || die "impossibile recuperare ultima versione da checkmk.com"
    printf '%s' "$v"
}

detect_deb_codename() {
    # Output: focal|jammy|noble|bullseye|bookworm
    [[ -r /etc/os-release ]] || die "manca /etc/os-release"
    # shellcheck disable=SC1091
    . /etc/os-release

    case "${ID:-}" in
        ubuntu)
            case "${VERSION_ID:-}" in
                20.04) echo "focal" ;;
                22.04) echo "jammy" ;;
                24.04) echo "noble" ;;
                *) die "ubuntu non supportato: ${VERSION_ID:-?}" ;;
            esac
            ;;
        debian)
            case "${VERSION_ID:-}" in
                11) echo "bullseye" ;;
                12) echo "bookworm" ;;
                *) die "debian non supportato: ${VERSION_ID:-?}" ;;
            esac
            ;;
        *) die "distribuzione non supportata: ${ID:-?}" ;;
    esac
}

detect_site() {
    local sites site_count site_list
    
    # Ottieni lista dei siti attivi
    sites=$(omd sites 2>/dev/null | awk '{print $1}' | grep -v '^SITE$' || true)
    site_count=$(echo "$sites" | grep -v '^$' | wc -l)
    
    if [[ $site_count -eq 0 ]]; then
        die "Nessun sito Checkmk trovato. Installare prima un sito con 'omd create <nome>'"
    fi
    
    if [[ $site_count -eq 1 ]]; then
        SITE_NAME=$(echo "$sites" | grep -v '^$')
        log "Rilevato automaticamente sito: $SITE_NAME"
    else
        log "Siti Checkmk disponibili:"
        echo "$sites" | nl
        echo
        read -r -p "Seleziona il numero del sito da aggiornare: " site_num
        SITE_NAME=$(echo "$sites" | sed -n "${site_num}p")
        
        if [[ -z "$SITE_NAME" ]]; then
            die "Selezione non valida"
        fi
        
        log "Sito selezionato: $SITE_NAME"
    fi
}

main() {
    # Inizializza report file
    cat > "$REPORT_FILE" <<EOF
================================================================
  CHECKMK AUTO-UPGRADE REPORT
================================================================
Server: $(hostname)
Data: $(date '+%Y-%m-%d %H:%M:%S')
User: $(whoami)

EOF

    require_root
    need_cmd omd
    need_cmd curl
    need_cmd grep
    need_cmd sed
    need_cmd wget
    need_cmd dpkg

    # Rileva automaticamente il sito o chiedi all'utente
    detect_site

    log "Sito: $SITE_NAME"
    current="$(get_current_version)"
    latest="$(get_latest_version)"
    
    cat >> "$REPORT_FILE" <<EOF
----------------------------------------------------------------
  INFORMAZIONI UPGRADE
----------------------------------------------------------------
Sito: $SITE_NAME
Versione corrente: $current
Ultima versione disponibile: $latest

EOF
    
    log "Versione corrente: $current"
    log "Ultima versione:   $latest"

    if [[ "$current" == "$latest" ]]; then
        log "Nessun aggiornamento necessario"
        cat >> "$REPORT_FILE" <<EOF
RISULTATO: Nessun aggiornamento necessario
Il sito è già alla versione più recente.
EOF
        exit 0
    fi

    echo
    echo "Aggiornamento previsto: $current -> $latest"
    
    # In modalità automatica (cron), non chiedere conferma
    if [[ -t 0 ]]; then
        read -r -p "Procedere? [y/N]: " confirm
        confirm="${confirm:-N}"
        [[ "$confirm" =~ ^[Yy]$ ]] || exit 0
    else
        log "Modalità automatica: procedo con l'upgrade"
    fi

    mkdir -p "$DOWNLOAD_DIR" "$BACKUP_DIR"

    backup_file="$BACKUP_DIR/${SITE_NAME}_pre-upgrade_$(date +%Y%m%d_%H%M%S).tar.gz"
    log "Backup: $backup_file"
    omd backup "$SITE_NAME" "$backup_file"

    codename="$(detect_deb_codename)"
    pkg="check-mk-raw-${latest}_0.${codename}_amd64.deb"
    url="https://download.checkmk.com/checkmk/${latest}/${pkg}"
    local_file="$DOWNLOAD_DIR/$pkg"

    log "Download: $url"
    rm -f "$local_file" 2>/dev/null || true
    wget -q --show-progress -O "$local_file" "$url"
    [[ -s "$local_file" ]] || die "download fallito: $local_file"

    log "Installazione pacchetto (.deb)"
    if ! dpkg -i "$local_file"; then
        warn "dpkg ha restituito errore (dipendenze?)"
        warn "Suggerimento: eseguire 'apt-get -f install' e riprovare"
        exit 1
    fi

    log "Stop sito: $SITE_NAME"
    omd stop "$SITE_NAME"

    log "Upgrade sito (omd update) - modalità automatica"
    # Usa --conflict=install per accettare automaticamente i nuovi file di configurazione
    # Usa -f per forzare l'update senza interazione
    omd -f update --conflict=install "$SITE_NAME"

    log "Start sito: $SITE_NAME"
    omd start "$SITE_NAME"

    new_v="$(get_current_version)"
    log "Versione dopo upgrade: $new_v"
    
    # Verifica stato servizi
    site_status=$(omd status "$SITE_NAME" 2>&1 || true)
    log "=== STATUS SERVIZI ==="
    echo "$site_status" | tee -a "$REPORT_FILE"

    echo
    log "=== PULIZIA AUTOMATICA ==="
    
    # 1. Rimuovi versioni OMD vecchie (mantieni solo quella in uso)
    log "Rimozione versioni CheckMK obsolete..."
    old_versions_removed=0
    if [[ -d /opt/omd/versions ]]; then
        for version_dir in /opt/omd/versions/*; do
            [[ -d "$version_dir" ]] || continue
            version_name=$(basename "$version_dir")
            
            # Salta la versione corrente e i symlink
            [[ "$version_name" == "$new_v" ]] && continue
            [[ -L "$version_dir" ]] && continue
            
            # Verifica che nessun site la usi
            if ! omd sites 2>/dev/null | grep -q "$version_name"; then
                log "  Rimuovo versione: $version_name"
                rm -rf "$version_dir" 2>/dev/null || warn "Impossibile rimuovere: $version_dir"
                ((old_versions_removed++)) || true
            fi
        done
    fi
    [[ $old_versions_removed -gt 0 ]] && log "Versioni rimosse: $old_versions_removed" || log "Nessuna versione da rimuovere"
    
    # 1b. Rimuovi pacchetti .deb obsoleti (mantieni solo la versione corrente)
    log "Rimozione pacchetti CheckMK obsoleti..."
    old_packages_removed=0
    if command -v dpkg >/dev/null 2>&1; then
        # Lista tutti i pacchetti check-mk-raw installati
        old_packages=$(dpkg -l | grep -E 'check-mk-raw-[0-9]' | awk '{print $2}' | grep -v "check-mk-raw-${new_v}" || true)
        if [[ -n "$old_packages" ]]; then
            for pkg in $old_packages; do
                log "  Rimuovo pacchetto: $pkg"
                apt-get remove -y "$pkg" >> "$REPORT_FILE" 2>&1 || warn "Impossibile rimuovere: $pkg"
                ((old_packages_removed++)) || true
            done
            # Cleanup finale
            apt-get autoremove -y >> "$REPORT_FILE" 2>&1 || true
            apt-get clean >> "$REPORT_FILE" 2>&1 || true
        fi
    fi
    [[ $old_packages_removed -gt 0 ]] && log "Pacchetti rimossi: $old_packages_removed" || log "Nessun pacchetto da rimuovere"
    
    # 2. Mantieni solo ultimi 3 backup in /opt/omd/backups (per questo site)
    log "Pulizia backup vecchi (mantiene ultimi 3)..."
    old_backups_removed=0
    if [[ -d "$BACKUP_DIR" ]]; then
        # Trova tutti i backup di questo site, ordina per data (più recenti primi)
        backup_list=$(find "$BACKUP_DIR" -maxdepth 1 -type f -name "${SITE_NAME}_pre-upgrade_*.tar.gz" 2>/dev/null | sort -r || true)
        backup_count=$(echo "$backup_list" | grep -c '^' || echo 0)
        
        if [[ $backup_count -gt 3 ]]; then
            # Salta i primi 3 (più recenti), elimina il resto
            echo "$backup_list" | tail -n +4 | while IFS= read -r old_backup; do
                log "  Rimuovo backup: $(basename "$old_backup")"
                rm -f "$old_backup" 2>/dev/null || warn "Impossibile rimuovere: $old_backup"
                ((old_backups_removed++)) || true
            done
        fi
    fi
    [[ $old_backups_removed -gt 0 ]] && log "Backup rimossi: $old_backups_removed" || log "Nessun backup da rimuovere"
    
    # Cleanup file download (automatico in modalità cron)
    if [[ ! -t 0 ]]; then
        rm -rf "$DOWNLOAD_DIR"
        log "File temporanei eliminati automaticamente"
    else
        echo
        read -r -p "Eliminare i file scaricati in $DOWNLOAD_DIR? [y/N]: " cleanup
        cleanup="${cleanup:-N}"
        if [[ "$cleanup" =~ ^[Yy]$ ]]; then
            rm -rf "$DOWNLOAD_DIR"
            log "File temporanei eliminati"
        else
            log "File mantenuti in: $DOWNLOAD_DIR"
        fi
    fi

    log "Backup corrente disponibile in: $backup_file"
    log "Upgrade completato: $current -> $new_v"
    
    # Riepilogo finale nel report
    cat >> "$REPORT_FILE" <<EOF

----------------------------------------------------------------
  RIEPILOGO UPGRADE
----------------------------------------------------------------
✅ UPGRADE COMPLETATO CON SUCCESSO

Versione iniziale:      $current
Versione finale:        $new_v
Backup creato:          $backup_file
Versioni OMD rimosse:   $old_versions_removed
Pacchetti .deb rimossi: $old_packages_removed
Backup vecchi rimossi:  $old_backups_removed

Servizi CheckMK:
$site_status

================================================================
Report generato: $(date '+%Y-%m-%d %H:%M:%S')
================================================================
EOF

    log "Report salvato in: $REPORT_FILE"
}

main "$@"
