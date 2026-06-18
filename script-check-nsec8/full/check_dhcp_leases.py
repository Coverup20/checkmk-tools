#!/usr/bin/env python3
"""check_dhcp_leases.py - CheckMK local check DHCP leases per pool (pure Python).

A separate CheckMK service for each DHCP pool active on NethSecurity 8.
Reads configuration from UCI (dhcp + network) and resolves the active lease file
from dnsmasq configuration, supporting both /tmp/dhcp.leases (volatile) and
/mnt/data/dnsmasq/dhcp.leases (persistent storage, NethSecurity >= 8.8).

Version: 2.0.0"""

import ipaddress
import subprocess
import sys
import time
from pathlib import Path

VERSION = "2.1.0"
LEASE_SOURCE = None  # resolved at runtime by resolve_lease_file()


def uci_show_parsed(section: str) -> dict:
    """Executes 'uci show <section>' and returns dict {full_key: value}."""
    result = subprocess.run(
        ["uci", "show", section],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, check=False
    )
    data = {}
    for line in result.stdout.splitlines():
        if '=' not in line:
            continue
        key, _, value = line.partition('=')
        data[key.strip()] = value.strip().strip("'")
    return data


def get_dhcp_pools() -> list:
    """Returns list of active DHCP pools from UCI dhcp.
    Each element: {name, interface, start, limit}
    Excludes: ignore=1, dhcpv4=disabled, limit=0."""
    data = uci_show_parsed("dhcp")

    sections: dict = {}
    for key, value in data.items():
        parts = key.split('.')
        if len(parts) == 2:
            sec = parts[1]
            if sec not in sections:
                sections[sec] = {}
            sections[sec]['_type'] = value
        elif len(parts) == 3:
            sec = parts[1]
            field = parts[2]
            if sec not in sections:
                sections[sec] = {}
            sections[sec][field] = value

    pools = []
    for sec_name, fields in sections.items():
        if fields.get('_type') != 'dhcp':
            continue
        if fields.get('ignore') == '1':
            continue
        if fields.get('dhcpv4') == 'disabled':
            continue
        iface = fields.get('interface', sec_name)
        try:
            start = int(fields.get('start', 100))
            limit = int(fields.get('limit', 0))
        except ValueError:
            continue
        if limit == 0:
            continue
        # NethSecurity salva limit = IP_configurati + 1 (off-by-one UI→UCI)
        # We subtract 1 to show the correct human value
        pools.append({
            'name': sec_name,
            'interface': iface,
            'start': start,
            'limit': limit - 1,
        })

    return pools


def get_interface_network(iface: str) -> str | None:
    """Returns the CIDR of the network associated with the UCI interface (e.g. '10.30.30.0/24').
    Try exact match first, then case-insensitive on all network interfaces."""
    def _resolve(name: str) -> str | None:
        data = uci_show_parsed(f"network.{name}")
        ipaddr = data.get(f"network.{name}.ipaddr")
        netmask = data.get(f"network.{name}.netmask")
        if not ipaddr:
            return None
        try:
            if netmask:
                net = ipaddress.IPv4Network(f"{ipaddr}/{netmask}", strict=False)
            else:
                net = ipaddress.IPv4Network(f"{ipaddr}/24", strict=False)
            return str(net)
        except ValueError:
            return None

    # Tentativo 1: match esatto
    result = _resolve(iface)
    if result:
        return result

    # Attempt 2: case-insensitive — scan all network interfaces
    all_net = uci_show_parsed("network")
    iface_lower = iface.lower()
    seen = set()
    for key in all_net:
        parts = key.split('.')
        if len(parts) >= 2:
            candidate = parts[1]
            if candidate not in seen and candidate.lower() == iface_lower:
                seen.add(candidate)
                result = _resolve(candidate)
                if result:
                    return result

    return None


