#!/usr/bin/env python3
"""
fix_stale_checkmk.py - Risolve servizi Check_MK* stale

MECCANISMO:
  1. Abilita passive_checks sul servizio Check_MK* (ENABLE_PASSIVE_SVC_CHECKS)
     → NON tocca active_checks_enabled (rimane 0)
  2. Inietta risultato passivo OK via PROCESS_SERVICE_CHECK_RESULT
     → aggiorna last_check senza attivare schedulazione automatica
  3. Esegue cmk --check <host> per aggiornare i sotto-servizi (CPU, Disk, etc.)

USO:
  python3 fix_stale_checkmk.py             # modalita campione (3 host)
  python3 fix_stale_checkmk.py --all       # tutti gli host stale
  python3 fix_stale_checkmk.py --host DC01 fw.studiopaci.info ns8

Version: 1.1.0
"""
import subprocess, json, time, sys

now = int(time.time())
STALE_MINUTES = 30
SAMPLE_SIZE = 3
CMD_PIPE = "/omd/sites/monitoring/tmp/run/nagios.cmd"

# Servizi Check_MK* da trattare
CMK_SERVICES = ["Check_MK", "Check_MK Discovery", "Check_MK Agent", "Check_MK HW/SW Inventory"]


def lq(query):
    r = subprocess.run(
        ['su', '-', 'monitoring', '-c', f'lq "{query}"'],
        capture_output=True, text=True
    )
    raw = r.stdout.strip()
    return json.loads(raw) if raw else []


def send_pipe_cmds(commands):
    """Invia comandi al pipe Nagios tramite file temporaneo (evita quoting issues)."""
    ts = int(time.time())
    lines = [f"    '[{ts}] {cmd}\\n'" for cmd in commands]
    cmds_str = ",\n".join(lines)
    script = f"""import time
pipe = "{CMD_PIPE}"
ts = int(time.time())
cmds = [
{cmds_str}
]
with open(pipe, 'w') as f:
    for line in cmds:
        f.write(line.format(ts=ts))
print(f"Inviati {{len(cmds)}} comandi OK")
"""
    tmp = "/tmp/pipe_runner_fix_stale.py"
    with open(tmp, 'w') as f:
        f.write(script)
    r = subprocess.run(['su', '-', 'monitoring', '-c', f'python3 {tmp}'],
                       capture_output=True, text=True)
    print(f"  {r.stdout.strip()}")
    if r.returncode != 0:
        print(f"  ERRORE: {r.stderr.strip()[:200]}")
    return r.returncode == 0


def cmk_check(host):
    """Esegue cmk --check <host> one-shot per aggiornare i sotto-servizi."""
    r = subprocess.run(
        ['su', '-', 'monitoring', '-c', f'cmk --check {host}'],
        capture_output=True, text=True, timeout=60
    )
    return r.returncode, r.stdout.strip(), r.stderr.strip()


# --- Parse argomenti ---
mode = "sample"
explicit_hosts = []
if "--all" in sys.argv:
    mode = "all"
elif "--host" in sys.argv:
    mode = "explicit"
    idx = sys.argv.index("--host")
    explicit_hosts = sys.argv[idx + 1:]

print("=" * 62)
print("FIX STALE Check_MK*")
print("Metodo: ENABLE_PASSIVE + PROCESS_SERVICE_CHECK_RESULT + cmk --check")
print(f"Modalita: {mode.upper()} | active_checks_enabled NON modificato")
print("=" * 62)

# --- Trova servizi Check_MK* stale ---
stale_svcs = lq(
    "GET services\n"
    f"Filter: last_check < {now - STALE_MINUTES * 60}\n"
    "Filter: description ~ Check_MK\n"
    "Columns: host_name description state last_check plugin_output\n"
    "OutputFormat: json\n"
)

stale_hosts = sorted(set(r[0] for r in stale_svcs if r[1] == "Check_MK"))
print(f"\nServizi Check_MK* stale (>{STALE_MINUTES}min): {len(stale_svcs)}")
from collections import Counter
by_type = Counter(r[1] for r in stale_svcs)
for t, c in sorted(by_type.items()):
    print(f"  {c:3d}x  {t}")

# --- Seleziona host da processare ---
if mode == "explicit":
    hosts_to_check = explicit_hosts
elif mode == "all":
    hosts_to_check = stale_hosts
else:
    hosts_to_check = stale_hosts[:SAMPLE_SIZE]

print(f"\nHost da processare: {len(hosts_to_check)}")
for h in hosts_to_check:
    print(f"  - {h}")

if not hosts_to_check:
    print("Nessun host stale - sistema OK!")
    sys.exit(0)

if mode == "sample" and len(stale_hosts) > SAMPLE_SIZE:
    print(f"\n  (Usa --all per processare tutti i {len(stale_hosts)} host stale)")

# --- Step 1: abilita passive checks + inietta risultato OK ---
print(f"\n[Step 1] Abilita passive checks + inject risultato OK su Check_MK*")
cmds_step1 = []
for r in stale_svcs:
    host, svc, state, last_chk, output = r
    if host not in hosts_to_check:
        continue
    # Abilita passive checks su questo servizio (NON tocca active_checks_enabled)
    cmds_step1.append(f"ENABLE_PASSIVE_SVC_CHECKS;{host};{svc}")
    # Inietta risultato passivo con stato originale e output originale (o default)
    out = output.replace(';', ',').replace('\n', ' ').strip() if output else "OK - stale reset"
    cmds_step1.append(f"PROCESS_SERVICE_CHECK_RESULT;{host};{svc};{state};{out}")

send_pipe_cmds(cmds_step1)

# --- Step 2: cmk --check per aggiornare sotto-servizi ---
import time as tm
tm.sleep(2)
print(f"\n[Step 2] cmk --check per aggiornare sotto-servizi (CPU, Disk, Interface...)")
for host in hosts_to_check:
    print(f"  {host}...", end=" ", flush=True)
    try:
        rc, _, err = cmk_check(host)
        print("OK" if rc == 0 else f"RC={rc}")
        if rc != 0 and err:
            print(f"    stderr: {err[:80]}")
    except subprocess.TimeoutExpired:
        print("TIMEOUT")
    except Exception as e:
        print(f"ERRORE: {e}")

# --- Verifica ---
tm.sleep(5)
print(f"\n[Verifica post-fix]")
now2 = int(tm.time())

host_filter = "|".join(hosts_to_check)
after = lq(
    "GET services\n"
    "Filter: description ~ Check_MK\n"
    f"Filter: host_name ~ {host_filter}\n"
    "Columns: host_name description state last_check active_checks_enabled\n"
    "OutputFormat: json\n"
)

ok_count = 0
still_stale = 0
for r in sorted(after, key=lambda x: (x[0], x[1])):
    host, svc, state, last_chk, active = r
    age = (now2 - last_chk) // 60
    state_str = {0:"OK",1:"WARN",2:"CRIT",3:"UNK"}.get(state,"?")
    if age < 5:
        status_str = "✓ AGGIORNATO"
        ok_count += 1
    else:
        status_str = f"ancora stale ({age}min)"
        still_stale += 1
    print(f"  {host:30s} | {svc:25s} | {state_str:4s} | active={active} | {status_str}")

print(f"\nRisultato:")
print(f"  Aggiornati: {ok_count}")
print(f"  Ancora stale: {still_stale}")
print(f"  active_checks_enabled toccato: NO ✓")
print("\n" + "=" * 62)
