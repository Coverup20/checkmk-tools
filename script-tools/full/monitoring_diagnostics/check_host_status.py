#!/usr/bin/env python3
"""
check_host_status.py - CheckMK/Nagios plugin: Host UP/DOWN via multi-probe confidence scoring

Sostituisce check_icmp con un approccio multi-layer che esegue TUTTI i check
in parallelo e calcola un punteggio di confidenza prima di emettere il verdetto.

NON si ferma al primo risultato — esegue tutto per evitare falsi positivi/negativi
causati da firewall ICMP, porte chiuse, o flapping momentaneo.

Probes eseguite in parallelo:
  - ICMP Ping (3x, 1s timeout)      → risponde       → forte indicatore UP
  - TCP su porte configurabili       → aperta/rif.    → indicatore UP
  - ARP table lookup                 → presente       → host visto su L2
  (traceroute disabilitato di default: troppo lento per check continuo)

Punteggio "HOST DOWN" (0-100):
  Ping 100% loss        → +25    Ping risponde        → -50 (host sicuramente UP)
  TCP porta timeout     → +10/15/20 per porta          → -20 (host risponde su TCP)
  ARP assente           → +15    ARP presente         → -10
  DNS risolve           → +5     DNS fallisce         → -10

Soglie verdetto:
  score >= warn_threshold (default 60) → WARNING  (probabile offline / incerto)
  score >= crit_threshold (default 90) → CRITICAL (offline confermato)
  score <  warn_threshold              → OK       (host attivo)

Exit codes (Nagios/CheckMK standard):
  0 = OK       (host attivo)
  1 = WARNING  (comportamento anomalo, incerto)
  2 = CRITICAL (host offline confermato)
  3 = UNKNOWN  (errore plugin)

Deploy su CheckMK server:
  cp check_host_status.py /omd/sites/monitoring/local/lib/nagios/plugins/check_host_status
  chmod +x /omd/sites/monitoring/local/lib/nagios/plugins/check_host_status

Configurazione WATO (Host Check Command):
  Setup → Hosts → Host Check Command → "Use a custom check plugin"
  Plugin:    check_host_status
  Arguments: -H $HOSTADDRESS$

  Varianti:
  -H $HOSTADDRESS$ --ports 22 443          # Host senza CMK agent
  -H $HOSTADDRESS$ --no-arp               # Host su segmento L2 diverso
  -H $HOSTADDRESS$ --warn 50 --crit 80    # Soglie personalizzate

Version: 1.0.0
"""

import argparse
import concurrent.futures
import errno
import re
import socket
import subprocess
import sys
import time
from typing import List, NamedTuple, Optional, Tuple

VERSION = "1.0.0"
SCRIPT_NAME = "check_host_status"

# Nagios exit codes
OK       = 0
WARNING  = 1
CRITICAL = 2
UNKNOWN  = 3

# Nomi porte leggibili
PORT_NAMES = {
    22:   "SSH",
    6556: "CMK",
    443:  "HTTPS",
    80:   "HTTP",
    3389: "RDP",
    8080: "HTTP-alt",
    5985: "WinRM",
    2222: "SSH-alt",
}

# Pesi punteggio "host DOWN"
W_PING_DOWN    = 25   # Ping 100% loss        → host probabilmente offline
W_PING_UP      = -50  # Ping risponde          → host sicuramente attivo
W_TCP_TIMEOUT  = {    # Per porta: timeout     → porta non risponde
    6556: 20,
    22:   15,
    443:  10,
    80:    8,
    3389: 10,
    8080:  5,
    5985:  8,
    2222:  8,
}
W_TCP_DEFAULT  = 8    # Peso default per porte non in lista
W_TCP_UP       = -20  # Porta aperta/rifiutata → host attivo
W_ARP_MISSING  = 15   # ARP assente            → host non visto su L2
W_ARP_PRESENT  = -10  # ARP presente           → host visto di recente
W_DNS_OK       = 5    # DNS risolve            → non è errore DNS
W_DNS_FAIL     = -10  # DNS non risolve        → forse problema DNS, non host


# ─── Struttura risultato probe ────────────────────────────────────────────────

