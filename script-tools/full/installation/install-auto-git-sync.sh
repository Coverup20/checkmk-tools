#!/bin/bash
# ==========================================================
#  Installazione Auto Git Sync Service
#  Installa e configura il servizio di sync automatico
#  Autore: ChatGPT per Marzio Bordin
# ==========================================================
VERSION="1.0.4"   # Versione script (aggiornare ad ogni modifica)

set -e

# Avoid getcwd/job-working-directory warnings if the current directory is removed
# (e.g., repo being recloned while this installer runs).
cd / 2>/dev/null || true

detect_os() {
    OS_ID="unknown"
    OS_LIKE=""
    OS_VERSION_ID=""
    if [[ -r /etc/os-release ]]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        OS_ID="${ID:-unknown}"
        OS_LIKE="${ID_LIKE:-}"
        OS_VERSION_ID="${VERSION_ID:-}"
    fi
    export OS_ID OS_LIKE OS_VERSION_ID
}

is_openwrt() {
    [[ -f /etc/openwrt_release ]] && return 0 || return 1
}

# OpenWrt repo per download dinamico pacchetti
REPO_PACKAGES="${REPO_PACKAGES:-https://downloads.openwrt.org/releases/23.05.0/packages/x86_64/packages}"

# Download dinamico pacchetto da repo OpenWrt (come install-checkmk-agent-persistent-nsec8.sh)
download_openwrt_package() {
    local package_name="$1"
    local repo_url="$2"
    local output_file="$3"
    echo "i  Download dinamico: $package_name"
    if ! wget -q -O /tmp/Packages.gz "${repo_url}/Packages.gz"; then
        echo "WARN  Download Packages.gz fallito"
        return 1
    fi
    local package_file
    package_file=$(gunzip -c /tmp/Packages.gz | grep "^Filename:" | grep "${package_name}_" | head -1 | awk '{print $2}')
    rm -f /tmp/Packages.gz
    if [ -z "$package_file" ]; then
        echo "WARN  $package_name non trovato nell'index OpenWrt"
        return 1
    fi
    if wget -O "$output_file" "${repo_url}/${package_file}" 2>/dev/null; then
        return 0
    else
        echo "WARN  Download fallito: ${repo_url}/${package_file}"
        return 1
    fi
}

pick_pkg_manager() {
    PKG_MGR=""
    if command -v apt-get >/dev/null 2>&1; then
        PKG_MGR="apt"
    elif command -v dnf >/dev/null 2>&1; then
        PKG_MGR="dnf"
    elif command -v yum >/dev/null 2>&1; then
        PKG_MGR="yum"
    elif command -v opkg >/dev/null 2>&1; then
        PKG_MGR="opkg"
    fi
    export PKG_MGR
}

pkg_update() {
    case "${PKG_MGR:-}" in
        apt) timeout 300 apt-get update -qq || true ;;
        yum) timeout 300 yum -y makecache fast || timeout 300 yum -y makecache || true ;;
        dnf) timeout 300 dnf -y makecache || true ;;
        *) return 1 ;;
    esac
}

pkg_install_git() {
    case "${PKG_MGR:-}" in
        apt)
            pkg_update
            timeout 300 apt-get install -y git
            ;;
        yum)
            pkg_update
            timeout 300 yum install -y git
            ;;
        dnf)
            pkg_update
            timeout 300 dnf install -y git
            ;;
        opkg)
            if download_openwrt_package "git" "$REPO_PACKAGES" "/tmp/git.ipk"; then
                if download_openwrt_package "git-http" "$REPO_PACKAGES" "/tmp/git-http.ipk"; then
                    opkg install /tmp/git.ipk /tmp/git-http.ipk
                    rm -f /tmp/git.ipk /tmp/git-http.ipk
                else
                    rm -f /tmp/git.ipk
                    echo " Download git-http fallito"
                    return 1
                fi
            else
                echo " Download git fallito"
                return 1
            fi
            ;;
        *)
            echo " Package manager non supportato. Installa git manualmente."
            return 1
            ;;
    esac
}

