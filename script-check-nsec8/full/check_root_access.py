#!/usr/bin/env python3
"""check_root_access.py - CheckMK local check root access (Python puro)."""

VERSION = "1.1.0"

import re
import subprocess
import sys
from pathlib import Path

LOG_FILE = Path("/var/log/messages")


def main() -> int:
    who = subprocess.run(["who"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False)
    active_sessions = sum(1 for line in (who.stdout or "").splitlines() if line.startswith("root"))

    successful_logins = 0
    failed_logins = 0
    recent_ips: list[str] = []
    if LOG_FILE.exists():
        for line in LOG_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()[-500:]:
            lower = line.lower()
            if ("accepted password" in lower or "accepted publickey" in lower) and " for root" in lower:
                successful_logins += 1
                match = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", line)
                if match:
                    recent_ips.append(match.group(1))
            if ("failed password" in lower or "authentication failure" in lower) and " for root" in lower:
                failed_logins += 1

    unique_ips = len(set(recent_ips))

    if failed_logins >= 10:
        status, status_text = 2, f"CRITICAL - Troppi tentativi falliti ({failed_logins})"
    elif failed_logins >= 5:
        status, status_text = 1, f"WARNING - Tentativi falliti: {failed_logins}"
    elif active_sessions > 2:
        status, status_text = 1, f"WARNING - Troppe sessioni root attive: {active_sessions}"
    elif successful_logins > 0 or active_sessions > 0:
        status, status_text = 0, f"OK - Accessi: {successful_logins}, Sessioni attive: {active_sessions}"
    else:
        status, status_text = 0, "OK - Nessun accesso recente"

    print(
        f"{status} Root.Access sessions={active_sessions};2;3;0 logins={successful_logins} failed={failed_logins};5;10;0 - {status_text} "
        f"| active_sessions={active_sessions} successful_logins={successful_logins} failed_logins={failed_logins} unique_ips={unique_ips}"
    )
    if recent_ips:
        print(f"0 Root.AccessIPs - Recent IPs: {' '.join(sorted(set(recent_ips))[:5])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
