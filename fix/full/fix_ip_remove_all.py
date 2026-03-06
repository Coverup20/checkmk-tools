#!/usr/bin/env python3
"""
fix_ip_remove_all.py - Rimuove IP hardcoded da hosts.mk per TUTTI i named host.
Lascia solo gli IP-named (es: 192.168.32.x come nome host).
CheckMK risolverà via DNS live ad ogni check.
"""
import re, ast, shutil, os
from datetime import datetime

HOSTS_MK = "/omd/sites/monitoring/etc/check_mk/conf.d/wato/rete_192_168_32_0_23/hosts.mk"
DNS_CACHE = "/omd/sites/monitoring/var/check_mk/ipaddresses.cache"


def is_ip(s):
    return bool(re.match(r'^\d+\.\d+\.\d+\.\d+$', s))


def extract_update_call(content, varname):
    marker = f"{varname}.update("
    pos = content.find(marker)
    if pos == -1:
        return None, -1, -1
    i = pos + len(marker) - 1
    depth = 0
    while i < len(content):
        if content[i] == '(':
            depth += 1
        elif content[i] == ')':
            depth -= 1
            if depth == 0:
                dict_str = content[pos + len(marker): i]
                return dict_str, pos, i + 1
        i += 1
    return None, -1, -1


with open(HOSTS_MK) as f:
    content = f.read()

ip_dict_str, ip_start, ip_end = extract_update_call(content, 'ipaddresses')
attr_dict_str, attr_start, attr_end = extract_update_call(content, 'host_attributes')

ipaddresses = ast.literal_eval(ip_dict_str)
host_attributes = ast.literal_eval(attr_dict_str)

to_remove = []

print("Rimozione IP hardcoded per tutti i named host:")
print("-" * 60)
for hostname in sorted(ipaddresses):
    if is_ip(hostname):
        print(f"  SKIP (IP-named):  {hostname}")
        continue
    to_remove.append((hostname, ipaddresses[hostname]))
    print(f"  REMOVE: {hostname:35s} = {ipaddresses[hostname]}")

print("-" * 60)
print(f"TOTALE: {len(to_remove)} IP rimossi")

if not to_remove:
    print("Niente da rimuovere.")
    raise SystemExit(0)

# Applica rimozioni
for hostname, _ in to_remove:
    del ipaddresses[hostname]
    if hostname in host_attributes and 'ipaddress' in host_attributes[hostname]:
        del host_attributes[hostname]['ipaddress']

# Backup hosts.mk
ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
backup = f"{HOSTS_MK}.backup_{ts}"
shutil.copy2(HOSTS_MK, backup)
print(f"Backup: {backup}")

# Ricostruisci sezioni
new_ip_call = f"ipaddresses.update({repr(ipaddresses)})"
new_attr_call = f"host_attributes.update({repr(host_attributes)})"

new_content = content[:attr_start] + new_attr_call + content[attr_end:]
_, ip_start2, ip_end2 = extract_update_call(new_content, 'ipaddresses')
new_content = new_content[:ip_start2] + new_ip_call + new_content[ip_end2:]

with open(HOSTS_MK, 'w') as f:
    f.write(new_content)

# Cancella DNS cache (forza risoluzione live)
if os.path.exists(DNS_CACHE):
    os.remove(DNS_CACHE)
    print(f"DNS cache cancellata: {DNS_CACHE}")

print("Fatto! Ora esegui: su - monitoring -c 'cmk -R'")
