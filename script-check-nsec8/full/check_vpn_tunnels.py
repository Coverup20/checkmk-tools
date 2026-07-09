#!/usr/bin/env python3
"""check_vpn_tunnels.py - CheckMK VPN tunnels check.

OpenVPN: reads /var/run/openvpn/*.status directly.
WireGuard: requires 'wg' command (netlink, no Python stdlib).
"""

import shutil
import subprocess
import sys
from pathlib import Path

VERSION = "1.1.0"
SERVICE = "VPN.Tunnels"


def count_openvpn_tunnels():
    """Count active OpenVPN tunnels (server + client) from status files."""
    total = 0
    active = 0
    status_dirs = [Path("/var/run/openvpn"), Path("/var/run/openvpn-server"), Path("/tmp/openvpn")]
    for d in status_dirs:
        if d.is_dir():
            for f in d.iterdir():
                if f.name.endswith(".status"):
                    total += 1
                    try:
                        text = f.read_text(encoding="utf-8", errors="ignore")
                        for line in text.splitlines():
                            if "," in line and "Connected" in line:
                                active += 1
                    except Exception:
                        pass
    return total, active


def count_wireguard_tunnels():
    """Count WireGuard peers via 'wg show'."""
    wg_bin = shutil.which("wg")
    if not wg_bin:
        return 0, 0
    try:
        result = subprocess.run([wg_bin, "show", "interfaces"],
                                capture_output=True, text=True, timeout=10)
        ifaces = result.stdout.strip().split()
        total = len(ifaces)
        active = 0
        for iface in ifaces:
            r = subprocess.run([wg_bin, "show", iface, "latest-handshakes"],
                               capture_output=True, text=True, timeout=10)
            for line in r.stdout.strip().splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[1] != "0":
                    active += 1
        return total, active
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return 0, 0


def main():
    ovpn_total, ovpn_active = count_openvpn_tunnels()
    wg_total, wg_active = count_wireguard_tunnels()
    total = ovpn_total + wg_total
    active = ovpn_active + wg_active
    inactive = total - active

    if total == 0:
        print(f"0 {SERVICE} - No VPN configured")
    elif active == 0:
        print(f"2 {SERVICE} - CRITICAL - All VPN down"
              f" | total={total} active={active} inactive={inactive}")
    elif active < total:
        print(f"1 {SERVICE} - WARNING - Some VPN down"
              f" | total={total} active={active} inactive={inactive}")
    else:
        print(f"0 {SERVICE} - OK - All VPN active"
              f" | total={total} active={active} inactive={inactive}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
