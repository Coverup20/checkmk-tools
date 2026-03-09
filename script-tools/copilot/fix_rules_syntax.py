#!/usr/bin/env python3
"""Fix rules.mk: sostituisce la riga errata custom_checks.setdefault con globals().setdefault"""
import pwd, os

RULES_MK = "/omd/sites/monitoring/etc/check_mk/conf.d/wato/clients/rules.mk"

with open(RULES_MK, "r") as f:
    content = f.read()

# Sostituisce la riga sbagliata
bad = "custom_checks.setdefault([])"
good = "globals().setdefault('custom_checks', [])"

if bad in content:
    content = content.replace(bad, good)
    with open(RULES_MK, "w") as f:
        f.write(content)
    pw = pwd.getpwnam("monitoring")
    os.chown(RULES_MK, pw.pw_uid, pw.pw_gid)
    print("OK: corretto custom_checks.setdefault -> globals().setdefault")
else:
    print("Riga errata non trovata - verifico contenuto del blocco custom_checks:")
    for i, line in enumerate(content.splitlines()):
        if 'custom' in line.lower():
            print(f"  {i+1}: {line}")

print("\nBloccato custom_checks in rules.mk:")
for line in content.splitlines():
    if 'custom_check' in line:
        print(f"  {line}")
