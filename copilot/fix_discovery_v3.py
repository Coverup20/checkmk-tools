#!/usr/bin/env python3
"""
Fix Discovery WARN - step finale: cmk -U per aggiornare i 'changed'
Gli autochecks sono già aggiornati da fix_discovery_v2.py.
Ora manca solo cmk -U per allineare i parametri 'changed'.
"""
import subprocess

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
print("cmk -U su tutti gli switch (aggiorna 'changed')")
print("=" * 60)

for host in SWITCHES:
    run(f"cmk -U {host}", f"cmk -U {host}")

print("\n" + "=" * 60)
print("cmk -R (reload)")
print("=" * 60)
run("cmk -R", "cmk -R")

print("\n=== DONE ===")
