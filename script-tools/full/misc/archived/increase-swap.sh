#!/usr/bin/env bash
set -euo pipefail

# increase-swap.sh
# Crea/ricrea uno swapfile (default 16GiB) in modo semplice e idempotente.
# Uso:
#   sudo ./increase-swap.sh
#   sudo ./increase-swap.sh --yes
#   sudo ./increase-swap.sh --size-gb 16 --file /swapfile

AUTO_YES=0
SIZE_GB=16
SWAPFILE="/swapfile"

die() {
    echo "[ERR] $*" >&2
    exit 1
}

log() {
    echo "[INFO] $*"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --yes|-y) AUTO_YES=1; shift ;;
        --size-gb) SIZE_GB="${2:-}"; shift 2 ;;
        --file) SWAPFILE="${2:-}"; shift 2 ;;
        -h|--help)
            cat <<EOF
Uso: sudo $0 [--yes] [--size-gb N] [--file PATH]

--yes        non chiede conferma
--size-gb N  dimensione swapfile in GiB (default: 16)
--file PATH  percorso swapfile (default: /swapfile)
EOF
            exit 0
            ;;
        *) die "argomento non riconosciuto: $1" ;;
    esac
done

[[ ${EUID:-$(id -u)} -eq 0 ]] || die "eseguire come root (sudo)"
[[ "$SIZE_GB" =~ ^[0-9]+$ ]] || die "--size-gb deve essere un intero"
(( SIZE_GB > 0 )) || die "--size-gb deve essere > 0"
[[ -n "$SWAPFILE" ]] || die "--file non valido"

log "Situazione attuale:"
free -h || true
swapon --show || true

active_swap="$(swapon --noheadings --show=NAME 2>/dev/null | head -n1 || true)"
if [[ -n "$active_swap" && "$active_swap" != "$SWAPFILE" ]]; then
    log "Swap attivo rilevato: $active_swap (lo lascio invariato)"
fi

log "Target swapfile: $SWAPFILE"
log "Nuova dimensione: ${SIZE_GB}GiB"

if (( AUTO_YES == 0 )); then
    read -r -p "Procedere? [y/N]: " confirm
    confirm="${confirm:-N}"
    [[ "$confirm" =~ ^[Yy]$ ]] || exit 0
fi

if swapon --show=NAME --noheadings 2>/dev/null | awk '{print $1}' | grep -qx "$SWAPFILE"; then
    log "Disattivo swap: $SWAPFILE"
    swapoff "$SWAPFILE"
fi

if [[ -e "$SWAPFILE" ]]; then
    log "Rimuovo file esistente: $SWAPFILE"
    rm -f "$SWAPFILE"
fi

log "Creo swapfile (${SIZE_GB}GiB)..."
bytes=$(( SIZE_GB * 1024 * 1024 * 1024 ))
if command -v fallocate >/dev/null 2>&1; then
    fallocate -l "$bytes" "$SWAPFILE" || dd if=/dev/zero of="$SWAPFILE" bs=1M count=$(( SIZE_GB * 1024 )) status=progress
else
    dd if=/dev/zero of="$SWAPFILE" bs=1M count=$(( SIZE_GB * 1024 )) status=progress
fi

chmod 600 "$SWAPFILE"
mkswap "$SWAPFILE" >/dev/null
swapon "$SWAPFILE"

if ! grep -qE "^\Q$SWAPFILE\E\s" /etc/fstab; then
    log "Aggiungo entry a /etc/fstab"
    echo "$SWAPFILE none swap sw 0 0" >> /etc/fstab
else
    log "Entry gia' presente in /etc/fstab"
fi

if ! grep -qE "^\s*vm\.swappiness\s*=" /etc/sysctl.conf; then
    log "Imposto vm.swappiness=10"
    echo "vm.swappiness=10" >> /etc/sysctl.conf
fi
sysctl -w vm.swappiness=10 >/dev/null 2>&1 || true

log "Fatto. Situazione finale:"
free -h || true
swapon --show || true
