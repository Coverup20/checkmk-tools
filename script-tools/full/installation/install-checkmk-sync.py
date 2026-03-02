#!/usr/bin/env python3
"""
install-checkmk-sync.py - Installer unificato CheckMK auto-sync

Installa in sequenza:
  STEP 1 → auto-git-sync        (git pull automatico ogni N secondi)
  STEP 2 → checkmk-python-full-sync  (deploy check Python ogni 5 minuti)

Compatibilità:
  - Linux con systemd   → service + timer (consigliato)
  - OpenWrt / cron-only → cron jobs fallback

Sostituisce:
  - install-auto-git-sync.sh
  - install-python-full-sync.py

Version: 1.0.2
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

VERSION = "1.0.2"

# ─── Costanti ─────────────────────────────────────────────────────────────────

REPO_DEFAULT_PATH = Path("/opt/checkmk-tools")
REPO_URL_DEFAULT = "https://github.com/Coverup20/checkmk-tools.git"
SYSTEMD_DIR = Path("/etc/systemd/system")
LOCAL_TARGET_DEFAULT = "/usr/lib/check_mk_agent/local"

# auto-git-sync
GIT_SYNC_SERVICE_NAME = "auto-git-sync.service"
GIT_SYNC_TIMER_NAME = "auto-git-sync.timer"
GIT_SYNC_LOG = "/var/log/auto-git-sync.log"
GIT_SYNC_CRON_MARKER = "git-auto-sync"

# checkmk-python-full-sync
PYTHON_SYNC_SERVICE_NAME = "checkmk-python-full-sync.service"
PYTHON_SYNC_TIMER_NAME = "checkmk-python-full-sync.timer"
PYTHON_SYNC_LOG = "/var/log/checkmk-python-full-sync.log"
PYTHON_SYNC_CRON_MARKER = "sync-python-full-checks"

OPENWRT_CRONTAB = Path("/etc/crontabs/root")


# ─── Utilities ────────────────────────────────────────────────────────────────

def run(cmd: List[str], **kwargs) -> None:
    """Esegue comando, solleva eccezione se fallisce."""
    subprocess.run(cmd, check=True, **kwargs)


def run_capture(cmd: List[str], cwd: str = "") -> subprocess.CompletedProcess:
    """Esegue comando e cattura output (non solleva eccezione)."""
    return subprocess.run(
        cmd,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        cwd=cwd or None,
    )


def require_root() -> None:
    if os.geteuid() != 0:
        print("[ERROR] Eseguire come root", file=sys.stderr)
        sys.exit(1)


def is_openwrt() -> bool:
    return Path("/etc/openwrt_release").exists()


def has_systemd() -> bool:
    return shutil.which("systemctl") is not None and SYSTEMD_DIR.exists()


def detect_pkg_manager() -> str:
    for name, cmd in [("apt", "apt-get"), ("dnf", "dnf"), ("yum", "yum"), ("opkg", "opkg")]:
        if shutil.which(cmd):
            return name
    return ""


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def get_repo_owner(repo_path: Path) -> str:
    result = run_capture(["stat", "-c", "%U", str(repo_path)])
    owner = (result.stdout or "root").strip()
    return owner if owner else "root"


def cron_update(lines_to_keep_filter: str, new_line: str, openwrt: bool = False) -> None:
    """Aggiorna crontab: rimuove righe con marker, aggiunge nuova riga."""
    if openwrt:
        current = []
        if OPENWRT_CRONTAB.exists():
            current = [
                l for l in OPENWRT_CRONTAB.read_text(encoding="utf-8").splitlines()
                if lines_to_keep_filter not in l
            ]
        current.append(new_line)
        OPENWRT_CRONTAB.write_text("\n".join(current) + "\n", encoding="utf-8")
        run_capture(["sh", "-c", "/etc/init.d/cron restart 2>/dev/null || true"])
    else:
        existing = run_capture(["crontab", "-l"])
        current = [
            l for l in (existing.stdout or "").splitlines()
            if lines_to_keep_filter not in l and l.strip()
        ]
        current.append(new_line)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".cron", delete=False) as f:
            f.write("\n".join(current) + "\n")
            tmp = f.name
        run(["crontab", tmp])
        Path(tmp).unlink(missing_ok=True)


# ─── Git prerequisiti ─────────────────────────────────────────────────────────

def ensure_git(pkg_mgr: str) -> None:
    if shutil.which("git"):
        return
    print("[INFO] git non trovato, installazione in corso...")
    if pkg_mgr == "apt":
        run(["apt-get", "update", "-y"])
        run(["apt-get", "install", "-y", "git"])
    elif pkg_mgr in ("dnf", "yum"):
        run([pkg_mgr, "install", "-y", "git"])
    else:
        print("[ERROR] Impossibile installare git automaticamente. Installare manualmente.", file=sys.stderr)
        sys.exit(1)
    print("[OK] git installato")


def ensure_repo(repo_path: Path, repo_url: str) -> None:
    if (repo_path / ".git").exists():
        return
    print(f"[INFO] Repository non trovato. Clonazione in {repo_path}...")
    repo_path.parent.mkdir(parents=True, exist_ok=True)
    run(["git", "clone", repo_url, str(repo_path)])
    print(f"[OK] Repository clonato: {repo_path}")


def update_repo(repo_path: Path) -> None:
    repo_str = str(repo_path)
    result = run_capture(["git", "fetch", "origin", "main"], cwd=repo_str)
    if result.returncode != 0:
        print(f"[WARN] git fetch fallito: {(result.stdout or '').strip()}")
        return
    run_capture(["git", "reset", "--hard", "origin/main"], cwd=repo_str)
    run_capture(["git", "clean", "-fd"], cwd=repo_str)
    head = run_capture(["git", "rev-parse", "--short", "HEAD"], cwd=repo_str)
    sha = (head.stdout or "").strip()
    print(f"[OK] Repository aggiornato → {sha or 'ok'}")


# ─── STEP 1: Auto Git Sync ────────────────────────────────────────────────────

_GIT_SYNC_SCRIPT = "/usr/local/bin/checkmk-git-sync.sh"

_GIT_SYNC_WRAPPER = """#!/bin/bash
REPO_DIR="{repo_dir}"
LOG_FILE="{log}"
cd "$REPO_DIR" || exit 0
if ! git fetch origin main >> "$LOG_FILE" 2>&1; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARN: git fetch fallito" >> "$LOG_FILE"
    exit 0
