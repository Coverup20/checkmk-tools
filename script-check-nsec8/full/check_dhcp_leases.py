#!/usr/bin/env python3
"""check_dhcp_leases.py - CheckMK local check DHCP leases (Python puro)."""

import subprocess
import sys
import time
from pathlib import Path

VERSION = "1.2.1"
SERVICE = "DHCP.Leases"
LEASE_FILE = Path("/tmp/dhcp.leases")


def get_total_max_leases() -> int:
    """Somma i limit di tutti i pool DHCP attivi (ignora sezioni con ignore=1).
    Gestisce correttamente firewall con multiple interfacce logiche."""
    result = subprocess.run(["uci", "show", "dhcp"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False)
    if result.returncode != 0:
        return 150  # fallback

    sections: dict = {}
    for line in result.stdout.splitlines():
        if '=' not in line:
            continue
        key, _, value = line.partition('=')
        key = key.strip()
        value = value.strip().strip("'")
        parts = key.split('.')
        if len(parts) == 2:
            sec = parts[1]
            if sec not in sections:
                sections[sec] = {}
            sections[sec]['_type'] = value
        elif len(parts) == 3:
            sec = parts[1]
            field = parts[2]
            if sec not in sections:
                sections[sec] = {}
            sections[sec][field] = value

    total = 0
    for fields in sections.values():
        if fields.get('_type') != 'dhcp':
            continue
        if fields.get('ignore') == '1':
            continue
        try:
            total += int(fields.get('limit', 0))
        except ValueError:
            pass

    return total if total > 0 else 150


def main() -> int:
    if not LEASE_FILE.exists():
        print("1 DHCP.Leases - File leases non trovato")
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

    max_leases = get_total_max_leases()
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
