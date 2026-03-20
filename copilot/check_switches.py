import subprocess

switches = ['SW-CEDPianoPrimo2', 'SW-AreaProgettazione1', 'SW-CEDPianoPrimo1', 'SW-AreaStrutture', 'SW-AreaGare']

# Prima: vediamo discovered_speed negli autochecks di uno switch
r = subprocess.run(['su', '-', 'monitoring', '-s', '/bin/bash', '-c',
    'grep discovered_speed /omd/sites/monitoring/var/check_mk/autochecks/SW-CEDPianoPrimo1.mk | head -3'],
    capture_output=True, text=True, timeout=10)
print("=== discovered_speed in autochecks ===")
print(r.stdout[:500] or '(nessun discovered_speed)')

# Poi forza check su tutti i switch
print("\n=== cmk --check su tutti i switch ===")
cmd = '/omd/sites/monitoring/bin/cmk --check ' + ' '.join(switches) + ' 2>&1'
r2 = subprocess.run(['su', '-', 'monitoring', '-s', '/bin/bash', '-c', cmd],
                    capture_output=True, text=True, timeout=120)
print('RC:', r2.returncode)
print(r2.stdout[-1500:] or '(no output)')
