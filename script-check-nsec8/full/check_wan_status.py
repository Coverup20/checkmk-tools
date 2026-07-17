#!/usr/bin/env python3
"""check_wan_status.py - CheckMK WAN status check.

Uses /proc/net/route for default route detection and interface status.
Gateway reachability via TCP connect() as ping replacement.
UCI for additional WAN interface discovery.
"""

import json
import socket
import subprocess
import sys
from pathlib import Path

VERSION = "1.3.0"
SERVICE = "WAN.Status"

try:
    from euci import EUci
    EUCI_AVAILABLE = True
except ImportError:
    EUci = None
    EUCI_AVAILABLE = False


def _ubus_interface_status(section):
    """Call `ubus call network.interface.<section> status` and return parsed JSON, or None."""
    try:
        result = subprocess.run(
            ["ubus", "call", f"network.interface.{section}", "status"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except Exception:
        pass
    return None


def _resolve_runtime_device(uci, section, configured_device):
    """Resolve the runtime device for a UCI interface section.

    For static/DHCP ethernet interfaces the configured device (e.g. eth1) is
    already the runtime device. For dynamic protocols (PPPoE and similar) the
    kernel creates a separate runtime device (e.g. pppoe-wan) once the
    interface comes up, which is what /proc/net/route and /sys/class/net
    actually expose - the UCI-configured device is not enough on its own.
    """
    status = _ubus_interface_status(section)
    if status:
        l3_device = status.get("l3_device")
        if l3_device:
            return l3_device
    return configured_device


def find_wan_interfaces():
    """Find WAN (red-role) interfaces using nethsec library.

    Primary: nethsec.inventory.get_networks() with role == "red", resolved to
    their runtime device via ubus (handles PPPoE/dynamic protocols correctly).
    Fallback: /proc/net/route for backward compatibility (library unavailable)
    """
    wan = []

    # Method 1: Use nethsec library (primary, robust)
    if EUCI_AVAILABLE:
        try:
            from nethsec.inventory import get_networks
            from nethsec.utils import get_all_by_type
            with EUci() as u:
                networks = get_networks(u)
                for dev, net in networks.items():
                    if net.get("props", {}).get("role") != "red":
                        continue
                    section = None
                    for s in get_all_by_type(u, "network", "interface"):
                        if u.get("network", s, "device", default=None) == dev:
                            section = s
                            break
                    runtime_dev = _resolve_runtime_device(u, section, dev) if section else dev
                    if runtime_dev not in wan:
                        wan.append(runtime_dev)
                if wan:
                    return wan  # Success - don't fall through
        except (ImportError, Exception):
            pass

    # Method 2: Fallback to /proc/net/route only if library unavailable
    try:
        for line in Path("/proc/net/route").read_text().splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "00000000":
                iface = parts[0].strip()
                if iface and iface not in wan:
                    wan.append(iface)
        return wan
    except Exception:
        pass

    return wan  # Return whatever we found (even if empty)


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
    degraded = 0
    for iface in wan:
        up = iface_is_up(iface)
        if up:
            gw = get_gateway(iface)
            # A failed TCP probe on the gateway's port 80 does NOT by itself
            # mean the WAN is down: most gateways/routers don't run an HTTP
            # server on port 80 at all, so a refused/failed connect() there
            # is expected on a perfectly healthy link. Only fall back to
            # WARNING if real internet connectivity also can't be confirmed.
            if gw and tcp_probe(gw):
                details.append((0, f"{iface}: UP (gateway {gw} reachable via TCP)"))
            elif tcp_probe("1.1.1.1", 443) or tcp_probe("8.8.8.8", 53):
                suffix = f" (gateway {gw} TCP probe on :80 inconclusive)" if gw else ""
                details.append((0, f"{iface}: UP (internet reachable){suffix}"))
            else:
                details.append((1, f"{iface}: UP but no connectivity" + (f" (gateway {gw})" if gw else "")))
                overall = max(overall, 1)
                degraded += 1
        else:
            details.append((2, f"{iface}: DOWN"))
            overall = max(overall, 2)
    labels = {0: "OK", 1: "WARNING", 2: "CRITICAL"}
    detail_texts = [d[1] for d in details]
    print(f"{overall} {SERVICE} - {'; '.join(detail_texts)}")
    for i, (_, d) in enumerate(details):
        print(f"{_ if i==0 else _} WAN.Interface{i} - {d}")

    total = len(details)
    up_count = sum(1 for state, _ in details if state == 0)
    down_count = sum(1 for state, _ in details if state == 2)
    print(
        f"0 WAN.Metrics - Total={total} Up={up_count} Down={down_count} Degraded={degraded}"
        f" | total={total} up={up_count} down={down_count} degraded={degraded}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
