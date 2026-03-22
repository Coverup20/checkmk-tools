#!/usr/bin/env python3
"""
diag_stale_services.py - Diagnostica servizi stale (>30min senza aggiornamento)
Analizza: check_type, distribution per host/servizio, stato Check_MK services
Version: 1.0.0
"""
import subprocess, json, time
from collections import defaultdict

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

print("=" * 65)
print("DIAGNOSTICA SERVIZI STALE")
print("=" * 65)

# 1. Tutti i servizi stale >30min con dettagli
stale_data = lq(
    "GET services\n"
    f"Filter: last_check < {now - 1800}\n"
    "Columns: host_name description check_type state last_check check_interval\n"
    "OutputFormat: json\n"
)

print(f"\nTotale servizi stale >30min: {len(stale_data)}")

if not stale_data:
    print("NESSUN SERVIZIO STALE - tutto OK!")
else:
    # Breakdown per check_type
    active_stale = [r for r in stale_data if r[2] == 0]
    passive_stale = [r for r in stale_data if r[2] == 1]
    print(f"  check_type=0 (attivi):  {len(active_stale)}")
    print(f"  check_type=1 (passivi): {len(passive_stale)}")

    # Breakdown per nome servizio (passivi)
    if passive_stale:
        svc_count = defaultdict(int)
        for r in passive_stale:
            svc_count[r[1]] += 1
        print(f"\nTop 15 servizi passivi stale (per frequenza):")
        for name, cnt in sorted(svc_count.items(), key=lambda x: -x[1])[:15]:
            print(f"  {cnt:4d}x  {name}")

    # Breakdown per host per i passivi
    if passive_stale:
        host_count = defaultdict(int)
        for r in passive_stale:
            host_count[r[0]] += 1
        print(f"\nHost con piu servizi passivi stale (top 15):")
        for host, cnt in sorted(host_count.items(), key=lambda x: -x[1])[:15]:
            # Trova l'eta stale peggiore per questo host
            ages = [(now - r[4]) // 60 for r in passive_stale if r[0] == host]
            max_age = max(ages)
            print(f"  {host:35s}  {cnt:3d} stale  (max {max_age}min fa)")

    # 2. Check_MK services - sono stale?
    print(f"\n{'=' * 65}")
    print("SERVIZI 'Check_MK' (principale collector agent):")
    checkmk_svcs = lq(
        "GET services\n"
        "Filter: description = Check_MK\n"
        "Columns: host_name state last_check check_interval plugin_output\n"
        "OutputFormat: json\n"
    )
    stale_checkmk = [(r[0], r[1], (now - r[2]) // 60, r[3], r[4][:50])
                     for r in checkmk_svcs if (now - r[2]) > 600]
    ok_checkmk = [(r[0], r[1], (now - r[2]) // 60, r[3])
                  for r in checkmk_svcs if (now - r[2]) <= 600]

    print(f"  Totale host con Check_MK service: {len(checkmk_svcs)}")
    print(f"  Aggiornati recenti (<=10min):     {len(ok_checkmk)}")
    print(f"  Stale (>10min):                   {len(stale_checkmk)}")

    if stale_checkmk:
        print(f"\n  Check_MK stale (>10min):")
        for host, state, age, interval, out in sorted(stale_checkmk, key=lambda x: -x[2]):
            state_str = {0: "OK", 1: "WARN", 2: "CRIT", 3: "UNK"}.get(state, "?")
            print(f"    {host:35s} state={state_str:4s} {age:4d}min fa  interval={interval}s  out={out}")

    # 3. SNMP checks stale
    print(f"\n{'=' * 65}")
    print("SERVIZI SNMP ATTIVI STALE:")
    snmp_stale = lq(
        "GET services\n"
        f"Filter: last_check < {now - 1800}\n"
        "Filter: check_type = 0\n"
        "Columns: host_name description state last_check\n"
        "OutputFormat: json\n"
    )
    print(f"  Totale: {len(snmp_stale)}")
    if snmp_stale:
        for r in sorted(snmp_stale, key=lambda x: x[3])[:15]:
            age = (now - r[3]) // 60
            print(f"  {r[0]:35s} | {r[1]:30s} | {age}min fa")

    # 4. Stato generale host (are they reachable?)
    print(f"\n{'=' * 65}")
    print("STATO HOST (quanti down/unreach?):")
    host_stats = lq(
        "GET hosts\n"
        "Stats: state = 0\n"
        "Stats: state = 1\n"
        "Stats: state = 2\n"
        "OutputFormat: json\n"
    )
    if host_stats:
        up, down, unreach = host_stats[0]
        print(f"  Up:          {up}")
        print(f"  Down:        {down}")
        print(f"  Unreachable: {unreach}")

print("\n" + "=" * 65)
print("FINE DIAGNOSTICA")
