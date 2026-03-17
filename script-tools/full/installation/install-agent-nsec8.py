#!/usr/bin/env python3
"""
install-agent-nsec8.py  —  CheckMK Agent Installer — ROCKSOLID Edition

Installa e configura CheckMK Agent su NethSecurity 8 / OpenWrt in modo
persistente e resistente ai major upgrade.

Funzionalità:
  - Installa prerequisiti (wget, socat, ar, tar, gzip)
  - Installa ns-checkmk-agent via opkg (con fallback a URL diretto)
  - Installa QEMU Guest Agent (rilevamento VM automatico)
  - Installa git, clona/aggiorna /opt/checkmk-tools
  - Deploya local checks da script-check-nsec8/full/
  - Configura cron auto-sync ogni minuto
  - Protegge installazione in sysupgrade.conf
  - Backup binari critici (tar/ar/gzip/libbfd)
  - Script di ripristino post-upgrade automatico
  - Autocheck all'avvio (rocksolid-startup-check.sh)

Uso:
  python3 install-agent-nsec8.py [--uninstall] [--help]

Variabili d'ambiente:
  CHECKMK_REPO_URL       Repository git (default: GitHub Coverup20)
  CHECKMK_REPO_DIR       Path clone locale (default: /opt/checkmk-tools)
  CHECKMK_AGENT_IPK_URL  URL diretto .ipk agente (fallback opkg)
  OPENWRT_REPO_BASE      Repository OpenWrt base per download dinamico
  OPENWRT_REPO_PACKAGES  Repository OpenWrt packages per download dinamico

Version: 2.0.0
"""

import gzip as _gzip
import io
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple

VERSION = "2.0.0"

# ---------------------------------------------------------------------------
# Costanti
# ---------------------------------------------------------------------------
REPO_URL = os.environ.get(
    "CHECKMK_REPO_URL", "https://github.com/Coverup20/checkmk-tools.git"
)
REPO_DIR = os.environ.get("CHECKMK_REPO_DIR", "/opt/checkmk-tools")
CHECKS_SRC = os.path.join(REPO_DIR, "script-check-nsec8", "full")
LOCAL_DIR = "/usr/lib/check_mk_agent/local"
SYSUPGRADE_CONF = "/etc/sysupgrade.conf"
CRON_FILE = "/etc/crontabs/root"
SYNC_SCRIPT = "/usr/local/bin/git-auto-sync.sh"
BACKUP_DIR = "/opt/checkmk-backups/binaries"
POST_UPGRADE_SCRIPT = "/etc/checkmk-post-upgrade.sh"
RC_LOCAL = "/etc/rc.local"
AUTOCHECK_SCRIPT = "/opt/checkmk-backups/rocksolid-startup-check.sh"
AUTOCHECK_URL = (
    "https://raw.githubusercontent.com/Coverup20/checkmk-tools/main"
    "/script-tools/full/upgrade_maintenance/rocksolid-startup-check.sh"
)

# URL diretto pacchetto agente (fallback se opkg non trova ns-checkmk-agent)
AGENT_IPK_URL = os.environ.get(
    "CHECKMK_AGENT_IPK_URL",
    "https://updates.nethsecurity.nethserver.org/checkmk_agent/"
    "8.7.1-checkmk_agent+b37c288d8/packages/x86_64/nethsecurity/"
    "ns-checkmk-agent_0.0.1-r1_all.ipk",
)

