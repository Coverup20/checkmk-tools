#!/usr/bin/env python3
"""
diag_scheduler.py - Diagnostica scheduler Nagios / Check_MK checks
Version: 1.0.0
"""
import subprocess, json, time
from datetime import datetime

now = int(time.time())

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

def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return r.stdout.strip()

print("=" * 65)
print("DIAGNOSTICA SCHEDULER - PERCHE' Check_MK NON GIRA?")
print("=" * 65)

# 1. next_check per i servizi Check_MK
checkmk_svcs = lq(
    "GET services\n"
    "Filter: description = Check_MK\n"
    "Columns: host_name state last_check next_check check_interval scheduled_downtime_depth active_checks_enabled\n"
    "OutputFormat: json\n"
)
print(f"\n[1] Check_MK services - scheduling status:")
print(f"  {'Host':35s}  {'state':4}  {'last':>8}  {'next':>10}  {'int':>4}  {'act':>3}  {'dow':>3}")
print(f"  {'-'*35}  {'-'*4}  {'-'*8}  {'-'*10}  {'-'*4}  {'-'*3}  {'-'*3}")
for r in sorted(checkmk_svcs, key=lambda x: x[0]):
    host, state, last_check, next_check, interval, downtime, active = r
    last_ago = (now - last_check) // 60 if last_check > 0 else -1
    next_in = (next_check - now) // 60 if next_check > 0 else -1
    state_str = {0:"OK",1:"WARN",2:"CRIT",3:"UNK"}.get(state,"?")
    next_str = f"+{next_in}min" if next_in >= 0 else f"-{-next_in}min"
    print(f"  {host:35s}  {state_str:4s}  {last_ago:5d}min  {next_str:>10s}  {interval:>4}  {active:>3}  {downtime:>3}")

# 2. nagiostats
print(f"\n[2] Nagios stats:")
stats = run("su - monitoring -c 'nagiostats 2>&1 | head -40'")
# Filtra righe rilevanti
relevant_keywords = ['Active Service', 'Passive Service', 'Checks', 'Latency', 'Execution', 'queue', 'Queue', 'OK', 'critical', 'warning', 'Buffer', 'External', 'Reachable', 'Active Host', 'Passive Host']
for line in stats.split('\n'):
    if any(kw.lower() in line.lower() for kw in relevant_keywords):
        print(f"  {line.strip()}")

# 3. Check_MK config - check global settings
print(f"\n[3] Nagios main.cfg - check execution settings:")
cfg_check = run("su - monitoring -c 'grep -E \"execute_service_checks|execute_host_checks|accept_passive|max_concurrent\" /omd/sites/monitoring/tmp/nagios/nagios.d/*.cfg 2>/dev/null | head -10'")
if not cfg_check:
    cfg_check = run("grep -E 'execute_service_checks|execute_host_checks|accept_passive|max_concurrent' /omd/sites/monitoring/tmp/nagios/*.cfg 2>/dev/null | head -10")
print(cfg_check or "  (non trovato con path standard)")

# 4. Check nagios.cfg / main.cfg direttamente
print(f"\n[4] Nagios main config - execute checks:")
cfg2 = run("grep -rE 'execute_service_checks|execute_host_checks|accept_passive_service_checks|max_concurrent_checks' /omd/sites/monitoring/tmp/nagios/ 2>/dev/null | head -10")
print(cfg2 or "  (file non trovati)")

# Prova path diverso
cfg3 = run("ls /omd/sites/monitoring/tmp/nagios/ 2>/dev/null")
print(f"\n[5] Contenuto tmp/nagios/:")
print(cfg3 or "  (vuoto/non accessibile)")

# 6. Statusmap nagios - controlla se execute_service_checks=1
print(f"\n[6] Nagios runtime - execute_service_checks:")
exec_check = lq(
    "GET status\n"
    "Columns: execute_service_checks accept_passive_service_checks\n"
    "OutputFormat: json\n"
)
print(f"  execute_service_checks:          {exec_check[0][0] if exec_check else 'N/A'}")
print(f"  accept_passive_service_checks:   {exec_check[0][1] if exec_check else 'N/A'}")

# 7. Latency check_mk
latency = lq(
    "GET services\n"
    "Filter: description = Check_MK\n"
    "Columns: host_name latency execution_time\n"
    "OutputFormat: json\n"
)
if latency:
    print(f"\n[7] Check_MK service latency (top 5):")
    for r in sorted(latency, key=lambda x: -x[1])[:5]:
        print(f"  {r[0]:35s}  latency={r[1]:.1f}s  exec={r[2]:.1f}s")

print("\n" + "=" * 65)