pkg_upgrade_git() {
    case "${PKG_MGR:-}" in
        apt)
            pkg_update
            timeout 300 apt-get install -y git || true
            ;;
        yum)
            pkg_update
            # On CentOS/RHEL 7 this may still keep git 1.8.x unless extra repos are enabled.
            timeout 300 yum -y update git || timeout 300 yum -y install git || true
            ;;
        dnf)
            pkg_update
            timeout 300 dnf -y upgrade git || timeout 300 dnf -y install git || true
            ;;
        *)
            echo "WARN  Package manager non supportato per upgrade automatico."
            ;;
    esac
}

detect_os
pick_pkg_manager

echo "i  OS rilevato: ${OS_ID}${OS_VERSION_ID:+ $OS_VERSION_ID}${OS_LIKE:+ (like: $OS_LIKE)}"
if [[ -n "${PKG_MGR:-}" ]]; then
    echo "i  Package manager: ${PKG_MGR}"
fi

# Funzione per installare git
install_git() {
    echo "i  Git non trovato, installazione in corso..."
    if ! pkg_install_git; then
        echo " Errore durante installazione git"
        exit 1
    fi
    echo "OK Git installato"
}

# Verifica se git e installato
if ! command -v git &> /dev/null; then
    install_git
fi

get_git_version() {
    # Example: "git version 1.8.3.1" -> "1.8.3.1"
    git --version 2>/dev/null | awk '{print $3}'
}

maybe_upgrade_git() {
    local ver major minor
    ver="$(get_git_version)"
    if [[ -z "${ver:-}" ]]; then
        return 0
    fi
    major="${ver%%.*}"
    local rest
    rest="${ver#*.}"
    minor="${rest%%.*}"
    major="${major:-0}"
    minor="${minor:-0}"

    # Git < 2.x is very old; offer an upgrade (best-effort).
    if [[ "$major" =~ ^[0-9]+$ ]] && [[ "$major" -lt 2 ]]; then
        echo "WARN  Git rilevato: $ver (molto vecchio)"
        echo "   Posso provare ad aggiornarlo (best-effort) tramite il package manager."
        read -r -p "Vuoi provare ad aggiornare Git ora? [s/N]: " upgrade_choice
        upgrade_choice="${upgrade_choice//$'\r'/}"
        if [[ "$upgrade_choice" =~ ^[SsYy]$ ]]; then
            echo "i  Tentativo aggiornamento Git..."
			pkg_upgrade_git

            local new_ver
            new_ver="$(get_git_version)"
            if [[ -n "${new_ver:-}" ]]; then
                echo "i  Git versione attuale: $new_ver"
            fi
        else
            echo "i  Upgrade Git saltato."
        fi
    fi
}

maybe_upgrade_git

# Cerca il repository checkmk-tools
# Priorita: /opt, poi /root, poi $HOME
if [[ -d "/opt/checkmk-tools/.git" ]]; then
    REPO_DIR="/opt/checkmk-tools"
elif [[ -d "/root/checkmk-tools/.git" ]]; then
    REPO_DIR="/root/checkmk-tools"
elif [[ -d "$HOME/checkmk-tools/.git" ]]; then
    REPO_DIR="$HOME/checkmk-tools"
