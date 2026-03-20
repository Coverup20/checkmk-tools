#!/usr/bin/env python3
"""
check_disk_all.py - CheckMK Local Check Disk Usage (Copilot)

Monitora TUTTI i filesystem rilevanti con:
  - Soglie WARNING/CRITICAL configurabili
  - Perfdata per ogni filesystem (grafici CheckMK)
  - Esclusione automatica filesystem temporanei/virtuali
  - Output multi-linea: un servizio per filesystem

Version: 1.0.0
"""

import subprocess
import sys
from typing import List, Optional, Tuple

VERSION = "1.0.0"

# Soglie percentuale uso
WARN_PCT = 80
CRIT_PCT = 95

# Filesystem da escludere (tipo)
EXCLUDE_FSTYPES = {
    "tmpfs", "devtmpfs", "sysfs", "proc", "devpts",
    "securityfs", "cgroup", "cgroup2", "pstore",
    "bpf", "tracefs", "debugfs", "hugetlbfs",
    "mqueue", "fusectl", "overlay", "squashfs",
}

# Mount point da escludere
EXCLUDE_MOUNTS = {
    "/run", "/run/lock", "/dev/shm", "/sys",
    "/proc", "/dev", "/run/user",
}


def should_exclude(mount: str, fstype: str) -> bool:
    if fstype in EXCLUDE_FSTYPES:
        return True
    if mount in EXCLUDE_MOUNTS:
        return True
    if mount.startswith("/run/user/"):
        return True
    if mount.startswith("/sys/"):
        return True
    if mount.startswith("/proc/"):
        return True
    return False


def get_disk_info() -> List[dict]:
    """
    Esegue df e restituisce lista di dict con info per filesystem.
    """
    try:
        r = subprocess.run(
            ["df", "-PT", "--block-size=1"],
            capture_output=True, text=True, timeout=10,
        )
        lines = r.stdout.splitlines()
    except Exception:
        return []

    results = []
    # Header: Filesystem Type 1-blocks Used Available Use% Mounted on
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 7:
            continue
        device   = parts[0]
        fstype   = parts[1]
        total_b  = int(parts[2])
        used_b   = int(parts[3])
        avail_b  = int(parts[4])
        pct_str  = parts[5].rstrip("%")
        mount    = parts[6]

        if should_exclude(mount, fstype):
            continue
        if total_b == 0:
            continue

        try:
            pct = int(pct_str)
        except ValueError:
            continue

        results.append({
            "device": device,
            "fstype": fstype,
            "mount": mount,
            "total_gb": total_b / 1024**3,
            "used_gb": used_b / 1024**3,
            "avail_gb": avail_b / 1024**3,
            "pct": pct,
        })

    return results


def service_name(mount: str) -> str:
    """Converte mount point in nome servizio CheckMK leggibile."""
    if mount == "/":
        return "Disk.root"
    clean = mount.strip("/").replace("/", "_")
    return f"Disk.{clean}"


def main() -> int:
    disks = get_disk_info()

    if not disks:
        print("3 Disk.All - UNKNOWN: impossibile leggere informazioni disco")
        return 0

    for d in disks:
        svc = service_name(d["mount"])
        pct = d["pct"]
        used_h = f"{d['used_gb']:.1f}GB"
        avail_h = f"{d['avail_gb']:.1f}GB"
        total_h = f"{d['total_gb']:.1f}GB"

        # Perfdata: used_gb e pct con soglie
        perf = (
            f"used={d['used_gb']:.2f}GB "
            f"avail={d['avail_gb']:.2f}GB "
            f"pct={pct};{WARN_PCT};{CRIT_PCT};0;100"
        )

        msg = f"{pct}% usato ({used_h}/{total_h}), {avail_h} liberi [{d['mount']}]"

        if pct >= CRIT_PCT:
            print(f"2 {svc} - CRITICAL: {msg} | {perf}")
        elif pct >= WARN_PCT:
            print(f"1 {svc} - WARNING: {msg} | {perf}")
        else:
            print(f"0 {svc} - OK: {msg} | {perf}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
