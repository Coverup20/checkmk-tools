import subprocess, time

# 1. cmk -U
print("=== cmk -U ===")
r = subprocess.run(['su', '-', 'monitoring', '-s', '/bin/bash', '-c',
                    '/omd/sites/monitoring/bin/cmk -U 2>&1'],
                   capture_output=True, text=True, timeout=60)
print('RC:', r.returncode)
print(r.stdout[-300:])

# 2. omd reload
print("\n=== omd reload ===")
r2 = subprocess.run(['omd', 'reload', 'monitoring'],
                    capture_output=True, text=True, timeout=30)
print('RC:', r2.returncode)
print(r2.stdout[-300:])

# 3. Attendi avvio
time.sleep(5)

# 4. cmk --check su tutti i switch
switches = ['SW-CEDPianoPrimo2', 'SW-AreaProgettazione1', 'SW-CEDPianoPrimo1', 'SW-AreaStrutture', 'SW-AreaGare']
print("\n=== cmk --check switch ===")
for host in switches:
    cmd = f'/omd/sites/monitoring/bin/cmk --check {host} 2>&1'
    r3 = subprocess.run(['su', '-', 'monitoring', '-s', '/bin/bash', '-c', cmd],
                        capture_output=True, text=True, timeout=30)
    print(f'{host}: RC={r3.returncode}')
    time.sleep(1)

print("\nDone")
