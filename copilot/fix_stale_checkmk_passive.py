#!/usr/bin/env python3
"""
fix_stale_checkmk_passive.py - Risolve servizi Check_MK stale via PROCESS_SERVICE_CHECK_RESULT
Uso: quando Check_MK / Check_MK Discovery / Check_MK Agent compaiono come "stale"
     nel pannello Service Problems, pur essendo in stato OK.

MECCANISMO: Invia PROCESS_SERVICE_CHECK_RESULT (passive result) al pipe Nagios,
            resettando il timestamp last_check senza abilitare active checks.
            NON modifica active_checks_enabled (rimane 0).

Version: 1.0.0
"""
import subprocess, json, time, sys
from collections import Counter

now = int(time.time())

# Soglia stale: servizi non aggiornati da più di N minuti
STALE_MINUTES = int(sys.argv[1]) if len(sys.argv) > 1 else 30
STALE_SECONDS = STALE_MINUTES * 60

# Pattern di servizi da trattare (tutti Check_MK*)
SERVICE_PATTERN = "Check_MK"


def lq(query):
    r = subprocess.run(
        ['su', '-', 'monitoring', '-c', f'lq "{query}"'],
        capture_output=True, text=True
    )
    raw = r.stdout.strip()
    return json.loads(raw) if raw else []


def send_passive_results(passive_entries):
    """
    Invia PROCESS_SERVICE_CHECK_RESULT al pipe Nagios.
    passive_entries: lista di dict {host, service, state, output}
    NON abilita active checks - è solo un risultato passivo.
    """
    ts = int(time.time())
    lines = []
    for e in passive_entries:
        # Escape output: rimuovi ; e newline che romperebbero il formato pipe
        out = e['output'].replace(';', ',').replace('\n', ' ').strip()
        if not out:
            out = "OK - stale reset via passive result"
        lines.append(f"    '[{ts}] PROCESS_SERVICE_CHECK_RESULT;{e['host']};{e['service']};{e['state']};{out}\\n'")

    cmds_str = ",\n".join(lines)
    script = f"""import time
pipe = "/omd/sites/monitoring/tmp/run/nagios.cmd"
ts = int(time.time())
entries = [
{cmds_str}
]
sent = 0
with open(pipe, 'w') as f:
    for line in entries:
        f.write(line.format(ts=ts))
        sent += 1
print(f"Inviati {{sent}} passive results OK")
"""
    tmp_path = "/tmp/passive_results_runner.py"
    with open(tmp_path, 'w') as f:
        f.write(script)
    r = subprocess.run(
        ['su', '-', 'monitoring', '-c', f'python3 {tmp_path}'],
        capture_output=True, text=True
    )
    out = r.stdout.strip()
    if out:
        print(f"  {out}")
    if r.returncode != 0:
        print(f"  ERRORE pipe: {r.stderr.strip()[:300]}")
    return r.returncode == 0


print("=" * 65)
print(f"FIX STALE Check_MK* (soglia: >{STALE_MINUTES} min)")
print("Metodo: PROCESS_SERVICE_CHECK_RESULT (passive - NO active check enable)")
print("=" * 65)

# 1. Trova servizi Check_MK* stale
stale_svcs = lq(
    "GET services\n"
    f"Filter: last_check < {now - STALE_SECONDS}\n"
    f"Filter: description ~ {SERVICE_PATTERN}\n"
    "Columns: host_name description state last_check plugin_output\n"
    "OutputFormat: json\n"
)

print(f"\nServizi {SERVICE_PATTERN}* stale >{STALE_MINUTES}min: {len(stale_svcs)}")

if not stale_svcs:
    print("Nessun servizio stale - sistema OK!")
    sys.exit(0)

# Breakdown per tipo
by_type = Counter(r[1] for r in stale_svcs)
for svc_type, cnt in sorted(by_type.items()):
    print(f"  {cnt:3d}x  {svc_type}")

# Dettaglio
print(f"\nDettaglio (primi 10):")
for r in sorted(stale_svcs, key=lambda x: x[3])[:10]:
    host, svc, state, last_chk, output = r
    age = (now - last_chk) // 60
    state_str = {0:"OK", 1:"WARN", 2:"CRIT", 3:"UNK"}.get(state, "?")
    print(f"  {host:35s} | {svc:25s} | {state_str:4s} | {age}min fa")

# 2. Prepara e invia passive results
print(f"\nPreparazione passive results...")
entries = []
for r in stale_svcs:
    host, svc, state, last_chk, output = r
    # Mantieni lo stato originale (non forzare a OK se era CRIT - es. idrac)
    entries.append({
        'host': host,
        'service': svc,
        'state': state,  # preserva stato originale
        'output': output if output else f"OK - passive reset {time.strftime('%H:%M:%S')}"
    })

print(f"Invio {len(entries)} passive results al pipe Nagios...")
ok = send_passive_results(entries)

# 3. Verifica dopo 5 secondi
import time as tm
tm.sleep(5)

still_stale = lq(
    "GET services\n"
    f"Filter: last_check < {now - STALE_SECONDS}\n"
    f"Filter: description ~ {SERVICE_PATTERN}\n"
    "Columns: host_name description\n"
    "OutputFormat: json\n"
)

print(f"\n[Verifica dopo 5s]")
print(f"  Ancora stale: {len(still_stale)}")
resolved = len(stale_svcs) - len(still_stale)
print(f"  Risolti:      {resolved}/{len(stale_svcs)}")

if still_stale:
    print(f"\n  Ancora stale:")
    for r in still_stale:
        print(f"    - {r[0]} | {r[1]}")

# Stato finale
final_stats = lq(
    "GET services\n"
    "Stats: state = 0\n"
    "Stats: state = 1\n"
    "Stats: state = 2\n"
    "Stats: state = 3\n"
    "OutputFormat: json\n"
)
if final_stats:
    ok_c, warn_c, crit_c, unk_c = final_stats[0]
    print(f"\nStato globale servizi: OK={ok_c} WARN={warn_c} CRIT={crit_c} UNKNOWN={unk_c}")

print(f"\n{'=' * 65}")
print("COMPLETATO")
print(f"  Nota: active_checks_enabled rimasto 0 su tutti i servizi Check_MK")
print(f"{'=' * 65}")