class ProbeResult(NamedTuple):
    name:   str    # identificatore breve
    status: str    # "up" / "down" / "unknown"
    score:  int    # contributo al punteggio finale
    msg:    str    # dettaglio per output


# ─── Probe singole ───────────────────────────────────────────────────────────

def probe_dns(host: str) -> Tuple[ProbeResult, Optional[str]]:
    """Risolve hostname. Ritorna (result, ip_risolto_o_None)."""
    try:
        ip = socket.gethostbyname(host)
        return ProbeResult("dns", "up", W_DNS_OK, f"→ {ip}"), ip
    except socket.gaierror as e:
        return ProbeResult("dns", "unknown", W_DNS_FAIL, f"NXDOMAIN: {e}"), None


def probe_ping(ip: str, count: int = 3, timeout: int = 1) -> ProbeResult:
    """ICMP ping multiplo. Analizza packet loss."""
    try:
        r = subprocess.run(
            ["ping", "-c", str(count), "-W", str(timeout), ip],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=count * (timeout + 1) + 3
        )
        out = r.stdout.decode("utf-8", errors="replace")

        m_loss = re.search(r"(\d+)%\s+packet loss", out)
        loss = int(m_loss.group(1)) if m_loss else 100

        if loss == 0:
            m_rtt = re.search(r"rtt \S+ = [\d.]+/([\d.]+)/", out)
            rtt = f"{float(m_rtt.group(1)):.1f}ms" if m_rtt else "ok"
            return ProbeResult("ping", "up", W_PING_UP, f"risponde ({rtt})")
        elif loss == 100:
            return ProbeResult("ping", "down", W_PING_DOWN, "100% packet loss")
        else:
            return ProbeResult("ping", "unknown", 0, f"{loss}% loss (instabile)")

    except subprocess.TimeoutExpired:
        return ProbeResult("ping", "down", W_PING_DOWN, "timeout")
    except OSError:
        return ProbeResult("ping", "unknown", 0, "ping non disponibile")
    except Exception as e:
        return ProbeResult("ping", "unknown", 0, str(e))


def probe_tcp(ip: str, port: int, timeout: float = 2.0) -> ProbeResult:
    """Test TCP su singola porta."""
    name = f"tcp/{PORT_NAMES.get(port, str(port))}"
    weight_down = W_TCP_TIMEOUT.get(port, W_TCP_DEFAULT)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        err = sock.connect_ex((ip, port))
        sock.close()

        if err == 0:
            return ProbeResult(name, "up", W_TCP_UP, "aperta")
        elif err == errno.ECONNREFUSED:
            # Host attivo, servizio non in ascolto su questa porta
            return ProbeResult(name, "up", W_TCP_UP, "rifiutata (host attivo)")
        else:
            return ProbeResult(name, "down", weight_down, f"timeout (errno {err})")

    except socket.timeout:
        return ProbeResult(name, "down", weight_down, "timeout")
    except Exception as e:
        return ProbeResult(name, "unknown", 0, str(e))


def probe_arp(ip: str) -> ProbeResult:
    """Verifica presenza entry ARP nella tabella locale."""
    try:
        r = subprocess.run(
            ["arp", "-n", ip],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5
        )
        out = r.stdout.decode("utf-8", errors="replace")

        if r.returncode != 0 or "no entry" in out.lower():
            return ProbeResult("arp", "down", W_ARP_MISSING, "nessuna entry ARP")
        elif "(incomplete)" in out:
            return ProbeResult("arp", "down", W_ARP_MISSING, "ARP incompleto (no risposta L2)")
        else:
            mac_m = re.search(r"([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})", out)
            mac = mac_m.group(1) if mac_m else "n/a"
            return ProbeResult("arp", "up", W_ARP_PRESENT, f"MAC {mac}")

    except OSError:
        return ProbeResult("arp", "unknown", 0, "arp non disponibile")
    except Exception as e:
        return ProbeResult("arp", "unknown", 0, str(e))


# ─── Engine principale ────────────────────────────────────────────────────────

