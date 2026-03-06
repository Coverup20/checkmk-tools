#!/usr/bin/env python3
"""
network_scan_to_folder.py - Scansione rete e creazione folder CheckMK

Fase 1: Ping sweep subnet → raccoglie IP attivi
Fase 2: Reverse DNS per ogni IP → raccoglie nomi host
Fase 3: Crea folder WATO con tutti gli host trovati (ping-only, IP hardcoded)

Usage:
  python3 network_scan_to_folder.py --subnet 192.168.32.0/23 --dry-run
  python3 network_scan_to_folder.py --subnet 192.168.32.0/23 --folder scansione
  python3 network_scan_to_folder.py --subnet 192.168.32.0/23 --subnet 10.0.0.0/24 --folder scansione

Version: 1.0.0
"""

import argparse
import ipaddress
import subprocess
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Optional

VERSION = "1.0.0"

WATO_BASE = "/omd/sites/monitoring/etc/check_mk/conf.d/wato"


# ---------------------------------------------------------------------------
# Network helpers
# ---------------------------------------------------------------------------

def ping(ip: str) -> bool:
    r = subprocess.run(["ping", "-c1", "-W1", ip], capture_output=True)
    return r.returncode == 0


def reverse_dns(ip: str) -> Optional[str]:
    """Reverse DNS via resolvectl (usa systemd-resolved, funziona con AD)."""
    try:
        r = subprocess.run(
            ["resolvectl", "query", ip],
            capture_output=True, text=True, timeout=5
        )
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                # Formato tipico: "192.168.x.x -- link#N: HOSTNAME.domain."
                m = re.search(r'--\s+\S+\s+(\S+)', line)
                if m:
                    name = m.group(1).rstrip('.')
                    return name.split('.')[0].upper()
            # Fallback
            m = re.search(r'\d+\.\d+\.\d+\.\d+\s+(\S+)', r.stdout)
            if m:
                return m.group(1).split('.')[0].upper()
    except Exception:
        pass
    return None


def scan_subnet(subnet: str, max_workers: int = 50) -> list:
    """Ping sweep parallelo. Ritorna lista IP attivi."""
    network = ipaddress.ip_network(subnet, strict=False)
    host_list = list(network.hosts())
    print(f"  Scansione {subnet}: {len(host_list)} IP...")

    live = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(ping, str(ip)): str(ip) for ip in host_list}
        done = 0
        for future in as_completed(futures):
            done += 1
            ip = futures[future]
            if future.result():
                live.append(ip)
            if done % 100 == 0:
                print(f"    {done}/{len(host_list)} testati, {len(live)} attivi...")

    print(f"  → {len(live)} host attivi in {subnet}")
    return live


def resolve_all(live_ips: list) -> list:
    """Per ogni IP attivo risolve hostname, torna lista di dict."""
    results = []
    seen_names = {}  # name → count, per deduplicazione

    for ip in sorted(live_ips, key=lambda x: ipaddress.ip_address(x)):
        hostname = reverse_dns(ip)

        if hostname:
            # Deduplicazione: se nome già visto, aggiungi suffisso
            if hostname in seen_names:
                seen_names[hostname] += 1
                cmk_name = f"{hostname}-{seen_names[hostname]}"
            else:
                seen_names[hostname] = 1
                cmk_name = hostname
            src = "DNS"
        else:
            # Nessun DNS → usa IP come nome (es: 192_168_32_105)
            cmk_name = "IP-" + ip.replace(".", "_")
            src = "IP "

        results.append({"ip": ip, "hostname": hostname, "name": cmk_name, "src": src})
        print(f"  {ip:<20} {src}  → {cmk_name}")

    return results


# ---------------------------------------------------------------------------
# CheckMK WATO helpers
# ---------------------------------------------------------------------------

def sanitize(name: str) -> str:
    """Caratteri validi per hostname CheckMK."""
    return re.sub(r'[^a-zA-Z0-9._-]', '-', name)


def read_wato_format() -> str:
    """Legge un .wato esistente per capire il formato (Python dict o JSON)."""
    for root, dirs, files in os.walk(WATO_BASE):
        if ".wato" in files:
            try:
                with open(os.path.join(root, ".wato")) as f:
                    return f.read().strip()
            except Exception:
                pass
    return ""


