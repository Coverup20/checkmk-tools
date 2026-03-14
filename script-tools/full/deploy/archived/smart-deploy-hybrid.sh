#!/usr/bin/env bash
set -euo pipefail

# smart-deploy-hybrid.sh
# Deploy di wrapper "smart" per script Checkmk:
# - crea un wrapper in local/plugins/notifications
# - il wrapper prova ad aggiornare da GitHub e poi esegue una copia in cache
# Output semplice (ASCII-only).

GITHUB_REPO="Coverup20/checkmk-tools"
BASE_URL="https://raw.githubusercontent.com/${GITHUB_REPO}/main"

log() { echo "[INFO] $*"; }
warn() { echo "[WARN] $*"; }
die() { echo "[ERR] $*" >&2; exit 1; }

need_cmd() { command -v "$1" >/dev/null 2>&1 || die "comando mancante: $1"; }

is_root() { [[ ${EUID:-$(id -u)} -eq 0 ]]; }

detect_env() {
    CHECKMK_LOCAL_DIR="/usr/lib/check_mk_agent/local"
    CHECKMK_SPOOL_DIR="/usr/lib/check_mk_agent/spool"
    CHECKMK_PLUGIN_DIR="/usr/lib/check_mk_agent/plugins"
    CHECKMK_NOTIFICATION_DIR=""
    CACHE_DIR="/var/cache/checkmk-scripts"
    ENV_TYPE="Agent"

    if [[ -d "/omd/sites" ]]; then
        # Prendi il primo sito se presente, altrimenti usa default
        local site
        site="$(ls -1 /omd/sites 2>/dev/null | head -n1 || true)"
        site="${site:-monitoring}"
        OMD_ROOT="/omd/sites/$site"
        CHECKMK_NOTIFICATION_DIR="$OMD_ROOT/local/share/check_mk/notifications"
        CACHE_DIR="$OMD_ROOT/var/cache/checkmk-scripts"
        ENV_TYPE="OMD"
    fi
}

download_to() {
    # download_to URL OUTFILE TIMEOUT_SECONDS
    local url="$1" out="$2" timeout_s="$3"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL --max-time "$timeout_s" "$url" -o "$out"
        return 0
    fi
    if command -v wget >/dev/null 2>&1; then
        wget -q --timeout="$timeout_s" -O "$out" "$url"
        return 0
    fi
    return 1
}

write_wrapper() {
    # write_wrapper NAME GITHUB_PATH TYPE TARGET_DIR
    local name="$1" github_path="$2" script_type="$3" target_dir="$4"
    local wrapper_file="$target_dir/$name"
    local github_url="$BASE_URL/$github_path"

    mkdir -p "$target_dir" 2>/dev/null || true

    # Wrapper: nessun output su stdout se non quello dello script vero.
    cat > "$wrapper_file" <<EOF
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_NAME="$name"
SCRIPT_TYPE="$script_type"
GITHUB_URL="$github_url"

CACHE_DIR="${CACHE_DIR}"
CACHE_FILE="\$CACHE_DIR/\$SCRIPT_NAME.sh"

TIMEOUT_SECONDS=8
EXEC_TIMEOUT_SECONDS=30
DEBUG="\${DEBUG:-0}"

dbg() {
    if [[ "\$DEBUG" == "1" ]]; then
        echo "[wrapper \$SCRIPT_NAME] \$*" >&2
    fi
}

download_to() {
    local url="\$1" out="\$2" timeout_s="\$3"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL --max-time "\$timeout_s" "\$url" -o "\$out"
        return 0
    fi
    if command -v wget >/dev/null 2>&1; then
        wget -q --timeout="\$timeout_s" -O "\$out" "\$url"
        return 0
    fi
    return 1
}

maybe_update() {
    mkdir -p "\$CACHE_DIR" 2>/dev/null || true

    local tmp="\$CACHE_FILE.tmp"
    if download_to "\$GITHUB_URL" "\$tmp" "\$TIMEOUT_SECONDS" 2>/dev/null; then
        # sanity check: deve essere uno script con shebang
        if head -n1 "\$tmp" | grep -qE '^#!'; then
            mv -f "\$tmp" "\$CACHE_FILE"
            chmod +x "\$CACHE_FILE" 2>/dev/null || true
            dbg "updated cache"
            return 0
        fi
        rm -f "\$tmp" 2>/dev/null || true
    fi
    rm -f "\$tmp" 2>/dev/null || true
    return 1
}

exec_cached() {
    if [[ -x "\$CACHE_FILE" ]]; then
        if command -v timeout >/dev/null 2>&1; then
            timeout "\$EXEC_TIMEOUT_SECONDS" "\$CACHE_FILE" "\$@"
        else
            "\$CACHE_FILE" "\$@"
        fi
        return 0
    fi
    return 1
}

main() {
    maybe_update >/dev/null 2>&1 || true

    if exec_cached "\$@"; then
        exit 0
    fi

    # Per local checks: stampa una riga CRITICAL se non c'e' nulla da eseguire.
    if [[ "\$SCRIPT_TYPE" == "local" ]]; then
        echo "2 \$SCRIPT_NAME - CRITICAL: no cached script (download failed)"
        exit 2
    fi

    exit 1
}

main "\$@"
EOF

    chmod +x "$wrapper_file"
}