fi
git reset --hard origin/main >> "$LOG_FILE" 2>&1
git clean -fd >> "$LOG_FILE" 2>&1
SHA=$(git rev-parse --short HEAD 2>/dev/null)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Sync OK ($SHA)" >> "$LOG_FILE"
"""

_GIT_SYNC_SERVICE_TPL = """\
[Unit]
Description=Auto Git Sync - checkmk-tools
Documentation=https://github.com/Coverup20/checkmk-tools
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User={user}
Group={user}
ExecStart=/bin/bash {script}
StandardOutput=journal
StandardError=journal
SyslogIdentifier=auto-git-sync
"""

_GIT_SYNC_TIMER_TPL = """\
[Unit]
Description=Auto Git Sync timer - ogni {interval}s

[Timer]
OnBootSec=30s
OnUnitActiveSec={interval}s
Persistent=false

[Install]
WantedBy=timers.target
"""


def install_git_sync_systemd(repo_path: Path, interval: int, owner: str) -> None:
    """Installa auto-git-sync come systemd service + timer."""
    # Prepara log file
    try:
        Path(GIT_SYNC_LOG).touch(exist_ok=True)
        run_capture(["chown", f"{owner}:{owner}", GIT_SYNC_LOG])
    except Exception:
        pass

    # Scrivi wrapper script bash (evita problemi ExecStart multi-riga in systemd)
    wrapper_content = _GIT_SYNC_WRAPPER.format(repo_dir=str(repo_path), log=GIT_SYNC_LOG)
    write_text(Path(_GIT_SYNC_SCRIPT), wrapper_content)
    Path(_GIT_SYNC_SCRIPT).chmod(0o755)

    svc_path = SYSTEMD_DIR / GIT_SYNC_SERVICE_NAME
    timer_path = SYSTEMD_DIR / GIT_SYNC_TIMER_NAME

    write_text(svc_path, _GIT_SYNC_SERVICE_TPL.format(
        user=owner,
        script=_GIT_SYNC_SCRIPT,
    ))
    write_text(timer_path, _GIT_SYNC_TIMER_TPL.format(interval=interval))

    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", GIT_SYNC_TIMER_NAME])
    run(["systemctl", "start", GIT_SYNC_TIMER_NAME])

    # Primo sync immediato (non fatale)
    result = run_capture(["systemctl", "start", GIT_SYNC_SERVICE_NAME])
    if result.returncode == 0:
        print(f"[OK] Primo sync eseguito")
    else:
        print(f"[WARN] Primo sync fallito (il timer lo rieseguirà): {(result.stdout or '').strip()[-200:]}")

    print(f"[OK] auto-git-sync.timer attivo → sync ogni {interval}s")
    print(f"     Log:     tail -f {GIT_SYNC_LOG}")
    print(f"     Status:  systemctl status {GIT_SYNC_TIMER_NAME}")


def install_git_sync_cron(repo_path: Path) -> None:
    """Installa git sync via cron (OpenWrt / sistemi senza systemd)."""
    cron_line = (
        f"* * * * * cd {repo_path} && "
        f"git fetch origin main >> {GIT_SYNC_LOG} 2>&1 && "
        f"git reset --hard origin/main >> {GIT_SYNC_LOG} 2>&1  # {GIT_SYNC_CRON_MARKER}"
    )
    cron_update(GIT_SYNC_CRON_MARKER, cron_line, openwrt=is_openwrt())
    print(f"[OK] auto-git-sync installato via cron (ogni minuto)")
    print(f"     Log:     tail -f {GIT_SYNC_LOG}")


# ─── STEP 2: Python Full Sync ─────────────────────────────────────────────────

_PYTHON_SYNC_SERVICE_TPL = """\
[Unit]
Description=CheckMK Python Full Checks Sync
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart={cmd}
StandardOutput=journal
StandardError=journal
SyslogIdentifier=checkmk-python-full-sync
"""

_PYTHON_SYNC_TIMER_CONTENT = """\
[Unit]
Description=CheckMK Python Full Checks Sync - ogni 5 minuti

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min
Persistent=true