else     echo " Repository checkmk-tools non trovato"
    echo "   Posizioni cercate:"
    echo "   - /opt/checkmk-tools (consigliato)"
    echo "   - /root/checkmk-tools"
    echo "   - $HOME/checkmk-tools"
    echo ""
    echo "i  Se vuoi clonare il repository in /opt/checkmk-tools:"
    echo "   cd /opt && git clone https://github.com/Coverup20/checkmk-tools.git"
    echo ""
    read -r -p "Inserisci il path del repository [/opt/checkmk-tools]: " REPO_DIR
    REPO_DIR="${REPO_DIR:-/opt/checkmk-tools}"
    
    # Se non esiste, offre di clonarlo
    if [[ ! -d "$REPO_DIR/.git" ]]; then
        read -r -p "Repository non trovato. Vuoi clonarlo in $REPO_DIR? [S/n]: " clone_choice
        if [[ "$clone_choice" =~ ^[Nn] ]]; then
    echo " Installazione annullata"
    exit 1
        fi
        
        # Crea directory parent se non esiste
        PARENT_DIR=$(dirname "$REPO_DIR")
        mkdir -p "$PARENT_DIR"
        
        echo " Clonazione repository in $REPO_DIR..."
        if ! timeout 120 git clone https://github.com/Coverup20/checkmk-tools.git "$REPO_DIR" 2>&1; then
    echo " Errore durante la clonazione (timeout o errore rete)"
    exit 1
        fi
        
        # Verifica che il clone sia riuscito
        if [[ ! -d "$REPO_DIR/.git" ]]; then
    echo " Repository clonato ma .git non trovato"
    exit 1
        fi
echo "OK Repository clonato con successo"
    fi
fi
echo "========================================="
echo "  Installazione Auto Git Sync Service"
echo "  Version v${VERSION}"
echo "========================================="
echo ""

# Verifica esecuzione come root
if [[ $EUID -ne 0 ]]; then
    echo " Questo script deve essere eseguito come root"
    echo "   Usa: sudo bash install-auto-git-sync.sh"
    exit 1
fi
echo "OK Esecuzione come root"

# Chiedi intervallo di sync
echo ""
echo "  Configurazione intervallo di sync"
echo ""
echo "Scegli ogni quanto eseguire il git pull:"
echo "  1) Ogni 30 secondi"
echo "  2) Ogni 1 minuto (consigliato)"
echo "  3) Ogni 5 minuti"
echo "  4) Ogni 10 minuti"
echo "  5) Ogni 30 minuti"
echo "  6) Personalizzato"
echo ""
read -r -p "Scelta [2]: " interval_choice

# Normalize common terminal artifacts (spaces, tabs, CRLF).
interval_choice="${interval_choice//$'\r'/}"
interval_choice="${interval_choice//$'\n'/}"
interval_choice="${interval_choice//$'\t'/}"
interval_choice="${interval_choice// /}"

case "$interval_choice" in
    1) SYNC_INTERVAL=30 ;;
    2|"") SYNC_INTERVAL=60 ;;
    3) SYNC_INTERVAL=300 ;;
    4) SYNC_INTERVAL=600 ;;
    5) SYNC_INTERVAL=1800 ;;
    6)
        read -r -p "Inserisci intervallo in secondi (10-3600): " SYNC_INTERVAL
        if ! [[ "$SYNC_INTERVAL" =~ ^[0-9]+$ ]] || [ "$SYNC_INTERVAL" -lt 10 ] || [ "$SYNC_INTERVAL" -gt 3600 ]; then
    echo " Valore non vali
do (deve essere tra 10 e 3600), uso default 60 secondi"
            SYNC_INTERVAL=60
        fi
        ;;
    *)
        echo " Scelta non valida, uso default 60 secondi"
        SYNC_INTERVAL=60
        ;;
esac

echo "OK Intervallo impostato: $SYNC_INTERVAL secondi"
echo ""

# Rileva l'utente proprietario del repository
REPO_OWNER=$(stat -c '%U' "$REPO_DIR" 2>/dev/null || echo "root")
REPO_OWNER_HOME=$(eval echo "~$REPO_OWNER" 2>/dev/null || echo "/root")

echo "i  Repository owner: $REPO_OWNER"
echo "i  Repository path: $REPO_DIR"
echo "i  Home directory: $REPO_OWNER_HOME"
echo ""

# Il servizio esegue direttamente da GitHub, non serve controllare il file locale
echo "i  Il servizio eseguira lo script direttamente da GitHub"

