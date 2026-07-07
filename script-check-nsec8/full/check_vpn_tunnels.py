#!/usr/bin/env python3
"""check_vpn_tunnels.py - CheckMK VPN tunnels check (pyuci beta).

OpenVPN: Python-native (reads /var/run/openvpn/*.status directly).
WireGuard: BLOCKED — no Python-native API to query WireGuard peers
without invoking the 'wg' command. The 'wg' tool communicates with the
kernel via netlink, which has no stdlib Python binding.
Keeping the WireGuard section requires subprocess — prohibited in beta.
"""

import sys
from pathlib import Path

BETA = True
VERSION = "1.1.0b1"
SERVICE = "VPN.Tunnels"

try:
    from euci import EUci
except ImportError:
    EUci = None


def main():
    total = 0
    active = 0
    inactive = 0
    details = []

    # OpenVPN: fully Python-native (file read)
    ovpn_dir = Path("/var/run/openvpn")
    if ovpn_dir.is_dir():
        for sf in sorted(ovpn_dir.glob("*.status")):
            total += 1
            cc = sum(1 for line in sf.read_text(encoding="utf-8", errors="ignore").splitlines() if line.startswith("CLIENT_LIST"))
            if cc > 0:
                active += 1
                details.append(f"OpenVPN_{sf.stem}:{cc}")
            else:
                inactive += 1
                details.append(f"OpenVPN_{sf.stem}:no_clients")

    # WireGuard: BLOCKED — requires 'wg' command (netlink kernel interface).
    # No Python stdlib equivalent exists. Skipped in beta.
    # See check_vpn_tunnels.py for the original WireGuard implementation.

    if total == 0:
        st, txt = 0, "No VPN configured [beta]"
    elif active == 0:
        st, txt = 2, "CRITICAL - All VPN down [beta]"
    elif active < total:
        st, txt = 1, "WARNING - Some VPN down [beta]"
    else:
        st, txt = 0, "OK - All VPN active [beta]"

    print(
        f"{st} {SERVICE} active={active};0;0;0;{total} "
        f"Total:{total} Active:{active} - {txt}"
        f" | total={total} active={active} inactive={inactive}"
    )
    if details:
        print(f"0 VPN.Details - {', '.join(details)} [beta]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
