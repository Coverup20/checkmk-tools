#!/usr/bin/env python3
"""
undo_reenable_checkmk.py - ANNULLA: ridisabilita Check_MK* services
Version: 1.0.0
"""
import subprocess, json, time

now = int(time.time())

def lq(query):
    r = subprocess.run(
        ['su', '-', 'monitoring', '-c', f'lq "{query}"'],
        capture_output=True, text=True
    )
    raw = r.stdout.strip()
    return json.loads(raw) if raw else []

def send_cmds_via_file(commands):
    ts = int(time.time())
    lines = [f"    '[{ts}] {cmd}\\n'" for cmd in commands]
    cmds_str = ",\n".join(lines)
    script = f"""import time
pipe = "/omd/sites/monitoring/tmp/run/nagios.cmd"
ts = int(time.time())
cmds = [
{cmds_str}
]
with open(pipe, 'w') as f:
    for cmd in cmds:
        f.write(cmd.format(ts=ts))
print(f"Inviati {{len(cmds)}} comandi OK")
"""
    tmp_path = "/tmp/nagios_disable_runner.py"
    with open(tmp_path, 'w') as f:
        f.write(script)
    r = subprocess.run(
        ['su', '-', 'monitoring', '-c', f'python3 {tmp_path}'],
        capture_output=True, text=True
    )
    print(r.stdout.strip())
    if r.returncode != 0:
        print(f"ERRORE: {r.stderr.strip()[:200]}")

# I servizi che ho erroneamente riabilitato
# (tutti Check_MK* che ora hanno active=1)
currently_enabled = lq(
    "GET services\n"
    "Filter: active_checks_enabled = 1\n"
    "Filter: description ~ Check_MK\n"
    "Columns: host_name description\n"
    "OutputFormat: json\n"
)

print(f"Servizi Check_MK* attualmente con active=1: {len(currently_enabled)}")

commands = []
for host, svc in currently_enabled:
    commands.append(f"DISABLE_SVC_CHECK;{host};{svc}")

print(f"Invio {len(commands)} DISABLE_SVC_CHECK...")
send_cmds_via_file(commands)

import time as tm; tm.sleep(3)

verifica = lq(
    "GET services\n"
    "Filter: active_checks_enabled = 1\n"
    "Filter: description ~ Check_MK\n"
    "Columns: host_name description\n"
    "OutputFormat: json\n"
)
print(f"Ancora active=1 dopo undo: {len(verifica)}")
if len(verifica) == 0:
    print("UNDO COMPLETATO - tutti ridisabilitati")
