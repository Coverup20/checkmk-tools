#!/usr/bin/env python3
"""
check_host_connectivity.py - CheckMK active check: host UP/DOWN via ARP + ICMP + TCP fallback

Sostituisce check_icmp per host con firewall attivo (Windows, Linux, router, ecc.).
Sequenza di check:
  1. ARP scan via nmap -sn (bypassa firewall, solo stessa subnet)
  2. ICMP ping fallback (cross-subnet)
  3. TCP port scan fallback (per host che bloccano ICMP, es. Windows con firewall strict)

Richiede: sudo nmap configurato per utente monitoring in /etc/sudoers.d/monitoring-nmap

Deploy su CheckMK server:
  cp check_host_connectivity.py /omd/sites/monitoring/local/lib/nagios/plugins/check_host_connectivity
  chmod +x /omd/sites/monitoring/local/lib/nagios/plugins/check_host_connectivity

Prerequisito (già configurato):
  /etc/sudoers.d/monitoring-nmap:
    monitoring ALL=(root) NOPASSWD: /usr/bin/nmap

Configurazione WATO (host check command):
  Setup → Hosts → Host Check Command → "Use a custom check plugin"
  Plugin: check_host_connectivity
  Arguments: -H $HOSTADDRESS$
  Con porte custom: -H $HOSTADDRESS$ --ports 22,80,443,445,3389

Usage:
  check_host_connectivity.py -H 192.168.32.100
  check_host_connectivity.py -H hostname.domain.local
  check_host_connectivity.py -H 192.168.32.100 --timeout 3
  check_host_connectivity.py -H 192.168.32.100 --ports 22,80,443,445,3389

Version: 2.3.0
"""

import argparse
import re
import socket
import subprocess
import sys
import time
from typing import List, Tuple

VERSION = "2.3.0"

# Porte TCP default per fallback (SSH, HTTP, HTTPS, SMB, RDP)
DEFAULT_TCP_PORTS = [22, 80, 443, 445, 3389]

# Exit codes Nagios/CheckMK
OK       = 0
WARNING  = 1
CRITICAL = 2
UNKNOWN  = 3


def parse_ports(ports_str: str) -> List[int]:
    """Parsa stringa di porte comma-separated in lista di interi."""
    result = []
    for p in ports_str.split(","):
        p = p.strip()
        if p.isdigit():
            port = int(p)
            if 1 <= port <= 65535:
                result.append(port)
    return result


def resolve_host(host: str) -> str:
    """Risolve hostname in IP. Ritorna stringa vuota se non risolve."""
    try:
        return socket.gethostbyname(host)
    except socket.gaierror:
        return ""


def check_nmap_arp(ip: str, timeout: float) -> Tuple[bool, float]:
    """
    Verifica se l'host è UP tramite ARP scan (nmap -sn).
    Usa sudo nmap per permettere ARP anche all'utente monitoring.

    Returns:
        (is_up, rtt_ms) — rtt_ms = -1 se non trovato
    """
    t0 = time.monotonic()
    try:
        result = subprocess.run(
            ["sudo", "/usr/bin/nmap", "-sn", "-n", "--reason", ip],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout + 5
        )
        elapsed = (time.monotonic() - t0) * 1000

        output = result.stdout
        if "Host is up" in output:
            # Estrai latency se disponibile
            m = re.search(r"\((\d+(?:\.\d+)?)s latency\)", output)
            if m:
                rtt = float(m.group(1)) * 1000
            else:
                rtt = round(elapsed, 1)
            return True, round(rtt, 2)
        return False, -1
    except subprocess.TimeoutExpired:
        return False, -1
    except Exception:
        return False, -1


