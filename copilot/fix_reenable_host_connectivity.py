#!/usr/bin/env python3
"""
fix_reenable_host_connectivity.py

Riabilita active checks e forza re-check su tutti i servizi
"Host Connectivity" che sono stati disabilitati da disable_active_checks.py.

Operazioni:
1. Query livestatus: tutti i Host Connectivity con active_checks_enabled = 0
2. ENABLE_SVC_CHECK per ciascuno
3. SCHEDULE_FORCED_SVC_CHECK per ciascuno (active check, legittimo)
4. Riepilogo finale
"""

import subprocess
import json
import time

CMD_PIPE = "/omd/sites/monitoring/tmp/run/nagios.cmd"
SERVICE = "Host Connectivity"

def run_lq(query):
    result = subprocess.run(
        ['su', '-', 'monitoring', '-c', f'lq "{query}"'],
        capture_output=True, text=True
    )
    return json.loads(result.stdout.strip() or '[]')

def send_cmd(cmd_str):
    ts = int(time.time())
    line = f"[{ts}] {cmd_str}\n"
    with open(CMD_PIPE, 'a') as f:
        f.write(line)

def main():
    print("=" * 60)
    print("fix_reenable_host_connectivity.py")
    print("=" * 60)

    # 1. Trova tutti Host Connectivity disabilitati
    data = run_lq(
        "GET services\n"
        f"Filter: description = {SERVICE}\n"
        "Filter: active_checks_enabled = 0\n"
        "Columns: host_name description active_checks_enabled\n"
        "OutputFormat: json\n"
    )

    print(f"Host Connectivity con active checks disabilitati: {len(data)}")

    if not data:
        print("Nessun servizio da riabilitare.")
        return 0

    ts = int(time.time())
    enabled = 0
    scheduled = 0

    for row in data:
        host = row[0]
        svc = row[1]

        # ENABLE_SVC_CHECK
        line_enable = f"[{ts}] ENABLE_SVC_CHECK;{host};{svc}\n"
        with open(CMD_PIPE, 'a') as f:
            f.write(line_enable)
        enabled += 1

        # SCHEDULE_FORCED_SVC_CHECK (Host Connectivity è un active check!)
        line_sched = f"[{ts}] SCHEDULE_FORCED_SVC_CHECK;{host};{svc};{ts}\n"
        with open(CMD_PIPE, 'a') as f:
            f.write(line_sched)
        scheduled += 1

    print(f"ENABLE_SVC_CHECK inviati:           {enabled}")
    print(f"SCHEDULE_FORCED_SVC_CHECK inviati: {scheduled}")

    # 2. Attendi 5 secondi e verifica
    print("\nAttendo 5 secondi per propagazione...")
    time.sleep(5)

    # Verifica quanti ancora disabilitati
    still_disabled = run_lq(
        "GET services\n"
        f"Filter: description = {SERVICE}\n"
        "Filter: active_checks_enabled = 0\n"
        "Columns: host_name\n"
        "OutputFormat: json\n"
    )
    print(f"Host Connectivity ancora disabilitati dopo fix: {len(still_disabled)}")

    # Conta stati
    stats = run_lq(
        "GET services\n"
        f"Filter: description = {SERVICE}\n"
        "Stats: state = 0\n"
        "Stats: state = 1\n"
        "Stats: state = 2\n"
        "OutputFormat: json\n"
    )
    if stats:
        ok, warn, crit = stats[0]
        print(f"\nStato servizi Host Connectivity (dopo pochi secondi):")
        print(f"  OK:   {ok}")
        print(f"  WARN: {warn}")
        print(f"  CRIT: {crit}")
        print(f"  (i check sono stati schedulati, i risultati arriveranno entro ~2 min)")

    print("\n" + "=" * 60)
    print("Fix completato - active checks riabilitati su tutti i client.")
    print("=" * 60)
    return 0

if __name__ == "__main__":
    exit(main())
