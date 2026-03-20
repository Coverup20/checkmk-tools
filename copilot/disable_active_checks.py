#!/usr/bin/env python3
"""
disable_active_checks.py - Disabilita active checks (ripristino passive mode).

IMPORTANTE: esclusi intenzionalmente i servizi Check_MK* (Check_MK, Check_MK Discovery,
Check_MK Agent, Check_MK HW/SW Inventory) perche' sono i collector principali.
Disabilitarli causa stale su TUTTI i servizi dipendenti.

Version: 1.1.0
"""
import socket
import select
import time

LIVE_SOCKET = "/omd/sites/monitoring/tmp/run/live"
NAGIOS_CMD = "/omd/sites/monitoring/tmp/run/nagios.cmd"

# Servizi da NON disabilitare mai: sono i collector principali di CheckMK
# Disabilitarli causa stale a cascata su tutti i servizi dipendenti
EXCLUDED_SERVICES = {
    "Check_MK",
    "Check_MK Discovery",
    "Check_MK Agent",
    "Check_MK HW/SW Inventory",
}


def ls(q):
    s = socket.socket(socket.AF_UNIX)
    s.connect(LIVE_SOCKET)
    s.sendall(q.encode())
    d = b""
    while True:
        r, _, __ = select.select([s], [], [], 2)
        if not r:
            break
        c = s.recv(65536)
        if not c:
            break
        d += c
    s.close()
    return [l for l in d.decode().split("\n") if l.strip()]


def send_cmd(command):
    with open(NAGIOS_CMD, "w") as f:
        f.write(command + "\n")


# Query tutti i servizi con active_checks_enabled = 1
rows = ls(
    "GET services\n"
    "Filter: active_checks_enabled = 1\n"
    "Columns: host_name description\n"
    "OutputFormat: csv\n\n"
)

ts = int(time.time())
count = 0
skipped = 0
print(f"Servizi con active checks abilitati: {len(rows)}")
for row in rows:
    parts = row.split(";", 1)
    if len(parts) < 2:
        continue
    host, service = parts[0].strip(), parts[1].strip()
    if service in EXCLUDED_SERVICES:
        print(f"  SKIP (escluso): {host} - {service}")
        skipped += 1
        continue
    cmd = f"[{ts}] DISABLE_SVC_CHECK;{host};{service}"
    send_cmd(cmd)
    print(f"  DISABLED: {host} - {service}")
    count += 1

print(f"\nDisabilitati active checks su {count} servizi.")
print(f"Esclusi (Check_MK*): {skipped} servizi.")
print("Fatto. I servizi torneranno in modalita' passiva.")
