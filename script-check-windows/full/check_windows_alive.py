#!/usr/bin/env python3
"""
check_windows_alive.py - CheckMK active check: host Windows UP/DOWN via ARP (nmap)

Sostituisce check_icmp per host Windows con Windows Firewall attivo.
Usa nmap -sn (ARP scan) che funziona anche con Windows Firewall che blocca ICMP e TCP.
Richiede: sudo nmap configurato per utente monitoring in /etc/sudoers.d/monitoring-nmap

Deploy su CheckMK server:
  cp check_windows_alive.py /omd/sites/monitoring/local/lib/nagios/plugins/check_windows_alive
  chmod +x /omd/sites/monitoring/local/lib/nagios/plugins/check_windows_alive

Prerequisito (già configurato):
  /etc/sudoers.d/monitoring-nmap:
    monitoring ALL=(root) NOPASSWD: /usr/bin/nmap

Configurazione WATO (host check command per host Windows):
  Setup → Hosts → Host Check Command → "Use a custom check plugin"
  Plugin: check_windows_alive
  Arguments: -H $HOSTADDRESS$

Usage:
  check_windows_alive.py -H 192.168.32.100
  check_windows_alive.py -H DESKTOP-ABC.ad.studiopaci.info
  check_windows_alive.py -H 192.168.32.100 --timeout 3

Version: 2.0.0
"""

import argparse
import re
import socket
import subprocess
import sys
import time
from typing import Tuple

VERSION = "2.0.0"

# Exit codes Nagios/CheckMK
OK       = 0
WARNING  = 1
CRITICAL = 2
UNKNOWN  = 3


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


def main() -> int:
    parser = argparse.ArgumentParser(
        description=f"CheckMK active check: Windows host UP/DOWN via ARP (nmap) v{VERSION}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esempi:
  check_windows_alive.py -H 192.168.32.100
  check_windows_alive.py -H DESKTOP-ABC.ad.studiopaci.info
  check_windows_alive.py -H 192.168.32.100 --timeout 5
""")
    parser.add_argument("-H", "--host", required=True,
                        help="Hostname o IP da controllare")
    parser.add_argument("--timeout", type=float, default=3.0,
                        help="Timeout attesa risposta ARP in secondi (default: 3)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = parser.parse_args()

    host = args.host.strip()

    # Risoluzione DNS
    resolved_ip = resolve_host(host)
    if not resolved_ip:
        print(f"CRITICAL - {host}: DNS non risolve")
        return CRITICAL

    # Test ARP via nmap (bypassa Windows Firewall)
    is_up, rtt = check_nmap_arp(resolved_ip, args.timeout)

    if is_up:
        rtt_str = f"{rtt}ms" if rtt >= 0 else "n/a"
        print(f"OK - {host} raggiungibile (ARP) | rta={rtt}ms;500;1000;0")
        return OK
    else:
        print(f"CRITICAL - {host} NON raggiungibile (nessuna risposta ARP)")
        return CRITICAL


if __name__ == "__main__":
    sys.exit(main())
