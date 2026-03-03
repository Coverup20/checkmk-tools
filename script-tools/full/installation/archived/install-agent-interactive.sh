#!/usr/bin/env bash
set -euo pipefail

# install-agent-interactive.sh
# Installazione interattiva Checkmk Agent (plain TCP 6556) + FRPC (opzionale).
# Output semplice (ASCII-only), senza cornici.

CHECKMK_BASE_URL="${CHECKMK_BASE_URL:-https://monitoring.nethlab.it/monitoring/check_mk/agents}"
FRP_VERSION="${FRP_VERSION:-0.64.0}"

MODE="install"
PKG_TYPE=""       # deb|rpm|openwrt
PKG_MANAGER=""    # apt|dnf|yum|opkg
OS_ID=""
OS_VER=""

log() { echo "[INFO] $*"; }
warn() { echo "[WARN] $*"; }
err() { echo "[ERR] $*" >&2; }
die() { err "$*"; exit 1; }

need_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "comando mancante: $1"
}

require_root() {
    [[ ${EUID:-$(id -u)} -eq 0 ]] || die "eseguire come root (sudo)"
}

download_to() {
    # download_to URL OUTFILE
    local url="$1" out="$2"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$url" -o "$out"
        return 0
    fi
    need_cmd wget
    wget -qO "$out" "$url"
}

detect_os() {
    # OpenWrt / NethSecurity 8 (procd)
    if [[ -f /etc/openwrt_release ]] || { [[ -r /etc/os-release ]] && grep -qi openwrt /etc/os-release; }; then
        OS_ID="openwrt"
        OS_VER=""
        if [[ -r /etc/openwrt_release ]]; then
            OS_VER="$(grep -E '^DISTRIB_RELEASE=' /etc/openwrt_release 2>/dev/null | cut -d"'" -f2 || true)"
        fi
        PKG_TYPE="openwrt"
        PKG_MANAGER="opkg"
        log "Sistema rilevato: ${OS_ID}${OS_VER:+ $OS_VER}"
        return 0
    fi

    if [[ -r /etc/os-release ]]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        OS_ID="${ID:-}"
        OS_VER="${VERSION_ID:-}"
    else
        OS_ID="$(uname -s | tr '[:upper:]' '[:lower:]')"
        OS_VER="$(uname -r)"
    fi

    # NethServer marker
    if [[ -f /etc/nethserver-release ]]; then
        OS_ID="nethserver"
    fi

    case "$OS_ID" in
        debian|ubuntu)
            PKG_TYPE="deb"
            PKG_MANAGER="apt"
            ;;
        rocky|rhel|centos|almalinux|fedora|nethserver|nethserver-enterprise)
            PKG_TYPE="rpm"
            if command -v dnf >/dev/null 2>&1; then
                PKG_MANAGER="dnf"
            else
                PKG_MANAGER="yum"
            fi
            ;;
        *)
            die "sistema operativo non supportato: ${OS_ID:-?}"
            ;;
    esac

    log "Sistema rilevato: ${OS_ID}${OS_VER:+ $OS_VER} ($PKG_TYPE)"
}

pkg_update() {
    case "$PKG_MANAGER" in
        apt) apt-get update -y ;;
        dnf) dnf -y makecache ;;
        yum) yum -y makecache ;;
        opkg) opkg update ;;
        *) return 0 ;;
    esac
}

pkg_install() {
    case "$PKG_MANAGER" in
        apt) apt-get install -y "$@" ;;
        dnf) dnf install -y "$@" ;;
        yum) yum install -y "$@" ;;
        opkg) opkg install "$@" ;;
        *) die "package manager non supportato: $PKG_MANAGER" ;;
    esac
}

latest_agent_filename() {
    # Output: filename (deb or rpm) from CHECKMK_BASE_URL listing
    local html
    html="$(curl -fsSL "$CHECKMK_BASE_URL/" 2>/dev/null || wget -qO- "$CHECKMK_BASE_URL/" 2>/dev/null || true)"
    [[ -n "$html" ]] || die "impossibile leggere listing: $CHECKMK_BASE_URL/"

    if [[ "$PKG_TYPE" == "deb" ]]; then
        printf '%s' "$html" | grep -oE 'check-mk-agent_[0-9.]+p[0-9]+-[0-9]+_all\.deb' | sort -V | tail -n1
        return 0
    fi

    if [[ "$PKG_TYPE" == "rpm" ]]; then
        printf '%s' "$html" | grep -oE 'check-mk-agent-[0-9.]+p[0-9]+-[0-9]+\.noarch\.rpm' | sort -V | tail -n1
        return 0
    fi

    return 1
}

