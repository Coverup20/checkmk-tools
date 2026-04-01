#!/usr/bin/env python3
"""check_uptime.py - CheckMK local check uptime/load (Python puro)."""

VERSION = "1.1.0"

import os
import sys
from pathlib import Path


def main() -> int:
    uptime_seconds = 0
    up = Path("/proc/uptime")
    if up.exists():
        first = up.read_text(encoding="utf-8", errors="ignore").split()[0]
        uptime_seconds = int(float(first))

    days = uptime_seconds // 86400
    hours = (uptime_seconds % 86400) // 3600
    minutes = (uptime_seconds % 3600) // 60

    load1 = load5 = load15 = 0.0
    loadavg = Path("/proc/loadavg")
    if loadavg.exists():
        fields = loadavg.read_text(encoding="utf-8", errors="ignore").split()
        if len(fields) >= 3:
            load1, load5, load15 = float(fields[0]), float(fields[1]), float(fields[2])

    cpu_count = os.cpu_count() or 1
    load1_norm = load1 / cpu_count

    if load1_norm > 1.5:
        status, status_text = 2, "CRITICAL - Load alto"
    elif load1_norm > 0.8:
        status, status_text = 1, "WARNING - Load elevato"
    else:
        status, status_text = 0, "OK"

    print(
        f"{status} Firewall.Uptime - Uptime: {days}d {hours}h {minutes}m, Load: {load1:.2f} {load5:.2f} {load15:.2f} ({cpu_count} CPU) - {status_text} "
        f"| uptime_seconds={uptime_seconds} load1={load1:.2f} load5={load5:.2f} load15={load15:.2f} cpu_count={cpu_count}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
