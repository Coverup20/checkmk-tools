#!/usr/bin/env python3
"""diag_passive_enabled.py - Verifica passive_checks_enabled sui servizi Check_MK*"""
import subprocess, json, time

now = int(time.time())

def lq(query):
    r = subprocess.run(
        ['su', '-', 'monitoring', '-c', f'lq "{query}"'],
        capture_output=True, text=True
    )
    raw = r.stdout.strip()
    return json.loads(raw) if raw else []

# Check passive_checks_enabled su Check_MK*
svcs = lq(
    "GET services\n"
    "Filter: description ~ Check_MK\n"
    "Columns: host_name description active_checks_enabled passive_checks_enabled check_freshness freshness_threshold\n"
    "OutputFormat: json\n"
)

print(f"Totale Check_MK* services: {len(svcs)}")
passive_0 = [r for r in svcs if r[3] == 0]
passive_1 = [r for r in svcs if r[3] == 1]
print(f"  passive_checks_enabled=0: {len(passive_0)}")
print(f"  passive_checks_enabled=1: {len(passive_1)}")
print(f"\nSample (primi 5):")
for r in svcs[:5]:
    print(f"  {r[0]:35s} | {r[1]:25s} | active={r[2]} passive={r[3]} freshness={r[4]} thresh={r[5]}")

# Verifica anche se check_freshness è impostato
fresh_check = [r for r in svcs if r[4] == 1]
print(f"\nCon check_freshness=1: {len(fresh_check)}")
