#!/usr/bin/env python3
"""Confronta hardcoded IP vs DNS IP e verifica quale risponde al ping."""
import re, subprocess

HOSTS_MK = "/omd/sites/monitoring/etc/check_mk/conf.d/wato/rete_192_168_32_0_23/hosts.mk"

def ping(ip):
    r = subprocess.run(["ping", "-c1", "-W1", ip], capture_output=True)
    return r.returncode == 0

def dns(hostname):
    r = subprocess.run(["dig", hostname, "+short"], capture_output=True, text=True, timeout=5)
    for line in r.stdout.splitlines():
        if re.match(r'^\d+\.\d+\.\d+\.\d+$', line.strip()):
            return line.strip()
    return None

with open(HOSTS_MK) as f:
    content = f.read()

# Estrai ipaddresses dict
m = re.search(r"ipaddresses\.update\((\{.*?\})\)", content, re.DOTALL)
import ast
ips = ast.literal_eval(m.group(1))

def is_ip(s):
    return bool(re.match(r'^\d+\.\d+\.\d+\.\d+$', s))

print(f"{'HOST':<25} {'HC_IP':<18} {'HC_PING':<8} {'DNS_IP':<18} {'DNS_PING':<8}")
print("-" * 85)

for host in sorted(ips):
    if is_ip(host):
        continue
    hc_ip = ips[host]
    hc_up = "UP" if ping(hc_ip) else "DOWN"
    d_ip = dns(host) or ""
    d_up = ("UP" if ping(d_ip) else "DOWN") if d_ip else "no-dns"
    marker = " <-- DIFF" if hc_ip != d_ip and d_ip else ""
    print(f"{host:<25} {hc_ip:<18} {hc_up:<8} {d_ip:<18} {d_up:<8}{marker}")
