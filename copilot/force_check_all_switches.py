#!/usr/bin/env python3
"""Forza cmk --check su tutti gli switch per aggiornare i risultati stale nel core."""
import subprocess

SWITCHES = [
    "SW-AreaProgettazione1",
    "SW-AreaGare",
    "SW-CEDPianoPrimo1",
    "SW-CEDPianoPrimo2",
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
        print(out[:800])
    print(f"    [RC={result.returncode}]")
    return result.returncode

print("=" * 60)
print("STEP 1: cmk --check su tutti gli switch (aggiorna risultati nel core)")
print("=" * 60)
for host in SWITCHES:
    run(f"cmk --check {host}", f"cmk --check {host}")

print("\n" + "=" * 60)
print("STEP 2: Forza check completo SW-AreaGare (include Discovery)")
print("=" * 60)
# NOTA: NON usare SCHEDULE_FORCED_SVC_CHECK per Check_MK Discovery (e' un servizio passivo CheckMK)
# cmk --check invia i risultati di TUTTI i servizi al core, incluso Discovery
run("cmk --check SW-AreaGare", "cmk --check SW-AreaGare (tutti i servizi, submits to core)")

print("\n" + "=" * 60)
print("STEP 3: Stato Discovery WARN rimanenti")
print("=" * 60)
import socket

def livestatus(q):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect("/omd/sites/monitoring/tmp/run/live")
    s.sendall(q.encode())
    s.shutdown(socket.SHUT_WR)
    d = b""
    while True:
        c = s.recv(4096)
        if not c: break
        d += c
    s.close()
    return d.decode("utf-8", errors="replace")

q = (
    "GET services\n"
    "Filter: description = Check_MK Discovery\n"
    "Filter: state > 0\n"
    "Columns: host_name state plugin_output\n"
    "OutputFormat: csv\n\n"
)
result = livestatus(q)
if not result.strip():
    print("Nessun Discovery WARN/CRIT - tutti OK!")
else:
    state_map = {"0": "OK", "1": "WARN", "2": "CRIT"}
    for line in result.strip().split("\n"):
        parts = line.split(";", 2)
        host = parts[0] if len(parts) > 0 else ""
        state = state_map.get(parts[1], parts[1]) if len(parts) > 1 else ""
        output = parts[2] if len(parts) > 2 else ""
        print(f"[{state}] {host}: {output}")

print("\n" + "=" * 60)
print("STEP 4: Totale alert per host/service")
print("=" * 60)
q2 = (
    "GET services\n"
    "Filter: state > 0\n"
    "Columns: host_name description state\n"
    "OutputFormat: csv\n\n"
)
result2 = livestatus(q2)
lines = [l for l in result2.strip().split("\n") if l]
print(f"Totale alert attivi: {len(lines)}")
for l in lines:
    parts = l.split(";", 2)
    state_map2 = {"0":"OK","1":"WARN","2":"CRIT","3":"UNKN"}
    s = state_map2.get(parts[2].strip() if len(parts)>2 else "", "?")
    print(f"  [{s}] {parts[0] if parts else ''} - {parts[1] if len(parts)>1 else ''}")
