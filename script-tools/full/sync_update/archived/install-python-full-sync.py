#!/usr/bin/env python3
"""
install-python-full-sync.py - Installer systemd per sync Python full checks

Crea:
- checkmk-python-full-sync.service (oneshot)
- checkmk-python-full-sync.timer (ogni 5 minuti)

Version: 1.3.0
"""

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List

VERSION = "1.3.0"
SYSTEMD_DIR = Path("/etc/systemd/system")
SERVICE_NAME = "checkmk-python-full-sync.service"
TIMER_NAME = "checkmk-python-full-sync.timer"
DEFAULT_SYNC_SCRIPT = Path("/opt/checkmk-tools/script-tools/full/sync_update/sync-python-full-checks.py")
DEFAULT_REPO_URL = "https://github.com/Coverup20/checkmk-tools.git"
CRON_LOG_FILE = "/var/log/checkmk-python-full-sync.log"


def run(cmd: List[str]) -> None:
    subprocess.run(cmd, check=True)


def run_capture(cmd: List[str], cwd: str = "") -> subprocess.CompletedProcess:
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


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def ensure_python_executable(script_path: Path) -> None:
    if not script_path.exists():
        print(f"[ERROR] Script sync non trovato: {script_path}", file=sys.stderr)
        sys.exit(1)

    current_mode = script_path.stat().st_mode
    script_path.chmod(current_mode | 0o111)


def detect_package_manager() -> str:
    if shutil.which("apt-get"):
        return "apt"
    if shutil.which("dnf"):
        return "dnf"
    if shutil.which("yum"):
        return "yum"
    return ""


def ensure_git_installed() -> None:
    if shutil.which("git"):
        return

    package_manager = detect_package_manager()
    if not package_manager:
        print("[ERROR] git non trovato e package manager non supportato", file=sys.stderr)
        sys.exit(1)

    print(f"[INFO] git non trovato, installazione via {package_manager}...")
    if package_manager == "apt":
        run(["apt-get", "update", "-y"])
        run(["apt-get", "install", "-y", "git"])
    elif package_manager == "dnf":
        run(["dnf", "-y", "makecache"])
        run(["dnf", "install", "-y", "git"])
    elif package_manager == "yum":
        run(["yum", "-y", "makecache"])
        run(["yum", "install", "-y", "git"])


def ensure_repo(repo_path: Path, repo_url: str) -> None:
    git_dir = repo_path / ".git"
    if git_dir.exists():
        return

    if repo_path.exists() and any(repo_path.iterdir()):
        print(f"[ERROR] Path repo esiste ma non è git: {repo_path}", file=sys.stderr)
        sys.exit(1)

    repo_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[INFO] Clonazione repository in {repo_path}...")
    run(["git", "clone", repo_url, str(repo_path)])


def update_repo(repo_path: Path) -> None:
    result = run_capture(["git", "-C", str(repo_path), "pull", "--ff-only"])
    output = (result.stdout or "").strip()
    if result.returncode == 0:
        if output:
            print(f"[INFO] git pull: {output.splitlines()[-1]}")
        else:
            print("[INFO] git pull: OK")
        return

    if "Unknown option: -C" in output:
        legacy = run_capture(["git", "pull", "--ff-only"], cwd=str(repo_path))
        if legacy.returncode == 0:
            legacy_out = (legacy.stdout or "").strip()
            if legacy_out:
                print(f"[INFO] git pull: {legacy_out.splitlines()[-1]}")
            else:
                print("[INFO] git pull: OK")
            return

    print(f"[WARN] git pull fallito: {output}")

    lower_output = output.lower()
    needs_autoheal = (
        "would be overwritten by merge" in lower_output
        or "please commit your changes or stash them" in lower_output
        or "your local changes" in lower_output
    )

    if not needs_autoheal:
        return

    print("[WARN] Auto-heal repo: tentativo stash modifiche locali + retry git pull")
    stash_msg = f"autoheal-install-python-full-sync-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    stash_result = run_capture(
        ["git", "-C", str(repo_path), "stash", "push", "--include-untracked", "-m", stash_msg]
    )
    stash_output = (stash_result.stdout or "").strip()
    if stash_result.returncode == 0:
        if stash_output:
            print(f"[INFO] git stash: {stash_output.splitlines()[-1]}")
        else:
            print("[INFO] git stash: OK")
    else:
        print(f"[WARN] git stash fallito: {stash_output}")

    retry = run_capture(["git", "-C", str(repo_path), "pull", "--ff-only"])
    retry_output = (retry.stdout or "").strip()
    if retry.returncode == 0:
        if retry_output:
            print(f"[INFO] git pull retry: {retry_output.splitlines()[-1]}")
        else:
            print("[INFO] git pull retry: OK")
        return

    print(f"[WARN] git pull retry fallito: {retry_output}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Installa timer systemd per sync script Python full")
    parser.add_argument(
        "--sync-script",
        default=str(DEFAULT_SYNC_SCRIPT),
        help="Path script sync-python-full-checks.py",
    )
    parser.add_argument(
        "--repo",
        default="/opt/checkmk-tools",
        help="Path repository locale",
    )
    parser.add_argument(
        "--repo-url",
        default=DEFAULT_REPO_URL,
        help="URL repository git da clonare se assente",
    )
    parser.add_argument(
        "--target",
        default="/usr/lib/check_mk_agent/local",
        help="Path local checks target",
    )
    parser.add_argument(
        "--category",
        default="auto",
        help="Categoria script-check-* o auto",
    )
    parser.add_argument(
        "--all-categories",
        action="store_true",
        help="Sincronizza tutte le categorie script-check-*",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Modalità rapida (stessi default, pensata per lancio senza complessità).",
    )
    parser.add_argument(
        "--auto-tier-by-runtime",
        dest="auto_tier_by_runtime",
        action="store_true",
        help="Abilita profiling runtime e deploy in local/60|100|150|200.",
    )
    parser.add_argument(
        "--no-auto-tier-by-runtime",
        dest="auto_tier_by_runtime",
        action="store_false",
        help="Disabilita profiling runtime (forza deploy root tradizionale).",
    )
    parser.set_defaults(auto_tier_by_runtime=None)
    return parser.parse_args()


