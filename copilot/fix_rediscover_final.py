#!/usr/bin/env python3
"""cmk -II sui 3 switch con 'changed' persistenti + verifica."""
import subprocess

SWITCHES = [
    "SW-AreaProgettazione1",
    "SW-AreaGare",
    "SW-AreaStrutture",
]

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

print("=" * 60)
print("cmk -II (full rediscovery) sui 3 switch rimanenti")
print("Aggiorna discovered_speed e risolve 'changed'")
print("=" * 60)

for host in SWITCHES:
    run(f"cmk -II {host}", f"cmk -II {host}")

run("cmk -R", "cmk -R")

print("\n" + "=" * 60)
print("Verifica finale --check-discovery")
print("=" * 60)
for host in SWITCHES:
    run(f"cmk --check-discovery {host}", f"cmk --check-discovery {host}")
