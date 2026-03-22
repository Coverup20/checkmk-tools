#!/usr/bin/env python3
"""
fix_reenable_checkmk_services.py - Riabilita Check_MK e Check_MK Discovery su tutti gli host
Causa: disable_active_checks.py di ieri aveva disabilitato TUTTI i check attivi,
       inclusi Check_MK e Check_MK Discovery (non solo Host Connectivity).
Fix: ENABLE_SVC_CHECK + SCHEDULE_FORCED_SVC_CHECK su Check_MK e Check_MK Discovery.
Version: 1.0.0
"""
import subprocess, json, time, os

now = int(time.time())
CMD_PIPE = "/omd/sites/monitoring/tmp/run/nagios.cmd"

def lq(query):
    r = subprocess.run(
        ['su', '-', 'monitoring', '-c', f'lq "{query}"'],
        capture_output=True, text=True
    )
    raw = r.stdout.strip()
    if not raw:
        return []
    try:
        return json.loads(raw)
    except:
        return []

def send_cmds(commands):
    """Invia comandi al pipe Nagios come utente monitoring"""
    script = f"""
import os, time
pipe = "{CMD_PIPE}"
ts = int(time.time())
cmds = {repr(commands)}
with open(pipe, 'w') as f:
    for cmd in cmds:
        f.write(f"[{{ts}}] {{cmd}}\\n")
print(f"Inviati {{len(cmds)}} comandi al pipe Nagios")
"""
    r = subprocess.run(
        ['su', '-', 'monitoring', '-c', f'python3 -c {repr(script)}'],
        capture_output=True, text=True
    )
    print(r.stdout.strip())
    if r.stderr.strip():
        print(f"STDERR: {r.stderr.strip()[:200]}")

print("=" * 60)
print("FIX: RIABILITAZIONE Check_MK SERVICES")
print("=" * 60)

# 1. Trova tutti i Check_MK e Check_MK Discovery con active_checks_enabled=0
disabled_svcs = lq(
    "GET services\n"
    "Filter: active_checks_enabled = 0\n"
    "Filter: description ~ Check_MK\n"
    "Columns: host_name description\n"
    "OutputFormat: json\n"
)

# Separa per tipo
checkmk_disabled = [r for r in disabled_svcs if r[1] == "Check_MK"]
discovery_disabled = [r for r in disabled_svcs if r[1] == "Check_MK Discovery"]

print(f"\nServizi trovati con active_checks_enabled=0:")
print(f"  Check_MK:           {len(checkmk_disabled)}")
print(f"  Check_MK Discovery: {len(discovery_disabled)}")

if not checkmk_disabled and not discovery_disabled:
    print("\nNessun servizio da riabilitare. Tutto OK!")
    exit(0)

# 2. Costruisci i comandi ENABLE + SCHEDULE_FORCED
commands = []
for host, svc in checkmk_disabled:
    commands.append(f"ENABLE_SVC_CHECK;{host};{svc}")
    commands.append(f"SCHEDULE_FORCED_SVC_CHECK;{host};{svc};{now}")

for host, svc in discovery_disabled:
    commands.append(f"ENABLE_SVC_CHECK;{host};{svc}")
    commands.append(f"SCHEDULE_FORCED_SVC_CHECK;{host};{svc};{now}")

print(f"\nComandi da inviare: {len(commands)}")
print(f"  ({len(checkmk_disabled)} ENABLE+FORCE Check_MK)")
print(f"  ({len(discovery_disabled)} ENABLE+FORCE Check_MK Discovery)")

# 3. Invia comandi
print(f"\nInvio comandi al pipe Nagios...")
send_cmds(commands)

# 4. Attendi 5 secondi e verifica
import time as time_module
time_module.sleep(5)

print(f"\n[Verifica post-fix]")
still_disabled = lq(
    "GET services\n"
    "Filter: active_checks_enabled = 0\n"
    "Filter: description ~ Check_MK\n"
    "Columns: host_name description\n"
    "OutputFormat: json\n"
)
print(f"  Ancora disabilitati dopo fix: {len(still_disabled)}")
if still_disabled:
    for r in still_disabled:
        print(f"    - {r[0]} | {r[1]}")
else:
    print("  TUTTI riabilitati!")

# 5. Controlla latency e next_check
print(f"\n[Stato Check_MK dopo fix (prime 5 righe)]")
after = lq(
    "GET services\n"
    "Filter: description = Check_MK\n"
    "Columns: host_name state active_checks_enabled next_check last_check\n"
    "OutputFormat: json\n"
)
now2 = int(time_module.time())
for r in sorted(after, key=lambda x: x[0])[:5]:
    host, state, active, next_chk, last_chk = r
    last_ago = (now2 - last_chk) // 60
    next_in = (next_chk - now2) // 60
    print(f"  {host:35s}  active={active}  last={last_ago}min fa  next={next_in:+d}min")

print(f"\n{'=' * 60}")
print("FIX COMPLETATO")
print("Attendere ~2-3 minuti per la propagazione dei check.")
print(f"{'=' * 60}")
