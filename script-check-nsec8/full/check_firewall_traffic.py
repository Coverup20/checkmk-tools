#!/usr/bin/env python3
"""check_firewall_traffic.py - CheckMK firewall traffic check.

Uses pyuci for interface discovery and /sys/class/net for byte counters.
No subprocess, no ubus.
"""

import sys
from pathlib import Path

VERSION = "1.1.0"
SERVICE = "Traffic"

try:
    from euci import EUci
    EUCI_AVAILABLE = True
except ImportError:
    EUci = None
    EUCI_AVAILABLE = False


def get_interfaces_from_uci():
    if not EUCI_AVAILABLE:
        return []
    try:
        with EUci() as u:
            net = u.get("network")
        ifaces = set()
        for key in net:
            parts = key.split(".")
            if len(parts) == 2 and parts[1] in ("device", "ifname"):
                val = net[key]
                ifaces.add(val)
        return sorted(ifaces)
    except Exception:
        return []


def get_interfaces_from_sys():
    try:
        return sorted(
            p.name for p in Path("/sys/class/net").iterdir()
            if p.is_symlink() and p.name not in ("lo", "sit0", "tunl0", "ip6tnl0")
        )
    except Exception:
        return []


def get_bytes(iface):
    dev_path = Path("/proc/net/dev")
    if not dev_path.exists():
        return None
    try:
        for line in dev_path.read_text().splitlines():
            if line.startswith(iface + ":"):
                parts = line.split(":", 1)[1].split()
                if len(parts) >= 9:
                    return int(parts[0]), int(parts[8])
    except Exception:
        pass
    return None


def main():
    ifaces = get_interfaces_from_sys()
    if not ifaces:
        print("1 Traffic - No interfaces found")
        return 0
    st = 0
    for iface in ifaces:
        b = get_bytes(iface)
        if b is None:
            continue
        rx_bytes, tx_bytes = b
        if rx_bytes == 0 and tx_bytes == 0:
            continue
        print(f"0 {iface}.{SERVICE} - RX: {rx_bytes} bytes, TX: {tx_bytes} bytes | rx_bytes={rx_bytes} tx_bytes={tx_bytes}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