install_checkmk_agent_linux() {
    local fname url tmp
    fname="$(latest_agent_filename)"
    [[ -n "$fname" ]] || die "impossibile determinare ultima versione agente"

    url="$CHECKMK_BASE_URL/$fname"
    tmp="/tmp/$fname"
    log "Download agente: $url"
    download_to "$url" "$tmp"

    log "Installazione pacchetto agente: $fname"
    if [[ "$PKG_TYPE" == "deb" ]]; then
        need_cmd dpkg
        dpkg -i "$tmp" || apt-get install -f -y
    else
        if command -v rpm >/dev/null 2>&1; then
            rpm -Uvh --replacepkgs "$tmp"
        else
            die "rpm non trovato"
        fi
    fi

    rm -f "$tmp" || true
    command -v /usr/bin/check_mk_agent >/dev/null 2>&1 || warn "check_mk_agent non trovato nel PATH (verifica installazione)"
}

install_checkmk_agent_openwrt() {
    # Su OpenWrt l'agente viene estratto dal .deb (serve ar+tar)
    need_cmd opkg
    pkg_update
    pkg_install ca-certificates wget tar gzip socat binutils 2>/dev/null || true
    need_cmd ar
    need_cmd tar

    local fname url tmpdir deb data_tar
    fname="$(latest_agent_filename)"
    [[ -n "$fname" ]] || die "impossibile determinare ultima versione agente"

    url="$CHECKMK_BASE_URL/$fname"
    tmpdir="$(mktemp -d)"
    deb="$tmpdir/$fname"

    log "Download agente (deb): $url"
    download_to "$url" "$deb"

    (cd "$tmpdir"; ar x "$deb")
    data_tar="$(ls "$tmpdir"/data.tar.* 2>/dev/null | head -n1 || true)"
    [[ -n "$data_tar" ]] || die "data.tar.* non trovato nel deb"
    tar -xf "$data_tar" -C "$tmpdir"

    if [[ -f "$tmpdir/usr/bin/check_mk_agent" ]]; then
        install -m 0755 "$tmpdir/usr/bin/check_mk_agent" /usr/bin/check_mk_agent
    elif [[ -f "$tmpdir/usr/bin/check-mk-agent" ]]; then
        install -m 0755 "$tmpdir/usr/bin/check-mk-agent" /usr/bin/check_mk_agent
    else
        die "binario agente non trovato nel deb"
    fi

    rm -rf "$tmpdir" || true
}

install_checkmk_agent() {
    if [[ "$PKG_TYPE" == "openwrt" ]]; then
        install_checkmk_agent_openwrt
    else
        pkg_update || true
        pkg_install ca-certificates curl wget 2>/dev/null || true
        install_checkmk_agent_linux
    fi
}

configure_plain_agent_openwrt() {
    need_cmd socat
    need_cmd /usr/bin/check_mk_agent

    cat >/etc/init.d/check_mk_agent <<'EOF'
#!/bin/sh /etc/rc.common
START=98
STOP=10
USE_PROCD=1

PROG=/usr/bin/check_mk_agent

start_service() {
    procd_open_instance
    procd_set_param command socat TCP-LISTEN:6556,reuseaddr,fork,keepalive EXEC:$PROG
    procd_set_param respawn
    procd_set_param stdout 1
    procd_set_param stderr 1
    procd_close_instance
}

stop_service() {
    killall socat >/dev/null 2>&1 || true
}
EOF

    chmod +x /etc/init.d/check_mk_agent
    /etc/init.d/check_mk_agent enable >/dev/null 2>&1 || true
    /etc/init.d/check_mk_agent restart
}

