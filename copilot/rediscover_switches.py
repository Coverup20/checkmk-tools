#!/usr/bin/env python3
# Eseguire come root su srv-monitoring-sp: python3 /tmp/rediscover_switches.py
VERSION = "1.0.1"

import subprocess

switches = ['SW-CEDPianoPrimo2', 'SW-AreaProgettazione1', 'SW-CEDPianoPrimo1', 'SW-AreaStrutture', 'SW-AreaGare']

# cmk -II: full rediscovery (aggiorna discovered_speed al valore attuale)
print("=== cmk -II su tutti i switch ===")
cmd = '/omd/sites/monitoring/bin/cmk -II ' + ' '.join(switches)
r = subprocess.run(['su', '-', 'monitoring', '-s', '/bin/bash', '-c', cmd],
                   capture_output=True, text=True, timeout=120)
print('RC:', r.returncode)
print(r.stdout[-2000:] or '(no stdout)')
if r.stderr:
    print('STDERR:', r.stderr[-300:])

# cmk -U: aggiorna config core
print("\n=== cmk -U ===")
r2 = subprocess.run(['su', '-', 'monitoring', '-s', '/bin/bash', '-c',
                     '/omd/sites/monitoring/bin/cmk -U'],
                    capture_output=True, text=True, timeout=60)
print('RC:', r2.returncode)
print(r2.stdout[-500:] or '(no stdout)')
if r2.stderr:
    print('STDERR:', r2.stderr[-300:])
