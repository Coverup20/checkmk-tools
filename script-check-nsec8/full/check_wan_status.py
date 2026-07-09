#!/usr/bin/env python3
"""check_wan_status.py - CheckMK WAN status check.

Uses /proc/net/route for default route detection and interface status.
Gateway reachability via TCP connect() as ping replacement.
UCI for additional WAN interface discovery.
"""

import socket
import sys
from pathlib import Path

VERSION = "1.2.0"
SERVICE = "WAN.Status"

try:
    from euci import EUci
    EUCI_AVAILABLE = True
except ImportError:
    EUci = None
    EUCI_AVAILABLE = False


def find_wan_interfaces():
    wan = []
    try:
        for line in Path("/proc/net/route").read_text().splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 8 and parts[1] == "00000000":
                iface = parts[0]
                if iface not in wan:
                    wan.append(iface)
    except Exception:
        pass
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
    p = Path(f"/sys/class/net/{iface}/operstate")
    if p.exists():
        return p.read_text().strip() == "up"
    return False


def tcp_probe(host, port=80, timeout=3):
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True
    except Exception:
        return False


def get_gateway(iface):
    try:
        for line in Path("/proc/net/route").read_text().splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 8 and parts[0] == iface and parts[1] == "00000000":
                gw_hex = parts[2]
                gw = ".".join(str(int(gw_hex[i:i+2], 16)) for i in range(6, -1, -2))
                return gw
    except Exception:
        pass
    return None


def main():
    wan = find_wan_interfaces()
    if not wan:
        print(f"0 {SERVICE} - No WAN interfaces found")
        return 0
    overall = 0
    details = []
    for iface in wan:
        up = iface_is_up(iface)
        if up:
            gw = get_gateway(iface)
            if gw:
                if tcp_probe(gw):
                    details.append((0, f"{iface}: UP (gateway {gw} reachable via TCP)"))
                else:
                    details.append((1, f"{iface}: UP but gateway {gw} TCP unreachable"))
                    overall = max(overall, 1)
            elif tcp_probe("1.1.1.1", 443) or tcp_probe("8.8.8.8", 53):
                details.append((0, f"{iface}: UP (internet reachable)"))
            else:
                details.append((1, f"{iface}: UP but no connectivity"))
                overall = max(overall, 1)
        else:
            details.append((2, f"{iface}: DOWN"))
            overall = max(overall, 2)
    labels = {0: "OK", 1: "WARNING", 2: "CRITICAL"}
    detail_texts = [d[1] for d in details]
    print(f"{overall} {SERVICE} - {'; '.join(detail_texts)}")
    for i, (_, d) in enumerate(details):
        print(f"{_ if i==0 else _} WAN.Interface{i} - {d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
