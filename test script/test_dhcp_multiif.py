"""Test rapido logica get_total_max_leases con multi-interfaccia."""
# Simula: lan=150, wan(ignore), blue=100, green=50, dnsmasq section
uci_output = """dhcp.ns_dnsmasq=dnsmasq
dhcp.ns_dnsmasq.domain=nethlab.it
dhcp.lan=dhcp
dhcp.lan.interface=lan
dhcp.lan.start=100
dhcp.lan.limit=150
dhcp.lan.leasetime=12h
dhcp.wan=dhcp
dhcp.wan.interface=wan
dhcp.wan.ignore=1
dhcp.ns_blue=dhcp
dhcp.ns_blue.interface=blue
dhcp.ns_blue.start=10
dhcp.ns_blue.limit=100
dhcp.ns_green=dhcp
dhcp.ns_green.interface=green
dhcp.ns_green.limit=50
dhcp.odhcpd=odhcpd
dhcp.odhcpd.maindhcp=0
"""

def get_total_from_string(uci_str):
    sections = {}
    for line in uci_str.splitlines():
        if '=' not in line:
            continue
        key, _, value = line.partition('=')
        key = key.strip()
        value = value.strip().strip("'")
        parts = key.split('.')
        if len(parts) == 2:
            sec = parts[1]
            if sec not in sections:
                sections[sec] = {}
            sections[sec]['_type'] = value
        elif len(parts) == 3:
            sec = parts[1]
            field = parts[2]
            if sec not in sections:
                sections[sec] = {}
            sections[sec][field] = value

    total = 0
    for sec, fields in sections.items():
        if fields.get('_type') != 'dhcp':
            continue
        if fields.get('ignore') == '1':
            continue
        try:
            total += int(fields.get('limit', 0))
        except ValueError:
            pass
    return total if total > 0 else 150

result = get_total_from_string(uci_output)
expected = 300  # lan=150 + blue=100 + green=50
ok = result == expected
print(f"{'PASS' if ok else 'FAIL'} - get_total_max_leases: atteso {expected}, ottenuto {result}")

# Test: solo dhcp.lan (nsec8-stable reale)
single_if = """dhcp.lan=dhcp
dhcp.lan.interface=lan
dhcp.lan.limit=150
dhcp.wan=dhcp
dhcp.wan.ignore=1
dhcp.odhcpd=odhcpd
"""
result2 = get_total_from_string(single_if)
ok2 = result2 == 150
print(f"{'PASS' if ok2 else 'FAIL'} - single interface: atteso 150, ottenuto {result2}")

# Test: nessun pool attivo -> fallback 150
empty = "dhcp.odhcpd=odhcpd\n"
result3 = get_total_from_string(empty)
ok3 = result3 == 150
print(f"{'PASS' if ok3 else 'FAIL'} - fallback: atteso 150, ottenuto {result3}")

all_pass = ok and ok2 and ok3
print(f"\n{'ALL PASS' if all_pass else 'SOME FAILED'}")
import sys; sys.exit(0 if all_pass else 1)
