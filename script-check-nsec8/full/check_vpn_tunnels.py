#!/usr/bin/env python3
"""check_vpn_tunnels.py - CheckMK VPN tunnels check.

OpenVPN: enumerates configured instances via UCI/nethsec, connected clients
via nethsec.ovpn.list_connected_clients() (openvpn-status socket).
WireGuard: peer count via nethsec.inventory.fact_wireguard() (config-level,
authoritative), liveness/freshness via 'wg show' (not exposed by the library).
"""

import shutil
import subprocess
import sys
import time

VERSION = "1.2.0"
SERVICE = "VPN.Tunnels"

# A WireGuard peer is considered active if it handshaked within this window,
# per doc/check_vpn_tunnels.md. The previous implementation only checked
# "handshake timestamp is nonzero, ever" - a peer that handshaked once and
# then went silent stayed "active" forever (permanent false-OK).
WG_HANDSHAKE_FRESH_SECONDS = 180

try:
    from euci import EUci
    EUCI_AVAILABLE = True
except ImportError:
    EUci = None
    EUCI_AVAILABLE = False


def count_openvpn_tunnels():
    """Count enabled OpenVPN instances and their connected clients.

    Replaces the previous file-based "," + "Connected" substring heuristic,
    which miscounted the openvpn-status CSV header line as a connected
    client (the header itself contains "Connected Since" - both a comma and
    the word "Connected") while real client rows (whose "Connected Since"
    field is an actual timestamp, not the literal word "Connected") never
    matched at all.
    """
    if not EUCI_AVAILABLE:
        return 0, 0
    try:
        from nethsec.utils import get_all_by_type
        from nethsec.ovpn import list_connected_clients
        with EUci() as u:
            instances = get_all_by_type(u, "openvpn", "openvpn")
    except Exception:
        return 0, 0

    total = 0
    active = 0
    for section, fields in instances.items():
        if fields.get("enabled") != "1":
            continue
        total += 1
        try:
            clients = list_connected_clients(section, type="subnet")
            active += len(clients) if clients else 0
        except Exception:
            pass
    return total, active


def count_wireguard_tunnels():
    """Count WireGuard peers: total from nethsec (config, authoritative),
    active from 'wg show' handshake freshness (not covered by the library).

    The previous implementation derived "total" from the number of
    interfaces and "active" from a per-peer handshake check across all
    interfaces - mixing interface count and peer count made active > total
    possible whenever an interface had more than one peer. Now both are
    peer-level counts, comparable in the same unit.
    """
    if not EUCI_AVAILABLE:
        return 0, 0
    try:
        from nethsec.inventory import fact_wireguard
        with EUci() as u:
            wg_facts = fact_wireguard(u)
    except Exception:
        wg_facts = {}

    servers = wg_facts.get("servers", {}) if wg_facts else {}
    total = sum(v.get("peers", 0) for v in servers.values())
    if total == 0:
        return 0, 0

    wg_bin = shutil.which("wg")
    if not wg_bin:
        return total, 0
    active = 0
    now = int(time.time())
    try:
        result = subprocess.run([wg_bin, "show", "interfaces"],
                                capture_output=True, text=True, timeout=10)
        ifaces = result.stdout.strip().split()
        for iface in ifaces:
            r = subprocess.run([wg_bin, "show", iface, "latest-handshakes"],
                               capture_output=True, text=True, timeout=10)
            for line in r.stdout.strip().splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        handshake_ts = int(parts[1])
                    except ValueError:
                        continue
                    if handshake_ts != 0 and (now - handshake_ts) <= WG_HANDSHAKE_FRESH_SECONDS:
                        active += 1
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return total, active


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
