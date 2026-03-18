#!/usr/bin/env python3
"""check_dhcp_leases.py - CheckMK local check DHCP leases per pool (Python puro).

Un servizio CheckMK separato per ogni pool DHCP attivo su NethSecurity 8.
Legge la configurazione da UCI (dhcp + network) e conta i lease da /tmp/dhcp.leases
mappando ogni IP al pool di appartenenza tramite IP range.

Version: 2.0.0
"""

import ipaddress
import subprocess
import sys
import time
from pathlib import Path

VERSION = "2.0.3"
LEASE_FILE = Path("/tmp/dhcp.leases")


def uci_show_parsed(section: str) -> dict:
    """Esegue 'uci show <section>' e restituisce dict {chiave_completa: valore}."""
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
    """Restituisce lista di pool DHCP attivi da UCI dhcp.
    Ogni elemento: {name, interface, start, limit}
    Esclude: ignore=1, dhcpv4=disabled, limit=0."""
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
        # Sottraiamo 1 per mostrare il valore umano corretto
        pools.append({
            'name': sec_name,
            'interface': iface,
            'start': start,
            'limit': limit - 1,
        })

    return pools


def get_interface_network(iface: str) -> str | None:
    """Restituisce il CIDR della rete associata all'interfaccia UCI (es: '10.30.30.0/24').
    Prova prima match esatto, poi case-insensitive su tutte le interfacce network."""
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

    # Tentativo 2: case-insensitive — scansiona tutte le interfacce network
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


def read_leases() -> list:
    """Legge /tmp/dhcp.leases e restituisce lista di (expire_ts: int, ip: str)."""
    if not LEASE_FILE.exists():
        return []
    leases = []
    for line in LEASE_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            expire = int(parts[0])
        except ValueError:
            expire = 0
        leases.append((expire, parts[2]))
    return leases


def count_leases_in_pool(pool: dict, network_cidr: str, leases: list, now: int) -> tuple:
    """Conta lease attivi/scaduti nel range IP del pool.
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
        print("1 DHCP.Leases - Nessun pool DHCP attivo trovato")
        return 0

    leases = read_leases()
    now = int(time.time())

    # Risolvi network CIDR per ogni pool, salta orfani silenziosamente,
    # deduplica pool con stesso CIDR tenendo quello con limit maggiore
    resolved: dict = {}  # cidr -> pool con limit massimo
    for pool in pools:
        cidr = get_interface_network(pool['interface'])
        if cidr is None:
            continue  # sezione UCI orfana, nessuna interfaccia network corrispondente
        existing = resolved.get(cidr)
        if existing is None or pool['limit'] > existing['limit']:
            resolved[cidr] = pool

    if not resolved:
        print("1 DHCP.Leases - Nessun pool DHCP con interfaccia valida trovato")
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
            f"| active={active} expired={expired} max={limit} percent={percent}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
