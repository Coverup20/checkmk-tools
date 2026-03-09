#!/usr/bin/env python3
"""
check_windows_alive.py - CheckMK active check: host Windows UP/DOWN via TCP

Sostituisce check_icmp per host Windows con Windows Firewall attivo (ICMP bloccato).
Tenta connessione TCP su porte tipiche Windows: 445, 135, 3389, 139.
Ritorna OK se ALMENO una porta risponde, CRITICAL se nessuna risponde.

Compatibile con interfaccia Nagios/CheckMK (exit code + output testuale).

Deploy su CheckMK server:
  cp check_windows_alive.py /omd/sites/monitoring/local/lib/nagios/plugins/check_windows_alive
  chmod +x /omd/sites/monitoring/local/lib/nagios/plugins/check_windows_alive

Configurazione WATO (host check command per host Windows):
  Setup → Hosts → Host Check Command → "Use a custom check plugin"
  Plugin: check_windows_alive
  Arguments: -H $HOSTADDRESS$

Usage:
  check_windows_alive.py -H 192.168.32.100
  check_windows_alive.py -H DESKTOP-ABC.ad.studiopaci.info
  check_windows_alive.py -H 192.168.32.100 --ports 445,135,3389
  check_windows_alive.py -H 192.168.32.100 --timeout 3
  check_windows_alive.py -H 192.168.32.100 --require-all   (OK solo se TUTTE le porte rispondono)

Version: 1.0.0
"""

import argparse
import socket
import sys
import time
from typing import List, Tuple

VERSION = "1.0.0"

# Porte Windows tipiche con descrizione
DEFAULT_PORTS = [
    (445,  "SMB"),
    (135,  "RPC"),
    (3389, "RDP"),
    (139,  "NetBIOS"),
]

# Exit codes Nagios/CheckMK
OK       = 0
WARNING  = 1
CRITICAL = 2
UNKNOWN  = 3


def check_tcp_port(host: str, port: int, timeout: float) -> Tuple[bool, float]:
    """
    Tenta connessione TCP a host:port.

    Returns:
        (success, rtt_ms) — rtt_ms = -1 se fallito
    """
    t0 = time.monotonic()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        rtt = (time.monotonic() - t0) * 1000
        sock.close()
        return result == 0, round(rtt, 1)
    except (socket.timeout, socket.gaierror, OSError):
        return False, -1


def resolve_host(host: str) -> str:
    """Risolve hostname in IP. Ritorna stringa vuota se non risolve."""
    try:
        return socket.gethostbyname(host)
    except socket.gaierror:
        return ""


def main() -> int:
    parser = argparse.ArgumentParser(
        description=f"CheckMK active check: Windows host UP/DOWN via TCP v{VERSION}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esempi:
  check_windows_alive.py -H 192.168.32.100
  check_windows_alive.py -H DESKTOP-ABC.ad.studiopaci.info --timeout 2
  check_windows_alive.py -H 192.168.32.100 --ports 445,135
  check_windows_alive.py -H 192.168.32.100 --require-all
""")
    parser.add_argument("-H", "--host", required=True,
                        help="Hostname o IP da controllare")
    parser.add_argument("--ports", default=None,
                        help="Porte da testare, separate da virgola (default: 445,135,3389,139)")
    parser.add_argument("--timeout", type=float, default=2.0,
                        help="Timeout connessione TCP in secondi (default: 2)")
    parser.add_argument("--require-all", action="store_true",
                        help="OK solo se TUTTE le porte rispondono (default: basta una)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = parser.parse_args()

    # Parse porte
    if args.ports:
        try:
            port_list = [(int(p.strip()), str(p.strip())) for p in args.ports.split(",")]
        except ValueError:
            print(f"UNKNOWN - Porte non valide: {args.ports}")
            return UNKNOWN
    else:
        port_list = DEFAULT_PORTS

    host = args.host.strip()

    # Risoluzione DNS (solo per info nell'output)
    resolved_ip = resolve_host(host)
    if not resolved_ip:
        print(f"CRITICAL - {host}: DNS non risolve")
        return CRITICAL

    # Test porte
    results = []
    open_ports = []
    closed_ports = []

    for port, label in port_list:
        ok, rtt = check_tcp_port(resolved_ip, port, args.timeout)
        results.append((port, label, ok, rtt))
        if ok:
            open_ports.append((port, label, rtt))
        else:
            closed_ports.append((port, label))

    # Determina stato
    if args.require_all:
        is_up = len(closed_ports) == 0
    else:
        is_up = len(open_ports) > 0

    # Costruisci output
    open_str  = ", ".join(f"{label}/{port}" for port, label, _ in open_ports)
    closed_str = ", ".join(f"{label}/{port}" for port, label in closed_ports)

    if is_up:
        # Usa RTT della prima porta aperta come metrica principale
        rtt_main = open_ports[0][2]
        ports_detail = open_str if open_str else "-"
        if closed_ports:
            ports_detail += f" (chiuse: {closed_str})"
        msg = f"OK - {host} raggiungibile | TCP aperte: {ports_detail}"
        # Performance data CheckMK
        perf = f" | rta={rtt_main}ms;500;1000;0"
        print(msg + perf)
        return OK
    else:
        tested = ", ".join(f"{label}/{port}" for port, label in closed_ports)
        msg = f"CRITICAL - {host} NON raggiungibile (TCP: {tested} tutti chiusi/timeout)"
        print(msg)
        return CRITICAL


if __name__ == "__main__":
    sys.exit(main())