[Install]
WantedBy=timers.target
"""


def _build_sync_cmd(py_bin: str, sync_script: Path, repo_path: Path,
                    target: str, category: str, all_categories: bool,
                    scripts: str = "", temp_dir: str = "") -> str:
    parts = [py_bin, str(sync_script), "--repo", str(repo_path), "--target", target]
    if scripts:
        parts.extend(["--scripts", scripts])
    elif all_categories:
        parts.append("--all-categories")
    else:
        parts.extend(["--category", category])
    if temp_dir:
        parts.extend(["--temp-dir", temp_dir])
    return " ".join(parts)


def _find_sync_script(repo_path: Path) -> Path:
    candidate = repo_path / "script-tools/full/sync_update/sync-python-full-checks.py"
    if not candidate.exists():
        print(f"[ERROR] Script sync non trovato: {candidate}", file=sys.stderr)
        sys.exit(1)
    # Rendi eseguibile
    candidate.chmod(candidate.stat().st_mode | 0o111)
    return candidate


def install_python_sync_systemd(repo_path: Path, target: str,
                                 category: str, all_categories: bool,
                                 scripts: str = "", temp_dir: str = "") -> None:
    """Installa checkmk-python-full-sync come systemd service + timer."""
    py_bin = shutil.which("python3")
    if not py_bin:
        print("[ERROR] python3 non trovato nel PATH", file=sys.stderr)
        sys.exit(1)

    sync_script = _find_sync_script(repo_path)
    cmd = _build_sync_cmd(py_bin, sync_script, repo_path, target,
                          category, all_categories, scripts, temp_dir)

    # Modalità temp: esecuzione one-shot senza installare timer
    if temp_dir:
        print(f"[INFO] Modalità anteprima → esecuzione one-shot (nessun timer installato)")
        result = run_capture([py_bin, str(sync_script),
                              "--repo", str(repo_path),
                              "--target", target,
                              "--temp-dir", temp_dir]
                             + (["--scripts", scripts] if scripts else ["--all-categories"])
                             )
        print(result.stdout or "")
        print(f"[OK] Anteprima completata in: {temp_dir}")
        return

    svc_path = SYSTEMD_DIR / PYTHON_SYNC_SERVICE_NAME
    timer_path = SYSTEMD_DIR / PYTHON_SYNC_TIMER_NAME

    write_text(svc_path, _PYTHON_SYNC_SERVICE_TPL.format(cmd=cmd))
    write_text(timer_path, _PYTHON_SYNC_TIMER_CONTENT)

    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", "--now", PYTHON_SYNC_TIMER_NAME])

    # Primo sync immediato
    result = run_capture(["systemctl", "start", PYTHON_SYNC_SERVICE_NAME])
    if result.returncode == 0:
        print(f"[OK] checkmk-python-full-sync.timer attivo → deploy ogni 5 min")
    else:
        print(f"[OK] checkmk-python-full-sync.timer attivo → deploy ogni 5 min")
        print(f"[WARN] Primo sync: controllare 'systemctl status {PYTHON_SYNC_SERVICE_NAME}'")

    print(f"     Log:     journalctl -u {PYTHON_SYNC_SERVICE_NAME} -f")
    print(f"     Status:  systemctl status {PYTHON_SYNC_TIMER_NAME}")


def install_python_sync_cron(repo_path: Path, target: str,
                              category: str, all_categories: bool,
                              scripts: str = "", temp_dir: str = "") -> None:
    """Installa python full sync via cron."""
    py_bin = shutil.which("python3")
    if not py_bin:
        print("[ERROR] python3 non trovato", file=sys.stderr)
        sys.exit(1)

    sync_script = _find_sync_script(repo_path)

    # Modalità temp: esecuzione one-shot senza installare cron
    if temp_dir:
        print(f"[INFO] Modalità anteprima → esecuzione one-shot")
        cmd_parts = [py_bin, str(sync_script),
                     "--repo", str(repo_path), "--target", target,
                     "--temp-dir", temp_dir]
        if scripts:
            cmd_parts += ["--scripts", scripts]
        else:
            cmd_parts.append("--all-categories")
        result = run_capture(cmd_parts)
        print(result.stdout or "")
        print(f"[OK] Anteprima completata in: {temp_dir}")
        return

    cmd = _build_sync_cmd(py_bin, sync_script, repo_path, target,
                          category, all_categories, scripts, temp_dir)
    cron_line = f"*/5 * * * * {cmd} >> {PYTHON_SYNC_LOG} 2>&1  # {PYTHON_SYNC_CRON_MARKER}"

    cron_update(PYTHON_SYNC_CRON_MARKER, cron_line, openwrt=is_openwrt())
    print(f"[OK] checkmk-python-full-sync installato via cron (ogni 5 min)")
    print(f"     Log:     tail -f {PYTHON_SYNC_LOG}")


# ─── Prompt interattivi ───────────────────────────────────────────────────────

def _ask(prompt: str) -> str:
    """
    Legge input da /dev/tty se stdin non è un tty (es. curl | python3 -).
    Fallback a input() standard.
    """
    import sys
    if not sys.stdin.isatty():
        try:
            with open("/dev/tty", "r") as tty:
                sys.stdout.write(prompt)
                sys.stdout.flush()
                return tty.readline().rstrip("\n")
        except OSError:
            return ""
    return input(prompt)

def ask_interval() -> int:
    print()
    print("  Scegli intervallo git sync:")
    print("  1) Ogni 30 secondi")
    print("  2) Ogni 1 minuto (consigliato)")
    print("  3) Ogni 5 minuti")
    print("  4) Ogni 10 minuti")
    print("  5) Ogni 30 minuti")
    choice = _ask("\n  Scelta [2]: ").strip().replace("\r", "") or "2"
    mapping = {"1": 30, "2": 60, "3": 300, "4": 600, "5": 1800}
    interval = mapping.get(choice, 60)
    print(f"[OK] Intervallo: {interval}s")
    return interval


def ask_category(repo_path: Path) -> Tuple[str, bool]:
    categories = sorted([
        d.name for d in repo_path.iterdir()
        if d.is_dir() and d.name.startswith("script-check-")
    ])
    if not categories:
        return "auto", False

    print()
    print("  Scegli categoria da deployare:")
    print("  0) Tutte le categorie")
    for i, cat in enumerate(categories, 1):
        print(f"  {i}) {cat}")
    print("  a) Auto-detect (consigliato)")

    choice = _ask("\n  Scelta [a]: ").strip().lower().replace("\r", "") or "a"

    if choice == "0":
        return "auto", True
    if choice == "a":
        return "auto", False
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(categories):
            return categories[idx], False
    except ValueError:
        pass
    return "auto", False


def ask_scripts(repo_path: Path) -> Tuple[str, bool, str]:
    """
    Selezione interattiva script e modalità deploy.

    Returns:
        (scripts_csv, all_categories, temp_dir)
        scripts_csv:    stringa "nome1,nome2,..." oppure "" (tutte le categorie)
        all_categories: True se l'utente ha scelto tutto
        temp_dir:       path temp se anteprima, altrimenti ""
    """
    # Raccogli tutti i launcher disponibili
    all_launchers: List[Tuple[str, str]] = []  # (stem, categoria)
    for cat in sorted(repo_path.glob("script-check-*/")):
        remote = cat / "remote"
        if remote.is_dir():
            for launcher in sorted(remote.glob("*.py")):
                all_launchers.append((launcher.stem, cat.name))

    if not all_launchers:
        print("[WARN] Nessuno script trovato nel repository.")
        return "", True, ""

    print()
    print("  Script disponibili:")
    print("  ─" * 35)
    print(f"  {'#':<4} {'Nome script':<45} Categoria")
    print("  ─" * 35)
    for i, (stem, cat) in enumerate(all_launchers, 1):
        print(f"  {i:<4} {stem:<45} {cat}")
    print()
    print("  Seleziona script da deployare:")
    print("  - Numeri separati da virgola/spazio: es. 1,3,5  oppure  1 3 5")
    print("  - Intervalli: es. 1-5")
    print("  - 0 o invio = tutti")
    print()

    raw = _ask("  Scelta [0 = tutti]: ").strip().replace("\r", "") or "0"

    selected_indices: List[int] = []
    if raw == "0" or raw == "":
        selected_indices = list(range(len(all_launchers)))
    else:
        # Parsing: virgole, spazi, trattini per range
        tokens = raw.replace(",", " ").split()
        for token in tokens:
            if "-" in token and not token.startswith("-"):
                parts = token.split("-", 1)
                try:
                    start, end = int(parts[0]), int(parts[1])
                    selected_indices.extend(range(start - 1, end))
                except ValueError:
                    pass
            else:
                try:
                    selected_indices.append(int(token) - 1)
                except ValueError:
                    pass
        # Dedup e ordine
        selected_indices = sorted(set(
            i for i in selected_indices if 0 <= i < len(all_launchers)
        ))

    scripts_csv = ""
    all_cat = False
    if not selected_indices or selected_indices == list(range(len(all_launchers))):
        all_cat = True
        print("  → Tutti gli script selezionati")
    else:
        chosen = [all_launchers[i][0] for i in selected_indices]
        scripts_csv = ",".join(chosen)
        print(f"  → Selezionati {len(chosen)} script: {scripts_csv}")

    # Chiedi modalità deploy
    print()
    print("  Modalità deploy:")
    print("  1) Deploy reale → /usr/lib/check_mk_agent/local/ (default)")
    print(f"  2) Anteprima temp → /tmp/checkmk-sync-preview/ (nessun deploy reale)")
    mode = _ask("\n  Scelta [1]: ").strip().replace("\r", "") or "1"

    temp_dir = ""
    if mode == "2":
        temp_dir = "/tmp/checkmk-sync-preview"
        print(f"  → Anteprima in: {temp_dir}")
    else:
        print("  → Deploy reale")

    return scripts_csv, all_cat, temp_dir


# ─── Argomenti CLI ────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=f"install-checkmk-sync.py v{VERSION} - Installer unificato git-sync + deploy check Python",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esempi:
  # Installazione interattiva (consigliato)
  python3 install-checkmk-sync.py

  # Modalità rapida (tutti i default)
  python3 install-checkmk-sync.py --quick

  # Con categoria specifica e intervallo git custom
  python3 install-checkmk-sync.py --category script-check-ubuntu --git-interval 60

  # Deploy tutte le categorie, non interattivo
  python3 install-checkmk-sync.py --all-categories --quick
        """,
    )
    p.add_argument("--repo", default=str(REPO_DEFAULT_PATH),
                   help=f"Path repository locale (default: {REPO_DEFAULT_PATH})")
    p.add_argument("--repo-url", default=REPO_URL_DEFAULT,
                   help="URL repository git (usato solo se repo non esiste)")
    p.add_argument("--target", default=LOCAL_TARGET_DEFAULT,
                   help=f"Path local checks target (default: {LOCAL_TARGET_DEFAULT})")
    p.add_argument("--category", default="auto",
                   help="Categoria script-check-* o 'auto' (default: auto)")
    p.add_argument("--all-categories", action="store_true",
                   help="Sincronizza tutte le categorie script-check-*")
    p.add_argument("--scripts", default="",
                   help="Script specifici da deployare (nomi separati da virgola, senza .py)")
    p.add_argument("--temp", action="store_true",
                   help="Deploy in /tmp/checkmk-sync-preview/ invece di --target (anteprima)")
    p.add_argument("--git-interval", type=int, default=None,
                   help="Intervallo git pull in secondi (default: chiesto interattivamente)")
    p.add_argument("--quick", action="store_true",
                   help="Modalità non-interattiva: usa tutti i default senza domande")
    return p.parse_args()


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    args = parse_args()
    require_root()

    repo_path = Path(args.repo)
    openwrt = is_openwrt()
    use_systemd = has_systemd() and not openwrt

    # ── Header ───────────────────────────────────────────────────────────────
    print("=" * 52)
    print(f"  install-checkmk-sync.py v{VERSION}")
    print("  Installer unificato CheckMK auto-sync")
    print("=" * 52)
    print()
    print(f"  Sistema:    {'systemd' if use_systemd else 'cron (OpenWrt/non-systemd)'}")
    print(f"  Repository: {repo_path}")
    print(f"  Target:     {args.target}")
    print()

    # ── STEP 0: Prerequisiti ─────────────────────────────────────────────────
    print("── STEP 0: Prerequisiti ──────────────────────────────")
    pkg_mgr = detect_pkg_manager()
    ensure_git(pkg_mgr)
    ensure_repo(repo_path, args.repo_url)
    update_repo(repo_path)
    owner = get_repo_owner(repo_path)
    print(f"[OK] Owner repository: {owner}")

    # ── STEP 1: Auto Git Sync ─────────────────────────────────────────────────
    print()
    print("── STEP 1: Auto Git Sync ─────────────────────────────")

    if args.quick or args.git_interval is not None:
        interval = args.git_interval or 60
    else:
        interval = ask_interval()

    if use_systemd:
        install_git_sync_systemd(repo_path, interval, owner)
    else:
        install_git_sync_cron(repo_path)

    # ── STEP 2: Python Full Sync ──────────────────────────────────────────────
    print()
    print("── STEP 2: Python Full Sync (deploy local checks) ────")

    scripts = args.scripts
    temp_dir = "/tmp/checkmk-sync-preview" if args.temp else ""

    if args.quick:
        category = args.category
        all_cat = args.all_categories
    else:
        # Modalità interattiva: selezione granulare
        if not scripts and not args.all_categories:
            scripts, all_cat, temp_dir = ask_scripts(repo_path)
            category = args.category
        else:
            category = args.category
            all_cat = args.all_categories

    if scripts:
        print(f"[INFO] Script selezionati: {scripts}")
    else:
        print(f"[INFO] Categoria: {'TUTTE' if all_cat else category}")
    if temp_dir:
        print(f"[INFO] Modalità: ANTEPRIMA → {temp_dir}")

    if use_systemd:
        install_python_sync_systemd(repo_path, args.target, category, all_cat,
                                    scripts=scripts, temp_dir=temp_dir)
    else:
        install_python_sync_cron(repo_path, args.target, category, all_cat,
                                 scripts=scripts, temp_dir=temp_dir)

    # ── Riepilogo finale ──────────────────────────────────────────────────────
    print()
    print("=" * 52)
    print("  Installazione Completata!")
    print("=" * 52)
    print()
    if use_systemd:
        print("  Servizi installati:")
        print(f"  ✓ auto-git-sync.timer          (git pull ogni {interval}s)")
        print(f"  ✓ checkmk-python-full-sync.timer (deploy ogni 5min)")
        print()
        print("  Comandi utili:")
        print(f"  systemctl status {GIT_SYNC_TIMER_NAME}")
        print(f"  systemctl status {PYTHON_SYNC_TIMER_NAME}")
        print(f"  journalctl -u auto-git-sync -f")
        print(f"  journalctl -u checkmk-python-full-sync -f")
    else:
        print("  Cron jobs installati:")
        print(f"  ✓ git-auto-sync      (ogni minuto)")
        print(f"  ✓ python-full-sync   (ogni 5 minuti)")
        print()
        print("  Verifica: crontab -l")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
