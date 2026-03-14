#!/usr/bin/env bash
set -euo pipefail

# deploy-monitoring-scripts.sh
# Deploy interattivo di script r*.sh (repo checkmk-tools) in:
#   /usr/lib/check_mk_agent/local
# Output semplice (ASCII-only).

TARGET_DIR="/usr/lib/check_mk_agent/local"

die() { echo "[ERR] $*" >&2; exit 1; }
log() { echo "[INFO] $*"; }
warn() { echo "[WARN] $*"; }

require_root() {
    [[ ${EUID:-$(id -u)} -eq 0 ]] || die "eseguire come root (sudo)"
}

detect_system() {
    # ns7 | ns8 | proxmox | ubuntu | generic
    if [[ -f /etc/pve/version ]]; then
        echo "proxmox"; return 0
    fi

    if [[ -r /etc/os-release ]]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        if [[ "${ID:-}" == "nethserver" ]]; then
            case "${VERSION_ID:-}" in
                7*) echo "ns7"; return 0 ;;
                8*) echo "ns8"; return 0 ;;
            esac
        fi
        if grep -qiE 'nethserver' /etc/os-release; then
            if grep -qE 'VERSION_ID="?7' /etc/os-release; then echo "ns7"; return 0; fi
            if grep -qE 'VERSION_ID="?8' /etc/os-release; then echo "ns8"; return 0; fi
        fi
        if grep -qiE 'ubuntu|debian' /etc/os-release; then
            echo "ubuntu"; return 0
        fi
    fi

    if [[ -f /etc/nethserver-release ]]; then
        echo "ns7"; return 0
    fi

    echo "generic"
}

find_repo() {
    # 1) env
    if [[ -n "${REPO_DIR:-}" && -d "${REPO_DIR:-}/.git" ]]; then
        echo "$REPO_DIR"; return 0
    fi

    # 2) common paths
    for d in /opt/checkmk-tools /root/checkmk-tools "$HOME/checkmk-tools"; do
        if [[ -d "$d/.git" ]]; then
            echo "$d"; return 0
        fi
    done

    # 3) search upwards from this script location
    local here parent i
    here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    parent="$here"
    for i in 1 2 3 4 5; do
        if [[ -d "$parent/.git" ]]; then
            echo "$parent"; return 0
        fi
        parent="$(cd "$parent/.." && pwd)"
    done

    return 1
}

source_dir_for() {
    local repo="$1" system="$2" dir
    case "$system" in
        ns7) dir="$repo/script-check-ns7/remote" ;;
        ns8) dir="$repo/script-check-ns8/remote" ;;
        proxmox) dir="$repo/script-check-proxmox/remote" ;;
        ubuntu|generic) dir="$repo/script-check-ubuntu/remote" ;;
        *) return 1 ;;
    esac
    echo "$dir"
}

list_scripts() {
    local dir="$1"
    find "$dir" -type f -name 'r*.sh' 2>/dev/null | sort
}

select_scripts() {
    local -a scripts=("$@")
    local -a selected=()
    local selection num

    if [[ ${#scripts[@]} -eq 0 ]]; then
        return 0
    fi

    # Se non siamo interattivi, selezioniamo tutto.
    if [[ ! -t 0 ]]; then
        printf '%s\n' "${scripts[@]}"
        return 0
    fi

    echo
    echo "Script disponibili:"
    for i in "${!scripts[@]}"; do
        printf '%3d) %s\n' $((i+1)) "$(basename "${scripts[$i]}")"
    done
    echo
    echo "Selezione: numeri separati da spazi (es: 1 3 7), oppure 'a' per tutti, 'n' per annullare"
    read -r -p "Selezione: " selection
    selection="${selection:-n}"

    if [[ "$selection" =~ ^[Aa]$ ]]; then
        printf '%s\n' "${scripts[@]}"
        return 0
    fi
    if [[ "$selection" =~ ^[Nn]$ ]]; then
        return 0
    fi

    for num in $selection; do
        if [[ "$num" =~ ^[0-9]+$ ]] && (( num >= 1 )) && (( num <= ${#scripts[@]} )); then
            selected+=("${scripts[$((num-1))]}")
        else
            warn "Selezione non valida: $num"
        fi
    done

    if [[ ${#selected[@]} -eq 0 ]]; then
        return 0
    fi

    printf '%s\n' "${selected[@]}"
}

deploy_scripts() {
    local -a scripts=("$@")
    local ok=0 fail=0 src base dst

    mkdir -p "$TARGET_DIR"

    for src in "${scripts[@]}"; do
        base="$(basename "$src")"
        dst="$TARGET_DIR/$base"
        if cp "$src" "$dst"; then
            chmod +x "$dst" || true
            log "Installato: $base"
            ok=$((ok+1))
        else
            warn "Errore copia: $base"
            fail=$((fail+1))
        fi
    done

    echo
    log "Risultato: ok=$ok fail=$fail"
    log "Destinazione: $TARGET_DIR"
}

main() {
    require_root

    repo="$(find_repo || true)"
    [[ -n "$repo" ]] || die "repository checkmk-tools non trovato (provare a impostare REPO_DIR)"

    system="$(detect_system)"
    src_dir="$(source_dir_for "$repo" "$system" || true)"
    [[ -n "$src_dir" ]] || die "tipo sistema non supportato: $system"
    [[ -d "$src_dir" ]] || die "directory sorgente non trovata: $src_dir"

    log "Repo: $repo"
    log "Sistema: $system"
    log "Sorgente: $src_dir"
    log "Target: $TARGET_DIR"

    mapfile -t all_scripts < <(list_scripts "$src_dir")
    if [[ ${#all_scripts[@]} -eq 0 ]]; then
        die "nessuno script r*.sh trovato in: $src_dir"
    fi

    mapfile -t chosen < <(select_scripts "${all_scripts[@]}")
    if [[ ${#chosen[@]} -eq 0 ]]; then
        log "Nessuno script selezionato"
        exit 0
    fi

    if [[ -t 0 ]]; then
        echo
        echo "Script selezionati: ${#chosen[@]}"
        read -r -p "Procedere con il deploy? [y/N]: " confirm
        confirm="${confirm:-N}"
        [[ "$confirm" =~ ^[Yy]$ ]] || exit 0
    fi

    deploy_scripts "${chosen[@]}"
}

main "$@"
