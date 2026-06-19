#!/usr/bin/env python3
"""check_uptime.py - CheckMK uptime/load check (pyuci beta).

Already Python-native: reads /proc/uptime and /proc/loadavg directly.
Beta adds pyuci import check and identifies itself as beta.
"""

import os
import sys
from pathlib import Path

BETA = True
VERSION = "1.1.0b1"
SERVICE = "Firewall.Uptime"

try:
    from euci import EUci
except ImportError:
    EUci = None


def main():
    up_sec = 0
    up = Path("/proc/uptime")
    if up.exists():
        parts = up.read_text().split()
        if parts:
            up_sec = int(float(parts[0]))

    days = up_sec // 86400
    hours = (up_sec % 86400) // 3600
    mins = (up_sec % 3600) // 60

    l1 = l5 = l15 = 0.0
    la = Path("/proc/loadavg")
    if la.exists():
        f = la.read_text().split()
        if len(f) >= 3:
            l1, l5, l15 = float(f[0]), float(f[1]), float(f[2])

    cpu = os.cpu_count() or 1
    norm = l1 / cpu

    if norm > 1.5:
        st, txt = 2, "CRITICAL - Load alto"
    elif norm > 0.8:
        st, txt = 1, "WARNING - Load elevato"
    else:
        st, txt = 0, "OK"

    print(
        f"{st} {SERVICE} - Uptime: {days}d {hours}h {mins}m, "
        f"Load: {l1:.2f} {l5:.2f} {l15:.2f} ({cpu} CPU) - {txt} [beta]"
        f" | uptime_seconds={up_sec} load1={l1:.2f} load5={l5:.2f} "
        f"load15={l15:.2f} cpu_count={cpu}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
