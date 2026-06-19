#!/usr/bin/env python3
"""check_dhcp_leases.py - CheckMK local check DHCP leases (pyuci beta).

Beta version using pyuci for all UCI access. No subprocess, no shell.
Lease file resolution supports /tmp/dhcp.leases and /mnt/data/dnsmasq/dhcp.leases.
"""

import ipaddress
import sys
import time
from pathlib import Path

BETA = True
VERSION = "2.1.0b1"
SERVICE = "DHCP.Leases"

try:
    from euci import EUci
    EUCI_AVAILABLE = True
except ImportError:
    EUci = None
    EUCI_AVAILABLE = False


def uci_get(config, section=None, option=None):
    """Read UCI via pyuci.euci. Returns value or None on error/missing."""
    if not EUCI_AVAILABLE:
        return None
    try:
        with EUci() as u:
            if section is None:
                return u.get(config)
            if option is None:
                return u.get(config, section)
            return u.get(config, section, option, default=None)
    except Exception:
        return None


def get_dhcp_pools():
    """Return active DHCP pools from UCI using pyuci."""
    config = uci_get("dhcp")
    if config is None:
        return []

    # Build section dict: {section_name: {field: value}}
    sections = {}
    for key, value in config.items():
        parts = key.split(".")
        sec = parts[0]
        if sec not in sections:
            sections[sec] = {}
        if len(parts) == 1:
            sections[sec]["_type"] = value
        elif len(parts) == 2:
            sections[sec][parts[1]] = value
        elif len(parts) >= 2:
            field = ".".join(parts[1:])
            sections[sec][field] = value

    pools = []
    for sec_name, fields in sections.items():
        if fields.get("_type") != "dhcp":
            continue
        if fields.get("ignore") == "1":
            continue
        if fields.get("dhcpv4") == "disabled":
            continue
        iface = fields.get("interface", sec_name)
        try:
            start = int(fields.get("start", 100))
            raw_limit = int(fields.get("limit", 0))
        except (ValueError, TypeError):
            continue
        if raw_limit == 0:
            continue
        pools.append({
            "name": sec_name,
            "interface": iface,
            "start": start,
            "limit": raw_limit - 1,
        })
    return pools


def get_interface_network(iface):
    """Return CIDR for an interface from UCI network config."""
    net_config = uci_get("network")
    if net_config is None:
        return None

    iface_lower = iface.lower()
    candidates = set()
    for key in net_config:
        parts = key.split(".")
        if len(parts) >= 2:
            candidates.add(parts[0])

    # Try exact match
    for name in sorted(candidates):
        if name == iface:
            ipaddr = net_config.get(f"{name}.ipaddr")
            netmask = net_config.get(f"{name}.netmask")
            if ipaddr:
                try:
                    if netmask:
                        net = ipaddress.IPv4Network(f"{ipaddr}/{netmask}", strict=False)
                    else:
                        net = ipaddress.IPv4Network(f"{ipaddr}/24", strict=False)
                    return str(net)
                except ValueError:
                    return None

    # Case-insensitive fallback
    for name in sorted(candidates):
        if name.lower() == iface_lower:
            ipaddr = net_config.get(f"{name}.ipaddr")
            netmask = net_config.get(f"{name}.netmask")
            if ipaddr:
                try:
                    if netmask:
                        net = ipaddress.IPv4Network(f"{ipaddr}/{netmask}", strict=False)
                    else:
                        net = ipaddress.IPv4Network(f"{ipaddr}/24", strict=False)
                    return str(net)
                except ValueError:
                    return None
    return None


def resolve_lease_file():
    """Resolve active lease file: 1) pyuci UCI, 2) /mnt/data, 3) /tmp."""
    # Method 1: pyuci
    if EUCI_AVAILABLE:
        try:
            path = uci_get("dhcp", "ns_dnsmasq", "leasefile")
            if path:
                p = Path(path)
                if p.is_absolute() and p.is_file():
                    return p, str(p)
        except Exception:
            pass

    # Method 2: /mnt/data via /proc/mounts
    try:
        mounts = Path("/proc/mounts").read_text()
        if " /mnt/data " in mounts:
            p = Path("/mnt/data/dnsmasq/dhcp.leases")
            if p.is_file():
                return p, str(p)
    except Exception:
        pass

    # Method 3: /tmp
    p = Path("/tmp/dhcp.leases")
    if p.is_file():
        return p, str(p)

    return None, "no lease file found (checked pyuci UCI, /mnt/data, /tmp)"


def read_leases():
    """Read resolved lease file, return (leases_list, source_str)."""
    lf, src = resolve_lease_file()
    if lf is None:
        return [], src
    if not lf.exists():
        return [], src
    leases = []
    text = lf.read_text(encoding="utf-8", errors="ignore")
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            expire = int(parts[0])
        except ValueError:
            expire = 0
        leases.append((expire, parts[2]))
    return leases, src


def count_leases_in_pool(pool, network_cidr, leases, now):
    """Count active/expired leases in pool IP range."""
    try:
        net = ipaddress.IPv4Network(network_cidr, strict=False)
        base = int(net.network_address)
        pool_start = base + pool["start"]
        pool_end = pool_start + pool["limit"] - 1
    except Exception:
        return 0, 0

    active = 0
    expired = 0
    for expire, ip_str in leases:
        try:
            ip_int = int(ipaddress.IPv4Address(ip_str))
        except Exception:
            continue
        if pool_start <= ip_int <= pool_end:
            if expire > now:
                active += 1
            else:
                expired += 1
    return active, expired


def main():
    if not EUCI_AVAILABLE:
        print(f"3 {SERVICE} - pyuci not available (beta requirement)")
        return 0

    pools = get_dhcp_pools()
    if not pools:
        print(f"1 {SERVICE} - No active DHCP pool found")
        return 0

    leases, lease_source = read_leases()
    if leases is None:
        print(f"3 {SERVICE} - UNKNOWN: {lease_source}")
        return 0
    now = int(time.time())

    resolved = {}
    for pool in pools:
        cidr = get_interface_network(pool["interface"])
        if cidr is None:
            continue
        existing = resolved.get(cidr)
        if existing is None or pool["limit"] > existing["limit"]:
            resolved[cidr] = pool

    if not resolved:
        print(f"1 {SERVICE} - No DHCP pool with valid interface found")
        return 0

    for network_cidr, pool in resolved.items():
        name = pool["name"]
        limit = pool["limit"]
        active, expired = count_leases_in_pool(pool, network_cidr, leases, now)
        percent = int(active * 100 / limit) if limit > 0 else 0
        warn = int(limit * 80 / 100)
        crit = int(limit * 90 / 100)

        if percent >= 90:
            status, stext = 2, "CRITICAL"
        elif percent >= 80:
            status, stext = 1, "WARNING"
        else:
            status, stext = 0, "OK"

        print(
            f"{status} DHCP.{name} active={active};{warn};{crit};0;{limit} "
            f"[{network_cidr}] Lease attivi: {active}/{limit} ({percent}%) - {stext} "
            f"source={lease_source} [beta]"
            f" | active={active} expired={expired} max={limit} percent={percent}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
