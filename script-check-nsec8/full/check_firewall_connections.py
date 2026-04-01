#!/usr/bin/env python3
"""check_firewall_connections.py - CheckMK local check conntrack (Python puro)."""

import sys
from pathlib import Path

SERVICE = "Firewall.Connections"


def read_int(path: str) -> int:
    return int(Path(path).read_text(encoding="utf-8", errors="ignore").strip())


def main() -> int:
    count_path = Path("/proc/sys/net/netfilter/nf_conntrack_count")
    max_path = Path("/proc/sys/net/netfilter/nf_conntrack_max")
    if not count_path.exists() or not max_path.exists():
        print("1 Firewall.Connections - Conntrack non disponibile")
        return 0

    current = read_int(str(count_path))
    max_value = read_int(str(max_path))
    percent = int(current * 100 / max_value) if max_value > 0 else 0

    if percent >= 90:
        status, status_text = 2, "CRITICAL"
    elif percent >= 80:
        status, status_text = 1, "WARNING"
    else:
        status, status_text = 0, "OK"

    warn = int(max_value * 80 / 100)
    crit = int(max_value * 90 / 100)
    print(
        f"{status} {SERVICE} connections={current};{warn};{crit};0;{max_value} "
        f"Connessioni attive: {current}/{max_value} ({percent}%) - Status: {status_text} "
        f"| current={current} max={max_value} percent={percent}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
