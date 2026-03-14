#!/usr/bin/env python3
"""
force-update-checkmk.py - Forza aggiornamento servizi di un host su CheckMK

Esegue flush cache, service discovery completo e ricarica configurazione
per un host specifico sul server CheckMK.

Version: 1.0.0
"""

import argparse
import shutil
import subprocess
import sys

VERSION = "1.0.0"


def run_capture(cmd: list) -> tuple:
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    return result.returncode, result.stdout or ""


def cmk_cmd(site: str, *args: str) -> list:
    """Costruisce comando cmk da eseguire come site user."""
    if shutil.which("su"):
        return ["su", "-", site, "-c", " ".join(["cmk"] + list(args))]
    # Fallback: esecuzione diretta (se già come utente corretto)
    return ["cmk"] + list(args)


def step(n: int, msg: str) -> None:
    print(f"\n{n}. {msg}...")


def main() -> int:
    p = argparse.ArgumentParser(
        description=f"force-update-checkmk.py v{VERSION} - Forza aggiornamento servizi host CheckMK",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esempi:
  python3 force-update-checkmk.py
  python3 force-update-checkmk.py --host MioHost --site monitoring
  python3 force-update-checkmk.py --host WS2022AD --grep Ransomware
        """,
    )
    p.add_argument("--host", default="WS2022AD", help="Nome host CheckMK (default: WS2022AD)")
    p.add_argument("--site", default="monitoring", help="Nome site OMD (default: monitoring)")
    p.add_argument("--grep", default="Ransomware",
                   help="Pattern grep per filtrare output debug (default: Ransomware)")
    p.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = p.parse_args()

    host = args.host
    site = args.site
    grep_pattern = args.grep

    print(f"=== FORCE UPDATE {host} SU CHECKMK ===")

    # 1. Flush cache
    step(1, "Flush cache host")
    rc, out = run_capture(cmk_cmd(site, "--flush", host))
    print(out)
    if rc != 0:
        print(f"[WARN] --flush exit code {rc}")

    # 2. Service discovery
    step(2, "Service discovery completo")
    rc, out = run_capture(cmk_cmd(site, "-II", host))
    print(out)
    if rc != 0:
        print(f"[WARN] -II exit code {rc}")

    # 3. Ricarica configurazione
    step(3, "Ricarica configurazione")
    rc, out = run_capture(cmk_cmd(site, "-O"))
    print(out)
    if rc != 0:
        print(f"[WARN] -O exit code {rc}")

    # 4. Debug plugin
    step(4, f"Output agent debug (filtro: {grep_pattern})")
    rc, out = run_capture(cmk_cmd(site, "--debug", "--detect-plugins", host))
    found = False
    for line in out.splitlines():
        if grep_pattern.lower() in line.lower():
            print(line)
            found = True
    if not found:
        print(f"[INFO] Nessuna riga con '{grep_pattern}' nell'output debug")

    # 5. Lista check attivi
    step(5, f"Verifica check attivi (filtro: {grep_pattern.lower()})")
    rc, out = run_capture(cmk_cmd(site, "--list-checks", host))
    found = False
    for line in out.splitlines():
        if grep_pattern.lower() in line.lower():
            print(line)
            found = True
    if not found:
        print(f"[INFO] Nessun check con '{grep_pattern.lower()}' trovato")

    print()
    print("=== COMPLETATO ===")
    print("Verifica nella Web GUI tra 1-2 minuti")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