def run_all_probes(
    host: str,
    ports: List[int],
    skip_arp: bool,
    tcp_timeout: float,
) -> Tuple[int, List[ProbeResult]]:
    """
    Esegue DNS + tutte le probe in parallelo ove possibile.

    Returns:
        (score_0_100, lista_ProbeResult)
    """
    results: List[ProbeResult] = []

    # DNS prima (bloccante: serve l'IP per tutto il resto)
    dns_result, ip = probe_dns(host)
    results.append(dns_result)

    if ip is None:
        # Prova comunque con l'host così com'è (potrebbe essere già un IP)
        ip = host

    # Ping + TCP + ARP in parallelo
    futures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        futures.append(ex.submit(probe_ping, ip))
        for port in ports:
            futures.append(ex.submit(probe_tcp, ip, port, tcp_timeout))
        if not skip_arp:
            futures.append(ex.submit(probe_arp, ip))

        for f in concurrent.futures.as_completed(futures):
            try:
                results.append(f.result())
            except Exception as e:
                results.append(ProbeResult("unknown", "unknown", 0, str(e)))

    raw = sum(r.score for r in results)
    score = max(0, min(100, raw))
    return score, results


# ─── Formattazione output Nagios ──────────────────────────────────────────────

def format_output(
    host: str,
    score: int,
    results: List[ProbeResult],
    warn: int,
    crit: int,
) -> Tuple[int, str]:
    """
    Calcola exit code e compone la stringa di output Nagios.

    Returns:
        (exit_code, output_string)
    """
    # Verdetto
    if score >= crit:
        code   = CRITICAL
        status = "CRITICAL"
        verb   = "OFFLINE"
    elif score >= warn:
        code   = WARNING
        status = "WARNING"
        verb   = "PROBABILE OFFLINE"
    else:
        code   = OK
        status = "OK"
        verb   = "attivo"

    # Sintesi probe per il testo dell'output
    up_probes   = [r.name for r in results if r.status == "up"]
    down_probes = [r.name for r in results if r.status == "down"]

    up_str   = ", ".join(up_probes)   if up_probes   else "nessuno"
    down_str = ", ".join(down_probes) if down_probes else "nessuno"

    if code == OK:
        detail = f"risponde su: {up_str}"
    elif code == CRITICAL:
        detail = f"non risponde su: {down_str}"
    else:
        detail = f"up={up_str} | down={down_str}"

    # Performance data
    perf = f"confidence={score}%;{warn};{crit}"

    output = f"{status} - {host} {verb} (confidenza: {score}%) - {detail} | {perf}"
    return code, output


# ─── Entry point ─────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        prog=SCRIPT_NAME,
        description=f"CheckMK active check: host status via multi-probe confidence v{VERSION}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esempi:
  check_host_status -H 192.168.10.100
  check_host_status -H ns8.dominio.it --ports 22 6556 443
  check_host_status -H 10.0.0.50 --no-arp --warn 50 --crit 80
  check_host_status -H 192.168.32.100 --timeout 3

Soglie:
  confidenza >= --crit (default 90) → CRITICAL (host offline)
  confidenza >= --warn (default 60) → WARNING  (incerto)
  confidenza <  --warn              → OK       (host attivo)
        """
    )
    parser.add_argument("-H", "--host", required=True,
                        help="Hostname o IP da controllare")
    parser.add_argument("--ports", nargs="+", type=int, default=[22, 6556, 443, 80],
                        help="Porte TCP da testare (default: 22 6556 443 80)")
    parser.add_argument("--no-arp", action="store_true",
                        help="Salta ARP (host su segmento L2 diverso)")
    parser.add_argument("--timeout", type=float, default=2.0,
                        help="Timeout TCP per porta in secondi (default: 2)")
    parser.add_argument("--warn", type=int, default=60,
                        help="Soglia WARNING (default: 60)")
    parser.add_argument("--crit", type=int, default=90,
                        help="Soglia CRITICAL (default: 90)")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {VERSION}")
    args = parser.parse_args()

    if args.warn >= args.crit:
        print(f"UNKNOWN - --warn ({args.warn}) deve essere < --crit ({args.crit})")
        return UNKNOWN

    score, results = run_all_probes(
        args.host,
        args.ports,
        skip_arp=args.no_arp,
        tcp_timeout=args.timeout,
    )

    code, output = format_output(args.host, score, results, args.warn, args.crit)
    print(output)
    return code


if __name__ == "__main__":
    sys.exit(main())