# Crea directory log se non esiste
if ! mkdir -p /var/log 2>/dev/null; then
    echo "WARN  Impossibile creare directory /var/log (gia esistente)"
fi

if touch /var/log/auto-git-sync.log 2>/dev/null; then
    chown "$REPO_OWNER:$REPO_OWNER" /var/log/auto-git-sync.log 2>/dev/null || echo "WARN  Impossibile cambiare owner del log file"
    echo "OK Log file preparato"
else     echo "WARN  Impossibile creare log file, verra usato journalctl"
fi

# ===================================================================
# OpenWrt / NethSecurity: usa cron invece di systemd
# ===================================================================
if is_openwrt || ! command -v systemctl &>/dev/null; then
    CRON_FILE="/etc/crontabs/root"
    SYNC_SCRIPT="/usr/local/bin/git-auto-sync.sh"

    mkdir -p /usr/local/bin
    cat > "$SYNC_SCRIPT" <<'SYNCSCRIPT'
#!/bin/sh
REPO_DIR="/opt/checkmk-tools"
LOG_FILE="/var/log/auto-git-sync.log"
MAX_LOG_SIZE=1048576
if [ -f "$LOG_FILE" ] && [ "$(stat -c%s "$LOG_FILE" 2>/dev/null || echo 0)" -gt "$MAX_LOG_SIZE" ]; then
    mv "$LOG_FILE" "$LOG_FILE.old" 2>/dev/null || true
fi
[ -d "$REPO_DIR/.git" ] || exit 1
cd "$REPO_DIR" || exit 1
if git pull origin main >> "$LOG_FILE" 2>&1; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Sync OK" >> "$LOG_FILE"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Git pull failed" >> "$LOG_FILE"
fi
SYNCSCRIPT

    chmod +x "$SYNC_SCRIPT"
    # Rimuovi eventuale entry precedente
    [ -f "$CRON_FILE" ] && sed -i '/git-auto-sync/d' "$CRON_FILE" 2>/dev/null || true
    echo "* * * * * $SYNC_SCRIPT" >> "$CRON_FILE"
    /etc/init.d/cron restart >/dev/null 2>&1 || true
    echo "OK Auto Git Sync installato via cron (OpenWrt/NethSecurity)"
    echo "   Script: $SYNC_SCRIPT"
    echo "   Cron:   $CRON_FILE"
    echo "   Log:    /var/log/auto-git-sync.log"
    echo ""
    echo "Verifica con: crontab -l"
    exit 0
fi

# Crea service file personalizzato che esegue direttamente da GitHub
echo "i  Creazione service file personalizzato..."
cat > /etc/systemd/system/auto-git-sync.service << 'EOF'
[Unit]
Description=Auto Git Sync Service
Documentation=https://github.com/Coverup20/checkmk-tools
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=PLACEHOLDER_USER
Group=PLACEHOLDER_GROUP
WorkingDirectory=PLACEHOLDER_HOME
Environment="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="HOME=PLACEHOLDER_HOME"
ExecStart=/bin/bash -c 'set -euo pipefail; TEMP_SCRIPT=$(mktemp); cleanup(){ rm -f "$TEMP_SCRIPT" "$TEMP_SCRIPT.lf" 2>/dev/null || true; }; trap cleanup EXIT; curl -fsSL https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/full/sync_update/auto-git-sync.sh -o "$TEMP_SCRIPT"; if [[ ! -s "$TEMP_SCRIPT" ]]; then echo "auto-git-sync: download produced empty file" >&2; exit 1; fi; lf_count=$(LC_ALL=C tr -cd "\n" <"$TEMP_SCRIPT" | wc -c | tr -d " "); if [[ "${lf_count:-0}" == "0" ]]; then LC_ALL=C tr "\r" "\n" <"$TEMP_SCRIPT" >"$TEMP_SCRIPT.lf"; mv -f "$TEMP_SCRIPT.lf" "$TEMP_SCRIPT"; fi; sed -i "s/\r$//" "$TEMP_SCRIPT" 2>/dev/null || true; if ! bash -n "$TEMP_SCRIPT"; then echo "auto-git-sync: downloaded script is not valid bash" >&2; head -n 80 "$TEMP_SCRIPT" >&2 || true; exit 1; fi; bash "$TEMP_SCRIPT" PLACEHOLDER_INTERVAL'
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=auto-git-sync

