#!/usr/bin/env python3
"""
Fix finale:
1. Forza cmk --check-discovery su tutti gli switch (aggiorna livestatus)
2. Fix ns8/rules.mk duplicato
3. Mostra contenuto autochecks per diagnosi
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

def run(cmd, desc=""):
    print(f"\n>>> {desc or cmd}")
    result = subprocess.run(
        ["su", "-", "monitoring", "-s", "/bin/bash", "-c", cmd],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    out = result.stdout.strip()
    if out:
        print(out[:1500])
    print(f"    [RC={result.returncode}]")
    return result.returncode

# --- 1. Mostra contenuto reale di un autochecks per capire il formato ---
print("=" * 60)
print("STEP 1: Contenuto reale autochecks SW-AreaProgettazione1")
print("=" * 60)
ac = f"{BASE}/SW-AreaProgettazione1.mk"
if os.path.exists(ac):
    with open(ac) as f:
        content = f.read()
    print(content[:2000])
else:
    print("FILE NON TROVATO!")

# --- 2. Fix ns8/rules.mk duplicato ---
print("\n" + "=" * 60)
print("STEP 2: Fix ns8/rules.mk (rimuove duplicato)")
print("=" * 60)
ns8_rules = "/omd/sites/monitoring/etc/check_mk/conf.d/wato/ns8/rules.mk"
if os.path.exists(ns8_rules):
    rule_single = """# Ignora filesystem overlay Podman (container NS8) - volatili, cambiano ogni ciclo
ignored_services = [
  {'value': True,
   'condition': {
     'host_name': ['ns8'],
     'service_description': [{'$regex': '^Filesystem /var/lib/containers/'}]
   }},
] + ignored_services
"""
    with open(ns8_rules, "w") as f:
        f.write(rule_single)
    subprocess.run(["chown", "monitoring:monitoring", ns8_rules])
    subprocess.run(["chmod", "660", ns8_rules])
    print(f"ns8/rules.mk riscritto (deduplicato), {len(rule_single)} bytes")
else:
    print("ns8/rules.mk non esiste!")

# --- 3. Forza cmk --check-discovery su tutti gli switch ---
print("\n" + "=" * 60)
print("STEP 3: cmk --check-discovery (forza aggiornamento Discovery check)")
print("=" * 60)
for host in SWITCHES:
    run(f"cmk --check-discovery {host}", f"cmk --check-discovery {host}")

# Per ns8 anche
run("cmk --check-discovery ns8", "cmk --check-discovery ns8")

# --- 4. cmk -R finale ---
print("\n" + "=" * 60)
print("STEP 4: cmk -R")
print("=" * 60)
run("cmk -R", "cmk -R")

print("\n=== DONE ===")