def create_wato_folder(folder_name: str, hosts: list, subnets: list, dry_run: bool = False):
    """Crea directory + .wato + hosts.mk."""
    folder_path = os.path.join(WATO_BASE, folder_name)
    wato_file  = os.path.join(folder_path, ".wato")
    hosts_file = os.path.join(folder_path, "hosts.mk")

    # Controlla se folder esiste già
    if os.path.exists(folder_path) and not dry_run:
        backup = f"{hosts_file}.backup_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
        try:
            os.rename(hosts_file, backup)
            print(f"  Backup hosts.mk esistente → {backup}")
        except Exception:
            pass

    # Determina formato .wato dal resto del sito
    sample = read_wato_format()
    if sample.startswith("{"):
        # Python dict format (comune in CMK 2.x)
        wato_content = f"{{'title': u'Scansione Rete', 'attributes': {{}}, 'num_hosts': {len(hosts)}, 'lock': False}}\n"
    else:
        wato_content = f"{{'title': u'Scansione Rete', 'attributes': {{}}, 'num_hosts': {len(hosts)}, 'lock': False}}\n"

    # Costruisce all_hosts e ipaddresses
    folder_tag = f"/wato/{folder_name}/"
    all_hosts_entries = []
    ip_dict = {}

    for h in hosts:
        name = sanitize(h["name"])
        # Tag: ping-only, no agent, wato-managed
        entry = f"{name}|ping|no-agent|wato|{folder_tag}"
        all_hosts_entries.append(entry)
        ip_dict[name] = h["ip"]

    subnet_comment = ", ".join(subnets)
    hosts_mk = f"""# Generato da network_scan_to_folder.py v{VERSION}
# Data: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
# Subnet scansionate: {subnet_comment}
# Host totali: {len(hosts)} ({sum(1 for h in hosts if h['src'] == 'DNS')} con DNS, {sum(1 for h in hosts if h['src'] == 'IP ')} IP-only)

all_hosts += {repr(all_hosts_entries)}

ipaddresses.update({repr(ip_dict)})
"""

    if dry_run:
        print(f"\n[DRY RUN] Folder: {folder_path}")
        print(f"[DRY RUN] {len(all_hosts_entries)} host")
        print(f"\n--- hosts.mk preview ---")
        for line in hosts_mk.splitlines()[:30]:
            print(f"  {line}")
        if hosts_mk.count('\n') > 30:
            print(f"  ... ({hosts_mk.count(chr(10)) - 30} righe omesse)")
        return

    os.makedirs(folder_path, exist_ok=True)
    with open(wato_file, "w") as f:
        f.write(wato_content)
    with open(hosts_file, "w") as f:
        f.write(hosts_mk)

    print(f"  Folder:   {folder_path}")
    print(f"  .wato:    OK")
    print(f"  hosts.mk: {len(all_hosts_entries)} host scritti")


def apply_checkmk(dry_run: bool = False):
    if dry_run:
        print("[DRY RUN] Salterebbe: cmk -R")
        return
    print("\nApplicazione CheckMK (cmk -R)...")
    r = subprocess.run(["cmk", "-R"], capture_output=True, text=True)
    if r.returncode == 0:
        print("cmk -R: OK")
    else:
        print(f"cmk -R WARNING:\n{r.stderr[:500]}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=f"Network scan → CheckMK folder v{VERSION}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esempi:
  # Preview senza scrivere
  python3 network_scan_to_folder.py --subnet 192.168.32.0/23 --dry-run

  # Crea folder "scansione" (default)
  python3 network_scan_to_folder.py --subnet 192.168.32.0/23

  # Più subnet, nome folder custom
  python3 network_scan_to_folder.py --subnet 192.168.32.0/24 --subnet 192.168.33.0/24 --folder scansione_lab
""")
    parser.add_argument("--subnet", action="append", required=True,
                        metavar="CIDR",
                        help="Subnet da scansionare (ripetibile: --subnet A --subnet B)")
    parser.add_argument("--folder", default="scansione",
                        help="Nome folder WATO (default: scansione)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview senza scrivere nulla")
    parser.add_argument("--workers", type=int, default=50,
                        help="Thread paralleli per ping (default: 50)")
    args = parser.parse_args()

    print(f"Network Scan → CheckMK Folder v{VERSION}")
    print(f"Subnet:  {', '.join(args.subnet)}")
    print(f"Folder:  {args.folder}")
    print(f"Dry-run: {args.dry_run}")
    print("=" * 60)

    # Fase 1: Ping sweep su tutte le subnet
    print("\n[Fase 1] Ping sweep...")
    all_live = []
    for subnet in args.subnet:
        live = scan_subnet(subnet, args.workers)
        all_live.extend(live)

    # Deduplicazione nel caso subnet si sovrappongano
    all_live = list(set(all_live))
    print(f"\nTotale IP attivi: {len(all_live)}")

    if not all_live:
        print("Nessun host trovato. Uscita.")
        sys.exit(0)

    # Fase 2: Risoluzione DNS inversa
    print("\n[Fase 2] Risoluzione DNS inversa...")
    hosts = resolve_all(all_live)

    named   = sum(1 for h in hosts if h["src"] == "DNS")
    ip_only = len(hosts) - named
    print(f"\nRiepilogo: {len(hosts)} host | {named} con nome DNS | {ip_only} IP-only")

    # Fase 3: Crea folder WATO
    print(f"\n[Fase 3] Creazione folder WATO '{args.folder}'...")
    create_wato_folder(args.folder, hosts, args.subnet, args.dry_run)

    # Applica
    apply_checkmk(args.dry_run)

    # Report finale
    if not args.dry_run:
        print("\n=== REPORT FINALE ===")
        print(f"{'NOME CMK':<32} {'IP':<20} {'DNS originale'}")
        print("-" * 70)
        for h in sorted(hosts, key=lambda x: x["name"]):
            dns_orig = h["hostname"] or "-"
            print(f"{sanitize(h['name']):<32} {h['ip']:<20} {dns_orig}")
        print("-" * 70)
        print(f"Totale: {len(hosts)} host nella folder '{args.folder}'")


if __name__ == "__main__":
    main()
