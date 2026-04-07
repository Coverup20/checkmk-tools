#!/usr/bin/env python3
"""check_vpn_tunnels.py - CheckMK local check VPN tunnels (pure Python)."""

VERSION = "1.1.0"

import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    total_tunnels = 0
    active_tunnels = 0
    inactive_tunnels = 0
    details: list[str] = []

    openvpn_dir = Path("/var/run/openvpn")
    if openvpn_dir.is_dir():
        for status_file in sorted(openvpn_dir.glob("*.status")):
            total_tunnels += 1
            client_count = sum(1 for line in status_file.read_text(encoding="utf-8", errors="ignore").splitlines() if line.startswith("CLIENT_LIST"))
            if client_count > 0:
                active_tunnels += 1
                details.append(f"OpenVPN_{status_file.stem}: {client_count} client")
            else:
                inactive_tunnels += 1
                details.append(f"OpenVPN_{status_file.stem}: no clients")

    if shutil.which("wg"):
        interfaces = subprocess.run(["wg", "show", "interfaces"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False)
        for iface in (interfaces.stdout or "").split():
            total_tunnels += 1
            peers = subprocess.run(["wg", "show", iface, "peers"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False)
            peer_count = len([p for p in (peers.stdout or "").splitlines() if p.strip()])
            if peer_count > 0:
                active_tunnels += 1
                details.append(f"WireGuard_{iface}: {peer_count} peers")
            else:
                inactive_tunnels += 1
                details.append(f"WireGuard_{iface}: no active peers")

    if total_tunnels == 0:
        status, status_text = 0, "No VPN configured"
    elif active_tunnels == 0:
        status, status_text = 2, "CRITICAL - All VPN down"
    elif active_tunnels < total_tunnels:
        status, status_text = 1, "WARNING - Some VPN down"
    else:
        status, status_text = 0, "OK - All VPN active"

    print(
        f"{status} VPN.Tunnels active={active_tunnels};0;0;0;{total_tunnels} "
        f"Total:{total_tunnels} Active:{active_tunnels} - {status_text} "
        f"| total={total_tunnels} active={active_tunnels} inactive={inactive_tunnels}"
    )
    if details:
        print(f"0 VPN.Details - {', '.join(details)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