configure_plain_agent_systemd() {
    need_cmd systemctl

    systemctl stop check-mk-agent.socket cmk-agent-ctl-daemon.service 2>/dev/null || true
    systemctl disable check-mk-agent.socket cmk-agent-ctl-daemon.service 2>/dev/null || true

    cat >/etc/systemd/system/check-mk-agent-plain.socket <<'EOF'
[Unit]
Description=Checkmk Agent (TCP 6556 plain)
Documentation=https://docs.checkmk.com/

[Socket]
ListenStream=6556
Accept=yes

[Install]
WantedBy=sockets.target
EOF

    cat >/etc/systemd/system/check-mk-agent-plain@.service <<'EOF'
[Unit]
Description=Checkmk Agent (TCP 6556 plain) connection

[Service]
ExecStart=-/usr/bin/check_mk_agent
StandardInput=socket
EOF

    systemctl daemon-reload
    systemctl enable --now check-mk-agent-plain.socket
}

configure_plain_agent() {
    if [[ "$PKG_TYPE" == "openwrt" ]]; then
        configure_plain_agent_openwrt
    else
        configure_plain_agent_systemd
    fi
}

install_frpc() {
    local arch="amd64"
    case "$(uname -m)" in
        x86_64) arch="amd64";;
        aarch64|arm64) arch="arm64";;
    esac

    local url="https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/frp_${FRP_VERSION}_linux_${arch}.tar.gz"
    local tmpdir
    tmpdir=$(mktemp -d)

    log "Download FRPC: $url"
    if command -v curl >/dev/null 2>&1; then
        curl -fL "$url" -o "$tmpdir/frp.tgz"
    else
        need_cmd wget
        wget -O "$tmpdir/frp.tgz" "$url"
    fi

    tar -xzf "$tmpdir/frp.tgz" -C "$tmpdir"
    local bin
    bin=$(find "$tmpdir" -type f -name frpc -print -quit)
    [[ -n "$bin" ]] || die "frpc non trovato nell'archivio"
    install -m 0755 "$bin" /usr/local/bin/frpc
    rm -rf "$tmpdir"

    log "FRPC installato in /usr/local/bin/frpc"
}

configure_frpc() {
    local current_hostname
    current_hostname=$(hostname 2>/dev/null || echo "host")

    echo
    log "Configurazione FRPC"
    read -r -p "Nome host [default: $current_hostname]: " FRPC_HOSTNAME
    FRPC_HOSTNAME=${FRPC_HOSTNAME:-$current_hostname}

    read -r -p "Server FRP remoto [default: monitor.nethlab.it]: " FRP_SERVER
    FRP_SERVER=${FRP_SERVER:-monitor.nethlab.it}

    while true; do
        read -r -p "Porta remota (es: 20001): " REMOTE_PORT
        [[ "$REMOTE_PORT" =~ ^[0-9]+$ ]] && break
        err "Porta remota obbligatoria (numero)"
    done

    while true; do
        read -r -p "Token FRP (obbligatorio): " AUTH_TOKEN
        [[ -n "$AUTH_TOKEN" ]] && break
        err "Token obbligatorio per autenticazione FRP"
    done

    mkdir -p /etc/frp
    cat >/etc/frp/frpc.toml <<EOF
[common]
server_addr = "$FRP_SERVER"
server_port = 7000
auth.method = "token"
auth.token  = "$AUTH_TOKEN"
tls.enable  = true
log.to      = "/var/log/frpc.log"
log.level   = "debug"

[$FRPC_HOSTNAME]
type        = "tcp"
local_ip    = "127.0.0.1"
local_port  = 6556
remote_port = $REMOTE_PORT
EOF

    if [[ "$PKG_TYPE" == "openwrt" ]]; then
        cat >/etc/init.d/frpc <<'EOF'
#!/bin/sh /etc/rc.common
START=99
STOP=10
USE_PROCD=1

start_service() {
    procd_open_instance
    procd_set_param command /usr/local/bin/frpc -c /etc/frp/frpc.toml
    procd_set_param respawn
    procd_close_instance
}

stop_service() {
    killall frpc >/dev/null 2>&1 || true
}
EOF
        chmod +x /etc/init.d/frpc
        /etc/init.d/frpc enable >/dev/null 2>&1 || true
        /etc/init.d/frpc restart
    else
        cat >/etc/systemd/system/frpc.service <<'EOF'
[Unit]
Description=FRP Client Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/frpc -c /etc/frp/frpc.toml
Restart=on-failure
RestartSec=5s
User=root

[Install]
WantedBy=multi-user.target
EOF
        systemctl daemon-reload
        systemctl enable --now frpc
    fi

    log "FRPC configurato: $FRP_SERVER:$REMOTE_PORT -> localhost:6556"
}

