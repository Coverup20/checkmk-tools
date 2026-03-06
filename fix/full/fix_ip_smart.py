#!/usr/bin/env python3
"""
fix_ip_smart.py - Aggiorna hosts.mk in modo intelligente:
- Se DNS (resolvectl) trova il nome → rimuove hardcode (CheckMK userà DNS live)
- Se DNS non trova il nome → mantiene hardcode (unica fonte di verità)
"""
import re, ast, subprocess, shutil, os
from datetime import datetime

HOSTS_MK = "/omd/sites/monitoring/etc/check_mk/conf.d/wato/rete_192_168_32_0_23/hosts.mk"
DNS_CACHE = "/omd/sites/monitoring/var/check_mk/ipaddresses.cache"


def is_ip(s):
    return bool(re.match(r'^\d+\.\d+\.\d+\.\d+$', s))


def resolve_resolvectl(hostname):
    """Usa resolvectl (systemd-resolved) per risolvere nomi host."""
    r = subprocess.run(
        ["resolvectl", "query", hostname],
        capture_output=True, text=True, timeout=10
    )
    # Output: "HOSTNAME: A.B.C.D  -- link: ..."
    for line in r.stdout.splitlines():
        m = re.search(r':\s+(\d+\.\d+\.\d+\.\d+)', line)
        if m:
            return m.group(1)
    return None


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

removed = []
kept_nodns = []
kept_same = []

print(f"{'HOST':<30} {'HC_IP':<18} {'DNS_IP':<18} {'AZIONE'}")
print("-" * 80)

for hostname in sorted(ipaddresses):
    if is_ip(hostname):
        continue
    hc_ip = ipaddresses[hostname]
    dns_ip = resolve_resolvectl(hostname)

    if dns_ip is None:
        kept_nodns.append((hostname, hc_ip))
        print(f"{hostname:<30} {hc_ip:<18} {'(no DNS)':<18} KEEP (no record)")
    else:
        removed.append((hostname, hc_ip, dns_ip))
        match = " (=)" if dns_ip == hc_ip else " (DIFF!)"
        print(f"{hostname:<30} {hc_ip:<18} {dns_ip:<18} REMOVE{match}")

print("-" * 80)
print(f"RIMOSSI: {len(removed)} | MANTENUTI (no DNS): {len(kept_nodns)}")

if not removed:
    print("Niente da rimuovere.")
    raise SystemExit(0)

# Applica rimozioni solo per host CON record DNS
for hostname, _, _ in removed:
    del ipaddresses[hostname]
    if hostname in host_attributes and 'ipaddress' in host_attributes[hostname]:
        del host_attributes[hostname]['ipaddress']

# Backup
ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
backup = f"{HOSTS_MK}.backup_{ts}"
shutil.copy2(HOSTS_MK, backup)
print(f"Backup: {backup}")

# Ricostruisci
new_ip_call = f"ipaddresses.update({repr(ipaddresses)})"
new_attr_call = f"host_attributes.update({repr(host_attributes)})"

new_content = content[:attr_start] + new_attr_call + content[attr_end:]
_, ip_start2, ip_end2 = extract_update_call(new_content, 'ipaddresses')
new_content = new_content[:ip_start2] + new_ip_call + new_content[ip_end2:]

with open(HOSTS_MK, 'w') as f:
    f.write(new_content)

# Cancella DNS cache di CheckMK
if os.path.exists(DNS_CACHE):
    os.remove(DNS_CACHE)
    print(f"DNS cache cancellata: {DNS_CACHE}")

print("Fatto! Ora esegui: su - monitoring -c 'cmk -R'")
