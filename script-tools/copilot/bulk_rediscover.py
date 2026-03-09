#!/usr/bin/env python3
"""
bulk_rediscover.py - Ridiscovery bulk host CheckMK con servizio PING

Trova tutti gli host con servizio PING ancora attivo ed esegue cmk -II
per rimuoverlo (richiede regola ignored_services attiva nella folder).

Usage (come utente monitoring):
  python3 bulk_rediscover.py
  python3 bulk_rediscover.py --dry-run
  python3 bulk_rediscover.py --service "PING"

Version: 1.0.0
"""

import argparse
import socket
import subprocess
import sys

VERSION = "1.0.0"

LIVE = "/omd/sites/monitoring/tmp/run/live"
BATCH_SIZE = 20


def livestatus(query: str) -> list:
    """Esegue query Livestatus via Unix socket."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(LIVE)
    sock.sendall((query + "\n").encode())
    sock.shutdown(socket.SHUT_WR)
    data = b""
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
    sock.close()
    lines = data.decode().strip().split("\n")
    return [l for l in lines if l.strip()]


def get_hosts_with_service(service_name: str) -> list:
    """Ritorna lista hostname che hanno il servizio specificato."""
    query = (
        "GET services\n"
        "Columns: host_name\n"
        f"Filter: description = {service_name}\n"
        "OutputFormat: csv\n"
        "Separators: 10 59 44 124\n"
    )
    rows = livestatus(query)
    return sorted([r.strip() for r in rows if r.strip()])


def rediscover_batch(hosts: list, dry_run: bool = False) -> bool:
    """Esegue cmk -II su un batch di host."""
    if dry_run:
        print(f"  [DRY RUN] cmk -II {' '.join(hosts[:3])}{'...' if len(hosts) > 3 else ''}")
        return True
    cmd = ["cmk", "-II"] + hosts
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  WARN: {r.stderr[:200]}")
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=f"Bulk rediscovery CheckMK v{VERSION}")
    parser.add_argument("--service", default="PING", help="Nome servizio da rimuovere (default: PING)")
    parser.add_argument("--dry-run", action="store_true", help="Mostra cosa farebbe senza eseguire")
    args = parser.parse_args()

    print(f"bulk_rediscover.py v{VERSION}")
    print(f"Ricerca host con servizio '{args.service}'...")

    hosts = get_hosts_with_service(args.service)

    if not hosts:
        print(f"Nessun host con servizio '{args.service}' trovato. Niente da fare.")
        return 0

    print(f"Trovati {len(hosts)} host:")
    for h in hosts:
        print(f"  {h}")

    if args.dry_run:
        print(f"\n[DRY RUN] Verrebbero eseguiti {len(hosts) // BATCH_SIZE + 1} batch cmk -II")

    total = len(hosts)
    done = 0
    errors = 0

    for i in range(0, total, BATCH_SIZE):
        batch = hosts[i:i + BATCH_SIZE]
        print(f"\nBatch {i // BATCH_SIZE + 1}/{(total + BATCH_SIZE - 1) // BATCH_SIZE}: {len(batch)} host...")
        ok = rediscover_batch(batch, dry_run=args.dry_run)
        if not ok:
            errors += 1
        done += len(batch)
        print(f"  Progresso: {done}/{total}")

    print(f"\nRidiscovery completata: {done} host, {errors} errori batch.")

    if not args.dry_run:
        print("Ricarico configurazione (cmk -O)...")
        r = subprocess.run(["cmk", "-O"], capture_output=True, text=True)
        if r.returncode == 0:
            print("cmk -O: OK")
        else:
            print(f"cmk -O WARN:\n{r.stderr[:300]}")

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
