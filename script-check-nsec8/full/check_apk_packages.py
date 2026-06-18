#!/usr/bin/env python3
"""check_apk_packages.py - CheckMK local check APK packages."""

import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

SERVICE = "APK.Packages"


def run_lines(cmd, timeout=15):
    result = subprocess.run(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True,
                            timeout=timeout, check=False)
    return (result.stdout or "").splitlines()


def count_apk_events(log_path, install_terms, remove_terms):
    """Count apk install/remove events from log file.

    A line counts only when it contains both 'apk' and the relevant term.
    """
    installs = 0
    removes = 0
    try:
        text = log_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return 0, 0

    for line in text.splitlines():
        if "apk" not in line:
            continue
        for term in install_terms:
            if term in line:
                installs += 1
                break
        for term in remove_terms:
            if term in line:
                removes += 1
                break
    return installs, removes


def main():
    if shutil.which("apk") is None:
        print(f"2 {SERVICE} - apk not available")
        return 0

    # 1. Installed packages count
    installed_count = len(run_lines(["apk", "info"]))

    # 2. Available upgrades
    # apk list --upgradable output lines contain {package-name} (new-version) [upgrade]
    # Ignore blank lines and warning lines that are not package results.
    upgradable_lines = run_lines(["apk", "list", "--upgradable"], timeout=10)
    updates_available = 0
    for line in upgradable_lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("WARNING:") or line.startswith("ERROR:"):
            continue
        # A real package line contains '{' and '}' with the package name
        if "{" in line and "}" in line:
            updates_available += 1

    # 3. Repository index age
    last_update_age = 0
    cache_dir = Path("/var/cache/apk")
    if cache_dir.is_dir():
        mtimes = []
        for f in cache_dir.rglob("*"):
            if f.is_file() and "APKINDEX" in f.name:
                mtimes.append(int(f.stat().st_mtime))
        if mtimes:
            last_update_age = int((time.time() - max(mtimes)) / 86400)

    # 4. Recent installs / removals from apk log
    recent_installs = 0
    recent_removes = 0
    for log_candidate in ["/var/log/apk.log", "/var/log/messages"]:
        lp = Path(log_candidate)
        if lp.is_file():
            recent_installs, recent_removes = count_apk_events(
                lp,
                install_terms=["add", "install"],
                remove_terms=["del", "remove"],
            )
            break

    # 5. /overlay disk usage
    overlay_used_pct = 0
    overlay_free = 0
    try:
        usage = shutil.disk_usage("/overlay")
        overlay_free = int(usage.free / 1024)
        overlay_used_pct = int((usage.used * 100) / usage.total) if usage.total else 0
    except Exception:
        pass

    # 6. Status determination
    if overlay_used_pct >= 95:
        status = 2
        status_text = f"CRITICAL - /overlay space: {overlay_used_pct}%"
    elif overlay_used_pct >= 85:
        status = 1
        status_text = f"WARNING - /overlay space: {overlay_used_pct}%"
    elif updates_available >= 10:
        status = 1
        status_text = f"WARNING - {updates_available} updates available"
    elif last_update_age >= 30:
        status = 1
        status_text = f"WARNING - Package list outdated ({last_update_age} days)"
    elif updates_available > 0:
        status = 0
        status_text = f"OK - {updates_available} updates available"
    else:
        status = 0
        status_text = f"OK - {installed_count} packages installed"

    print(
        f"{status} {SERVICE} - {status_text} "
        f"| installed={installed_count} "
        f"updates_available={updates_available} "
        f"overlay_free_kb={overlay_free} "
        f"overlay_used_pct={overlay_used_pct} "
        f"last_update_age_days={last_update_age} "
        f"recent_installs={recent_installs} "
        f"recent_removes={recent_removes}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
