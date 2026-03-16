#!/usr/bin/env python3
"""
install-checkmk-agent-persistent-nsec8.py

Installa e configura CheckMK Agent su NethSecurity 8 / OpenWrt in modo persistente:
  - Installa ns-checkmk-agent via opkg (con fallback a URL diretto)
  - Crea /usr/lib/check_mk_agent/local/ e deploya i local check dal repo
  - Installa git se mancante, clona/aggiorna /opt/checkmk-tools
  - Configura cron auto-sync ogni minuto
  - Protegge installazione in sysupgrade.conf (sopravvive a major upgrade)

Uso:
  python3 install-checkmk-agent-persistent-nsec8.py [--uninstall]

Version: 1.0.1
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

VERSION = "1.0.1"

# ---------------------------------------------------------------------------
# Costanti configurabili via variabili d'ambiente
# ---------------------------------------------------------------------------
REPO_URL = os.environ.get("CHECKMK_REPO_URL", "https://github.com/Coverup20/checkmk-tools.git")
REPO_DIR = os.environ.get("CHECKMK_REPO_DIR", "/opt/checkmk-tools")
CHECKS_SRC = os.path.join(REPO_DIR, "script-check-nsec8", "full")
LOCAL_DIR = "/usr/lib/check_mk_agent/local"
SYSUPGRADE_CONF = "/etc/sysupgrade.conf"
CRON_FILE = "/etc/crontabs/root"
SYNC_SCRIPT = "/usr/local/bin/git-auto-sync.sh"

# URL diretto pacchetto (usato come fallback se opkg non trova ns-checkmk-agent)
AGENT_IPK_URL = os.environ.get(
    "CHECKMK_AGENT_IPK_URL",
    "https://updates.nethsecurity.nethserver.org/checkmk_agent/"
    "8.7.1-checkmk_agent+b37c288d8/packages/x86_64/nethsecurity/"
    "ns-checkmk-agent_0.0.1-r1_all.ipk",
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
# Funzioni principali
# ---------------------------------------------------------------------------

def detect_system() -> Tuple[str, str]:
    """Rileva versione OS e architettura. Restituisce (version, arch)."""
    version = "unknown"
    arch = "x86_64"

    for path in ("/etc/os-release", "/etc/openwrt_release"):
        if os.path.exists(path):
            with open(path) as f:
                for line in f:
                    if line.startswith("VERSION=") or line.startswith("DISTRIB_RELEASE"):
                        version = line.split("=", 1)[1].strip().strip("'\"").split()[0]
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


def install_agent() -> None:
    """Installa ns-checkmk-agent via opkg (prima tenta da repo, poi da URL diretto)."""
    log("opkg update")
    run(["opkg", "update"])

    # Tenta installazione da repo configurati
    r = run(["opkg", "install", "ns-checkmk-agent"], check=False)
    if r.returncode == 0:
        log("ns-checkmk-agent installato da repository opkg")
        return

    # Fallback: URL diretto
    warn(f"ns-checkmk-agent non trovato nei repo, installo da URL diretto: {AGENT_IPK_URL}")
    run(["opkg", "install", AGENT_IPK_URL])
    log("ns-checkmk-agent installato da URL diretto")


def start_agent_service() -> None:
    """Abilita e avvia il servizio check_mk_agent."""
    init = "/etc/init.d/check_mk_agent"
    if not os.path.exists(init):
        die(f"Init script non trovato: {init} — installazione agente fallita?")

    run([init, "enable"], check=False)
    r = run([init, "restart"], check=False)
    if r.returncode != 0:
        run([init, "start"], check=False)

    # Verifica
    r = run([init, "status"], capture=True, check=False)
    status = r.stdout.strip()
    if "running" in status:
        log("check_mk_agent in esecuzione (porta 6556)")
    else:
        warn(f"check_mk_agent stato: {status} — verificare manualmente")


def install_git_if_missing() -> bool:
    """Installa git e git-http via opkg se mancante. Restituisce True se git disponibile."""
    if cmd_exists("git"):
        r = run(["git", "--version"], capture=True, check=False)
        log(f"Git già installato: {r.stdout.strip()}")
        return True

    log("Git non trovato, tento installazione via opkg...")
    r = run(["opkg", "install", "git", "git-http"], check=False)
    if r.returncode == 0 and cmd_exists("git"):
        log("Git installato")
        return True

    warn("Git non disponibile nei repo NethSecurity — auto-sync disabilitato")
    warn("I local checks sono stati deployati dal repo già presente in /opt/checkmk-tools/")
    return False


def setup_repo(git_available: bool = True) -> None:
    """Clona o aggiorna /opt/checkmk-tools. Se git non disponibile, logga warning."""
    repo = Path(REPO_DIR)

    if not git_available:
        if repo.exists():
            log(f"Repository già presente in {REPO_DIR} (git non disponibile, skip update)")
        else:
            warn(f"Git non disponibile e {REPO_DIR} non esiste — impossibile clonare")
        return

    if (repo / ".git").exists():
        log(f"Repository presente in {REPO_DIR}, aggiorno...")
        r = run(["git", "-C", REPO_DIR, "pull"], check=False)
        if r.returncode != 0:
            warn("git pull fallito, continuo comunque")
        else:
            log("Repository aggiornato")
    else:
        log(f"Clono {REPO_URL} in {REPO_DIR}...")
        repo.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", REPO_URL, REPO_DIR])
        log("Repository clonato")


def deploy_local_checks() -> None:
    """Copia i local check da script-check-nsec8/full/ in /usr/lib/check_mk_agent/local/."""
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


def setup_cron(git_available: bool = True) -> None:
    """Crea sync script e aggiunge cron job ogni minuto. Skip se git non disponibile."""
    if not git_available:
        log("Git non disponibile — skip configurazione auto-sync cron")
        return
    sync_script_content = """\