def check_ping_icmp(ip: str, timeout: float) -> Tuple[bool, float]:
    """
    Fallback ICMP ping quando ARP non è disponibile (host su subnet diversa o nmap assente).

    Returns:
        (is_up, rtt_ms) — rtt_ms = -1 se non risponde
    """
    t0 = time.monotonic()
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", str(int(timeout)), ip],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout + 5
        )
        elapsed = (time.monotonic() - t0) * 1000

        if result.returncode == 0:
            # Estrai rtt da output ping (es: "rtt min/avg/max/mdev = 0.123/0.123/0.123/0.000 ms")
            m = re.search(r"rtt .* = [\d.]+/([\d.]+)/", result.stdout)
            if m:
                rtt = float(m.group(1))
            else:
                rtt = round(elapsed, 1)
            return True, round(rtt, 2)
        return False, -1
    except subprocess.TimeoutExpired:
        return False, -1
    except Exception:
        return False, -1


def check_tcp_ports(ip: str, ports: List[int], timeout: float) -> Tuple[bool, float, int]:
    """
    Terzo fallback: prova connessione TCP su lista di porte comuni.
    Utile per host che bloccano ARP e ICMP (es. Windows con firewall strict,
    host su VPN, device con policy restrittive).

    Default ports: 22 (SSH), 80 (HTTP), 443 (HTTPS), 445 (SMB), 3389 (RDP)

    Returns:
        (is_up, rtt_ms, open_port) — open_port = -1 se nessuna porta risponde
    """
    for port in ports:
        t0 = time.monotonic()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((ip, port))
            elapsed = (time.monotonic() - t0) * 1000
            sock.close()
            if result == 0:
                return True, round(elapsed, 2), port
        except (socket.timeout, OSError):
            continue
    return False, -1, -1


def main() -> int:
    parser = argparse.ArgumentParser(
        description=f"CheckMK active check: host UP/DOWN via ARP + ICMP + TCP v{VERSION}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esempi:
  check_host_connectivity.py -H 192.168.32.100
  check_host_connectivity.py -H hostname.domain.local
  check_host_connectivity.py -H 192.168.32.100 --timeout 5
  check_host_connectivity.py -H 192.168.32.100 --ports 22,80,443,445,3389
""")
    parser.add_argument("-H", "--host", required=True,
                        help="Hostname o IP da controllare")
    parser.add_argument("--timeout", type=float, default=3.0,
                        help="Timeout per ogni singolo check in secondi (default: 3)")
    parser.add_argument("--ports", type=str,
                        default=",".join(str(p) for p in DEFAULT_TCP_PORTS),
                        help=f"Porte TCP per fallback (default: {','.join(str(p) for p in DEFAULT_TCP_PORTS)})")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = parser.parse_args()

    host = args.host.strip()
    tcp_ports = parse_ports(args.ports)

    # Risoluzione DNS
    resolved_ip = resolve_host(host)
    if not resolved_ip:
        print(f"CRITICAL - {host}: DNS non risolve")
        return CRITICAL

    # Step 1: ARP via nmap (stessa subnet, bypassa firewall)
    is_up, rtt = check_nmap_arp(resolved_ip, args.timeout)
    if is_up:
        print(f"OK - {host} raggiungibile (ARP) | rta={rtt}ms;500;1000;0")
        return OK

    # Step 2: ICMP ping fallback (cross-subnet)
    is_up_icmp, rtt_icmp = check_ping_icmp(resolved_ip, args.timeout)
    if is_up_icmp:
        print(f"OK - {host} raggiungibile (ICMP) | rta={rtt_icmp}ms;500;1000;0")
        return OK

    # Step 3: TCP port fallback (host con firewall che blocca ARP e ICMP)
    if tcp_ports:
        is_up_tcp, rtt_tcp, open_port = check_tcp_ports(resolved_ip, tcp_ports, args.timeout)
        if is_up_tcp:
            print(f"OK - {host} raggiungibile (TCP:{open_port}) | rta={rtt_tcp}ms;500;1000;0")
            return OK

    ports_str = f", porte TCP {args.ports} chiuse" if tcp_ports else ""
    print(f"CRITICAL - {host} NON raggiungibile (no ARP, no ICMP{ports_str})")
    return CRITICAL


if __name__ == "__main__":
    sys.exit(main())
