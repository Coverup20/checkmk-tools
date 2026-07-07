#!/usr/bin/env python3
"""check_wan_status.py - CheckMK WAN status check (pyuci beta).

BLOCKED: WAN status requires:
  1. ubus (no Python binding) or UCI for interface discovery — UCI available via pyuci
  2. ping (ICMP) for gateway reachability — no Python stdlib equivalent
     without raw sockets (requires CAP_NET_RAW or root).
  3. /proc/net/route for default route detection — available via /proc

This beta uses pyuci for interface discovery and /proc/net/route for
default route detection. Gateway ping is replaced by a connect()-based
reachability test (TCP port 80/443), which is a limited approximation.
"""

import socket
import sys
from pathlib import Path

BETA = True
VERSION = "1.1.1b1"
SERVICE = "WAN.Status"

try:
    from euci import EUci
    EUCI_AVAILABLE = True
except ImportError:
    EUci = None
    EUCI_AVAILABLE = False


def find_wan_interfaces():
    """Find WAN interfaces via /proc/net/route (default route) + UCI."""
    wan = []

    # Method 1: /proc/net/route for default gateway
    try:
        for line in Path("/proc/net/route").read_text().splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 8:
                iface = parts[0]
                dest = parts[1]
                # Destination 00000000 = 0.0.0.0 = default route
                if dest == "00000000":
                    if iface not in wan:
                        wan.append(iface)
    except Exception:
        pass

    # Method 2: UCI for WAN interface names
    if not wan and EUCI_AVAILABLE:
        try:
            with EUci() as u:
                net = u.get("network")
            for key in net:
                parts = key.split(".")
                if len(parts) == 1:
                    continue
                name = parts[0]
                if name.lower().startswith(("wan", "wwan", "vwan")):
                    if name not in wan:
                        wan.append(name)
        except Exception:
            pass

    return wan


def iface_is_up(iface):
    """Check if interface is up via /sys/class/net/<iface>/operstate."""
    p = Path(f"/sys/class/net/{iface}/operstate")
    if p.exists():
        return p.read_text().strip() == "up"
    return False


def tcp_probe(host, port=80, timeout=3):
    """Test TCP connectivity to a host:port as ping replacement."""
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True
    except Exception:
        return False


def get_gateway(iface):
    """Get gateway IP for interface from /proc/net/route."""
    try:
        for line in Path("/proc/net/route").read_text().splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 8 and parts[0] == iface and parts[1] == "00000000":
                # Gateway is in hex network byte order
                gw_hex = parts[2]
                gw = ".".join(str(int(gw_hex[i:i+2], 16)) for i in range(6, -1, -2))
                return gw
    except Exception:
        pass
    return None


def main():
    wan = find_wan_interfaces()
    if not wan:
        print(f"0 {SERVICE} status=ERROR No WAN interfaces found [beta]")
        return 0

    overall = 0
    details = []

    for iface in wan:
        up = iface_is_up(iface)
        if up:
            gw = get_gateway(iface)
            if gw:
                if tcp_probe(gw):
                    details.append(f"{iface}: UP (gateway {gw} reachable via TCP)")
                else:
                    details.append(f"{iface}: UP but gateway {gw} TCP unreachable")
                    overall = max(overall, 1)
            elif tcp_probe("1.1.1.1", 443) or tcp_probe("8.8.8.8", 53):
                details.append(f"{iface}: UP (internet reachable)")
            else:
                details.append(f"{iface}: UP but no connectivity")
                overall = max(overall, 1)
        else:
            details.append(f"{iface}: DOWN")
            overall = max(overall, 2)

    labels = {0: "OK", 1: "WARNING", 2: "CRITICAL"}
    print(f"{overall} {SERVICE} status={labels[overall]} {' '.join(details)} [beta]")
    for i, d in enumerate(details):
        st = 0 if "UP" in d else (2 if "DOWN" in d else 1)
        print(f"{st} WAN.Interface{i} - {d} [beta]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
