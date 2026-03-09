#!/usr/bin/env python3
"""
Aggiunge un custom_check 'Windows Alive' nel clients/rules.mk.
Questo fa sì che active_checks_rules_exist=True → CheckMK NON genera PING.
Il servizio 'Windows Alive' usa check_windows_alive (ARP) come la host check,
dando un risultato significativo invece di PING ICMP inutile.
"""
import uuid

RULES_MK = "/omd/sites/monitoring/etc/check_mk/conf.d/wato/clients/rules.mk"

with open(RULES_MK, "r") as f:
    content = f.read()

# Verifica che non ci sia già la regola
if "custom_checks" in content:
    print("ATTENZIONE: custom_checks già presente in rules.mk!")
    print("Contenuto attuale delle regole custom:")
    for line in content.splitlines():
        if "custom" in line.lower():
            print(f"  {line}")
else:
    rule_id = str(uuid.uuid4())
    new_rule = f"""

custom_checks.setdefault([])

custom_checks = [
{{'id': '{rule_id}', 'value': {{'service_description': 'Windows Alive', 'command_line': 'check_windows_alive -H $HOSTADDRESS$', 'active': True}}, 'condition': {{'host_folder': '/%s/' % FOLDER_PATH}}, 'options': {{'description': 'ARP check via nmap - sostituisce PING inutile', 'disabled': False}}}},
] + custom_checks
"""
    content += new_rule
    with open(RULES_MK, "w") as f:
        f.write(content)
    
    import pwd, os
    pw = pwd.getpwnam("monitoring")
    os.chown(RULES_MK, pw.pw_uid, pw.pw_gid)
    print(f"OK: aggiunta regola custom_checks 'Windows Alive' (id: {rule_id})")
    print("\nContenuto aggiunto:")
    print(new_rule)