def setup_cron_fallback(exec_cmd: List[str]) -> None:
    cron_line = f"*/5 * * * * {' '.join(exec_cmd)} >> {CRON_LOG_FILE} 2>&1"

    existing = run_capture(["crontab", "-l"])
    current_lines = []
    if existing.returncode == 0:
        current_lines = [line for line in (existing.stdout or "").splitlines() if "sync-python-full-checks.py" not in line]

    current_lines.append(cron_line)
    new_content = "\n".join(current_lines).strip() + "\n"

    temp_path = Path("/tmp/checkmk-python-full-sync.cron")
    temp_path.write_text(new_content, encoding="utf-8")
    run(["crontab", str(temp_path)])
    print("[OK] systemd non disponibile: configurato fallback cron ogni 5 minuti")
    print(f"[OK] Cron: {cron_line}")


def main() -> int:
    args = parse_args()
    require_root()

    repo_path = Path(args.repo)
    ensure_git_installed()
    ensure_repo(repo_path, args.repo_url)
    update_repo(repo_path)

    sync_script = Path(args.sync_script)
    if not sync_script.exists() and repo_path.exists():
        candidate = repo_path / "script-tools/full/sync_update/sync-python-full-checks.py"
        if candidate.exists():
            sync_script = candidate

    ensure_python_executable(sync_script)

    py_bin = shutil.which("python3")
    if not py_bin:
        print("[ERROR] python3 non trovato nel PATH", file=sys.stderr)
        return 1

    cmd = [
        py_bin,
        str(sync_script),
        "--repo",
        str(repo_path),
        "--target",
        args.target,
    ]

    if args.all_categories:
        cmd.append("--all-categories")
    else:
        cmd.extend(["--category", args.category])

    enable_auto_tier = args.auto_tier_by_runtime
    if enable_auto_tier is None:
        enable_auto_tier = (not args.all_categories) and args.category in {"auto", "script-check-proxmox"}
    if enable_auto_tier:
        cmd.append("--auto-tier-by-runtime")

    service_content = f"""[Unit]
Description=CheckMK Python Full Checks Sync
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart={' '.join(cmd)}
"""

    timer_content = """[Unit]
Description=Run CheckMK Python Full Checks Sync every 5 minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min
Persistent=true

[Install]
WantedBy=timers.target
"""

    service_path = SYSTEMD_DIR / SERVICE_NAME
    timer_path = SYSTEMD_DIR / TIMER_NAME

    if not SYSTEMD_DIR.exists():
        setup_cron_fallback(cmd)
        run(cmd)
        print(f"[OK] install-python-full-sync.py v{VERSION}")
        print(f"[OK] Repo:    {repo_path}")
        print("[OK] Mode:    cron-fallback")
        return 0

    write_text(service_path, service_content)
    write_text(timer_path, timer_content)

    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", "--now", TIMER_NAME])
    run(["systemctl", "start", SERVICE_NAME])

    print(f"[OK] install-python-full-sync.py v{VERSION}")
    print(f"[OK] Repo:    {repo_path}")
    print(f"[OK] Service: {service_path}")
    print(f"[OK] Timer:   {timer_path}")
    print(f"[OK] Verifica: systemctl status {TIMER_NAME} --no-pager")
    return 0


if __name__ == "__main__":
    sys.exit(main())