def resolve_lease_file():
    """Determine the active dnsmasq lease file using authoritative sources.

    Resolution order:
    1. Read UCI dhcp.ns_dnsmasq.leasefile (authoritative dnsmasq config).
    2. If UCI unavailable, check /mnt/data (persistent storage) fallback.
    3. Final fallback to /tmp/dhcp.leases.
    Returns (Path, source_description) or (None, error_message).
    """
    # Method 1: authoritative UCI config
    try:
        rc = subprocess.run(
            ["uci", "get", "dhcp.ns_dnsmasq.leasefile"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, check=False
        )
        if rc.returncode == 0:
            path = rc.stdout.strip().strip("'")
            p = Path(path)
            if p.is_absolute() and p.is_file():
                return p, str(p)
    except Exception:
        pass

    # Method 2: persistent storage (NethSecurity >= 8.8) — check via /proc/mounts
    try:
        mounts = Path("/proc/mounts").read_text()
        if " /mnt/data " in mounts:
            p = Path("/mnt/data/dnsmasq/dhcp.leases")
            if p.is_file():
                return p, str(p)
    except Exception:
        pass

    # Method 3: fallback to volatile /tmp
    p = Path("/tmp/dhcp.leases")
    if p.is_file():
        return p, str(p)

    # No lease file found
    return None, "no lease file found (checked UCI, /mnt/data, /tmp)"


def read_leases():
    """Reads the resolved lease file and returns list of (expire_ts: int, ip: str)."""
    lf, src = resolve_lease_file()
    if lf is None:
        return [], src
    if not lf.exists():
        return [], src
    leases = []
    for line in lf.read_text(encoding="utf-8", errors="ignore").splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            expire = int(parts[0])
        except ValueError:
            expire = 0
        leases.append((expire, parts[2]))
    return leases, src


def count_leases_in_pool(pool: dict, network_cidr: str, leases: list, now: int) -> tuple:
    """Count active/expired leases in the pool's IP range.
    Range: network_base + start ... network_base + start + limit - 1"""
    try:
        net = ipaddress.IPv4Network(network_cidr, strict=False)
        base = int(net.network_address)
        pool_start_int = base + pool['start']
        pool_end_int = pool_start_int + pool['limit'] - 1
    except Exception:
        return 0, 0

    active = 0
    expired = 0
    for expire, ip_str in leases:
        try:
            ip_int = int(ipaddress.IPv4Address(ip_str))
        except Exception:
            continue
        if pool_start_int <= ip_int <= pool_end_int:
            if expire > now:
                active += 1
            else:
                expired += 1

    return active, expired


def main() -> int:
    pools = get_dhcp_pools()

    if not pools:
        print("1 DHCP.Leases - No active DHCP pool found")
        return 0

    leases, lease_source = read_leases()
    if leases is None:
        print(f"3 DHCP.Leases - UNKNOWN: {lease_source}")
        return 0
    now = int(time.time())

    # Fix network CIDR for each pool, skip orphans silently,
    # deduplicate pool with same CIDR keeping the one with higher limit
    resolved: dict = {}  # cidr -> pool con limit massimo
    for pool in pools:
        cidr = get_interface_network(pool['interface'])
        if cidr is None:
            continue  # orphan UCI section, no matching network interface
        existing = resolved.get(cidr)
        if existing is None or pool['limit'] > existing['limit']:
            resolved[cidr] = pool

    if not resolved:
        print("1 DHCP.Leases - No DHCP pool with valid interface found")
        return 0

    for network_cidr, pool in resolved.items():
        name = pool['name']
        limit = pool['limit']

        active, expired = count_leases_in_pool(pool, network_cidr, leases, now)
        percent = int(active * 100 / limit) if limit > 0 else 0

        warn = int(limit * 80 / 100)
        crit = int(limit * 90 / 100)

        if percent >= 90:
            status, status_text = 2, "CRITICAL"
        elif percent >= 80:
            status, status_text = 1, "WARNING"
        else:
            status, status_text = 0, "OK"

        print(
            f"{status} DHCP.{name} active={active};{warn};{crit};0;{limit} "
            f"[{network_cidr}] Lease attivi: {active}/{limit} ({percent}%) - {status_text} "
            f"source={lease_source} "
            f"| active={active} expired={expired} max={limit} percent={percent}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
