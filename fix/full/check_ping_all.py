#!/usr/bin/env python3
"""Verifica quanti IP nella cache CheckMK rispondono al ping."""
import ast, subprocess, re

CACHE = "/omd/sites/monitoring/var/check_mk/ipaddresses.cache"
HOSTS_MK = "/omd/sites/monitoring/etc/check_mk/conf.d/wato/rete_192_168_32_0_23/hosts.mk"

def ping(ip):
    r = subprocess.run(["ping", "-c1", "-W1", ip], capture_output=True)
    return r.returncode == 0

with open(CACHE) as f:
    cache = ast.literal_eval(f.read())

with open(HOSTS_MK) as f:
    content = f.read()

m = re.search(r"ipaddresses\.update\((\{.*?\})\)", content, re.DOTALL)
hc_ips = ast.literal_eval(m.group(1)) if m else {}

# Tutti gli host del folder
all_hosts_m = re.search(r"all_hosts \+= \[([^\]]+)\]", content)
all_hosts = re.findall(r"'([^']+)'", all_hosts_m.group(1)) if all_hosts_m else []

print(f"{'HOST':<30} {'IP USATO':<20} {'PING'}")
print("-" * 60)
up = []
down = []
for host in sorted(all_hosts):
    # IP usato: hardcode (da hosts.mk) oppure cache
    ip = hc_ips.get(host) or cache.get((host, 4)) or cache.get(host)
    if not ip:
        ip = host  # IP-named host
    up_flag = ping(ip)
    status = "UP" if up_flag else "DOWN"
    src = "HC" if host in hc_ips else ("DNS" if (host,4) in cache else "IP-name")
    print(f"{host:<30} {ip:<20} {status}  ({src})")
    if up_flag:
        up.append(host)
    else:
        down.append(host)

print("-" * 60)
print(f"UP: {len(up)} | DOWN: {len(down)}")
