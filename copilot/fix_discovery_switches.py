#!/usr/bin/env python3
"""
Fix Check_MK Discovery WARN su switch e ns8.
- Switch: cmk -I (accept new) + cmk -U (update params)
- SW-CEDPianoPrimo1: cmk -II (full rediscovery per rimuovere vanished Interface 17)
- ns8: ignora filesystem overlay Podman + cmk -II
"""
import subprocess
import sys

def run(cmd, desc=""):
    print(f"\n>>> {desc or cmd}")
    result = subprocess.run(
        ["su", "-", "monitoring", "-s", "/bin/bash", "-c", cmd],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    out = result.stdout.strip()
    if out:
        print(out[-2000:])  # ultimi 2000 char per evitare flood
    rc = result.returncode
    print(f"    [RC={rc}]")
    return rc

print("=" * 60)
print("STEP 1: cmk -I + cmk -U su tutti e 4 gli switch")
print("=" * 60)

switches_normal = [
    "SW-AreaProgettazione1",
    "SW-AreaGare",
    "SW-AreaStrutture",
]

for host in switches_normal:
    print(f"\n--- {host} ---")
    run(f"cmk -I -h '{host}'", f"cmk -I {host}")
    run(f"cmk -U -h '{host}'", f"cmk -U {host}")

# CEDPianoPrimo1: full rediscovery per rimuovere Interface 17 vanished
print("\n--- SW-CEDPianoPrimo1 (full rediscovery) ---")
run("cmk -II -h 'SW-CEDPianoPrimo1'", "cmk -II SW-CEDPianoPrimo1 (rimuove vanished Interface 17)")

print("\n" + "=" * 60)
print("STEP 2: ns8 - aggiunge regola ignored_services per overlay Podman")
print("=" * 60)

# Leggi rules.mk ns8 se esiste già
import os

ns8_rules = "/omd/sites/monitoring/etc/check_mk/conf.d/wato/ns8/rules.mk"

if not os.path.exists(os.path.dirname(ns8_rules)):
    os.makedirs(os.path.dirname(ns8_rules), exist_ok=True)
    print(f"Creata directory: {os.path.dirname(ns8_rules)}")

if os.path.exists(ns8_rules):
    with open(ns8_rules, "r") as f:
        content = f.read()
    print(f"Contenuto attuale di {ns8_rules}:")
    print(content[:1000])
else:
    content = ""
    print(f"File {ns8_rules} non esiste, lo creo.")

# Aggiungi regola ignored_services per overlay Podman solo se non già presente
if "containers/storage/overlay" not in content:
    new_rule = """
# Ignora filesystem overlay Podman (container NS8) - volatili, cambiano ogni ciclo
ignored_services = [
  {'value': True,
   'condition': {
     'host_name': ['ns8'],
     'service_description': [{'$regex': '^Filesystem /var/lib/containers/'}]
   }},
] + ignored_services

"""
    # Scrivi backup + nuovo file
    import shutil, datetime
    if os.path.exists(ns8_rules):
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        bak = ns8_rules + f".backup_{ts}"
        shutil.copy2(ns8_rules, bak)
        subprocess.run(["chown", "monitoring:monitoring", bak])
        subprocess.run(["chmod", "660", bak])
        print(f"Backup creato: {bak}")
        new_content = content + new_rule
    else:
        new_content = new_rule.lstrip()

    with open(ns8_rules, "w") as f:
        f.write(new_content)
    # Permessi obbligatori per WATO
    subprocess.run(["chown", "monitoring:monitoring", ns8_rules])
    subprocess.run(["chmod", "660", ns8_rules])
    print(f"Regola ignored_services aggiunta a {ns8_rules}")
else:
    print("Regola overlay Podman gia' presente, skip.")

print("\n--- ns8: full rediscovery per rimuovere overlay df vanished/unmonitored ---")
run("cmk -II -h 'ns8'", "cmk -II ns8")

print("\n" + "=" * 60)
print("STEP 3: omd reload per applicare tutto")
print("=" * 60)
run("omd reload monitoring", "omd reload monitoring")

print("\n" + "=" * 60)
print("STEP 4: cmk --check su tutti i 5 host")
print("=" * 60)

for host in ["SW-AreaProgettazione1", "SW-AreaGare", "SW-CEDPianoPrimo1", "SW-AreaStrutture", "ns8"]:
    run(f"cmk --check '{host}'", f"cmk --check {host}")

print("\n=== COMPLETATO ===")
