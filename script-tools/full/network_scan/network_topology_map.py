#!/usr/bin/env python3
"""network_topology_map.py - LAN/VLAN discovery and interactive topology map

Builds a network map of an unknown environment starting from nothing but a
seed subnet (or auto-detected local interfaces):

  [Fase 1] Ping sweep each queued subnet with nmap (-sn) -> live hosts + MAC.
  [Fase 2] Probe SNMPv2c on every live host, trying a list of default
           community strings first; on failure, interactively offer to enter
           a custom community for that specific host (cached for reuse).
  [Fase 3] For hosts that answer SNMP, walk IF-MIB/BRIDGE-MIB/Q-BRIDGE-MIB
           (VLANs) and LLDP-MIB/CISCO-CDP-MIB (physical neighbors), and read
           ipAddrTable/ipNetToMediaTable to discover subnets not in the
           original seed list.
  [Fase 4] Newly discovered subnets are queued back into Fase 1 (with
           confirmation, unless --yes), so the map grows outward from what
           was actually found on the wire instead of a fixed input list.
  [Fase 5] Render an editable draw.io/diagrams.net diagram (.drawio, plain
           XML, no external tool needed to generate it): router/firewall on
           top, switches below them, then one bounded box per VLAN (label
           "N/D" when unknown) holding that VLAN's devices grouped by kind
           (phone/printer/host). Only genuine physical links (LLDP/CDP,
           bridge-FDB-derived switch-port attachment) are pre-drawn as
           edges - open the file in draw.io/diagrams.net to drag in and
           connect by hand whatever SNMP couldn't discover (a firewall's
           real uplink, which switch an end host is actually plugged into).

Requires the `nmap` binary always, and `snmpget`/`snmpbulkwalk` (net-snmp)
for the SNMP phases (Fase 2-4 are skipped with a warning if not found).
Rendering (Fase 5) is pure Python, no external tool required to generate
the .drawio file - only to open/edit it (draw.io desktop app, or
app.diagrams.net in a browser).

SNMPv2c only. No SNMPv3 support yet (documented as a known limitation).

This tool sends ping/ARP discovery traffic and SNMP GET/WALK requests
(read-only) to every host it queues, including default-credential probing.
Only ever point it at networks you are explicitly authorized to assess.

Usage:
    network_topology_map.py --subnets 192.168.1.0/24,10.0.0.0/24
    network_topology_map.py --auto-detect
    network_topology_map.py  # fully interactive

Version: 1.0.0"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import shutil
import socket
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

VERSION = "1.0.0"

DEFAULT_COMMUNITIES = [
    "public", "private", "community", "cisco", "admin",
    "manager", "snmpd", "switch", "router", "netman",
]

DEFAULT_SNMP_TIMEOUT = 2
DEFAULT_SNMP_RETRIES = 1
DEFAULT_MAX_EXPANSIONS = 25

OID_SYSDESCR = "1.3.6.1.2.1.1.1.0"
OID_SYSNAME = "1.3.6.1.2.1.1.5.0"
OID_IPADENTADDR = "1.3.6.1.2.1.4.20.1.1"
OID_IPADENTNETMASK = "1.3.6.1.2.1.4.20.1.3"
OID_IPNETTOMEDIA_PHYSADDR = "1.3.6.1.2.1.4.22.1.2"
OID_IPNETTOMEDIA_NETADDR = "1.3.6.1.2.1.4.22.1.3"
OID_DOT1DTPFDB_PORT = "1.3.6.1.2.1.17.4.3.1.2"
OID_DOT1DBASEPORT_IFINDEX = "1.3.6.1.2.1.17.1.4.1.2"
OID_IFDESCR = "1.3.6.1.2.1.2.2.1.2"
OID_DOT1QVLANSTATICNAME = "1.3.6.1.2.1.17.7.1.4.3.1.1"
OID_DOT1QPVID = "1.3.6.1.2.1.17.7.1.4.5.1.1"
OID_LLDP_REM_SYSNAME = "1.0.8802.1.1.2.1.4.1.1.9"
OID_LLDP_REM_PORTID = "1.0.8802.1.1.2.1.4.1.1.7"
OID_CDP_DEVICEID = "1.3.6.1.4.1.9.9.23.1.2.1.1.6"
OID_CDP_DEVICEPORT = "1.3.6.1.4.1.9.9.23.1.2.1.1.7"



@dataclass
class NodeRecord:
    ip: str
    mac: Optional[str] = None
    vendor: Optional[str] = None
    hostname: Optional[str] = None
    sysname: Optional[str] = None
    sysdescr: Optional[str] = None
    role: str = "host"  # host | switch | router
    vlans: Set[str] = field(default_factory=set)
    snmp_ok: bool = False


@dataclass
class EdgeRecord:
    a: str
    b: str
    kind: str  # physical | subnet
    label: str = ""


def log(message: str) -> None:
    print(f"[INFO] {message}")


def warn(message: str) -> None:
    print(f"[WARN] {message}")


def die(message: str) -> None:
    print(f"[ERR] {message}", file=sys.stderr)
    raise SystemExit(1)


# ---------------------------------------------------------------------------
# Pure parsing / logic helpers (unit-tested, no subprocess/network I/O)
# ---------------------------------------------------------------------------

def parse_nmap_xml(xml_text: str) -> List[Dict[str, Optional[str]]]:
    """Parse `nmap -oX -` output into a list of {ip, mac, vendor, hostname}."""
    hosts: List[Dict[str, Optional[str]]] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return hosts

    for host_el in root.findall("host"):
        status_el = host_el.find("status")
        if status_el is not None and status_el.get("state") != "up":
            continue

        ip = None
        mac = None
        vendor = None
        for addr_el in host_el.findall("address"):
            addrtype = addr_el.get("addrtype")
            if addrtype == "ipv4":
                ip = addr_el.get("addr")
            elif addrtype == "mac":
                mac = addr_el.get("addr")
                vendor = addr_el.get("vendor") or None

        if not ip:
            continue

        hostname = None
        hostnames_el = host_el.find("hostnames")
        if hostnames_el is not None:
            name_el = hostnames_el.find("hostname")
            if name_el is not None:
                hostname = name_el.get("name")

        hosts.append({"ip": ip, "mac": mac, "vendor": vendor, "hostname": hostname})

    return hosts


# net-snmp's textual stand-ins for the SNMPv2 exception values (noSuchObject,
# noSuchInstance, endOfMibView): printed as the "value" on an otherwise
# well-formed "<oid> <text>" line when the walked subtree is empty on that
# agent. Left unfiltered, every one of these looked like a real table row -
# e.g. a firewall/hypervisor/printer with no bridge/VLAN MIB at all still
# produced a non-empty bridge_entries/vlan_entries list, so classify_device()
# called it a "switch" purely because SNMP answered at all.
SNMP_EXCEPTION_VALUES = {
    "No Such Object available on this agent at this OID",
    "No Such Instance currently exists at this OID",
    "No more variables left in this MIB View",
}


def parse_snmp_walk_output(text: str) -> List[Tuple[str, str]]:
    """Parse `snmpbulkwalk -Oqn` output ("<oid> <value>" per line).

    Rows whose value is one of net-snmp's exception placeholders are dropped -
    they mean "nothing at this OID", not "a row with this text".
    """
    results: List[Tuple[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(\.?[0-9.]+)\s+(.*)$", line)
        if not m:
            continue
        oid, value = m.group(1).lstrip("."), m.group(2).strip().strip('"')
        if value in SNMP_EXCEPTION_VALUES:
            continue
        results.append((oid, value))
    return results


def classify_device(has_vlan_or_bridge: bool, ip_interface_count: int) -> str:
    """Heuristic device role from SNMP table presence."""
    if has_vlan_or_bridge:
        return "switch"
    if ip_interface_count > 1:
        return "router"
    return "host"


def build_subnets_from_ip_table(
    ip_addr_entries: List[Tuple[str, str]],
    netmask_entries: List[Tuple[str, str]],
) -> Set[str]:
    """Combine ipAdEntAddr/ipAdEntNetMask walk rows (same index suffix) into CIDRs."""
    masks_by_index = {oid: value for oid, value in netmask_entries}
    subnets: Set[str] = set()
    for oid, addr in ip_addr_entries:
        mask = masks_by_index.get(oid)
        if not mask:
            continue
        try:
            network = ipaddress.ip_network(f"{addr}/{mask}", strict=False)
        except ValueError:
            continue
        if network.prefixlen == 32:
            continue
        subnets.add(str(network))
    return subnets


def decode_fdb_mac(oid: str) -> Optional[str]:
    """dot1dTpFdbPort walk OID -> 'AA:BB:CC:DD:EE:FF'.

    BRIDGE-MIB indexes dot1dTpFdbTable by the learned MAC address itself, so
    the walked OID is "<column-prefix>.<6 decimal octets>" - e.g. suffix
    "0.13.72.89.1.66" is the MAC 00:0D:48:59:01:42.
    """
    parts = oid.split(".")
    if len(parts) < 6:
        return None
    try:
        octets = [int(p) for p in parts[-6:]]
    except ValueError:
        return None
    if any(o < 0 or o > 255 for o in octets):
        return None
    return ":".join(f"{o:02X}" for o in octets)


def filter_direct_attachment_macs(
    bridge_entries: List[Tuple[str, str]], max_macs_per_port: int = 4,
) -> List[Tuple[str, str]]:
    """Drop FDB rows on ports where too many distinct MACs were learned.

    A switch's bridge-FDB records every MAC it has ever seen traffic for on
    each port - on an uplink/trunk port to another switch, that's every
    downstream device behind it, not devices wired directly into this one.
    Keeping those rows would draw dozens of hosts as if plugged straight
    into a small switch's single uplink port. A port with only a handful of
    learned MACs (an end device, or a phone with a PC daisy-chained through
    it) is kept as genuine direct attachment.
    """
    counts: Dict[str, int] = {}
    for _, port in bridge_entries:
        counts[port] = counts.get(port, 0) + 1
    return [(oid, port) for oid, port in bridge_entries if counts[port] <= max_macs_per_port]


def build_fdb_port_names(
    bridge_entries: List[Tuple[str, str]],
    port_ifindex_entries: List[Tuple[str, str]],
    ifdescr_entries: List[Tuple[str, str]],
) -> Dict[str, str]:
    """MAC address -> switch port name, from dot1dTpFdbPort + port/ifIndex + ifDescr walks."""
    ifindex_by_port = {oid.rsplit(".", 1)[-1]: value for oid, value in port_ifindex_entries}
    name_by_ifindex = {oid.rsplit(".", 1)[-1]: value for oid, value in ifdescr_entries}

    result: Dict[str, str] = {}
    for oid, port_value in bridge_entries:
        mac = decode_fdb_mac(oid)
        if not mac:
            continue
        ifindex = ifindex_by_port.get(port_value)
        port_name = name_by_ifindex.get(ifindex) if ifindex else None
        result[mac] = port_name or f"port{port_value}"
    return result


def build_port_vlan_labels(
    pvid_entries: List[Tuple[str, str]],
    vlan_name_entries: List[Tuple[str, str]],
) -> Dict[str, str]:
    """Bridge port number -> VLAN label ("10 (Voice)" or just "10"), from
    dot1qPvid (port's untagged/access VLAN) + dot1qVlanStaticName (VLAN id -> name)."""
    name_by_vlan_id = {oid.rsplit(".", 1)[-1]: name for oid, name in vlan_name_entries}
    result: Dict[str, str] = {}
    for oid, vlan_id in pvid_entries:
        port_num = oid.rsplit(".", 1)[-1]
        name = name_by_vlan_id.get(vlan_id)
        result[port_num] = f"{vlan_id} ({name})" if name else vlan_id
    return result


PHONE_VENDOR_KEYWORDS = (
    "yealink", "snom", "fanvil", "grandstream", "polycom",
    "cisco ip phone", "2n telekomunikace", "gigaset",
)
PRINTER_KEYWORDS = ("laserjet", "officejet", "deskjet", "printer")
FIREWALL_KEYWORDS = (
    "firewall", "nethsecurity", "pfsense", "opnsense",
    "fortigate", "checkpoint", "sonicwall", "asa",
)

KIND_ORDER = ["phone", "printer", "host"]

# draw.io/diagrams.net mxGraph style strings, core registered shape names
# only (cylinder/cube/ellipse/rounded rect) - not the mxgraph.cisco.* or
# mxgraph.basic.* stencil-library paths, which vary between draw.io
# versions and would silently fall back to a blank/red box if wrong. The
# label text always states the kind too, so identity never depends on the
# shape alone.
KIND_STYLE = {
    "router": "shape=cylinder;whiteSpace=wrap;html=1;fillColor=#bcd4f0;strokeColor=#2a78d6;",
    "firewall": "rounded=1;whiteSpace=wrap;html=1;fillColor=#f2b48c;strokeColor=#c9622c;",
    "switch": "shape=cube;whiteSpace=wrap;html=1;fillColor=#c7c6c0;strokeColor=#52514e;size=10;",
    "phone": "ellipse;whiteSpace=wrap;html=1;fillColor=#e5e4df;strokeColor=#898781;",
    "printer": "rounded=1;whiteSpace=wrap;html=1;fillColor=#e5e4df;strokeColor=#898781;",
    "host": "rounded=1;whiteSpace=wrap;html=1;fillColor=#eeeeee;strokeColor=#898781;",
}

KIND_GROUP_LABEL = {"phone": "Telefoni IP", "printer": "Stampanti", "host": "Host generici"}

NODE_W, NODE_H = 140.0, 50.0
COL_GAP, ROW_GAP = 20.0, 20.0
GROUP_HEADER, GROUP_PAD = 30.0, 15.0
KIND_GAP, VLAN_GAP = 20.0, 40.0
INFRA_NODE_W, INFRA_NODE_H = 140.0, 60.0
INFRA_GAP, INFRA_ROW_GAP = 30.0, 60.0
MARGIN = 40.0
GRID_COLUMNS = 6


def classify_kind(role: str, vendor: Optional[str], sysdescr: Optional[str]) -> str:
    """Diagram-shape bucket for a node: role wins for infra, else a vendor/sysDescr guess."""
    text = f"{vendor or ''} {sysdescr or ''}".lower()
    if role == "router":
        return "firewall" if any(k in text for k in FIREWALL_KEYWORDS) else "router"
    if role == "switch":
        return "switch"
    if any(k in text for k in PHONE_VENDOR_KEYWORDS):
        return "phone"
    if any(k in text for k in PRINTER_KEYWORDS):
        return "printer"
    return "host"


def vlan_label_for(node: "NodeRecord") -> str:
    return ", ".join(sorted(node.vlans)) if node.vlans else "N/D"


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _node_label(node: "NodeRecord", ip: str, kind: str) -> str:
    """HTML label (draw.io renders <br>/<i> when the style has html=1): device
    name, IP, and the kind in words - so identity never depends on the shape
    alone (in case an unfamiliar draw.io version doesn't render it as expected).

    Returns raw (unescaped) text, including the intentional <br>/<i> markup -
    the caller XML-escapes the whole thing once before writing it into an
    attribute (XML has no notion of "this literal tag stays unescaped"; even
    markup meant for draw.io's own HTML rendering must be &lt;-escaped like
    any other attribute content, or a hostname containing '<' or '&' would
    produce invalid XML).
    """
    hostname_or_sysname = node.hostname or node.sysname
    short = hostname_or_sysname.split(".")[0] if hostname_or_sysname else None
    device = f"{short}<br>{ip}" if short and short != ip else ip
    kind_label = KIND_GROUP_LABEL.get(kind, kind.capitalize())
    return f"{device}<br><i>{kind_label}</i>"


def chunk_into_rows(items: List[str], columns: int) -> List[List[str]]:
    """Split an ordered id list into fixed-width rows, left over into a
    shorter last row - used to wrap a group's devices into a grid instead of
    one arbitrarily wide line."""
    if not items:
        return []
    return [items[i:i + columns] for i in range(0, len(items), columns)]


def layout_grid(
    ips: List[str], x0: float, y0: float, columns: int = GRID_COLUMNS,
) -> Tuple[Dict[str, Tuple[float, float]], Tuple[float, float, float, float]]:
    """Grid-place `ips` with top-left corner at (x0, y0). Returns
    (ip -> (x, y) top-left of its box, bounding box (x, y, width, height))."""
    rows = chunk_into_rows(ips, columns)
    positions: Dict[str, Tuple[float, float]] = {}
    for r, row in enumerate(rows):
        for c, ip in enumerate(row):
            positions[ip] = (x0 + c * (NODE_W + COL_GAP), y0 + r * (NODE_H + ROW_GAP))
    n_cols = min(columns, len(ips)) if ips else 0
    n_rows = len(rows)
    width = n_cols * NODE_W + max(0, n_cols - 1) * COL_GAP if n_cols else 0.0
    height = n_rows * NODE_H + max(0, n_rows - 1) * ROW_GAP if n_rows else 0.0
    return positions, (x0, y0, width, height)


@dataclass
class DiagramLayout:
    kinds: Dict[str, str]
    # ip -> (x, y, width, height) of its device box
    positions: Dict[str, Tuple[float, float, float, float]]
    # background group boxes in draw order (outer VLAN box before its kind
    # sub-boxes, so z-order puts the sub-boxes on top): (label, x, y, w, h)
    groups: List[Tuple[str, float, float, float, float]]


def compute_diagram_layout(nodes: Dict[str, NodeRecord]) -> DiagramLayout:
    """Deterministic, non-overlapping layout: router/firewall row, switch
    row, then one box per VLAN (label "N/D" when unknown) stacked
    vertically, each containing its devices grouped into kind sub-boxes
    (phones, then printers, then hosts), each sub-box a wrapped grid.
    """
    kinds = {ip: classify_kind(n.role, n.vendor, n.sysdescr) for ip, n in nodes.items()}
    infra_ips = [ip for ip, k in kinds.items() if k in ("router", "firewall", "switch")]
    leaf_ips = [ip for ip, k in kinds.items() if k not in ("router", "firewall", "switch")]

    positions: Dict[str, Tuple[float, float, float, float]] = {}
    groups: List[Tuple[str, float, float, float, float]] = []

    y = MARGIN
    for kind_group in (("router", "firewall"), ("switch",)):
        ips = sorted(ip for ip in infra_ips if kinds[ip] in kind_group)
        if not ips:
            continue
        for i, ip in enumerate(ips):
            x = MARGIN + i * (INFRA_NODE_W + INFRA_GAP)
            positions[ip] = (x, y, INFRA_NODE_W, INFRA_NODE_H)
        y += INFRA_NODE_H + INFRA_ROW_GAP

    vlans = sorted({vlan_label_for(nodes[ip]) for ip in leaf_ips}, key=lambda v: (v == "N/D", v))
    for vlan in vlans:
        vlan_x, vlan_y = MARGIN, y
        inner_y = vlan_y + GROUP_HEADER
        vlan_box_index = len(groups)
        groups.append(("", 0, 0, 0, 0))  # placeholder, filled in once the height is known
        max_kind_width = 0.0
        for kind in KIND_ORDER:
            kind_ips = sorted(ip for ip in leaf_ips if kinds[ip] == kind and vlan_label_for(nodes[ip]) == vlan)
            if not kind_ips:
                continue
            grid_positions, (_, _, gw, gh) = layout_grid(
                kind_ips, vlan_x + 2 * GROUP_PAD, inner_y + GROUP_HEADER,
            )
            for ip, (px, py) in grid_positions.items():
                positions[ip] = (px, py, NODE_W, NODE_H)
            group_h = gh + GROUP_HEADER + GROUP_PAD
            groups.append((KIND_GROUP_LABEL[kind], vlan_x + GROUP_PAD, inner_y, gw + 2 * GROUP_PAD, group_h))
            max_kind_width = max(max_kind_width, gw + 2 * GROUP_PAD)
            inner_y += group_h + KIND_GAP

        vlan_h = (inner_y - KIND_GAP + GROUP_PAD) - vlan_y if inner_y > vlan_y + GROUP_HEADER else GROUP_HEADER + GROUP_PAD
        vlan_w = max_kind_width + 2 * GROUP_PAD
        groups[vlan_box_index] = (f"VLAN {vlan}", vlan_x, vlan_y, vlan_w, vlan_h)
        y = vlan_y + vlan_h + VLAN_GAP

    return DiagramLayout(kinds=kinds, positions=positions, groups=groups)


def build_drawio_xml(
    nodes: Dict[str, NodeRecord],
    physical_edges: List[EdgeRecord],
    layout: DiagramLayout,
    title: str = "Network Diagram",
) -> str:
    """Render draw.io/diagrams.net mxGraph XML: an editable diagram (not just
    a picture) so devices SNMP can't place on the wire - a firewall's real
    uplink, or which switch an end host is actually plugged into - can be
    dragged in and connected by hand afterwards. Group boxes (VLAN, then
    kind within it) come from compute_diagram_layout(); only genuine
    physical links (LLDP/CDP, bridge-FDB port attachment) are pre-drawn as
    edges here.
    """
    lines = [
        '<mxfile host="network_topology_map.py">',
        f'  <diagram name="{_xml_escape(title)}" id="network-topology">',
        '    <mxGraphModel dx="800" dy="600" grid="1" gridSize="10" guides="1" tooltips="1" '
        'connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1600" '
        'pageHeight="1200" math="0" shadow="0">',
        "      <root>",
        '        <mxCell id="0" />',
        '        <mxCell id="1" parent="0" />',
    ]

    for i, (label, x, y, w, h) in enumerate(layout.groups):
        cell_id = f"group_{i}"
        style = (
            "rounded=0;whiteSpace=wrap;html=1;verticalAlign=top;fontSize=11;"
            "fillColor=#f7f7f5;strokeColor=#c9c8c2;" if label.startswith("VLAN ") else
            "rounded=0;whiteSpace=wrap;html=1;verticalAlign=top;fontSize=10;"
            "fillColor=#ffffff;strokeColor=#d8d7d1;"
        )
        lines.append(
            f'        <mxCell id="{cell_id}" value="{_xml_escape(label)}" style="{style}" '
            'vertex="1" parent="1">'
        )
        lines.append(f'          <mxGeometry x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" as="geometry" />')
        lines.append("        </mxCell>")

    for ip, (x, y, w, h) in layout.positions.items():
        node = nodes[ip]
        kind = layout.kinds[ip]
        style = KIND_STYLE[kind]
        label = _xml_escape(_node_label(node, ip, kind))
        lines.append(f'        <mxCell id="{_xml_escape(ip)}" value="{label}" style="{style}" vertex="1" parent="1">')
        lines.append(f'          <mxGeometry x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" as="geometry" />')
        lines.append("        </mxCell>")

    seen_pairs: Set[Tuple[str, str]] = set()
    for i, edge in enumerate(physical_edges):
        pair = tuple(sorted((edge.a, edge.b)))
        if pair in seen_pairs or edge.a not in layout.positions or edge.b not in layout.positions:
            continue
        seen_pairs.add(pair)
        edge_style = "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=none;startArrow=none;strokeColor=#666666;"
        edge_label = f' value="{_xml_escape(edge.label)}"' if edge.label else ""
        lines.append(
            f'        <mxCell id="edge_{i}"{edge_label} style="{edge_style}" edge="1" '
            f'source="{_xml_escape(edge.a)}" target="{_xml_escape(edge.b)}" parent="1">'
        )
        lines.append('          <mxGeometry relative="1" as="geometry" />')
        lines.append("        </mxCell>")

    lines += [
        "      </root>",
        "    </mxGraphModel>",
        "  </diagram>",
        "</mxfile>",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Credential cache (per-IP SNMP community, never committed to git)
# ---------------------------------------------------------------------------

def load_cred_cache(path: Path) -> Dict[str, dict]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        warn(f"cache credenziali illeggibile, ignorata: {path}")
        return {}


def save_cred_cache(path: Path, cache: Dict[str, dict]) -> None:
    path.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# External tool wrappers (I/O; not unit-tested directly)
# ---------------------------------------------------------------------------

def check_dependencies() -> Tuple[bool, bool]:
    has_nmap = shutil.which("nmap") is not None
    has_snmp = shutil.which("snmpget") is not None and shutil.which("snmpbulkwalk") is not None
    if not has_nmap:
        warn("binario 'nmap' non trovato: la scoperta L3 non puo' funzionare.")
    if not has_snmp:
        warn("snmpget/snmpbulkwalk (net-snmp) non trovati: fasi SNMP/VLAN/LLDP disattivate.")
    return has_nmap, has_snmp


def nmap_ping_sweep(cidr: str, timeout: int = 120) -> List[Dict[str, Optional[str]]]:
    cmd = ["nmap", "-sn", "-oX", "-", cidr]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError) as exc:
        warn(f"nmap fallito su {cidr}: {exc}")
        return []
    return parse_nmap_xml(result.stdout)


def snmp_get(ip: str, community: str, oid: str, timeout: int, retries: int) -> Optional[str]:
    cmd = [
        "snmpget", "-v2c", "-c", community, "-Oqn",
        "-t", str(timeout), "-r", str(retries), ip, oid,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout * (retries + 2))
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    parsed = parse_snmp_walk_output(result.stdout)
    return parsed[0][1] if parsed else None


def snmp_walk(ip: str, community: str, oid: str, timeout: int, retries: int) -> List[Tuple[str, str]]:
    cmd = [
        "snmpbulkwalk", "-v2c", "-c", community, "-Oqn",
        "-t", str(timeout), "-r", str(retries), ip, oid,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout * (retries + 2) + 10)
    except (subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0:
        return []
    return parse_snmp_walk_output(result.stdout)


def probe_snmp_credential(
    ip: str,
    communities: List[str],
    cred_cache: Dict[str, dict],
    timeout: int,
    retries: int,
    interactive: bool,
    last_good: Optional[str],
) -> Optional[str]:
    """Return a working SNMPv2c community for `ip`, or None."""
    cached = cred_cache.get(ip, {}).get("community")
    ordered = []
    if cached:
        ordered.append(cached)
    if last_good and last_good not in ordered:
        ordered.append(last_good)
    for community in communities:
        if community not in ordered:
            ordered.append(community)

    for community in ordered:
        if snmp_get(ip, community, OID_SYSDESCR, timeout, retries) is not None:
            cred_cache[ip] = {"version": "2c", "community": community}
            return community

    if not interactive:
        return None

    answer = input(f"  Nessuna community di default valida per {ip}. Provarne una custom? [y/N]: ").strip().lower()
    while answer == "y":
        custom = input(f"  Community SNMPv2c per {ip} (INVIO per rinunciare): ").strip()
        if not custom:
            break
        if snmp_get(ip, custom, OID_SYSDESCR, timeout, retries) is not None:
            cred_cache[ip] = {"version": "2c", "community": custom}
            return custom
        answer = input("  Non valida. Riprovare? [y/N]: ").strip().lower()

    return None


# ---------------------------------------------------------------------------
# Local subnet auto-detection (best-effort, platform dependent)
# ---------------------------------------------------------------------------

def detect_local_subnets() -> List[str]:
    subnets: Set[str] = set()

    if shutil.which("ip"):
        try:
            result = subprocess.run(
                ["ip", "-o", "-4", "addr", "show"], capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                m = re.search(r"inet (\d+\.\d+\.\d+\.\d+/\d+)", line)
                if m:
                    net = ipaddress.ip_network(m.group(1), strict=False)
                    if not net.is_loopback:
                        subnets.add(str(net))
        except (subprocess.TimeoutExpired, OSError, ValueError):
            pass

    if not subnets and shutil.which("ipconfig"):
        try:
            result = subprocess.run(["ipconfig"], capture_output=True, text=True, timeout=5)
            addr = None
            for line in result.stdout.splitlines():
                if "IPv4" in line and ":" in line:
                    addr = line.split(":")[-1].strip()
                if "Subnet Mask" in line and addr and ":" in line:
                    mask = line.split(":")[-1].strip()
                    try:
                        net = ipaddress.ip_network(f"{addr}/{mask}", strict=False)
                        if not net.is_loopback:
                            subnets.add(str(net))
                    except ValueError:
                        pass
                    addr = None
        except (subprocess.TimeoutExpired, OSError):
            pass

    return sorted(subnets)


def reverse_dns(ip: str, timeout: float = 1.0) -> Optional[str]:
    old_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    try:
        return socket.gethostbyaddr(ip)[0]
    except (socket.herror, socket.gaierror, socket.timeout, OSError):
        return None
    finally:
        socket.setdefaulttimeout(old_timeout)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def write_drawio(xml_source: str, output_path: Path) -> None:
    output_path.write_text(xml_source, encoding="utf-8")


# ---------------------------------------------------------------------------
# Interactive prompts
# ---------------------------------------------------------------------------

def prompt_subnets() -> List[str]:
    detected = detect_local_subnets()
    if detected:
        print(f"Subnet locali rilevate: {', '.join(detected)}")
    print("Inserisci le subnet di partenza (CIDR, una per riga, INVIO vuoto per terminare):")
    subnets: List[str] = []
    while True:
        val = input(f"  subnet{len(subnets) + 1} [{'INVIO per usare le rilevate' if not subnets and detected else 'fine'}]: ").strip()
        if not val:
            if not subnets and detected:
                return detected
            if not subnets:
                print("  Devi inserire almeno una subnet.")
                continue
            break
        try:
            ipaddress.ip_network(val, strict=False)
            subnets.append(val)
        except ValueError:
            print(f"  '{val}' non e' un CIDR valido (es: 192.168.1.0/24). Riprova.")
    return subnets


def confirm(prompt_text: str, default_yes: bool, auto_yes: bool) -> bool:
    if auto_yes:
        return True
    default_hint = "Y/n" if default_yes else "y/N"
    answer = input(f"{prompt_text} [{default_hint}]: ").strip().lower()
    if not answer:
        return default_yes
    return answer in ("y", "yes", "s", "si")


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description=f"LAN/VLAN discovery + interactive topology map v{VERSION}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  network_topology_map.py --subnets 192.168.1.0/24
  network_topology_map.py --auto-detect --yes
  network_topology_map.py  # fully interactive""",
    )
    parser.add_argument("--subnets", help="CIDR list, comma separated (skips the prompt)")
    parser.add_argument("--auto-detect", action="store_true",
                         help="Seed with locally detected subnets, no prompt")
    parser.add_argument("--creds-file", default="network_topology_creds.json",
                         help="SNMP credential cache (JSON, local only, never commit)")
    parser.add_argument("--communities-file", help="extra file with one SNMP community per line")
    parser.add_argument("--snmp-timeout", type=int, default=DEFAULT_SNMP_TIMEOUT)
    parser.add_argument("--snmp-retries", type=int, default=DEFAULT_SNMP_RETRIES)
    parser.add_argument("--max-expansions", type=int, default=DEFAULT_MAX_EXPANSIONS,
                         help="safety cap on auto-discovered subnets queued for scanning")
    parser.add_argument("--skip-snmp", action="store_true", help="L3 discovery only, no SNMP/VLAN/LLDP")
    parser.add_argument("--no-expand", action="store_true",
                         help="do not queue subnets discovered via SNMP (seed subnets only)")
    parser.add_argument("--yes", action="store_true", help="auto-confirm every scan/expansion prompt")
    parser.add_argument("--output", help="diagram output path "
                         "(default: timestamped .drawio in ./topology-output)")
    args = parser.parse_args()

    print(f"NETWORK TOPOLOGY MAP v{VERSION}")
    print("=" * 60)

    has_nmap, has_snmp = check_dependencies()
    if not has_nmap:
        die("nmap e' obbligatorio, interrompo.")
    if args.skip_snmp:
        has_snmp = False

    if args.subnets:
        seed_subnets = [s.strip() for s in args.subnets.split(",") if s.strip()]
    elif args.auto_detect:
        seed_subnets = detect_local_subnets()
        if not seed_subnets:
            die("auto-detect non ha trovato subnet locali; usa --subnets.")
    else:
        seed_subnets = prompt_subnets()

    communities = list(DEFAULT_COMMUNITIES)
    if args.communities_file:
        extra = Path(args.communities_file).read_text(encoding="utf-8").splitlines()
        communities.extend(c.strip() for c in extra if c.strip())

    creds_path = Path(args.creds_file)
    cred_cache = load_cred_cache(creds_path)
    last_good_community: Optional[str] = None

    queue: List[str] = list(dict.fromkeys(seed_subnets))
    scanned: Set[str] = set()
    expansions_used = 0

    nodes: Dict[str, NodeRecord] = {}
    physical_edges: List[EdgeRecord] = []
    subnet_of: Dict[str, str] = {}

    phase = 1
    while queue:
        cidr = queue.pop(0)
        if cidr in scanned:
            continue
        scanned.add(cidr)

        print(f"\n[Fase {phase}] Ping sweep su {cidr}...")
        phase += 1
        live_hosts = nmap_ping_sweep(cidr)
        print(f"  -> {len(live_hosts)} host attivi")

        for h in live_hosts:
            ip = h["ip"]
            node = nodes.setdefault(ip, NodeRecord(ip=ip))
            node.mac = node.mac or h.get("mac")
            node.vendor = node.vendor or h.get("vendor")
            node.hostname = node.hostname or h.get("hostname") or reverse_dns(ip)
            subnet_of[ip] = cidr

        if not has_snmp:
            continue

        discovered_subnets: Set[str] = set()
        for h in live_hosts:
            ip = h["ip"]
            community = probe_snmp_credential(
                ip, communities, cred_cache, args.snmp_timeout, args.snmp_retries,
                interactive=not args.yes, last_good=last_good_community,
            )
            if not community:
                continue
            last_good_community = community
            node = nodes[ip]
            node.snmp_ok = True
            node.sysdescr = snmp_get(ip, community, OID_SYSDESCR, args.snmp_timeout, args.snmp_retries)
            node.sysname = snmp_get(ip, community, OID_SYSNAME, args.snmp_timeout, args.snmp_retries)

            bridge_entries = snmp_walk(ip, community, OID_DOT1DTPFDB_PORT, args.snmp_timeout, args.snmp_retries)
            vlan_entries = snmp_walk(ip, community, OID_DOT1QVLANSTATICNAME, args.snmp_timeout, args.snmp_retries)

            if bridge_entries:
                direct_entries = filter_direct_attachment_macs(bridge_entries)
                port_ifindex_entries = snmp_walk(
                    ip, community, OID_DOT1DBASEPORT_IFINDEX, args.snmp_timeout, args.snmp_retries,
                )
                ifdescr_entries = snmp_walk(ip, community, OID_IFDESCR, args.snmp_timeout, args.snmp_retries)
                fdb_port_names = build_fdb_port_names(direct_entries, port_ifindex_entries, ifdescr_entries)

                pvid_entries = snmp_walk(ip, community, OID_DOT1QPVID, args.snmp_timeout, args.snmp_retries)
                port_vlan_labels = build_port_vlan_labels(pvid_entries, vlan_entries)
                mac_port = {decode_fdb_mac(oid): port_value for oid, port_value in direct_entries}

                mac_to_ip = {n.mac: n_ip for n_ip, n in nodes.items() if n.mac}
                for mac, port_name in fdb_port_names.items():
                    attached_ip = mac_to_ip.get(mac)
                    if not attached_ip or attached_ip == ip:
                        continue
                    physical_edges.append(EdgeRecord(a=ip, b=attached_ip, kind="physical", label=port_name))
                    # The attached device's VLAN is the port's untagged VLAN
                    # on ITS switch - a fact about the leaf device, never
                    # about the switch itself (that was the earlier bug:
                    # dumping the switch's whole VLAN name table onto its
                    # own node instead of resolving per-port membership).
                    port_num = mac_port.get(mac)
                    vlan_label = port_vlan_labels.get(port_num) if port_num else None
                    if vlan_label:
                        nodes[attached_ip].vlans = {vlan_label}

            ip_addr_entries = snmp_walk(ip, community, OID_IPADENTADDR, args.snmp_timeout, args.snmp_retries)
            netmask_entries = snmp_walk(ip, community, OID_IPADENTNETMASK, args.snmp_timeout, args.snmp_retries)
            node.role = classify_device(
                has_vlan_or_bridge=bool(bridge_entries or vlan_entries),
                ip_interface_count=len(ip_addr_entries),
            )

            if not args.no_expand:
                new_subnets = build_subnets_from_ip_table(ip_addr_entries, netmask_entries)
                discovered_subnets |= new_subnets - scanned - set(queue)

            lldp_names = snmp_walk(ip, community, OID_LLDP_REM_SYSNAME, args.snmp_timeout, args.snmp_retries)
            lldp_ports = dict(snmp_walk(ip, community, OID_LLDP_REM_PORTID, args.snmp_timeout, args.snmp_retries))
            for oid, remote_name in lldp_names:
                port_label = lldp_ports.get(oid, "")
                neighbor_ip = _resolve_neighbor_ip(remote_name, nodes)
                if neighbor_ip:
                    physical_edges.append(EdgeRecord(a=ip, b=neighbor_ip, kind="physical", label=port_label))

            cdp_names = snmp_walk(ip, community, OID_CDP_DEVICEID, args.snmp_timeout, args.snmp_retries)
            cdp_ports = dict(snmp_walk(ip, community, OID_CDP_DEVICEPORT, args.snmp_timeout, args.snmp_retries))
            for oid, remote_name in cdp_names:
                port_label = cdp_ports.get(oid, "")
                neighbor_ip = _resolve_neighbor_ip(remote_name, nodes)
                if neighbor_ip:
                    physical_edges.append(EdgeRecord(a=ip, b=neighbor_ip, kind="physical", label=port_label))

        if discovered_subnets and not args.no_expand:
            if expansions_used >= args.max_expansions:
                warn(f"limite di {args.max_expansions} subnet aggiuntive raggiunto, scarto: {sorted(discovered_subnets)}")
            else:
                print(f"  Nuove subnet trovate via SNMP: {', '.join(sorted(discovered_subnets))}")
                if confirm("  Aggiungerle alla scansione?", default_yes=True, auto_yes=args.yes):
                    for s in sorted(discovered_subnets):
                        if expansions_used >= args.max_expansions:
                            break
                        queue.append(s)
                        expansions_used += 1

    save_cred_cache(creds_path, cred_cache)

    output_dir = Path("topology-output")
    output_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    output_path = Path(args.output) if args.output else output_dir / f"network-topology-{ts}.drawio"
    json_path = output_path.with_suffix(".json")

    snapshot = {
        "nodes": {
            ip: {
                "mac": n.mac, "vendor": n.vendor, "hostname": n.hostname, "sysname": n.sysname,
                "sysdescr": n.sysdescr, "role": n.role, "vlans": sorted(n.vlans), "snmp_ok": n.snmp_ok,
            }
            for ip, n in nodes.items()
        },
        "edges": [{"a": e.a, "b": e.b, "label": e.label} for e in physical_edges],
        "subnet_of": subnet_of,
    }
    json_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

    layout = compute_diagram_layout(nodes)
    xml_source = build_drawio_xml(nodes, physical_edges, layout, title=f"Rete - {datetime.now():%Y-%m-%d}")
    write_drawio(xml_source, output_path)

    switches = sum(1 for n in nodes.values() if n.role == "switch")
    routers = sum(1 for n in nodes.values() if n.role == "router")
    vlans_found = {v for n in nodes.values() for v in n.vlans}

    print("\n" + "=" * 60)
    print("RIEPILOGO")
    print(f"  Subnet scansionate:   {len(scanned)}")
    print(f"  Host trovati:         {len(nodes)}")
    print(f"  Switch identificati:  {switches}")
    print(f"  Router identificati:  {routers}")
    print(f"  VLAN trovate:         {len(vlans_found)}")
    print(f"  Link fisici (LLDP/CDP): {len(physical_edges)}")
    print(f"  Diagramma: {output_path}  (apri con draw.io / diagrams.net per modificarlo)")
    print(f"  JSON:      {json_path}")

    return 0


def _resolve_neighbor_ip(remote_name: str, nodes: Dict[str, NodeRecord]) -> Optional[str]:
    """Best-effort match of an LLDP/CDP remote system name to an already-known IP."""
    for ip, node in nodes.items():
        if node.sysname and node.sysname == remote_name:
            return ip
        if node.hostname and node.hostname.split(".")[0] == remote_name.split(".")[0]:
            return ip
    return None


if __name__ == "__main__":
    raise SystemExit(main())
