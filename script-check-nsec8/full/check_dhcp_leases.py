#!/usr/bin/env python3
"""check_dhcp_leases.py - CheckMK local check DHCP leases.

Uses pyuci for UCI access. No subprocess, no shell.
Lease file resolution supports /tmp/dhcp.leases and /mnt/data/dnsmasq/dhcp.leases.
"""

import ipaddress
import sys
import time
from pathlib import Path

VERSION = "2.1.0"
SERVICE = "DHCP.Leases"

try:
    from euci import EUci
    EUCI_AVAILABLE = True
except ImportError:
    EUci = None
    EUCI_AVAILABLE = False


def uci_get(config, section=None, option=None):
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
    config = uci_get("dhcp")
    if config is None:
        return []
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
        pools.append({"name": sec_name, "interface": iface, "start": start, "limit": raw_limit - 1})
    return pools


def get_interface_network(iface):
    net_config = uci_get("network")
    if net_config is None:
        return None
    iface_lower = iface.lower()
    candidates = set()
    for key in net_config:
        parts = key.split(".")
        if len(parts) >= 2:
            candidates.add(parts[0])
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
    if EUCI_AVAILABLE:
        try:
            path = uci_get("dhcp", "ns_dnsmasq", "leasefile")
            if path:
                p = Path(path)
                if p.is_absolute() and p.is_file():
                    return p, str(p)
        except Exception:
            pass
    try:
        mounts = Path("/proc/mounts").read_text()
        if " /mnt/data " in mounts:
            p = Path("/mnt/data/dnsmasq/dhcp.leases")
            if p.is_file():
                return p, str(p)
    except Exception:
        pass
    p = Path("/tmp/dhcp.leases")
    if p.is_file():
        return p, str(p)
    return None, "no lease file found"


def read_leases():
    lf, src = resolve_lease_file()
    if lf is None:
        return [], src
    if not lf.exists():
        return [], src
    leases = []
    try:
        for line in lf.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 4:
                leases.append({
                    "expiry": parts[0],
                    "mac": parts[1],
                    "ip": parts[2],
                    "hostname": parts[3] if len(parts) > 3 else "",
                })
    except Exception:
        pass
    return leases, src


def count_active_leases(leases):
    now = int(time.time())
    active = 0
    for lease in leases:
        try:
            expiry = int(lease["expiry"])
            if expiry == 0 or expiry > now:
                active += 1
        except ValueError:
            if lease["expiry"] == "never" or lease["expiry"] == "0":
                active += 1
    return active


def main():
    pools = get_dhcp_pools()
    if not pools or not EUCI_AVAILABLE:
        print(f"0 {SERVICE} - No active DHCP pool found")
        return 0
    leases, src = read_leases()
    active_count = count_active_leases(leases)
    print(
        f"0 {SERVICE} - Active: {active_count} leases (pool: {len(pools)} pool(s))"
        f" | active={active_count} pools={len(pools)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
