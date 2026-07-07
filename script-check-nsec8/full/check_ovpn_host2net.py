#!/usr/bin/env python3
"""check_ovpn_host2net.py - CheckMK OpenVPN check (pyuci beta).

Replaces subprocess ps with /proc scan for OpenVPN processes.
OpenVPN status files read directly.
"""

import sys
from pathlib import Path

BETA = True
VERSION = "1.1.0b1"
SERVICE = "OVPN.HostToNet"
STATUS_DIR = Path("/var/run/openvpn")

try:
    from euci import EUci
except ImportError:
    EUci = None


def count_openvpn_processes():
    """Count OpenVPN processes by scanning /proc for cmdline containing 'openvpn'."""
    count = 0
    try:
        for proc in Path("/proc").iterdir():
            if not proc.name.isdigit():
                continue
            try:
                cmdline = (proc / "cmdline").read_bytes()
                if b"openvpn" in cmdline:
                    count += 1
            except (PermissionError, FileNotFoundError, OSError):
                pass
    except PermissionError:
        pass
    return count


def main():
    if not STATUS_DIR.is_dir():
        print(f"0 {SERVICE} - OpenVPN not configured or not running [beta]")
        return 0

    sfiles = sorted(STATUS_DIR.glob("*.status"))
    if not sfiles:
        print(f"0 {SERVICE} - No active host-to-net OpenVPN server [beta]")
        return 0

    total_servers = len(sfiles)
    total_clients = 0
    details = []

    for sf in sfiles:
        name = sf.stem
        cc = 0
        for line in sf.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("CLIENT_LIST,"):
                cc += 1
        total_clients += cc
        details.append(f"{name}:{cc}_clients" if cc else f"{name}:0_clients")

    proc_count = count_openvpn_processes()
    if proc_count == 0:
        print(f"2 OVPN.Process - CRITICAL - No OpenVPN process running [beta]")
        return 0
    else:
        print(f"0 OVPN.Process - OK - {proc_count} OpenVPN processes active [beta]")

    st, txt = (1, f"WARNING - Many clients: {total_clients}") if total_clients >= 50 else (0, f"OK - {total_clients} clients on {total_servers} servers")

    print(
        f"{st} {SERVICE} clients={total_clients};50;100;0 servers={total_servers} - {txt} [beta]"
        f" | total_clients={total_clients} total_servers={total_servers}"
    )
    print(f"0 OVPN.Servers - Active: {' '.join([f.stem for f in sfiles])} [beta]")
    if details:
        print(f"0 OVPN.ClientDetails - {', '.join(details[:10])} [beta]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