# Repository OpenWrt per download dinamico pacchetti
REPO_BASE = os.environ.get(
    "OPENWRT_REPO_BASE",
    "https://downloads.openwrt.org/releases/23.05.0/packages/x86_64/base",
)
REPO_PACKAGES = os.environ.get(
    "OPENWRT_REPO_PACKAGES",
    "https://downloads.openwrt.org/releases/23.05.0/packages/x86_64/packages",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def log(msg: str) -> None:
    print(f"[INFO] {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"[WARN] {msg}", flush=True)


def die(msg: str) -> None:
    print(f"[ERR]  {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


def run(cmd: List[str], check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    """Esegue un comando, stampa output in tempo reale se non capture."""
    if capture:
        return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    result = subprocess.run(cmd)
    if check and result.returncode != 0:
        die(f"Comando fallito (exit {result.returncode}): {' '.join(cmd)}")
    return result


def cmd_exists(name: str) -> bool:
    return shutil.which(name) is not None


def is_root() -> bool:
    return os.geteuid() == 0


# ---------------------------------------------------------------------------
# Download dinamico pacchetti OpenWrt
# ---------------------------------------------------------------------------


def download_openwrt_package(
    package_name: str, repo_url: str, output_file: str
) -> bool:
    """
    Scarica un pacchetto OpenWrt in modo dinamico dall'index Packages.gz.
    Evita URL statici fragili: trova il filename dalla lista aggiornata.
    """
    log(f"Download dinamico pacchetto: {package_name}")
    packages_url = f"{repo_url}/Packages.gz"

    try:
        with urllib.request.urlopen(packages_url, timeout=30) as resp:
            raw = resp.read()
    except Exception as exc:
        warn(f"Download Packages.gz fallito [{repo_url}]: {exc}")
        return False

    try:
        with _gzip.open(io.BytesIO(raw)) as fh:
            text = fh.read().decode("utf-8", errors="replace")
    except Exception as exc:
        warn(f"Decompressione Packages.gz fallita: {exc}")
        return False

    package_file: Optional[str] = None
    for line in text.splitlines():
        if line.startswith("Filename:") and f"{package_name}_" in line:
            package_file = line.split(":", 1)[1].strip()
            break

    if not package_file:
        warn(f"Pacchetto '{package_name}' non trovato nell'index OpenWrt")
        return False

    log(f"Trovato nell'index: {package_file}")
    try:
        urllib.request.urlretrieve(f"{repo_url}/{package_file}", output_file)
        log(f"Download completato: {package_file}")
        return True
    except Exception as exc:
        warn(f"Download fallito [{package_file}]: {exc}")
        return False


# ---------------------------------------------------------------------------
# 1. Rilevamento sistema
# ---------------------------------------------------------------------------


def detect_system() -> Tuple[str, str]:
    """Rileva versione OS e architettura. Restituisce (version, arch)."""
    version = "unknown"
    arch = "x86_64"

    for path in ("/etc/os-release", "/etc/openwrt_release"):
        if os.path.exists(path):
            with open(path) as fh:
                for line in fh:
                    if line.startswith("VERSION=") or line.startswith(
                        "DISTRIB_RELEASE"
                    ):
                        version = (
                            line.split("=", 1)[1].strip().strip("'\"").split()[0]
                        )
                        break
            if version != "unknown":
                break

    r = run(["opkg", "print-architecture"], capture=True, check=False)
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] not in ("all", "noarch"):
            arch = parts[1]

    log(f"Sistema rilevato: {version} / {arch}")
    return version, arch


# ---------------------------------------------------------------------------
# 2. Prerequisiti
# ---------------------------------------------------------------------------


def install_prereqs() -> None:
    """Installa tool necessari: wget, socat, ca-certificates, ar, tar, gzip."""
    if not cmd_exists("opkg"):
        die("opkg non trovato — questo script richiede OpenWrt / NethSecurity")

    log("opkg update")
    run(["opkg", "update"], check=False)

    log("Installazione pacchetti base (wget, socat, ca-certificates)...")
    run(["opkg", "install", "wget", "socat", "ca-certificates"], check=False)

    if not cmd_exists("wget"):
        die("wget non disponibile dopo installazione — impossibile continuare")
    if not cmd_exists("socat"):
        die("socat non disponibile dopo installazione — impossibile continuare")

    # ar — richiesto dalla dependency chain binutils
    if not cmd_exists("ar"):
        log(
            "Installazione catena dipendenze binutils "
            "(libbfd -> ar -> objdump -> binutils)..."
        )
        for pkg in ("libbfd", "ar", "objdump", "binutils"):
            tmp = f"/tmp/{pkg}.ipk"
            if download_openwrt_package(pkg, REPO_BASE, tmp):
                run(["opkg", "install", "--force-depends", tmp], check=False)
                Path(tmp).unlink(missing_ok=True)
        if not cmd_exists("ar"):
            die("ar non disponibile dopo installazione — impossibile continuare")

    # tar
    if not cmd_exists("tar"):
        tmp = "/tmp/tar.ipk"
        if download_openwrt_package("tar", REPO_BASE, tmp):
            run(["opkg", "install", "--force-depends", tmp], check=False)
            Path(tmp).unlink(missing_ok=True)
        if not cmd_exists("tar"):
            die("tar non disponibile dopo installazione — impossibile continuare")

    # gzip
    if not cmd_exists("gzip"):
        tmp = "/tmp/gzip.ipk"
        if download_openwrt_package("gzip", REPO_BASE, tmp):
            run(["opkg", "install", "--force-depends", tmp], check=False)
            Path(tmp).unlink(missing_ok=True)
        if not cmd_exists("gzip"):
            die("gzip non disponibile dopo installazione — impossibile continuare")

    log("Prerequisiti verificati: wget, socat, ar, tar, gzip OK")


# ---------------------------------------------------------------------------
# 3. Installazione agente CheckMK
# ---------------------------------------------------------------------------


def install_agent() -> None:
    """Installa ns-checkmk-agent via opkg, con fallback a URL diretto."""
    log("Installazione ns-checkmk-agent via opkg...")
    r = run(["opkg", "install", "ns-checkmk-agent"], check=False)
    if r.returncode == 0:
        log("ns-checkmk-agent installato da repository opkg")
        return

    warn(
        f"ns-checkmk-agent non trovato nei repo — installo da URL diretto: "
        f"{AGENT_IPK_URL}"
    )
    run(["opkg", "install", AGENT_IPK_URL])
    log("ns-checkmk-agent installato da URL diretto")


def start_agent_service() -> None:
    """Abilita e avvia il servizio check_mk_agent."""
    init = "/etc/init.d/check_mk_agent"
    if not os.path.exists(init):
        die(
            f"Init script non trovato: {init} — "
            "installazione agente probabilmente fallita"
        )

    run([init, "enable"], check=False)
    r = run([init, "restart"], check=False)
    if r.returncode != 0:
        run([init, "start"], check=False)

    r = run([init, "status"], capture=True, check=False)
    if "running" in r.stdout:
        log("check_mk_agent in esecuzione (porta 6556)")
    else:
        warn(f"check_mk_agent stato: {r.stdout.strip()} — verificare manualmente")


# ---------------------------------------------------------------------------
# 4. QEMU Guest Agent
# ---------------------------------------------------------------------------


def install_qemu_ga() -> None:
    """Installa QEMU Guest Agent se il sistema e' una VM (Proxmox/KVM)."""
    product_name = ""
    try:
        product_name = Path("/sys/class/dmi/id/product_name").read_text().strip()
    except OSError:
        pass

    vm_keywords = ("qemu", "standard pc", "virtual", "kvm")
    if not any(kw in product_name.lower() for kw in vm_keywords):
        log(f"Sistema non identificato come VM ({product_name!r}) — skip qemu-guest-agent")
        return

    log(f"VM rilevata: {product_name} — installazione qemu-guest-agent")

    run(["opkg", "update"], check=False)
    r = run(["opkg", "install", "qemu-ga"], check=False)
    if r.returncode != 0:
        warn("Pacchetto qemu-ga non disponibile o gia' installato")

    if not os.path.exists("/usr/bin/qemu-ga"):
        warn("/usr/bin/qemu-ga non trovato — qemu-guest-agent non disponibile")
        return

    # Determina device e modalita'
    if os.path.exists("/dev/virtio-ports/org.qemu.guest_agent.0"):
        qemu_mode = "virtio-serial"
        qemu_path = "/dev/virtio-ports/org.qemu.guest_agent.0"
        log("Rilevato virtio-serial — configurazione Proxmox piena integrazione")
    elif os.path.exists("/dev/vport2p1"):
        qemu_mode = "virtio-serial"
        qemu_path = "/dev/vport2p1"
        log("Rilevato /dev/vport2p1 — configurazione virtio-serial diretta")
    else:
        qemu_mode = "isa-serial"
        qemu_path = "/dev/ttyS0"
        log("Fallback isa-serial")

    log(f"Modalita': {qemu_mode} su {qemu_path}")

    init_content = (
        "#!/bin/sh /etc/rc.common\n"
        "# QEMU Guest Agent init — generato da install-agent-nsec8.py\n"
        "START=99\n"
        "USE_PROCD=1\n\n"
        "start_service() {\n"
        "    procd_open_instance\n"
        f"    procd_set_param command /usr/bin/qemu-ga -m {qemu_mode} -p {qemu_path}\n"
        "    procd_set_param respawn\n"
        "    procd_set_param stdout 1\n"
        "    procd_set_param stderr 1\n"
        "    procd_close_instance\n"
        "}\n"
    )
    init_path = Path("/etc/init.d/qemu-ga")
    init_path.write_text(init_content)
    init_path.chmod(init_path.stat().st_mode | 0o111)

    run(["/etc/init.d/qemu-ga", "enable"], check=False)
    run(["/etc/init.d/qemu-ga", "start"], check=False)

    r = run(["pgrep", "qemu-ga"], capture=True, check=False)
    if r.returncode == 0:
        log(f"QEMU Guest Agent installato e attivo ({qemu_mode})")
    else:
        warn("QEMU Guest Agent non risulta in esecuzione")

    _add_to_sysupgrade("/usr/bin/qemu-ga", "QEMU Guest Agent - Binary")
    _add_to_sysupgrade("/etc/init.d/qemu-ga", "QEMU Guest Agent - Init Script")
    log("Installazione QEMU Guest Agent protetta contro major upgrade")


# ---------------------------------------------------------------------------
# 5. Git e repository
# ---------------------------------------------------------------------------


def install_git_if_missing() -> bool:
    """Installa git e git-http via opkg (o download dinamico). Restituisce True se disponibile."""
    if cmd_exists("git"):
        r = run(["git", "--version"], capture=True, check=False)
        log(f"Git gia' installato: {r.stdout.strip()}")
        return True

    log("Git non trovato — installazione via opkg...")
    r = run(["opkg", "install", "git", "git-http"], check=False)
    if r.returncode == 0 and cmd_exists("git"):
        log("Git installato via opkg")
        return True

    warn("opkg install git fallito — provo download dinamico da REPO_PACKAGES")
    for pkg in ("git", "git-http"):
        tmp = f"/tmp/{pkg}.ipk"
        if download_openwrt_package(pkg, REPO_PACKAGES, tmp):
            run(["opkg", "install", tmp], check=False)
            Path(tmp).unlink(missing_ok=True)

    if cmd_exists("git"):
        r = run(["git", "--version"], capture=True, check=False)
        log(f"Git installato: {r.stdout.strip()}")
        return True

    warn("Git non disponibile — auto-sync disabilitato")
    return False


def setup_repo(git_available: bool = True) -> None:
    """Clona o aggiorna /opt/checkmk-tools."""
    repo = Path(REPO_DIR)

    if not git_available:
        if repo.exists():
            log(f"Repository gia' presente in {REPO_DIR} (git non disponibile, skip update)")
        else:
            warn(f"Git non disponibile e {REPO_DIR} non esiste — impossibile clonare")
        return

    if (repo / ".git").exists():
        log(f"Repository presente, aggiorno {REPO_DIR}...")
        r = run(["git", "-C", REPO_DIR, "pull"], check=False)
        if r.returncode != 0:
            warn("git pull fallito — continuo comunque")
    else:
        log(f"Clono {REPO_URL} in {REPO_DIR}...")
        repo.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", REPO_URL, REPO_DIR])
        log("Repository clonato")


# ---------------------------------------------------------------------------
# 6. Local checks
# ---------------------------------------------------------------------------


def deploy_local_checks() -> None:
    """Copia i local check da script-check-nsec8/full/ in LOCAL_DIR."""
    src = Path(CHECKS_SRC)
    dst = Path(LOCAL_DIR)
    dst.mkdir(parents=True, exist_ok=True)

    if not src.exists():
        warn(f"Directory check non trovata: {src} — skip deploy checks")
        return

    deployed = 0
    for f in src.iterdir():
        if f.is_file() and (f.suffix in (".py", ".sh") or f.stat().st_mode & 0o111):
            dest_name = f.stem if f.suffix == ".py" else f.name
            dest_path = dst / dest_name
            shutil.copy2(f, dest_path)
            dest_path.chmod(dest_path.stat().st_mode | 0o111)
            deployed += 1

    log(f"Deploy local checks: {deployed} file in {LOCAL_DIR}")


# ---------------------------------------------------------------------------
# 7. Cron auto-sync
# ---------------------------------------------------------------------------


def setup_cron(git_available: bool = True) -> None:
    """Crea sync script e aggiunge cron job ogni minuto."""
    if not git_available:
        log("Git non disponibile — skip configurazione auto-sync cron")
        return

    sync_content = (
        "#!/bin/sh\n"
        f"# Auto Git Sync Worker — generato da install-agent-nsec8.py v{VERSION}\n"
        f'REPO_DIR="{REPO_DIR}"\n'
        'LOG_FILE="/var/log/auto-git-sync.log"\n'
        "MAX_LOG_SIZE=1048576\n\n"
        "if [ -f \"$LOG_FILE\" ] && [ \"$(stat -c%s \"$LOG_FILE\" 2>/dev/null || echo 0)\" -gt \"$MAX_LOG_SIZE\" ]; then\n"
        "    mv \"$LOG_FILE\" \"$LOG_FILE.old\" 2>/dev/null || true\n"
        "fi\n\n"
        "echo \"[$(date '+%Y-%m-%d %H:%M:%S')] Auto sync started\" >> \"$LOG_FILE\"\n\n"
        "if [ ! -d \"$REPO_DIR/.git\" ]; then\n"
        "    echo \"[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: Repository not found\" >> \"$LOG_FILE\"\n"
        "    exit 1\n"
        "fi\n\n"
        "cd \"$REPO_DIR\" || exit 1\n\n"
        "if git pull origin main >> \"$LOG_FILE\" 2>&1; then\n"
        "    echo \"[$(date '+%Y-%m-%d %H:%M:%S')] Sync completed\" >> \"$LOG_FILE\"\n"
        "else\n"
        "    echo \"[$(date '+%Y-%m-%d %H:%M:%S')] Git pull failed\" >> \"$LOG_FILE\"\n"
        "fi\n"
    )

    sync_path = Path(SYNC_SCRIPT)
    sync_path.parent.mkdir(parents=True, exist_ok=True)
    sync_path.write_text(sync_content)
    sync_path.chmod(sync_path.stat().st_mode | 0o111)
    log(f"Script sync creato: {SYNC_SCRIPT}")

    cron_path = Path(CRON_FILE)
    cron_path.parent.mkdir(parents=True, exist_ok=True)
    existing = cron_path.read_text() if cron_path.exists() else ""
    lines = [l for l in existing.splitlines() if "git-auto-sync" not in l]
    lines.append(f"* * * * * {SYNC_SCRIPT}")
    cron_path.write_text("\n".join(lines) + "\n")
    log("Cron job aggiunto (ogni minuto)")

    run(["/etc/init.d/cron", "restart"], check=False)


# ---------------------------------------------------------------------------
# 8. Protezione sysupgrade (ROCKSOLID)
# ---------------------------------------------------------------------------


def _add_to_sysupgrade(path: str, comment: str) -> None:
    """Aggiunge un path a sysupgrade.conf se non gia' presente."""
    conf = Path(SYSUPGRADE_CONF)
    if not conf.exists():
        conf.write_text("## File e directory preservati durante upgrade\n\n")
    existing = conf.read_text()
    if path not in existing:
        conf.write_text(existing + f"\n# {comment}\n{path}\n")


def setup_sysupgrade() -> None:
    """Aggiunge tutti i path critici a sysupgrade.conf."""
    entries = [
        ("/usr/bin/check_mk_agent",         "CheckMK Agent - Binary"),
        ("/etc/init.d/check_mk_agent",       "CheckMK Agent - Init Script"),
        ("/etc/check_mk/",                   "CheckMK Agent - Configuration"),
        ("/usr/local/bin/",                  "Script Custom Directory"),
        (f"{LOCAL_DIR}/",                    "CheckMK Agent Local Checks"),
        ("/usr/lib/check_mk_agent/plugins/", "CheckMK Agent Plugins"),
        (f"{REPO_DIR}/",                     "Repository checkmk-tools"),
        ("/opt/checkmk-backups/",            "Backup binari critici (tar, ar, gzip)"),
        ("/etc/nginx/",                      "NGINX configuration (Web UI NethSecurity)"),
        (SYNC_SCRIPT,                        "Git Auto Sync Script"),
        (CRON_FILE,                          "Cron Jobs (include git sync)"),
        ("/etc/cron.d/",                     "Cron Jobs Directory"),
        ("/var/spool/cron/crontabs/",        "User Crontabs"),
        ("/etc/opkg/customfeeds.conf",       "Custom package repositories"),
        (POST_UPGRADE_SCRIPT,                "Post-upgrade verification script"),
        (RC_LOCAL,                           "Boot Script (rc.local)"),
    ]

    conf = Path(SYSUPGRADE_CONF)
    if not conf.exists():
        conf.write_text("## File e directory preservati durante upgrade\n\n")

    existing = conf.read_text()
    added = 0
    for path, comment in entries:
        if path not in existing:
            existing += f"\n# {comment}\n{path}\n"
            added += 1

    conf.write_text(existing)
    log(f"sysupgrade.conf: {added} nuove entry aggiunte")


# ---------------------------------------------------------------------------
# 9. Backup binari critici (ROCKSOLID)
# ---------------------------------------------------------------------------


def backup_critical_binaries() -> None:
    """Backup di tar/ar/gzip/libbfd che si corrompono durante major upgrade."""
    bins = [
        "/usr/libexec/tar-gnu",
        "/usr/bin/ar",
        "/usr/libexec/gzip-gnu",
        "/usr/libexec/gunzip-gnu",
    ]
    for p in Path("/usr/lib").glob("libbfd-*.so"):
        bins.append(str(p))

    backup_path = Path(BACKUP_DIR)
    backup_path.mkdir(parents=True, exist_ok=True)

    log("ROCKSOLID: Backup binari critici (protegge da corruzione durante upgrade)...")

    ok = 0
    for bin_path in bins:
        p = Path(bin_path)
        if not p.exists():
            continue
        r = run(["file", str(p)], capture=True, check=False)
        if "ELF" not in r.stdout:
            warn(f"  Skip {p.name}: non e' un ELF valido")
            continue
        dest = backup_path / f"{p.name}.backup"
        try:
            shutil.copy2(p, dest)
            log(f"  Backup: {p}")
            ok += 1
        except OSError as exc:
            warn(f"  Backup fallito per {p}: {exc}")

    log(f"Binari critici backuppati ({ok}) in: {BACKUP_DIR}")


# ---------------------------------------------------------------------------
# 10. Script post-upgrade (ROCKSOLID)
# ---------------------------------------------------------------------------


def create_post_upgrade_script() -> None:
    """Crea /etc/checkmk-post-upgrade.sh — eseguito manualmente dopo major upgrade."""
    log(f"Creo script di ripristino post-upgrade: {POST_UPGRADE_SCRIPT}")

    script_lines = [
        "#!/bin/sh",
        "# checkmk-post-upgrade.sh — ripristino automatico dopo major upgrade",
        "# Generato da install-agent-nsec8.py",
        "",
        "log() { logger -t checkmk-post-upgrade \"$*\"; echo \"[POST-UPGRADE] $*\"; }",
        "",
        "log \"=== POST-UPGRADE: Inizio ripristino ===\"",
        "",
        "BACKUP_DIR=\"/opt/checkmk-backups/binaries\"",
        "",
        "if [ -d \"$BACKUP_DIR\" ]; then",
        "    log \"Ripristino binari critici da backup...\"",
        "    for backup in \"$BACKUP_DIR\"/*.backup; do",
        "        [ -f \"$backup\" ] || continue",
        "        basename_file=$(basename \"$backup\" .backup)",
        "        case \"$basename_file\" in",
        "            tar-gnu|gzip-gnu|gunzip-gnu|zcat-gnu) dest=\"/usr/libexec/$basename_file\" ;;",
        "            ar)                                    dest=\"/usr/bin/$basename_file\" ;;",
        "            libbfd-*.so)                           dest=\"/usr/lib/$basename_file\" ;;",
        "            *) log \"  SKIP: $basename_file\"; continue ;;",
        "        esac",
        "        if [ -f \"$dest\" ]; then",
        "            if ! file \"$dest\" 2>/dev/null | grep -q \"ELF\"; then",
        "                log \"  CORROTTO: $dest — ripristino\"",
        "                cp -p \"$backup\" \"$dest\" && log \"  RIPRISTINATO: $dest\" || log \"  ERRORE: $dest\"",
        "            else",
        "                log \"  OK: $dest\"",
        "            fi",
        "        else",
        "            log \"  MANCANTE: $dest — ripristino\"",
        "            cp -p \"$backup\" \"$dest\" && log \"  RIPRISTINATO: $dest\" || log \"  ERRORE: $dest\"",
        "        fi",
        "    done",
        "else",
        "    log \"ATTENZIONE: $BACKUP_DIR non trovata\"",
        "fi",
        "",
        "[ -x /usr/bin/check_mk_agent ] || { log \"ERRORE: check_mk_agent mancante!\"; exit 1; }",
        "[ -x /etc/init.d/check_mk_agent ] || { log \"ERRORE: init script mancante!\"; exit 1; }",
        "/etc/init.d/check_mk_agent enable  2>/dev/null || true",
        "/etc/init.d/check_mk_agent restart 2>/dev/null || true",
        "",
        "if [ ! -L /etc/nginx/uci.conf ] && [ -f /var/lib/nginx/uci.conf ]; then",
        "    log \"Ripristino symlink nginx uci.conf...\"",
        "    ln -sf /var/lib/nginx/uci.conf /etc/nginx/uci.conf 2>/dev/null || true",
        "    /etc/init.d/nginx restart 2>/dev/null || true",
        "fi",
        "",
        "sleep 2",
        "if pgrep -f \"socat TCP-LISTEN:6556\" >/dev/null 2>&1; then",
        "    log \"CheckMK Agent attivo su porta 6556\"",
        "else",
        "    log \"WARN: socat non in esecuzione — riavvio\"",
        "    /etc/init.d/check_mk_agent restart 2>/dev/null || true",
        "fi",
        "",
        "log \"=== POST-UPGRADE: Ripristino completato ===\"",
    ]

    post_path = Path(POST_UPGRADE_SCRIPT)
    post_path.write_text("\n".join(script_lines) + "\n")
    post_path.chmod(post_path.stat().st_mode | 0o111)
    _add_to_sysupgrade(POST_UPGRADE_SCRIPT, "Post-upgrade verification script")
    log(f"Script post-upgrade creato: {POST_UPGRADE_SCRIPT}")


# ---------------------------------------------------------------------------
# 11. Autocheck all'avvio (ROCKSOLID)
# ---------------------------------------------------------------------------


def install_autocheck() -> None:
    """Scarica rocksolid-startup-check.sh e lo configura in rc.local."""
    log("Installazione script autocheck all'avvio")

    Path(AUTOCHECK_SCRIPT).parent.mkdir(parents=True, exist_ok=True)

    downloaded = False
    log("Download rocksolid-startup-check.sh da GitHub...")
    try:
        urllib.request.urlretrieve(AUTOCHECK_URL, AUTOCHECK_SCRIPT)
        Path(AUTOCHECK_SCRIPT).chmod(
            Path(AUTOCHECK_SCRIPT).stat().st_mode | 0o111
        )
        log(f"Script rocksolid installato: {AUTOCHECK_SCRIPT}")
        downloaded = True
    except Exception as exc:
        warn(f"Download da GitHub fallito ({exc}) — provo da repository locale")

    if not downloaded:
        local_src = (
            Path(REPO_DIR)
            / "script-tools/full/upgrade_maintenance/rocksolid-startup-check.sh"
        )
        if local_src.exists():
            shutil.copy2(local_src, AUTOCHECK_SCRIPT)
            Path(AUTOCHECK_SCRIPT).chmod(
                Path(AUTOCHECK_SCRIPT).stat().st_mode | 0o111
            )
            log("Script rocksolid copiato da repository locale")
        else:
            warn("ATTENZIONE: rocksolid-startup-check.sh non disponibile — skip autocheck")
            return

    # Configura rc.local
    rc_path = Path(RC_LOCAL)
    if not rc_path.exists():
        rc_path.write_text(
            "#!/bin/sh\n"
            "# Put your custom commands here that should be executed once\n"
            "# the system init finished. By default this file does nothing.\n\n"
            "exit 0\n"
        )
        rc_path.chmod(rc_path.stat().st_mode | 0o111)

    content = rc_path.read_text()
    lines = [
        l for l in content.splitlines()
        if "rocksolid-startup-check" not in l
        and "ROCKSOLID Autocheck" not in l
        and l != "exit 0"
    ]
    lines.append(
        "# ROCKSOLID Autocheck — avvio da /opt/checkmk-backups/ (upgrade-resistant)"
    )
    lines.append(
        f"[ -x {AUTOCHECK_SCRIPT} ] && bash {AUTOCHECK_SCRIPT} "
        ">> /var/log/rocksolid-startup.log 2>&1 &"
    )
    lines.append("exit 0")
    rc_path.write_text("\n".join(lines) + "\n")
    log(f"Autocheck configurato in {RC_LOCAL}")

    _add_to_sysupgrade(RC_LOCAL, "Boot Script (rc.local)")

    # Test immediato
    log("Test esecuzione autocheck...")
    r = run([AUTOCHECK_SCRIPT], check=False)
    if r.returncode == 0:
        log("Test autocheck completato — log in /var/log/rocksolid-startup.log")
    else:
        warn(f"Test autocheck exit code {r.returncode}")


# ---------------------------------------------------------------------------
# 12. Disinstallazione
# ---------------------------------------------------------------------------


def uninstall() -> None:
    """Rimuove agente, cron, sync script e post-upgrade. NON rimuove /opt/checkmk-tools."""
    log("Disinstallazione CheckMK Agent...")

    init = "/etc/init.d/check_mk_agent"
    if os.path.exists(init):
        run([init, "stop"], check=False)
        run([init, "disable"], check=False)

    subprocess.run(["killall", "socat"], capture_output=True)
    run(["opkg", "remove", "ns-checkmk-agent"], check=False)

    # Rimuovi cron entry
    if os.path.exists(CRON_FILE):
        lines = [
            l for l in Path(CRON_FILE).read_text().splitlines()
            if "git-auto-sync" not in l
        ]
        Path(CRON_FILE).write_text("\n".join(lines) + "\n")
        run(["/etc/init.d/cron", "restart"], check=False)

    # Rimuovi script generati
    for p in (SYNC_SCRIPT, POST_UPGRADE_SCRIPT):
        if os.path.exists(p):
            os.remove(p)
            log(f"Rimosso: {p}")

    # Rimuovi voce autocheck da rc.local
    if os.path.exists(RC_LOCAL):
        lines = [
            l for l in Path(RC_LOCAL).read_text().splitlines()
            if "rocksolid-startup-check" not in l
            and "ROCKSOLID Autocheck" not in l
        ]
        Path(RC_LOCAL).write_text("\n".join(lines) + "\n")

    log("Disinstallazione completata")
    log(f"NOTA: {REPO_DIR} e {BACKUP_DIR} NON sono stati rimossi")
    warn(
        f"Le entry in {SYSUPGRADE_CONF} non sono state modificate — "
        "rimuovile manualmente se desiderato"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def usage() -> None:
    print(
        f"install-agent-nsec8.py v{VERSION}\n\n"
        "CheckMK Agent Installer — ROCKSOLID Edition\n"
        "Installazione persistente resistente ai major upgrade NethSecurity/OpenWrt\n\n"
        "Uso:\n"
        "  python3 install-agent-nsec8.py\n"
        "  python3 install-agent-nsec8.py --uninstall\n\n"
        "Variabili d'ambiente:\n"
        f"  CHECKMK_REPO_URL       (default: {REPO_URL})\n"
        f"  CHECKMK_REPO_DIR       (default: {REPO_DIR})\n"
        f"  CHECKMK_AGENT_IPK_URL  (default: URL NethSecurity)\n"
        f"  OPENWRT_REPO_BASE      (default: downloads.openwrt.org/23.05.0 base)\n"
        f"  OPENWRT_REPO_PACKAGES  (default: downloads.openwrt.org/23.05.0 packages)\n"
    )


def main() -> int:
    args = sys.argv[1:]

    if "-h" in args or "--help" in args:
        usage()
        return 0

    if not is_root():
        die("Questo script deve essere eseguito come root")

    if "--uninstall" in args:
        uninstall()
        return 0

    print()
    print("=" * 62)
    print("  CheckMK Agent Installer — ROCKSOLID Edition")
    print(f"  v{VERSION}")
    print("  Resistente ai major upgrade NethSecurity / OpenWrt")
    print("=" * 62)
    print()

    log(f"=== install-agent-nsec8.py v{VERSION} ===")

    log("--- [1/10] Rilevamento sistema ---")
    detect_system()

    log("--- [2/10] Installazione prerequisiti ---")
    install_prereqs()

    log("--- [3/10] Installazione agente CheckMK ---")
    install_agent()

    log("--- [4/10] Avvio servizio agente ---")
    start_agent_service()

    log("--- [5/10] QEMU Guest Agent ---")
    install_qemu_ga()

    log("--- [6/10] Installazione git ---")
    git_ok = install_git_if_missing()

    log("--- [7/10] Setup repository ---")
    setup_repo(git_available=git_ok)

    log("--- [8/10] Deploy local checks ---")
    deploy_local_checks()

    log("--- [9/10] Cron auto-sync + sysupgrade + backup binari ---")
    setup_cron(git_available=git_ok)
    setup_sysupgrade()
    backup_critical_binaries()
    create_post_upgrade_script()

    log("--- [10/10] Autocheck all'avvio ---")
    install_autocheck()

    print()
    print("=" * 62)
    print("  INSTALLAZIONE COMPLETATA — ROCKSOLID MODE ATTIVO")
    print("=" * 62)
    print()
    print("Protezioni attivate:")
    print(f"  [+] File critici aggiunti a {SYSUPGRADE_CONF}")
    print(f"  [+] Binari critici backuppati in {BACKUP_DIR}")
    print(f"  [+] Script post-upgrade: {POST_UPGRADE_SCRIPT}")
    print(f"  [+] Autocheck all'avvio: {AUTOCHECK_SCRIPT}")
    print()
    print("Auto Git Sync:")
    print(f"  [+] Repository: {REPO_DIR}")
    print("  [+] Sync automatico ogni minuto (se git disponibile)")
    print("  [+] Log: /var/log/auto-git-sync.log")
    print()
    print("Test agent locale: nc 127.0.0.1 6556 | head")
    print(f"Post-upgrade manuale: sh {POST_UPGRADE_SCRIPT}")
    print(f"Disinstallazione: python3 {sys.argv[0]} --uninstall")
    return 0


if __name__ == "__main__":
    sys.exit(main())
