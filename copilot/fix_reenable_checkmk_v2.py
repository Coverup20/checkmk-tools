#!/usr/bin/env python3
"""
fix_reenable_checkmk_v2.py - Riabilita Check_MK* services (v2 - file-based pipe write)
Version: 1.0.1
"""
import subprocess, json, time, os, tempfile

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

def send_cmds_via_file(commands):
    """
    Scrive i comandi su un file temporaneo, poi li invia al pipe Nagios
    eseguendo come utente monitoring (evita problemi di quoting con -c).
    """
    # Crea script Python con i comandi hardcoded
    ts = int(time.time())
    lines = [f"    '[{ts}] {cmd}\\n'" for cmd in commands]
    cmds_str = ",\n".join(lines)
    
    script = f"""import time
pipe = "/omd/sites/monitoring/tmp/run/nagios.cmd"
ts = int(time.time())
cmds = [
{cmds_str}
]
sent = 0
with open(pipe, 'w') as f:
    for cmd in cmds:
        f.write(cmd.format(ts=ts))
        sent += 1
print(f"Inviati {{sent}} comandi al pipe Nagios OK")
"""
    
    # Scrivi script su file temporaneo
    tmp_path = "/tmp/nagios_cmds_runner.py"
    with open(tmp_path, 'w') as f:
        f.write(script)
    os.chmod(tmp_path, 0o644)
    
    # Esegui come utente monitoring
    r = subprocess.run(
        ['su', '-', 'monitoring', '-c', f'python3 {tmp_path}'],
        capture_output=True, text=True
    )
    if r.stdout.strip():
        print(f"  {r.stdout.strip()}")
    if r.returncode != 0 and r.stderr.strip():
        print(f"  ERRORE: {r.stderr.strip()[:300]}")
    return r.returncode == 0

print("=" * 60)
print("FIX v2: RIABILITAZIONE Check_MK SERVICES")
print("=" * 60)

# 1. Trova TUTTI i servizi Check_MK* disabilitati
disabled_svcs = lq(
    "GET services\n"
    "Filter: active_checks_enabled = 0\n"
    "Filter: description ~ Check_MK\n"
    "Columns: host_name description\n"
    "OutputFormat: json\n"
)

print(f"\nServizi Check_MK* con active_checks_enabled=0: {len(disabled_svcs)}")

# Conta per tipo
from collections import Counter
by_type = Counter(r[1] for r in disabled_svcs)
for svc_type, cnt in sorted(by_type.items()):
    print(f"  {cnt:3d}x  {svc_type}")

if not disabled_svcs:
    print("\nNessun servizio da riabilitare!")
    exit(0)

# 2. Costruisci comandi
commands = []
for host, svc in disabled_svcs:
    commands.append(f"ENABLE_SVC_CHECK;{host};{svc}")
    commands.append(f"SCHEDULE_FORCED_SVC_CHECK;{host};{svc};{now}")

print(f"\nComandi da inviare: {len(commands)}")

# 3. Invia tramite file
print("Invio comandi...")
ok = send_cmds_via_file(commands)

# 4. Attendi e verifica
import time as tm
tm.sleep(5)

print(f"\n[Verifica dopo 5s]")
still_disabled = lq(
    "GET services\n"
    "Filter: active_checks_enabled = 0\n"
    "Filter: description ~ Check_MK\n"
    "Columns: host_name description\n"
    "OutputFormat: json\n"
)
print(f"  Ancora disabilitati: {len(still_disabled)}")
if len(still_disabled) == 0:
    print("  TUTTI riabilitati!")
elif len(still_disabled) < len(disabled_svcs):
    print(f"  Parzialmente riabilitati ({len(disabled_svcs) - len(still_disabled)} / {len(disabled_svcs)})")
    for r in still_disabled[:5]:
        print(f"    - {r[0]} | {r[1]}")

# 5. Verifica stato Check_MK services
print(f"\n[Stato Check_MK dopo fix]")
after = lq(
    "GET services\n"
    "Filter: description = Check_MK\n"
    "Columns: host_name active_checks_enabled next_check last_check\n"
    "OutputFormat: json\n"
)
now2 = int(tm.time())
active_count = sum(1 for r in after if r[1] == 1)
print(f"  Check_MK con active=1: {active_count}/{len(after)}")
for r in sorted(after, key=lambda x: x[0])[:5]:
    host, active, next_chk, last_chk = r
    last_ago = (now2 - last_chk) // 60
    next_in = (next_chk - now2) // 60
    print(f"  {host:35s}  active={active}  next={next_in:+d}min")

print(f"\n{'=' * 60}")
print("Attendi 2-3 minuti per la propagazione dei risultati.")
print(f"{'=' * 60}")