main() {
    detect_env

    if ! is_root; then
        die "eseguire come root (sudo)"
    fi

    # Servono almeno curl o wget sul nodo target.
    if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
        die "serve curl o wget per scaricare da GitHub"
    fi

    if [[ ! -d "/usr/lib/check_mk_agent" ]]; then
        warn "Directory /usr/lib/check_mk_agent non trovata: continuo, ma i path potrebbero non esistere"
    fi

    mkdir -p "$CACHE_DIR" 2>/dev/null || true

    log "Environment: $ENV_TYPE"
    log "Cache dir:   $CACHE_DIR"

    # name => "path:type"
    declare -A SCRIPTS=()
    SCRIPTS["check_cockpit_sessions"]="script-check-ns7/check_cockpit_sessions.sh:local"
    SCRIPTS["check_dovecot_status"]="script-check-ns7/check_dovecot_status.sh:local"
    SCRIPTS["check_ssh_root_sessions"]="script-check-ns7/check_ssh_root_sessions.sh:local"
    SCRIPTS["check_postfix_status"]="script-check-ns7/check_postfix_status.sh:local"
    SCRIPTS["telegram_realip"]="script-notify-checkmk/telegram_realip:notification"

    local deployed=0
    for name in "${!SCRIPTS[@]}"; do
        IFS=':' read -r github_path script_type <<< "${SCRIPTS[$name]}"
        url="$BASE_URL/$github_path"

        target_dir="$CHECKMK_LOCAL_DIR"
        case "$script_type" in
            local) target_dir="$CHECKMK_LOCAL_DIR" ;;
            spool) target_dir="$CHECKMK_SPOOL_DIR" ;;
            plugin) target_dir="$CHECKMK_PLUGIN_DIR" ;;
            notification)
                if [[ -z "${CHECKMK_NOTIFICATION_DIR}" ]]; then
                    warn "skip $name (notification): non-OMD environment"
                    continue
                fi
                target_dir="$CHECKMK_NOTIFICATION_DIR"
                ;;
            *) target_dir="$CHECKMK_LOCAL_DIR" ;;
        esac

        log "Deploy: $name ($script_type) -> $target_dir"

        # Popola cache iniziale (best effort)
        cache_file="$CACHE_DIR/$name.sh"
        tmp="$cache_file.tmp"
        if download_to "$url" "$tmp" 12 2>/dev/null; then
            if head -n1 "$tmp" | grep -qE '^#!'; then
                mv -f "$tmp" "$cache_file"
                chmod +x "$cache_file" 2>/dev/null || true
            else
                rm -f "$tmp" 2>/dev/null || true
                warn "download ok ma contenuto non valido: $name"
            fi
        else
            rm -f "$tmp" 2>/dev/null || true
            warn "download fallito (continua): $name"
        fi

        write_wrapper "$name" "$github_path" "$script_type" "$target_dir"
        deployed=$((deployed + 1))
    done

    log "Wrapper creati: $deployed"
}

main "$@"
