#!/usr/bin/env python3
"""upgrade-checkmk.py

Python wrapper for upgrade-checkmk.sh with outcome management for automations/emails:
- No updates available
- Update completed with final version
- Update failed with rollback performed

Version: 1.1.1"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

VERSION = "1.1.1"
REPORT_FILE = Path("/tmp/checkmk-upgrade-report.txt")
BACKUP_DIR = Path("/opt/omd/backups")
EMAIL_FROM = "no-reply@nethesis.it"


def detect_shell_backend() -> Path | None:
    candidates = [
        Path(__file__).with_name("upgrade-checkmk.sh"),
        Path("/usr/local/bin/upgrade-checkmk.sh"),
        Path("/opt/checkmk-tools/script-tools/full/upgrade_maintenance/upgrade-checkmk.sh"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def run_cmd(cmd: list[str], check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=check)


def read_report() -> str:
    if not REPORT_FILE.exists():
        return ""
    return REPORT_FILE.read_text(encoding="utf-8", errors="ignore")


def detect_site_from_report(report: str) -> str:
    match = re.search(r"^Sito:\s*(\S+)", report, re.MULTILINE)
    if match:
        return match.group(1)

    sites = run_cmd(["omd", "sites"])
    for line in sites.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("SITE"):
            continue
        return line.split()[0]
    return ""


def get_current_version(site_name: str) -> str:
    if not site_name:
        return "unknown"
    out = run_cmd(["omd", "version", site_name])
    match = re.search(r"[0-9]+\.[0-9]+\.[0-9]+p[0-9]+", out.stdout)
    return match.group(0) if match else "unknown"


def get_latest_backup(site_name: str) -> Path | None:
    if not site_name or not BACKUP_DIR.exists():
        return None
    candidates = sorted(BACKUP_DIR.glob(f"{site_name}_pre-upgrade_*.tar.gz"), reverse=True)
    return candidates[0] if candidates else None


def execute_rollback(site_name: str, backup_file: Path) -> tuple[bool, str]:
    if not site_name:
        return False, "site non determinato"
    if not backup_file.exists():
        return False, f"backup non trovato: {backup_file}"

    stop_res = run_cmd(["omd", "stop", site_name])
    if stop_res.returncode not in (0,):
        return False, f"stop fallito: {stop_res.stderr.strip() or stop_res.stdout.strip()}"

    restore_res = run_cmd(["omd", "restore", site_name, str(backup_file)])
    if restore_res.returncode != 0:
        return False, f"restore fallito: {restore_res.stderr.strip() or restore_res.stdout.strip()}"

    start_res = run_cmd(["omd", "start", site_name])
    if start_res.returncode != 0:
        return False, f"start post-rollback fallito: {start_res.stderr.strip() or start_res.stdout.strip()}"

    return True, "rollback eseguito"


def send_mail(recipient: str, subject: str, body: str) -> None:
    if not recipient:
        return
    cmd = ["mail", "-r", EMAIL_FROM, "-s", subject, recipient]
    result = subprocess.run(cmd, input=body, text=True, capture_output=True)
    if result.returncode != 0:
        subprocess.run(["mail", "-s", subject, recipient], input=body, text=True, capture_output=True)


def build_message(status: str, site_name: str, version: str, details: str = "") -> tuple[str, str]:
    host = os.uname().nodename
    if status == "NO_UPDATE":
        subject = f"CheckMK Auto-Upgrade - Nessun aggiornamento ({host})"
        body = f"Nessun aggiornamento disponibile per il sito {site_name}.\nVersione corrente: {version}\n"
    elif status == "SUCCESS":
        subject = f"CheckMK Auto-Upgrade - Completato ({host})"
        body = f"Aggiornamento completato alla versione: {version}\nSito: {site_name}\n"
    elif status == "FAILED_ROLLBACK":
        subject = f"CheckMK Auto-Upgrade - Fallito con rollback ({host})"
        body = f"Aggiornamento fallito: eseguito rollback.\nSito: {site_name}\nDettagli: {details}\n"
    else:
        subject = f"CheckMK Auto-Upgrade - Fallito ({host})"
        body = f"Aggiornamento fallito e rollback non eseguito.\nSito: {site_name}\nDettagli: {details}\n"
    return subject, body


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Wrapper upgrade-checkmk con esiti strutturati")
    parser.add_argument("--email", default="", help="Email destinatario report esito")
    parser.add_argument("forward_args", nargs=argparse.REMAINDER, help="Argomenti da inoltrare allo script shell")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    script = detect_shell_backend()
    if script is None:
        print(
            "ERROR: missing target script: upgrade-checkmk.sh "
            "(checked: sibling, /usr/local/bin, /opt/checkmk-tools/script-tools/full/upgrade_maintenance)",
            file=sys.stderr,
        )
        return 1

    forward = args.forward_args
    if forward and forward[0] == "--":
        forward = forward[1:]

    run = subprocess.run(["bash", str(script), *forward], text=True)
    report = read_report()
    site_name = detect_site_from_report(report)

    no_update = "Nessun aggiornamento necessario" in report
    if run.returncode == 0 and no_update:
        version = get_current_version(site_name)
        subject, body = build_message("NO_UPDATE", site_name, version)
        send_mail(args.email, subject, body)
        print(f"NO_UPDATE: sito {site_name} già alla versione {version}")
        return 0

    if run.returncode == 0:
        version = get_current_version(site_name)
        subject, body = build_message("SUCCESS", site_name, version)
        send_mail(args.email, subject, body)
        print(f"SUCCESS: aggiornamento completato alla versione {version}")
        return 0

    backup = get_latest_backup(site_name)
    if backup is not None:
        rollback_ok, detail = execute_rollback(site_name, backup)
        if rollback_ok:
            subject, body = build_message("FAILED_ROLLBACK", site_name, get_current_version(site_name), detail)
            send_mail(args.email, subject, body)
            print("FAILED_ROLLBACK: aggiornamento fallito, eseguito rollback")
            return 2
        subject, body = build_message("FAILED", site_name, get_current_version(site_name), detail)
        send_mail(args.email, subject, body)
        print(f"FAILED: aggiornamento fallito, rollback non riuscito ({detail})")
        return 1

    subject, body = build_message("FAILED", site_name, "unknown", "backup non disponibile")
    send_mail(args.email, subject, body)
    print("FAILED: aggiornamento fallito, rollback non eseguito (backup non disponibile)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
