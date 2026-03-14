#!/usr/bin/env bash
set -euo pipefail

# update-scripts-from-repo.sh
# Cerca script locali e li sostituisce con la corrispondente versione "r<nome>" nel repository.
# Output semplice (ASCII-only).
#
# Uso:
#   sudo ./update-scripts-from-repo.sh [REPO_DIR] [SEARCH_PATH]
#   sudo ./update-scripts-from-repo.sh [REPO_DIR] --auto
#
# Note:
# - Per ogni file aggiornato viene creato un backup sotto /tmp.
# - In modalita' --auto cerca sotto / (escludendo /proc,/sys,/dev,/run,/tmp,/var/tmp e .git).

REPO_DIR="${1:-/opt/checkmk-tools}"
SEARCH_PATH="${2:-/opt/omd}"
AUTO_MODE=0

die() { echo "[ERR] $*" >&2; exit 1; }
log() { echo "[INFO] $*"; }
warn() { echo "[WARN] $*"; }

if [[ "${2:-}" == "--auto" || "${3:-}" == "--auto" ]]; then
    AUTO_MODE=1
fi

[[ ${EUID:-$(id -u)} -eq 0 ]] || die "eseguire come root (sudo)"
[[ -d "$REPO_DIR" ]] || die "repository non trovato: $REPO_DIR"
command -v git >/dev/null 2>&1 || die "git non trovato"

BACKUP_DIR="/tmp/script-backup-$(date +%Y%m%d-%H%M%S)"

log "Repository: $REPO_DIR"
if (( AUTO_MODE == 1 )); then
    log "Modalita: auto (scan /)"
else
    log "Modalita: manual (scan $SEARCH_PATH)"
fi

log "Aggiorno repository (git pull)..."
cd "$REPO_DIR"
if ! git diff --quiet || ! git diff --cached --quiet; then
    warn "Modifiche locali rilevate: eseguo git stash"
    git stash push -m "Auto-stash before update $(date +%Y%m%d-%H%M%S)" >/dev/null 2>&1 || true
fi
git pull --rebase --autostash origin main >/dev/null 2>&1 || git pull origin main >/dev/null 2>&1 || true

mkdir -p "$BACKUP_DIR"
log "Backup in: $BACKUP_DIR"

updated=0
errors=0

scan_one_tree() {
    local root="$1"
    local find_cmd=(find "$root" -type f \( -name "*.sh" -o -executable \) -print0)
    if [[ "$root" == "/" ]]; then
        find_cmd=(find / \(
            -path /proc -o -path /sys -o -path /dev -o -path /run -o -path /tmp -o -path /var/tmp -o -path '*/.git'
        \) -prune -o -type f \( -name "*.sh" -o -executable \) -print0)
    fi

    while IFS= read -r -d '' target_script; do
        local name dir repo_script backup_path
        name="$(basename "$target_script")"
        dir="$(dirname "$target_script")"

        [[ "$name" =~ ^r ]] && continue
        [[ "$name" =~ \.(backup|bak|old|tmp)$ ]] && continue
        [[ "$name" =~ ^\. ]] && continue
        [[ "$target_script" == "$REPO_DIR"/* ]] && continue

        repo_script="$(find "$REPO_DIR" -type f -name "r${name}" 2>/dev/null | head -n1 || true)"
        [[ -n "$repo_script" && -f "$repo_script" ]] || continue

        backup_path="$BACKUP_DIR$dir"
        mkdir -p "$backup_path"
        cp -a "$target_script" "$backup_path/" || true

        if head -n1 "$repo_script" 2>/dev/null | grep -q "bash"; then
            if ! bash -n "$repo_script" 2>/dev/null; then
                warn "Skip (syntax): $repo_script"
                ((errors++))
                continue
            fi
        fi

        cp -a "$repo_script" "$target_script"
        chmod +x "$target_script" || true
        log "Aggiornato: $target_script"
        ((updated++))
    done < <("${find_cmd[@]}" 2>/dev/null)
}

if (( AUTO_MODE == 1 )); then
    scan_one_tree "/"
else
    [[ -d "$SEARCH_PATH" ]] || die "search path non trovato: $SEARCH_PATH"
    scan_one_tree "$SEARCH_PATH"
fi

log "Risultato: updated=$updated errors=$errors"
log "Per ripristinare: cp -a $BACKUP_DIR/* /"
exit 0