# Security hardening - permetti scrittura in repo (include .git)
PrivateTmp=yes
NoNewPrivileges=yes

[Install]
WantedBy=multi-user.target
EOF

# Sostituisci placeholder con valori reali
sed -i "s|PLACEHOLDER_USER|$REPO_OWNER|g" /etc/systemd/system/auto-git-sync.service
sed -i "s|PLACEHOLDER_GROUP|$REPO_OWNER|g" /etc/systemd/system/auto-git-sync.service
sed -i "s|PLACEHOLDER_HOME|$REPO_OWNER_HOME|g" /etc/systemd/system/auto-git-sync.service
sed -i "s|PLACEHOLDER_REPO|$REPO_DIR|g" /etc/systemd/system/auto-git-sync.service
sed -i "s|PLACEHOLDER_INTERVAL|$SYNC_INTERVAL|g" /etc/systemd/system/auto-git-sync.service

echo "OK Service file creato e installato"

# Verifica che systemd sia disponibile
if ! command -v systemctl &> /dev/null; then
    echo " systemd non disponibile su questo sistema"
    echo "   Il servizio non puo essere installato"
    exit 1
fi

# Ricarica systemd
if ! systemctl daemon-reload 2>&1; then
    echo " Errore durante reload di systemd"
    exit 1
fi
echo "OK Systemd ricaricato"

# Abilita il servizio all'avvio
if ! systemctl enable auto-git-sync.service 2>&1; then
    echo " Errore durante abilitazione servizio"
    exit 1
fi
echo "OK Servizio abilitato all'avvio"

# Riavvia il servizio se gia attivo
if systemctl is-active --quiet auto-git-sync.service; then
    echo "i  Servizio gia attivo, riavvio in corso..."
    systemctl restart auto-git-sync.service
    echo "OK Servizio riavviato con nuova configurazione"
fi

# Mostra menu opzioni
echo ""
echo "========================================="
echo "  Installazione Completata!"
echo "========================================="
echo ""
echo " Configurazione:"
echo "   - Utente: $REPO_OWNER"
echo "   - Repository: $REPO_DIR"
echo "   - Intervallo sync: $SYNC_INTERVAL secondi"
echo ""
echo "Comandi disponibili:"
echo ""
echo "  - Avvia servizio:"
echo "    systemctl start auto-git-sync"
echo ""
echo "  - Ferma servizio:"
echo "    systemctl stop auto-git-sync"
echo ""
echo "  - Riavvia servizio:"
echo "    systemctl restart auto-git-sync"
echo ""
echo "  - Stato servizio:"
echo "    systemctl status auto-git-sync"
echo ""
echo "  - Log in tempo reale:"
echo "    journalctl -u auto-git-sync -f"
echo ""
echo "  - Log completo:"
echo "    tail -f /var/log/auto-git-sync.log"
echo ""
echo "  - Disabilita servizio:"
echo "    systemctl disable auto-git-sync"
echo ""

read -r -p "Vuoi avviare il servizio ora? (s/N): " start_now
if [[ "$start_now" =~ ^[sS]$ ]]; then
    systemctl start auto-git-sync
    echo ""
    echo "OK Servizio avviato!"
    echo ""
    sleep 2
    systemctl status auto-git-sync --no-pager
else     echo ""
    echo "i  Servizio non avviato. Usa 'systemctl start auto-git-sync' per avviarlo."
fi
echo ""
echo "========================================="
