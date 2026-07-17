#!/usr/bin/env python3
"""check_apk_packages.py - CheckMK APK packages check.

Installed package count via `apk info` (stable CLI interface).
Pending updates via nethsec.inventory.info_package_updates_available().
APKINDEX age from /var/cache/apk.
Recent installs/removes from /var/log/apk.log.
/overlay disk usage from shutil.
"""

import subprocess
import sys
import time
from pathlib import Path

VERSION = "1.1.0"
SERVICE = "APK.Packages"

try:
    from euci import EUci
    EUCI_AVAILABLE = True
except ImportError:
    EUci = None
    EUCI_AVAILABLE = False


def get_installed_count():
    """Count installed packages via `apk info` (stable CLI interface).

    The previous implementation counted "\\nP:" occurrences in the raw
    /lib/apk/db/installed index file - an internal on-disk format, not a
    stable interface, unlike the documented migration-guide intent of using
    the apk CLI directly.
    """
    try:
        result = subprocess.run(
            ["apk", "info"], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return len([l for l in result.stdout.splitlines() if l.strip()])
    except Exception:
        pass
    return 0


def get_updates_available():
    """Whether package updates are available, via nethsec.inventory.

    The previous implementation had `updates_available = 0` as a dead
    constant, never reassigned anywhere in the file, yet reported
    unconditionally as perfdata - the check always claimed zero pending
    updates regardless of reality. Note: the library function returns a
    boolean (any update available or not), not a count - perfdata below
    reflects that (0/1 flag), not a package count.
    """
    if not EUCI_AVAILABLE:
        return False
    try:
        from nethsec.inventory import info_package_updates_available
        with EUci() as u:
            return bool(info_package_updates_available(u))
    except Exception:
        return False


def main():
    installed_count = get_installed_count()
    updates_available = 1 if get_updates_available() else 0

    # APKINDEX age
    last_update_age = 0
    cache_dir = Path("/var/cache/apk")
    if cache_dir.is_dir():
        mtimes = []
        for f in cache_dir.rglob("*"):
            if f.is_file() and "APKINDEX" in f.name:
                mtimes.append(int(f.stat().st_mtime))
        if mtimes:
            last_update_age = int((time.time() - max(mtimes)) / 86400)

    # Recent installs/removes
    recent_installs = 0
    recent_removes = 0
    for log_path in [Path("/var/log/apk.log"), Path("/var/log/messages")]:
        if log_path.exists():
            try:
                for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if "apk" not in line:
                        continue
                    if "add" in line or "install" in line:
                        recent_installs += 1
                    if "del" in line or "remove" in line:
                        recent_removes += 1
            except Exception:
                pass
            break

    # /overlay disk usage
    overlay_used_pct = 0
    overlay_free = 0
    try:
        import shutil
        du = shutil.disk_usage("/overlay")
        overlay_free = int(du.free / 1024)
        overlay_used_pct = int((du.used * 100) / du.total) if du.total else 0
    except Exception:
        pass

    # Status determination
    if overlay_used_pct >= 95:
        st, txt = 2, f"CRITICAL - /overlay: {overlay_used_pct}%"
    elif overlay_used_pct >= 85:
        st, txt = 1, f"WARNING - /overlay: {overlay_used_pct}%"
    elif last_update_age >= 30:
        st, txt = 1, f"WARNING - APKINDEX outdated ({last_update_age}d)"
    else:
        st, txt = 0, f"OK - ~{installed_count} packages"

    print(
        f"{st} {SERVICE} - {txt} "
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
