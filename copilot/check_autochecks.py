import subprocess

# Leggi autochecks di SW-CEDPianoPrimo1 per item specifici
r = subprocess.run(
    ['su', '-', 'monitoring', '-s', '/bin/bash', '-c',
     "grep -A3 -E \"'item': '43'|'item': '30'|'item': '16'\" "
     "/omd/sites/monitoring/var/check_mk/autochecks/SW-CEDPianoPrimo1.mk"],
    capture_output=True, text=True, timeout=10
)
print("=== SW-CEDPianoPrimo1 items 43/30/16 ===")
print(r.stdout[:2000] or '(vuoto)')

# Leggi autochecks di SW-AreaStrutture per item 16
r2 = subprocess.run(
    ['su', '-', 'monitoring', '-s', '/bin/bash', '-c',
     "grep -A3 -E \"'item': '16'\" "
     "/omd/sites/monitoring/var/check_mk/autochecks/SW-AreaStrutture.mk"],
    capture_output=True, text=True, timeout=10
)
print("\n=== SW-AreaStrutture item 16 ===")
print(r2.stdout[:1000] or '(vuoto)')
