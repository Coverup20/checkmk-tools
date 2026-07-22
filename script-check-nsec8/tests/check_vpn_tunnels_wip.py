#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

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

VERSION = "1.6.0"
WIREGUARD_SERVICE = "VPN.Tunnel"

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


def list_openvpn_tunnels():
    """Per-tunnel detail for every enabled, non-road-warrior OpenVPN instance.

    Returns a list of {"name": section, "label": str, "up": bool, "clients":
    int} - "up" is a single yes/no fact for that one named tunnel (unlike the
    aggregate total/active counts in count_openvpn_tunnels(), which lump
    every tunnel together and can't tell an operator *which* tunnel, out of
    several, is the one that's down). "clients" is the connected-session
    count for subnet/routed servers (0 or 1 for p2p/client instances, since a
    p2p tunnel has exactly one remote peer by definition). "label" is the
    human-facing name - the "ns_name" field NethSecurity's own UI sets (e.g.
    "Checkmk" for UCI section "ns_Checkmk") when present, falling back to the
    raw UCI section name otherwise (e.g. instances predating that field, or
    ones configured outside the ns-openvpn API) - used for the CheckMK
    service name instead of "name" so it doesn't leak the "ns_" UCI-section
    prefix into what an operator sees.

    Road-warrior (host-to-net) servers are excluded entirely, same as
    /usr/libexec/rpcd/ns.ovpntunnel::list_tunnels() ("skip road warrior
    servers" via `if 'ns_auth_mode' in vpn: continue` - the field ns.ovpnrw
    sets on every road-warrior instance it creates). They're already covered
    by check_ovpn_host2net.py, which treats 0 connected clients as normal
    (road warriors connect ad-hoc); counting them here too meant the same
    instance got conflicting verdicts across the two checks - a road warrior
    with no client currently connected made this check report CRITICAL "All
    VPN down" even when every real site-to-site tunnel was healthy.

    Replaces the previous file-based "," + "Connected" substring heuristic,
    which miscounted the openvpn-status CSV header line as a connected
    client (the header itself contains "Connected Since" - both a comma and
    the word "Connected") while real client rows (whose "Connected Since"
    field is an actual timestamp, not the literal word "Connected") never
    matched at all.

    Also replaces a later bug where every instance was queried with a
    hardcoded type="subnet", regardless of its actual role/topology. Verified
    live: a healthy, ping-verified p2p (site-to-site) OpenVPN tunnel returns
    {} from list_connected_clients(section, type="subnet") - CLIENT_LIST
    lines (what "subnet" parses) are only ever emitted by routed/subnet
    servers, never by p2p instances - so every p2p tunnel was permanently
    reported as 0 active clients (false CRITICAL/"All VPN down"), the mirror
    image of the earlier WireGuard permanent-false-OK bug. Role/topology
    detection below mirrors /usr/libexec/rpcd/ns.ovpntunnel (list_tunnels):
    outbound "client"/"ns_client" instances are always queried with
    type="p2p" and are considered active only once real traffic has flowed
    in both directions (bytes_received > 0 and bytes_sent > 0); everything
    else is queried with its own "topology" (default "subnet" - matches the
    UCI default set by ns.ovpnrw for road-warrior servers).
    """
    if not EUCI_AVAILABLE:
        return []
    try:
        from nethsec.utils import get_all_by_type
        from nethsec.ovpn import list_connected_clients
        with EUci() as u:
            instances = get_all_by_type(u, "openvpn", "openvpn")
    except Exception:
        return []

    details = []
    for section, fields in instances.items():
        if fields.get("enabled") != "1":
            continue
        if "ns_auth_mode" in fields:
            continue  # road warrior server - covered by check_ovpn_host2net
        is_client = fields.get("client") == "1" or fields.get("ns_client") == "1"
        if is_client:
            vpn_type = "p2p"
        else:
            vpn_type = fields.get("topology", "subnet")
            if vpn_type not in ("subnet", "p2p"):
                vpn_type = "subnet"
        try:
            clients = list_connected_clients(section, type=vpn_type)
        except Exception:
            clients = None

        if is_client:
            stats = (clients or {}).get("stats", {})
            up = stats.get("bytes_received", 0) > 0 and stats.get("bytes_sent", 0) > 0
            count = 1 if up else 0
        else:
            count = len(clients) if clients else 0
            up = count > 0
        label = fields.get("ns_name") or section
        details.append({"name": section, "label": label, "up": up, "clients": count})
    return details


def count_openvpn_tunnels():
    """Aggregate total/active OpenVPN tunnel counts - see list_openvpn_tunnels()
    for the per-tunnel breakdown this is derived from."""
    details = list_openvpn_tunnels()
    total = len(details)
    active = sum(d["clients"] for d in details)
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
    # One service per OpenVPN tunnel, named after it - with more than one
    # net-to-net/p2p tunnel, a single aggregate service could only ever say
    # "1 of 2 down", never which one. WireGuard peers don't get the same
    # treatment: 'wg show' only exposes peers by public key, no human-facing
    # name to hang a service on, so they still go through the aggregate
    # WIREGUARD_SERVICE below instead.
    for tunnel in list_openvpn_tunnels():
        state = 0 if tunnel["up"] else 2
        text = "UP" if tunnel["up"] else "DOWN"
        print(f"{state} VPN.Tunnel.{tunnel['label']} - {tunnel['label']}: {text}")

    wg_total, wg_active = count_wireguard_tunnels()
    wg_inactive = wg_total - wg_active

    # Perfdata must be the single whitespace-free 3rd field (CheckMK's local
    # check parser never re-scans the free-text field for a later "|") -
    # putting it after the label as before produced zero graphed metrics.
    perfdata = f"total={wg_total}|active={wg_active}|inactive={wg_inactive}"
    if wg_total == 0:
        print(f"0 {WIREGUARD_SERVICE} {perfdata} No WireGuard peers configured")
    elif wg_active == 0:
        print(f"2 {WIREGUARD_SERVICE} {perfdata} CRITICAL - All WireGuard peers down")
    elif wg_active < wg_total:
        print(f"1 {WIREGUARD_SERVICE} {perfdata} WARNING - Some WireGuard peers down")
    else:
        print(f"0 {WIREGUARD_SERVICE} {perfdata} OK - All WireGuard peers active")

    return 0


if __name__ == "__main__":
    sys.exit(main())
