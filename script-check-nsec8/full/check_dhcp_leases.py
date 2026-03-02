#!/usr/bin/env python3
"""check_dhcp_leases.py - CheckMK local check DHCP leases (Python puro)."""

import subprocess
import sys
import time
from pathlib import Path

VERSION = "1.1.0"
SERVICE = "DHCP.Leases"
LEASE_FILE = Path("/tmp/dhcp.leases")


def uci_get(path: str, default: int) -> int:
    result = subprocess.run(["uci", "get", path], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False)
    if result.returncode != 0:
        return default
    value = (result.stdout or "").strip()
    return int(value) if value.isdigit() else default


def main() -> int:
    if not LEASE_FILE.exists():
        print("1 DHCP_Leases - File leases non trovato")
        return 0

    now = int(time.time())
    active_leases = 0
    expired_leases = 0
    total_leases = 0

    for line in LEASE_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        parts = line.split()
        if len(parts) < 1:
            continue
        total_leases += 1
        expire = int(parts[0]) if parts[0].isdigit() else 0
        if expire > now:
            active_leases += 1
        else:
            expired_leases += 1

    max_leases = uci_get("dhcp.lan.limit", 150)
    percent = int((active_leases * 100 / max_leases)) if max_leases > 0 else 0

    if percent >= 90:
        status, status_text = 2, "CRITICAL"
    elif percent >= 80:
        status, status_text = 1, "WARNING"
    else:
        status, status_text = 0, "OK"

    warn = int(max_leases * 80 / 100)
    crit = int(max_leases * 90 / 100)
    print(
        f"{status} {SERVICE} active={active_leases};{warn};{crit};0;{max_leases} "
        f"Lease attivi: {active_leases}/{max_leases} ({percent}%) - {status_text} "
        f"| active={active_leases} expired={expired_leases} total={total_leases} max={max_leases} percent={percent}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
