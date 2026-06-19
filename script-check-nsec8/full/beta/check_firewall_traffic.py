#!/usr/bin/env python3
"""check_firewall_traffic.py - CheckMK firewall traffic check (pyuci beta).

Replaces ubus with pyuci (UCI) for interface discovery and /sys/class/net
for byte counters. No subprocess, no ubus.
"""

import sys
from pathlib import Path

BETA = True
VERSION = "1.1.0b1"
SERVICE = "Firewall.Traffic"

try:
    from euci import EUci
    EUCI_AVAILABLE = True
except ImportError:
    EUci = None
    EUCI_AVAILABLE = False


def get_wan_lan_interfaces():
    """Read WAN and LAN interfaces from UCI network config using pyuci."""
    if not EUCI_AVAILABLE:
        return [], []
    try:
        with EUci() as u:
            net_config = u.get("network")
    except Exception:
        return [], []

    # Parse section types and names
    sections = {}
    for key, value in net_config.items():
        parts = key.split(".")
        sec = parts[0]
        if sec not in sections:
            sections[sec] = {}
        if len(parts) == 1:
            sections[sec]["_type"] = value
        elif len(parts) == 2:
            sections[sec][parts[1]] = value

    wan = []
    lan = []
    for name, fields in sections.items():
        if fields.get("_type") not in ("interface",):
            continue
        ifname = fields.get("ifname", name)
        if name.lower().startswith(("wan", "wwan", "vwan")) or fields.get("role") == "wan":
            wan.append(name)
        elif name.lower() in ("lan",) or fields.get("role") == "lan":
            lan.append(name)

    # Fallback: if nothing found, scan /sys/class/net for physical interfaces
    if not wan and not lan:
        for iface in sorted(Path("/sys/class/net").iterdir()):
            name = iface.name
            if name in ("lo", "sit*"):
                continue
            try:
                # Check if it's physical (has device directory)
                if (iface / "device").exists():
                    if name.startswith(("eth", "enp")):
                        wan.append(name)
            except OSError:
                pass
        lan = ["br-lan"] if Path("/sys/class/net/br-lan").exists() else []

    return wan, lan


def read_stat(device, metric):
    p = Path(f"/sys/class/net/{device}/statistics/{metric}")
    if not p.exists():
        return 0
    return int(p.read_text().strip())


def emit_for_iface(iface):
    device = iface
    # For UCI interface names, try to resolve to actual device
    # (simplified: use the interface name directly)
    dev_path = Path(f"/sys/class/net/{device}")
    if not dev_path.exists():
        return

    rx_b = read_stat(device, "rx_bytes")
    tx_b = read_stat(device, "tx_bytes")
    rx_p = read_stat(device, "rx_packets")
    tx_p = read_stat(device, "tx_packets")
    rx_e = read_stat(device, "rx_errors")
    tx_e = read_stat(device, "tx_errors")

    st = 1 if (rx_e > 100 or tx_e > 100) else 0
    print(
        f"{st} {iface}.Traffic - RX: {rx_b} bytes, TX: {tx_b} bytes [beta]"
        f" | rx_bytes={rx_b} tx_bytes={tx_b} rx_packets={rx_p} "
        f"tx_packets={tx_p} rx_errors={rx_e} tx_errors={tx_e}"
    )


def main():
    wan, lan = get_wan_lan_interfaces()
    for iface in wan + lan:
        emit_for_iface(iface)
    return 0


if __name__ == "__main__":
    sys.exit(main())