#!/bin/sh
# Auto Git Sync Worker — generato da install-checkmk-agent-persistent-nsec8.py
REPO_DIR="{repo_dir}"
LOG_FILE="/var/log/auto-git-sync.log"
MAX_LOG_SIZE=1048576

if [ -f "$LOG_FILE" ] && [ "$(stat -c%s "$LOG_FILE" 2>/dev/null || echo 0)" -gt "$MAX_LOG_SIZE" ]; then
    mv "$LOG_FILE" "$LOG_FILE.old" 2>/dev/null || true
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Auto sync started" >> "$LOG_FILE"

if [ ! -d "$REPO_DIR/.git" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: Repository not found" >> "$LOG_FILE"
    exit 1
fi

cd "$REPO_DIR" || exit 1

if git pull origin main >> "$LOG_FILE" 2>&1; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Sync completed" >> "$LOG_FILE"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Git pull failed" >> "$LOG_FILE"
fi
""".format(repo_dir=REPO_DIR)

    sync_path = Path(SYNC_SCRIPT)
    sync_path.parent.mkdir(parents=True, exist_ok=True)
    sync_path.write_text(sync_script_content)
    sync_path.chmod(sync_path.stat().st_mode | 0o111)
    log(f"Script sync creato: {SYNC_SCRIPT}")

    # Cron
    cron_path = Path(CRON_FILE)
    cron_path.parent.mkdir(parents=True, exist_ok=True)
    existing = cron_path.read_text() if cron_path.exists() else ""

    # Rimuovi vecchie entry
    lines = [l for l in existing.splitlines() if "git-auto-sync" not in l]
    lines.append(f"* * * * * {SYNC_SCRIPT}")
    cron_path.write_text("\n".join(lines) + "\n")
    log("Cron job aggiunto (ogni minuto)")

    # Riavvia cron
    run(["/etc/init.d/cron", "restart"], check=False)


def setup_sysupgrade() -> None:
    """Aggiunge i path critici a sysupgrade.conf per persistenza dopo major upgrade."""
    entries = [
        (f"{REPO_DIR}/",  "CheckMK Tools Repository"),
        (SYNC_SCRIPT,     "Git Auto Sync Script"),
        (CRON_FILE,       "Cron Jobs"),
        (LOCAL_DIR + "/", "CheckMK Local Checks"),
    ]

    conf = Path(SYSUPGRADE_CONF)
    if not conf.exists():
        conf.write_text(
            "## File e directory preservati durante upgrade\n\n"
        )

    existing = conf.read_text()
    added = 0
    for path, comment in entries:
        if path not in existing:
            existing += f"\n# {comment}\n{path}\n"
            added += 1

    conf.write_text(existing)
    log(f"sysupgrade.conf: {added} nuove entry aggiunte")


def uninstall() -> None:
    """Rimuove agente, cron, sync script. NON rimuove /opt/checkmk-tools."""
    log("Disinstallazione CheckMK Agent...")

    init = "/etc/init.d/check_mk_agent"
    if os.path.exists(init):
        run([init, "stop"], check=False)
        run([init, "disable"], check=False)

    subprocess.run(["killall", "socat"], capture_output=True)

    run(["opkg", "remove", "ns-checkmk-agent"], check=False)

    # Rimuovi cron
    if os.path.exists(CRON_FILE):
        lines = [l for l in Path(CRON_FILE).read_text().splitlines()
                 if "git-auto-sync" not in l]
        Path(CRON_FILE).write_text("\n".join(lines) + "\n")
        run(["/etc/init.d/cron", "restart"], check=False)

    # Rimuovi sync script
    if os.path.exists(SYNC_SCRIPT):
        os.remove(SYNC_SCRIPT)

    log("Disinstallazione completata")
    log(f"NOTA: {REPO_DIR} NON è stato rimosso")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def usage() -> None:
    print(
        f"install-checkmk-agent-persistent-nsec8.py v{VERSION}\n\n"
        "Installa CheckMK Agent + git sync + local checks su NethSecurity 8 / OpenWrt\n\n"
        "Uso:\n"
        "  python3 install-checkmk-agent-persistent-nsec8.py\n"
        "  python3 install-checkmk-agent-persistent-nsec8.py --uninstall\n\n"
        "Variabili d'ambiente:\n"
        f"  CHECKMK_REPO_URL     (default: {REPO_URL})\n"
        f"  CHECKMK_REPO_DIR     (default: {REPO_DIR})\n"
        f"  CHECKMK_AGENT_IPK_URL  (default: URL NethSecurity)\n"
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

    log(f"=== install-checkmk-agent-persistent-nsec8.py v{VERSION} ===")

    detect_system()

    log("--- [1/7] Installazione agente CheckMK ---")
    install_agent()

    log("--- [2/7] Avvio servizio agente ---")
    start_agent_service()

    log("--- [3/7] Installazione git ---")
    git_ok = install_git_if_missing()

    log("--- [4/7] Setup repository ---")
    setup_repo(git_available=git_ok)

    log("--- [5/7] Deploy local checks ---")
    deploy_local_checks()

    log("--- [6/7] Cron auto-sync ---")
    setup_cron(git_available=git_ok)

    log("--- [7/7] Protezione sysupgrade ---")
    setup_sysupgrade()

    print()
    log("=== Installazione completata ===")
    log(f"Agent:       porta 6556")
    log(f"Repo:        {REPO_DIR}  (auto-sync ogni minuto)")
    log(f"Local checks: {LOCAL_DIR}")
    log(f"Log sync:    /var/log/auto-git-sync.log")
    log(f"Disinstalla: python3 {sys.argv[0]} --uninstall")
    return 0


if __name__ == "__main__":
    sys.exit(main())
