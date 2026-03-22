#!/usr/bin/env python3
"""cmk -U sui 3 switch che hanno ancora 'changed', poi verifica finale."""
import subprocess

SWITCHES_CHANGED = [
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
print("cmk -U (aggiorna discovered_speed e altri parametri changed)")
print("=" * 60)
for host in SWITCHES_CHANGED:
    run(f"cmk -IU {host}", f"cmk -IU {host}")

run("cmk -R", "cmk -R")

print("\n" + "=" * 60)
print("Verifica finale --check-discovery")
print("=" * 60)
for host in SWITCHES_CHANGED:
    run(f"cmk --check-discovery {host}", f"cmk --check-discovery {host}")
