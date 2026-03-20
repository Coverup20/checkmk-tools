#!/usr/bin/env python3
"""
Fix Discovery WARN - sintassi corretta CMK 2.4.
cmk -I <host> (senza -h) + verifica autochecks + cmk -R
"""
import subprocess
import os

def run(cmd, desc=""):
    print(f"\n>>> {desc or cmd}")
    result = subprocess.run(
        ["su", "-", "monitoring", "-s", "/bin/bash", "-c", cmd],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    out = result.stdout.strip()
    if out:
        print(out[:2000])
    print(f"    [RC={result.returncode}]")
    return result.returncode

SWITCHES = [
    "SW-AreaProgettazione1",
    "SW-AreaGare",
    "SW-CEDPianoPrimo1",
    "SW-AreaStrutture",
]

print("=" * 60)
print("STEP 1: cmk -I <host> (sintassi corretta, senza -h)")
print("=" * 60)

for host in SWITCHES:
    print(f"\n--- {host} ---")
    # Sintassi corretta CMK 2.4: cmk -I hostname
    run(f"cmk -I {host}", f"cmk -I {host}")

print("\n--- SW-CEDPianoPrimo1: full rediscovery (vanished Interface 17) ---")
run("cmk -II SW-CEDPianoPrimo1", "cmk -II SW-CEDPianoPrimo1")

print("\n" + "=" * 60)
print("STEP 2: Verifica autochecks aggiornati")
print("=" * 60)
for host in SWITCHES:
    ac_file = f"/omd/sites/monitoring/var/check_mk/autochecks/{host}.mk"
    if os.path.exists(ac_file):
        result = subprocess.run(["grep", "-c", "if64", ac_file],
                               stdout=subprocess.PIPE, text=True)
        count = result.stdout.strip()
        print(f"  {host}: {count} servizi if64 in autochecks")
    else:
        print(f"  {host}: autochecks file NON TROVATO!")

print("\n" + "=" * 60)
print("STEP 3: ns8 - verifica regola overlay + cmk -II")
print("=" * 60)

ns8_rules = "/omd/sites/monitoring/etc/check_mk/conf.d/wato/ns8/rules.mk"
if os.path.exists(ns8_rules):
    with open(ns8_rules) as f:
        content = f.read()
    print(f"ns8/rules.mk esiste ({len(content)} bytes)")
    if "containers/storage/overlay" in content:
        print("  -> Regola overlay Podman: PRESENTE")
    else:
        print("  -> Regola overlay Podman: ASSENTE!")
else:
    print(f"ns8/rules.mk NON ESISTE!")

run("cmk -II ns8", "cmk -II ns8 (rimuove overlay df)")

print("\n" + "=" * 60)
print("STEP 4: cmk -R (reload core)")
print("=" * 60)
run("cmk -R", "cmk -R")

print("\n=== COMPLETATO ===")
