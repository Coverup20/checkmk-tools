#!/usr/bin/env python3
"""check_uptime.py - CheckMK uptime/load check.

Reads /proc/uptime and /proc/loadavg directly.
"""

import os
import sys
from pathlib import Path

VERSION = "1.1.0"
SERVICE = "Firewall.Uptime"

# Per-CPU load thresholds, matching doc/check_uptime.md.
LOAD_WARN = 0.8
LOAD_CRIT = 1.5


def main():
    uptime_path = Path("/proc/uptime")
    loadavg_path = Path("/proc/loadavg")

    if not uptime_path.exists():
        print(f"1 {SERVICE} - /proc/uptime not available")
        return 0

    uptime_sec = 0
    try:
        uptime_sec = int(float(uptime_path.read_text().split()[0]))
    except (IndexError, ValueError, OSError):
        pass

    days = uptime_sec // 86400
    hours = (uptime_sec % 86400) // 3600
    minutes = (uptime_sec % 3600) // 60

    l1 = l5 = l15 = 0.0
    # CPU count via os.cpu_count() - the previous /sys/devices/system/cpu/online
    # parsing assumed a single contiguous range ("0-N") and mis-parsed
    # non-contiguous ranges (e.g. "0-2,4-5" after a CPU hotplug event); its
    # fallback scanned plain /proc (not /proc/cpuinfo) for "cpuN" entries
    # that don't exist there, always finding nothing - net effect, a real
    # multi-core box could be silently treated as single-core, producing
    # false WARNING/CRITICAL under normal multi-core load.
    cpu = os.cpu_count() or 1
    if loadavg_path.exists():
        try:
            parts = loadavg_path.read_text().split()
            l1 = float(parts[0]) if len(parts) > 0 else 0.0
            l5 = float(parts[1]) if len(parts) > 1 else 0.0
            l15 = float(parts[2]) if len(parts) > 2 else 0.0
        except (IndexError, ValueError, OSError):
            pass

    if days > 0:
        up_str = f"{days}d {hours}h {minutes}m"
    elif hours > 0:
        up_str = f"{hours}h {minutes}m"
    else:
        up_str = f"{minutes}m"

    load_per_cpu = l1 / max(cpu, 1)
    if load_per_cpu >= LOAD_CRIT:
        st, txt = 2, "CRITICAL"
    elif load_per_cpu >= LOAD_WARN:
        st, txt = 1, "WARNING"
    else:
        st, txt = 0, "OK"

    # NOTE: the previous version hardcoded the CheckMK state field to "0"
    # here regardless of the computed txt/threshold - meaning this check
    # could NEVER actually alert in CheckMK no matter how high the load was
    # ("CRITICAL"/"WARNING" was only decorative text, not the real state).
    print(
        f"{st} {SERVICE} - Uptime: {up_str}, Load: {l1:.2f} {l5:.2f} {l15:.2f} ({cpu} CPU) - {txt}"
        f" | uptime_seconds={uptime_sec} load1={l1:.2f} load5={l5:.2f} load15={l15:.2f} cpu_count={cpu}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
