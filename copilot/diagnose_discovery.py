#!/usr/bin/env python3
"""
Diagnosi approfondita: legge e mostra gli autochecks attuali degli switch
e verifica cosa trova il discovery live.
"""
import subprocess
import os

SWITCHES = [
    "SW-AreaProgettazione1",
    "SW-AreaGare",
    "SW-CEDPianoPrimo1",
    "SW-AreaStrutture",
]
BASE = "/omd/sites/monitoring/var/check_mk/autochecks"

def run(cmd):
    result = subprocess.run(
        ["su", "-", "monitoring", "-s", "/bin/bash", "-c", cmd],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    return result.stdout.strip(), result.returncode

print("=" * 60)
print("AUTOCHECKS ATTUALI - servizi if64")
print("=" * 60)
for host in SWITCHES:
    path = f"{BASE}/{host}.mk"
    if os.path.exists(path):
        out, _ = run(f"grep 'if64' {path} | grep -o 'Interface [0-9]*' | sort -t' ' -k2 -n")
        lines = [l for l in out.split("\n") if l.strip()]
        print(f"\n{host}: {len(lines)} porte if64")
        print("  " + ", ".join(lines))
    else:
        print(f"\n{host}: FILE NON TROVATO!")

print("\n" + "=" * 60)
print("DISCOVERY LIVE - cosa trovano ora gli switch via SNMP")
print("=" * 60)
for host in SWITCHES:
    print(f"\n--- {host} ---")
    out, rc = run(f"cmk --services {host} 2>/dev/null | grep if64 | awk '{{print $2, $3}}'")
    if not out:
        # cmk --services potrebbe non esistere, prova con --list-checks
        out, rc = run(f"cmk -I --dry-run {host} 2>&1 | head -30")
    print(f"  {out[:500] if out else '(nessun output)'} [RC={rc}]")

print("\n" + "=" * 60)
print("VERIFICA ns8/rules.mk contenuto")
print("=" * 60)
ns8_rules = "/omd/sites/monitoring/etc/check_mk/conf.d/wato/ns8/rules.mk"
if os.path.exists(ns8_rules):
    with open(ns8_rules) as f:
        print(f.read())
else:
    print("FILE NON ESISTE!")
