#!/usr/bin/env python3
"""
Cambia tag 'ping': 'ping' → 'ping': 'no-ping' in tutti gli host del folder clients.
Rimuove anche la regola active_checks_enabled aggiunta in precedenza.
"""
import re, pwd, os

HOSTS_MK = "/omd/sites/monitoring/etc/check_mk/conf.d/wato/clients/hosts.mk"
RULES_MK = "/omd/sites/monitoring/etc/check_mk/conf.d/wato/clients/rules.mk"

# --- Fix hosts.mk: ping -> no-ping ---
with open(HOSTS_MK, "r") as f:
    content = f.read()

before = content.count("'ping': 'ping'")
content = content.replace("'ping': 'ping'", "'ping': 'no-ping'")
after_count = content.count("'ping': 'no-ping'")

with open(HOSTS_MK, "w") as f:
    f.write(content)

pw = pwd.getpwnam("monitoring")
os.chown(HOSTS_MK, pw.pw_uid, pw.pw_gid)
print(f"hosts.mk: sostituiti {before} tag 'ping:ping' → 'ping:no-ping'  (ora presenti: {after_count})")

# --- Fix rules.mk: rimuovi blocco active_checks_enabled ---
with open(RULES_MK, "r") as f:
    rules = f.read()

idx = rules.find("\n\nextra_service_conf.setdefault('active_checks_enabled'")
if idx != -1:
    rules = rules[:idx]
    with open(RULES_MK, "w") as f:
        f.write(rules)
    os.chown(RULES_MK, pw.pw_uid, pw.pw_gid)
    print("rules.mk: rimossa regola active_checks_enabled")
else:
    print("rules.mk: blocco active_checks_enabled non trovato (già pulito?)")
