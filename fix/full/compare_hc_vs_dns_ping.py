#!/usr/bin/env python3
"""
Confronto HC originale vs DNS attuale: pinga entrambi per ogni host.
Mostra se i vecchi IP HC rispondono meglio degli IP DNS.
"""
import ast, subprocess, re

BACKUP = "/omd/sites/monitoring/etc/check_mk/conf.d/wato/rete_192_168_32_0_23/hosts.mk.backup_2026-03-06_11-56-15"
CACHE  = "/omd/sites/monitoring/var/check_mk/ipaddresses.cache"

def ping(ip):
    r = subprocess.run(["ping", "-c1", "-W1", ip], capture_output=True)
    return r.returncode == 0

# Leggi HC originali
with open(BACKUP) as f:
    content = f.read()
m = re.search(r"ipaddresses\.update\((\{.*?\})\)", content, re.DOTALL)
hc_orig = ast.literal_eval(m.group(1)) if m else {}

# Leggi cache DNS
with open(CACHE) as f:
    cache = ast.literal_eval(f.read())
dns_ips = {k[0]: v for k, v in cache.items() if isinstance(k, tuple)}

hosts = sorted(set(hc_orig.keys()) | set(dns_ips.keys()))

print(f"{'HOST':<28} {'HC_ORIG':<18} {'DNS_NOW':<18} {'HC_PING':<10} {'DNS_PING'}")
print("-" * 90)

hc_up = dns_up = same_ip = hc_only = dns_only = both_up = both_down = 0
changed = []

for h in hosts:
    hc_ip  = hc_orig.get(h)
    dns_ip = dns_ips.get(h)
    if not hc_ip and not dns_ip:
        continue
    p_hc  = ping(hc_ip)  if hc_ip  else None
    p_dns = ping(dns_ip) if dns_ip else None

    hc_s  = "UP" if p_hc  else ("DOWN" if hc_ip  else "N/A")
    dns_s = "UP" if p_dns else ("DOWN" if dns_ip else "N/A")

    diff = " <<CHANGED>>" if (hc_ip and dns_ip and hc_ip != dns_ip) else ""
    print(f"{h:<28} {(hc_ip or 'N/A'):<18} {(dns_ip or 'N/A'):<18} {hc_s:<10} {dns_s}{diff}")

    if p_hc:  hc_up  += 1
    if p_dns: dns_up += 1
    if hc_ip and dns_ip and hc_ip == dns_ip: same_ip += 1
    if hc_ip and dns_ip and hc_ip != dns_ip: changed.append(h)

print("-" * 90)
print(f"HC originali UP:  {hc_up}")
print(f"DNS attuali UP:   {dns_up}")
print(f"IP cambiati:      {len(changed)}")
print(f"IP invariati:     {same_ip}")
