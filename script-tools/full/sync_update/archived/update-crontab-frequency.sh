#!/usr/bin/env bash
set -euo pipefail

# Script interattivo per aggiornare la frequenza del ticket-monitor.
# Output semplice (ASCII-only).

TARGET_CMD="/opt/ydea-toolkit/rydea-ticket-monitor.sh"

log() { echo "[INFO] $*"; }
warn() { echo "[WARN] $*"; }
err() { echo "[ERR] $*" >&2; }

current_crontab() {
    crontab -l 2>/dev/null || true
}

get_current_freq() {
    current_crontab | awk -v cmd="$TARGET_CMD" '$0 ~ cmd { print $1; exit }'
}

describe_freq() {
    case "$1" in
        "*/1") echo "1 minuto" ;;
        "*/5") echo "5 minuti" ;;
        "*/10") echo "10 minuti" ;;
        "*/15") echo "15 minuti" ;;
        "*/30") echo "30 minuti" ;;
        "") echo "non impostata" ;;
        *) echo "$1 (personalizzato)" ;;
    esac
}

validate_freq() {
    # Accetta: */N oppure una lista tipo 0,15,30,45
    [[ "$1" =~ ^\*/[0-9]+$ ]] && return 0
    [[ "$1" =~ ^[0-9]+(,[0-9]+)*$ ]] && return 0
    return 1
}

apply_change() {
    local new_freq="$1"
    local backup_file="/tmp/crontab.backup.$(date +%Y%m%d_%H%M%S)"
    current_crontab >"$backup_file"
    log "Backup crontab: $backup_file"

    # Se esiste una riga con TARGET_CMD, sostituisce solo il primo campo (minute).
    # Se non esiste, aggiunge una riga standard: <freq> * * * * <cmd>
    local updated
    updated="$(
        current_crontab | awk -v cmd="$TARGET_CMD" -v nf="$new_freq" '
            BEGIN { found=0 }
            $0 ~ cmd {
                found=1
                # ricostruisci: nuovo minuto + resto dei campi
                $1=nf
                print
                next
            }
            { print }
            END {
                if (found==0) {
                    print nf " * * * * " cmd
                }
            }
        '
    )"

    printf '%s\n' "$updated" | crontab -
}

main() {
    local current_freq
    current_freq="$(get_current_freq)"

    echo "Configurazione frequenza ticket-monitor"
    echo
    echo "Frequenza attuale: $(describe_freq "$current_freq")"${current_freq:+" ($current_freq)"}
    echo
    echo "Scegli nuova frequenza:"
    echo "  1) Ogni 1 minuto   (*/1)"
    echo "  2) Ogni 5 minuti   (*/5)"
    echo "  3) Ogni 10 minuti  (*/10)"
    echo "  4) Ogni 15 minuti  (*/15)"
    echo "  5) Ogni 30 minuti  (*/30)"
    echo "  6) Personalizzato"
    echo "  0) Esci"
    echo

    local choice new_freq
    read -r -p "Scelta [1-6, 0]: " choice

    case "$choice" in
        1) new_freq="*/1" ;;
        2) new_freq="*/5" ;;
        3) new_freq="*/10" ;;
        4) new_freq="*/15" ;;
        5) new_freq="*/30" ;;
        6)
            read -r -p "Inserisci frequenza (es. */5 oppure 0,15,30,45): " new_freq
            ;;
        0)
            echo "Annullato."
            exit 0
            ;;
        *)
            err "Scelta non valida"
            exit 1
            ;;
    esac

    if ! validate_freq "$new_freq"; then
        err "Formato frequenza non valido: $new_freq"
        exit 1
    fi

    echo
    echo "Cambio frequenza: ${current_freq:-<vuota>} -> $new_freq"
    read -r -p "Confermi? [s/N]: " confirm
    if [[ "$confirm" != "s" && "$confirm" != "S" ]]; then
        echo "Annullato."
        exit 0
    fi

    apply_change "$new_freq"
    echo
    log "Crontab aggiornato"
    current_crontab | grep -E "ydea-ticket-monitor|ydea-health-monitor" || true
}

main "$@"
