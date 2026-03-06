#!/usr/bin/env python3
"""
fix_ip_safe_removal.py - Rimuove IP hardcoded da hosts.mk SOLO se DNS AD risolve allo stesso IP.
Se DNS restituisce IP diverso o non trova il nome -> mantiene l'IP hardcoded.
"""
import re, ast, subprocess, shutil
from datetime import datetime

HOSTS_MK = "/omd/sites/monitoring/etc/check_mk/conf.d/wato/rete_192_168_32_0_23/hosts.mk"
DOMAIN = "ad.studiopaci.info"


def is_ip(s):
    return bool(re.match(r'^\d+\.\d+\.\d+\.\d+$', s))


def resolve_dns(hostname):
    # Usa il DNS di sistema (risolve tramite VPN/tunnel verso AD)
    for name in [f"{hostname}.{DOMAIN}", hostname]:
        try:
            r = subprocess.run(
                ["dig", name, "+short", "A"],
                capture_output=True, text=True, timeout=5
            )
            for line in r.stdout.strip().splitlines():
                line = line.strip()
                if re.match(r'^\d+\.\d+\.\d+\.\d+$', line):
                    return line
        except Exception:
            pass
    return None


def extract_update_call(content, varname):
    """Find positions and dict string inside varname.update({...})."""
    marker = f"{varname}.update("
    pos = content.find(marker)
    if pos == -1:
        return None, -1, -1
    i = pos + len(marker) - 1  # points to '('
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
kept_nodns = []
kept_mismatch = []

print("Analisi DNS per ogni host con nome proprio:")
print("-" * 70)
for hostname in sorted(ipaddresses):
    if is_ip(hostname):
        continue
    hardcoded_ip = ipaddresses[hostname]
    dns_ip = resolve_dns(hostname)
    if dns_ip is None:
        kept_nodns.append((hostname, hardcoded_ip))
        print(f"  KEEP (no DNS):      {hostname:30s} = {hardcoded_ip}")
    elif dns_ip == hardcoded_ip:
        to_remove.append(hostname)
        print(f"  REMOVE (DNS match): {hostname:30s} = {hardcoded_ip}")
    else:
        kept_mismatch.append((hostname, hardcoded_ip, dns_ip))
        print(f"  KEEP (DNS diff):    {hostname:30s}  hc={hardcoded_ip}  dns={dns_ip}")

print("-" * 70)
print(f"TOTALE: {len(to_remove)} da rimuovere | {len(kept_nodns)} no DNS | {len(kept_mismatch)} DNS diverso")

if not to_remove:
    print("Niente da rimuovere.")
    raise SystemExit(0)

# Applica rimozioni
for hostname in to_remove:
    del ipaddresses[hostname]
    if hostname in host_attributes and 'ipaddress' in host_attributes[hostname]:
        del host_attributes[hostname]['ipaddress']

# Backup
ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
backup = f"{HOSTS_MK}.backup_{ts}"
shutil.copy2(HOSTS_MK, backup)
print(f"Backup: {backup}")

# Ricostruisci le due sezioni
new_ip_call = f"ipaddresses.update({repr(ipaddresses)})"
new_attr_call = f"host_attributes.update({repr(host_attributes)})"

# Sostituisci host_attributes prima (posizione più avanzata nel file)
new_content = content[:attr_start] + new_attr_call + content[attr_end:]

# Ricalcola posizione ipaddresses nel nuovo contenuto e sostituisci
_, ip_start2, ip_end2 = extract_update_call(new_content, 'ipaddresses')
new_content = new_content[:ip_start2] + new_ip_call + new_content[ip_end2:]

with open(HOSTS_MK, 'w') as f:
    f.write(new_content)

print(f"Fatto! Rimossi {len(to_remove)} IP hardcoded.")
print("Esegui: su - monitoring -c 'cmk -O'")