uninstall_frpc() {
    log "Rimozione FRPC"
    if [[ "$PKG_TYPE" == "openwrt" ]]; then
        /etc/init.d/frpc stop >/dev/null 2>&1 || true
        /etc/init.d/frpc disable >/dev/null 2>&1 || true
        rm -f /etc/init.d/frpc
    else
        systemctl stop frpc 2>/dev/null || true
        systemctl disable frpc 2>/dev/null || true
        rm -f /etc/systemd/system/frpc.service
        systemctl daemon-reload 2>/dev/null || true
    fi
    rm -f /usr/local/bin/frpc
    rm -rf /etc/frp
}


uninstall_agent() {
    log "Rimozione agente"
    if [[ "$PKG_TYPE" == "openwrt" ]]; then
        /etc/init.d/check_mk_agent stop >/dev/null 2>&1 || true
        /etc/init.d/check_mk_agent disable >/dev/null 2>&1 || true
        rm -f /etc/init.d/check_mk_agent
        rm -f /usr/bin/check_mk_agent
        rm -rf /etc/check_mk
        return 0
    fi

    systemctl stop check-mk-agent-plain.socket 2>/dev/null || true
    systemctl disable check-mk-agent-plain.socket 2>/dev/null || true
    rm -f /etc/systemd/system/check-mk-agent-plain.socket /etc/systemd/system/check-mk-agent-plain@.service
    systemctl daemon-reload 2>/dev/null || true

    if [[ "$PKG_TYPE" == "deb" ]]; then
        dpkg -r check-mk-agent 2>/dev/null || true
    elif [[ "$PKG_TYPE" == "rpm" ]]; then
        rpm -e check-mk-agent 2>/dev/null || true
    fi

    rm -f /usr/bin/check_mk_agent
    rm -rf /etc/check_mk
}

show_usage() {
    cat <<EOF
Uso: sudo $0 [--help] [--uninstall-frpc|--uninstall-agent|--uninstall]

Env:
  CHECKMK_BASE_URL  (default: $CHECKMK_BASE_URL)
  FRP_VERSION       (default: $FRP_VERSION)
EOF
}

parse_args() {
    case "${1:-}" in
        --help|-h) MODE="help" ;;
        --uninstall-frpc) MODE="uninstall-frpc" ;;
        --uninstall-agent) MODE="uninstall-agent" ;;
        --uninstall) MODE="uninstall-all" ;;
        "") MODE="install" ;;
        *) MODE="help" ;;
    esac
}

main() {
    parse_args "${1:-}"
    if [[ "$MODE" == "help" ]]; then
        show_usage
        exit 0
    fi

    require_root
    detect_os

    case "$MODE" in
        uninstall-frpc)
            uninstall_frpc
            exit 0
            ;;
        uninstall-agent)
            uninstall_agent
            exit 0
            ;;
        uninstall-all)
            uninstall_frpc
            uninstall_agent
            exit 0
            ;;
    esac

    echo
    log "Questa installazione configurera':"
    echo "- Checkmk Agent plain TCP (porta 6556)"
    if [[ "$PKG_TYPE" == "openwrt" ]]; then
        echo "- Listener: socat (init.d/procd)"
    else
        echo "- Socket systemd: check-mk-agent-plain.socket"
    fi
    echo
    read -r -p "Procedi con l'installazione? [s/N]: " CONFIRM
    [[ "$CONFIRM" =~ ^[sS]$ ]] || exit 0

    install_checkmk_agent
    configure_plain_agent

    echo
    read -r -p "Vuoi installare anche FRPC? [s/N]: " INSTALL_FRPC
    if [[ "$INSTALL_FRPC" =~ ^[sS]$ ]]; then
        install_frpc
        configure_frpc
    fi

    echo
    log "Completato"
}

main "$@"
