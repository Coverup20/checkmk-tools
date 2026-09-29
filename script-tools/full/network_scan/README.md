# network_scan

Network scan scripts (nmap).

## network_topology_map.py

LAN/VLAN discovery and enterprise-style network diagram for an environment
where no prior inventory exists. Starting from a seed subnet (or
auto-detected local interfaces), it ping-sweeps with `nmap`, probes SNMPv2c
on every live host (default community strings first, falling back to an
interactive per-host prompt), and - where SNMP succeeds - walks
IF-MIB/BRIDGE-MIB/Q-BRIDGE-MIB (VLANs, bridge-FDB port attachment) and
LLDP-MIB/CISCO-CDP-MIB (physical neighbors). Subnets discovered via SNMP
(router/switch IP tables) are queued back for scanning, with confirmation,
so the map grows outward from what is actually found on the wire.

Output: an editable draw.io/diagrams.net diagram (`.drawio`, plain XML) -
router/firewall on top, switches below them, then one bounded box per VLAN
(label "N/D" when unknown) holding that VLAN's devices grouped by kind
(phone/printer/host); only genuine physical links (LLDP/CDP, bridge-FDB port
attachment) are pre-drawn as edges. Open the file in draw.io/diagrams.net
(desktop app, or app.diagrams.net in a browser) to drag in and connect by
hand whatever SNMP couldn't discover - a firewall's real uplink, or which
switch an end host is actually plugged into. Also written: a JSON snapshot
of the raw discovered data (nodes/edges/subnets) for reuse without
rescanning.

Requirements:

- `nmap` (always required)
- `snmpget` + `snmpbulkwalk` (net-snmp; optional - SNMP/VLAN/LLDP phases are
  skipped with a warning if missing, falling back to L3-only discovery)
- Rendering itself (Fase 5) is pure Python, no extra package or external
  binary - only opening/editing the `.drawio` file needs draw.io/diagrams.net

Usage:

```bash
python3 network_topology_map.py --subnets 192.168.1.0/24,10.0.0.0/24
python3 network_topology_map.py --auto-detect --yes
python3 network_topology_map.py  # fully interactive
python3 network_topology_map.py --subnets 10.0.0.0/24 --output map.drawio
```

SNMPv2c only (no SNMPv3 support). The credential cache file
(`network_topology_creds.json` by default) and every generated output
(`topology-output/`, `network-topology-*.drawio/.json`) contain real
environment data (IPs, MACs, working community strings) and must never be
committed - see `.gitignore`.

Only ever point this at networks you are explicitly authorized to assess:
it sends ping/ARP discovery traffic and SNMP GET/WALK requests - including
default-credential probing - to every host it queues.
