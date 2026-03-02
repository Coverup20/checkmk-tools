#!/usr/bin/env python3
"""check_opkg_packages.py - CheckMK local check OPKG packages (Python puro)."""

import shutil
import subprocess
import sys
import time
from pathlib import Path

SERVICE = "OPKG.Packages"


def run_lines(cmd: list[str], timeout: int = 15) -> list[str]:
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=timeout, check=False)
    return (result.stdout or "").splitlines()


def main() -> int:
    if shutil.which("opkg") is None:
        print("2 OPKG_Packages - opkg non disponibile")
        return 0

    installed_count = len(run_lines(["opkg", "list-installed"]))
    updates_available = len(run_lines(["opkg", "list-upgradable"], timeout=10))

    last_update_age = 0
    lists_dir = Path("/var/opkg-lists")
    if lists_dir.exists():
        mtimes = [int(path.stat().st_mtime) for path in lists_dir.glob("*") if path.is_file()]
        if mtimes:
            last_update_age = int((time.time() - max(mtimes)) / 86400)

    recent_installs = 0
    recent_removes = 0
    log_file = Path("/var/log/messages")
    if log_file.exists():
        content = log_file.read_text(encoding="utf-8", errors="ignore")
        recent_installs = content.count("opkg") if "install" in content else 0
        recent_removes = content.count("remove") if "opkg" in content else 0

    overlay_used_pct = 0
    overlay_free = 0
    try:
        usage = shutil.disk_usage("/overlay")
        overlay_free = int(usage.free / 1024)
        overlay_used_pct = int((usage.used * 100) / usage.total) if usage.total else 0
    except Exception:
        pass

    if overlay_used_pct >= 95:
        status, status_text = 2, f"CRITICAL - Spazio /overlay: {overlay_used_pct}%"
    elif overlay_used_pct >= 85:
        status, status_text = 1, f"WARNING - Spazio /overlay: {overlay_used_pct}%"
    elif updates_available >= 10:
        status, status_text = 1, f"WARNING - {updates_available} aggiornamenti disponibili"
    elif last_update_age >= 30:
        status, status_text = 1, f"WARNING - Lista pacchetti obsoleta ({last_update_age} giorni)"
    elif updates_available > 0:
        status, status_text = 0, f"OK - {updates_available} aggiornamenti disponibili"
    else:
        status, status_text = 0, f"OK - {installed_count} pacchetti installati"

    print(
        f"{status} {SERVICE} installed={installed_count} updates={updates_available};10;20;0 "
        f"overlay_used_pct={overlay_used_pct};85;95;0;100 - {status_text} "
        f"| installed={installed_count} updates_available={updates_available} overlay_free_kb={overlay_free} overlay_used_pct={overlay_used_pct} "
        f"last_update_age_days={last_update_age} recent_installs={recent_installs} recent_removes={recent_removes}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
