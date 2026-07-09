#!/usr/bin/env python3
"""check_uptime.py - CheckMK uptime/load check.

Reads /proc/uptime and /proc/loadavg directly.
"""

import sys
from pathlib import Path

VERSION = "1.0.0"
SERVICE = "Firewall.Uptime"


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
    cpu = 1
    if loadavg_path.exists():
        try:
            parts = loadavg_path.read_text().split()
            l1 = float(parts[0]) if len(parts) > 0 else 0.0
            l5 = float(parts[1]) if len(parts) > 1 else 0.0
            l15 = float(parts[2]) if len(parts) > 2 else 0.0
            # CPU count from /proc/cpuinfo or nproc
            try:
                cpu = int(Path("/sys/devices/system/cpu/online").read_text().split("-")[-1]) + 1
            except Exception:
                try:
                    cpu = len([p for p in Path("/proc").iterdir() if p.name.startswith("cpu") and p.name[3:].isdigit()])
                except Exception:
                    cpu = 1
        except (IndexError, ValueError, OSError):
            pass

    if days > 0:
        up_str = f"{days}d {hours}h {minutes}m"
    elif hours > 0:
        up_str = f"{hours}h {minutes}m"
    else:
        up_str = f"{minutes}m"

    txt = "OK"
    if l1 / max(cpu, 1) > 5:
        txt = "CRITICAL"
    elif l1 / max(cpu, 1) > 2:
        txt = "WARNING"

    print(
        f"0 {SERVICE} - Uptime: {up_str}, Load: {l1:.2f} {l5:.2f} {l15:.2f} ({cpu} CPU) - {txt}"
        f" | uptime_seconds={uptime_sec} load1={l1:.2f} load5={l5:.2f} load15={l15:.2f} cpu_count={cpu}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
