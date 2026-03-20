import subprocess, time

switches = ['SW-CEDPianoPrimo2', 'SW-AreaProgettazione1', 'SW-CEDPianoPrimo1', 'SW-AreaStrutture']

for host in switches:
    print(f"\n--- cmk --check {host} ---")
    cmd = f'/omd/sites/monitoring/bin/cmk --check {host} 2>&1'
    r = subprocess.run(
        ['su', '-', 'monitoring', '-s', '/bin/bash', '-c', cmd],
        capture_output=True, text=True, timeout=30
    )
    print(f'RC: {r.returncode}')
    print(r.stdout[-300:] or '(no stdout)')
    time.sleep(1)

print("\nDone - attendi 30 sec poi ricontrolla livestatus")
