#!/usr/bin/env python3
"""
Diagnostica profonda: verifica CMC scheduler, run manuale cmk --check, log errori
"""
import subprocess, socket, select, time, os

def live(q):
    s = socket.socket(socket.AF_UNIX)
    s.connect("/omd/sites/monitoring/tmp/run/live")
    s.sendall(q.encode())
    d = b""
    while True:
        r, _, __ = select.select([s], [], [], 3)
        if not r: break
        c = s.recv(65536)
        if not c: break
        d += c
    s.close()
    return d.decode().strip()

def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
    return r.stdout.strip(), r.stderr.strip(), r.returncode

print("=" * 70)
print("DIAGNOSTICA PROFONDA CMC SCHEDULER")
print("=" * 70)

# 1. Stato OMD
print("\n[1] OMD STATUS:")
out, err, rc = run("su - monitoring -c 'omd status 2>&1' | head -20")
print(out or err)

# 2. Verifica globali CMC
print("\n[2] GLOBAL FLAGS (active_checks, passive_checks):")
r = live("GET status\nColumns: enable_checks enable_flap_detection execute_service_checks accept_passive_checks accept_passive_service_checks\n")
print(r)

# 3. Controlla host-level flags
print("\n[3] HOST check flags (primissimi stale):")
r = live("GET hosts\nFilter: name = ns8\nColumns: name active_checks_enabled passive_checks_enabled check_interval\n")
print(f"  ns8: {r}")
r = live("GET hosts\nFilter: name = DC01\nColumns: name active_checks_enabled passive_checks_enabled check_interval\n")
print(f"  DC01: {r}")
r = live("GET hosts\nFilter: name = fw.studiopaci.info\nColumns: name active_checks_enabled passive_checks_enabled check_interval\n")
print(f"  fw.studiopaci.info: {r}")

# 4. Quanto tempo fa è stato schedulato Check_MK per ns8
print("\n[4] SCHEDULING info per ns8 Check_MK:")
r = live("GET services\nFilter: host_name = ns8\nFilter: description = Check_MK\nColumns: host_name description last_check next_check staleness active_checks_enabled check_interval\n")
print(f"  {r}")

# 5. Test manuale cmk --check su un host piccolo
print("\n[5] TEST cmk --check ns8 (output prime 20 righe):")
out, err, rc = run("su - monitoring -c 'cmk --check ns8 2>&1' | head -20")
print(f"  RC={rc}")
print(out or err or "(nessun output)")

# 6. Controlla ultimi log CMC
print("\n[6] LOG CMC (ultimi errori):")
cmc_log = "/omd/sites/monitoring/var/log/cmc.log"
if os.path.exists(cmc_log):
    out, _, _ = run(f"tail -30 {cmc_log} | grep -i 'error\\|warn\\|fail\\|disable\\|stale' | head -20")
    print(out or "  (nessun errore recente)")
else:
    print(f"  File non trovato: {cmc_log}")

# 7. Controlla se ci sono host con execute_service_checks disabilitato
print("\n[7] HOST con checks disabilitati (active/passive):")
r = live("GET hosts\nFilter: active_checks_enabled = 0\nColumns: name active_checks_enabled\n")
hosts_disabled = [l.split(";")[0] for l in r.split("\n") if l.strip()]
print(f"  Host con active_checks_enabled=0: {len(hosts_disabled)}")
if hosts_disabled[:10]:
    for h in hosts_disabled[:10]:
        print(f"    - {h}")

# 8. Conta servizi con next_check nel passato (check scaduto ma non eseguito)
print("\n[8] Servizi con next_check nel passato > 5 min:")
now = int(time.time())
r = live(f"GET services\nFilter: next_check < {now - 300}\nFilter: active_checks_enabled = 1\nStats: state >= 0\n")
print(f"  (active=1 e next_check scaduto): {r}")

# 9. Verifica periodo check
print("\n[9] CHECK il periodo corrente (timeperiod):")
out, _, rc = run("date")
print(f"  Data/ora: {out}")
r = live("GET timeperiods\nColumns: name in\n")
for line in r.split("\n"):
    if line.strip():
        print(f"  Timeperiod: {line}")

print("\n" + "=" * 70)
