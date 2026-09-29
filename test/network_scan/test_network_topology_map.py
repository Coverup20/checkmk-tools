"""Unit tests for network_topology_map.py pure-logic functions.

No real subprocess/network calls: nmap/snmp wrappers are exercised only via
their parsers (fed canned text), or via monkeypatching the thin I/O
functions they call.
"""

import json

NMAP_XML_SAMPLE = """<?xml version="1.0"?>
<nmaprun>
  <host>
    <status state="up"/>
    <address addr="192.168.1.1" addrtype="ipv4"/>
    <address addr="AA:BB:CC:DD:EE:01" addrtype="mac" vendor="Cisco Systems"/>
    <hostnames><hostname name="switch01.lan" type="PTR"/></hostnames>
  </host>
  <host>
    <status state="up"/>
    <address addr="192.168.1.50" addrtype="ipv4"/>
  </host>
  <host>
    <status state="down"/>
    <address addr="192.168.1.99" addrtype="ipv4"/>
  </host>
</nmaprun>
"""

SNMP_WALK_SAMPLE = '.1.3.6.1.2.1.1.1.0 "Cisco IOS Software"\n.1.3.6.1.2.1.1.5.0 switch01\n'


def test_parse_nmap_xml_skips_down_hosts_and_extracts_mac(topology_module):
    hosts = topology_module.parse_nmap_xml(NMAP_XML_SAMPLE)

    assert [h["ip"] for h in hosts] == ["192.168.1.1", "192.168.1.50"]
    first = hosts[0]
    assert first["mac"] == "AA:BB:CC:DD:EE:01"
    assert first["vendor"] == "Cisco Systems"
    assert first["hostname"] == "switch01.lan"
    assert hosts[1]["mac"] is None


def test_parse_nmap_xml_malformed_returns_empty(topology_module):
    assert topology_module.parse_nmap_xml("not xml at all") == []


def test_parse_snmp_walk_output_strips_quotes_and_leading_dot(topology_module):
    parsed = topology_module.parse_snmp_walk_output(SNMP_WALK_SAMPLE)

    assert parsed == [
        ("1.3.6.1.2.1.1.1.0", "Cisco IOS Software"),
        ("1.3.6.1.2.1.1.5.0", "switch01"),
    ]


def test_parse_snmp_walk_output_ignores_blank_lines(topology_module):
    text = "\n.1.3.6.1.2.1.1.1.0 value\n\n"
    assert topology_module.parse_snmp_walk_output(text) == [("1.3.6.1.2.1.1.1.0", "value")]


def test_parse_snmp_walk_output_drops_snmp_exception_placeholders(topology_module):
    # Real net-snmp output against a firewall/hypervisor/printer with no
    # bridge/VLAN MIB at all: the walked subtree is empty, but snmpbulkwalk
    # still prints one line with this text as the "value" - it must not be
    # mistaken for an actual table row (that was the exact bug: it made
    # classify_device() think every SNMP-capable non-switch was a switch).
    text = ".1.3.6.1.2.1.17.4.3.1.2 No Such Object available on this agent at this OID\n"
    assert topology_module.parse_snmp_walk_output(text) == []


def test_parse_snmp_walk_output_mixes_real_rows_and_exceptions(topology_module):
    text = (
        ".1.3.6.1.2.1.17.7.1.4.3.1.1.10 \"vlan10\"\n"
        ".1.3.6.1.2.1.17.7.1.4.3.1.1.20 No Such Instance currently exists at this OID\n"
    )
    assert topology_module.parse_snmp_walk_output(text) == [
        ("1.3.6.1.2.1.17.7.1.4.3.1.1.10", "vlan10"),
    ]


def test_classify_device_switch_from_bridge_or_vlan_table(topology_module):
    assert topology_module.classify_device(has_vlan_or_bridge=True, ip_interface_count=1) == "switch"


def test_classify_device_router_from_multiple_interfaces(topology_module):
    assert topology_module.classify_device(has_vlan_or_bridge=False, ip_interface_count=3) == "router"


def test_classify_device_plain_host(topology_module):
    assert topology_module.classify_device(has_vlan_or_bridge=False, ip_interface_count=1) == "host"


def test_build_subnets_from_ip_table_combines_addr_and_mask_by_index(topology_module):
    ip_entries = [("1.192.168.1.1", "192.168.1.1"), ("1.10.0.0.1", "10.0.0.1")]
    mask_entries = [("1.192.168.1.1", "255.255.255.0"), ("1.10.0.0.1", "255.255.255.0")]

    subnets = topology_module.build_subnets_from_ip_table(ip_entries, mask_entries)

    assert subnets == {"192.168.1.0/24", "10.0.0.0/24"}


def test_build_subnets_from_ip_table_skips_host_routes_and_missing_mask(topology_module):
    ip_entries = [("1", "10.0.0.1"), ("2", "10.0.0.2")]
    mask_entries = [("1", "255.255.255.255")]  # /32 host route -> skipped; index 2 has no mask

    subnets = topology_module.build_subnets_from_ip_table(ip_entries, mask_entries)

    assert subnets == set()


def test_classify_kind_role_wins_for_infra(topology_module):
    assert topology_module.classify_kind("switch", vendor="Cisco", sysdescr=None) == "switch"
    assert topology_module.classify_kind("router", vendor=None, sysdescr=None) == "router"


def test_classify_kind_detects_phone_by_vendor(topology_module):
    assert topology_module.classify_kind("host", vendor="Yealink(Xiamen) Network Technology", sysdescr=None) == "phone"


def test_classify_kind_detects_printer_by_sysdescr(topology_module):
    text = "HP ETHERNET MULTI-ENVIRONMENT,PID:HP LaserJet 400 M401dn"
    assert topology_module.classify_kind("host", vendor="Hewlett Packard", sysdescr=text) == "printer"


def test_classify_kind_defaults_to_host(topology_module):
    assert topology_module.classify_kind("host", vendor="Dell", sysdescr=None) == "host"


def test_classify_kind_detects_firewall_among_routers(topology_module):
    assert topology_module.classify_kind("router", vendor=None, sysdescr="NethSecurity firewall appliance") == "firewall"
    assert topology_module.classify_kind("router", vendor=None, sysdescr=None) == "router"


def test_decode_fdb_mac_from_oid_suffix(topology_module):
    # dot1dTpFdbPort OID index is the 6 MAC octets, e.g. 00:0D:48:59:01:42
    oid = "1.3.6.1.2.1.17.4.3.1.2.0.13.72.89.1.66"
    assert topology_module.decode_fdb_mac(oid) == "00:0D:48:59:01:42"


def test_decode_fdb_mac_rejects_short_or_invalid_oid(topology_module):
    assert topology_module.decode_fdb_mac("1.2.3") is None
    assert topology_module.decode_fdb_mac("1.2.3.4.5.999") is None


def test_filter_direct_attachment_macs_drops_high_fanout_uplink_port(topology_module):
    # A real 8-port switch where every one of 61 downstream hosts was
    # learned on the same port (its uplink to the core switch) - the exact
    # shape that produced 61 bogus "directly connected" edges before this fix.
    bridge_entries = [(f"1.3.6.1.2.1.17.4.3.1.2.0.0.0.0.0.{i}", "8") for i in range(1, 62)]
    bridge_entries.append(("1.3.6.1.2.1.17.4.3.1.2.0.0.0.0.1.100", "2"))  # a real direct-attach port

    result = topology_module.filter_direct_attachment_macs(bridge_entries, max_macs_per_port=4)

    assert result == [("1.3.6.1.2.1.17.4.3.1.2.0.0.0.0.1.100", "2")]


def test_filter_direct_attachment_macs_keeps_low_fanout_ports(topology_module):
    # A phone with a PC daisy-chained through its second port: 2 MACs, kept.
    bridge_entries = [
        ("1.3.6.1.2.1.17.4.3.1.2.0.0.0.0.0.1", "5"),
        ("1.3.6.1.2.1.17.4.3.1.2.0.0.0.0.0.2", "5"),
    ]

    result = topology_module.filter_direct_attachment_macs(bridge_entries, max_macs_per_port=4)

    assert result == bridge_entries


def test_build_fdb_port_names_resolves_port_to_ifdescr(topology_module):
    bridge_entries = [("1.3.6.1.2.1.17.4.3.1.2.0.13.72.89.1.66", "3")]
    port_ifindex_entries = [("1.3.6.1.2.1.17.1.4.1.2.3", "10003")]
    ifdescr_entries = [("1.3.6.1.2.1.2.2.1.2.10003", "GigabitEthernet0/3")]

    result = topology_module.build_fdb_port_names(bridge_entries, port_ifindex_entries, ifdescr_entries)

    assert result == {"00:0D:48:59:01:42": "GigabitEthernet0/3"}


def test_build_fdb_port_names_falls_back_to_port_number(topology_module):
    bridge_entries = [("1.3.6.1.2.1.17.4.3.1.2.0.13.72.89.1.66", "3")]

    result = topology_module.build_fdb_port_names(bridge_entries, [], [])

    assert result == {"00:0D:48:59:01:42": "port3"}


def _boxes_overlap(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def test_layout_grid_wraps_rows_and_computes_bbox(topology_module):
    positions, (x, y, w, h) = topology_module.layout_grid(["a", "b", "c"], x0=10, y0=20, columns=2)

    assert positions["a"] == (10, 20)
    assert positions["b"][1] == 20  # same row as "a"
    assert positions["c"][1] > 20  # wrapped to row 2
    assert w > 0 and h > 0


def test_compute_diagram_layout_places_infra_above_leaf_vlan_box(topology_module):
    NodeRecord = topology_module.NodeRecord

    nodes = {
        "192.168.1.1": NodeRecord(ip="192.168.1.1", role="switch", snmp_ok=True),
        "192.168.1.2": NodeRecord(ip="192.168.1.2", role="router", snmp_ok=True),
        "192.168.1.50": NodeRecord(ip="192.168.1.50", role="host", vendor="Yealink phone"),
    }

    layout = topology_module.compute_diagram_layout(nodes)

    router_y = layout.positions["192.168.1.2"][1]
    switch_y = layout.positions["192.168.1.1"][1]
    phone_y = layout.positions["192.168.1.50"][1]
    assert router_y < switch_y < phone_y
    assert layout.kinds["192.168.1.50"] == "phone"
    assert any(label == "VLAN N/D" for label, *_ in layout.groups)
    assert any(label == "Telefoni IP" for label, *_ in layout.groups)


def test_compute_diagram_layout_no_overlapping_group_boxes(topology_module):
    NodeRecord = topology_module.NodeRecord

    nodes = {}
    for i in range(3):
        nodes[f"10.0.0.{i}"] = NodeRecord(ip=f"10.0.0.{i}", role="host", vlans={"10"})
    for i in range(3):
        nodes[f"10.0.1.{i}"] = NodeRecord(ip=f"10.0.1.{i}", role="host", vendor="Yealink")

    layout = topology_module.compute_diagram_layout(nodes)

    # A VLAN box is expected to overlap (contain) its own kind sub-boxes -
    # that's the nesting, not a bug. The real invariant is that boxes at the
    # same nesting level - VLAN vs VLAN, or kind-group vs kind-group - never
    # overlap each other.
    vlan_boxes = [(x, y, w, h) for label, x, y, w, h in layout.groups if label.startswith("VLAN ")]
    kind_boxes = [(x, y, w, h) for label, x, y, w, h in layout.groups if not label.startswith("VLAN ")]
    for boxes in (vlan_boxes, kind_boxes):
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                assert not _boxes_overlap(a, b)


def test_build_drawio_xml_is_well_formed_and_contains_real_edge_only(topology_module):
    import xml.etree.ElementTree as ET

    NodeRecord = topology_module.NodeRecord
    EdgeRecord = topology_module.EdgeRecord

    nodes = {
        "192.168.1.1": NodeRecord(ip="192.168.1.1", role="switch", hostname="core-sw"),
        "192.168.1.50": NodeRecord(ip="192.168.1.50", role="host", vendor="Yealink phone"),
        "192.168.1.51": NodeRecord(ip="192.168.1.51", role="host"),  # unattached, no edge
    }
    edges = [EdgeRecord(a="192.168.1.1", b="192.168.1.50", kind="physical", label="Gi0/3")]
    layout = topology_module.compute_diagram_layout(nodes)

    xml_source = topology_module.build_drawio_xml(nodes, edges, layout, title="Test")

    root = ET.fromstring(xml_source)  # raises if not well-formed
    assert root.tag == "mxfile"

    vertex_ids = {c.get("id") for c in root.iter("mxCell") if c.get("vertex") == "1"}
    assert {"192.168.1.1", "192.168.1.50", "192.168.1.51"} <= vertex_ids

    drawn_edges = [
        (c.get("source"), c.get("target"))
        for c in root.iter("mxCell") if c.get("edge") == "1"
    ]
    assert drawn_edges == [("192.168.1.1", "192.168.1.50")]  # only the real link, never .51


def test_build_drawio_xml_escapes_special_characters_in_labels(topology_module):
    import xml.etree.ElementTree as ET

    NodeRecord = topology_module.NodeRecord
    nodes = {"192.168.1.1": NodeRecord(ip="192.168.1.1", role="host", hostname='PC & "reception" <lobby>')}
    layout = topology_module.compute_diagram_layout(nodes)

    xml_source = topology_module.build_drawio_xml(nodes, [], layout)

    ET.fromstring(xml_source)  # must still be well-formed with these characters in a label


def test_vlan_label_for_falls_back_to_nd(topology_module):
    NodeRecord = topology_module.NodeRecord
    assert topology_module.vlan_label_for(NodeRecord(ip="10.0.0.1")) == "N/D"
    assert topology_module.vlan_label_for(NodeRecord(ip="10.0.0.1", vlans={"20"})) == "20"


def test_build_port_vlan_labels_resolves_name(topology_module):
    pvid_entries = [("1.3.6.1.2.1.17.7.1.4.5.1.1.3", "10")]
    vlan_name_entries = [("1.3.6.1.2.1.17.7.1.4.3.1.1.10", "Voice")]

    result = topology_module.build_port_vlan_labels(pvid_entries, vlan_name_entries)

    assert result == {"3": "10 (Voice)"}


def test_build_port_vlan_labels_without_name_falls_back_to_id(topology_module):
    pvid_entries = [("1.3.6.1.2.1.17.7.1.4.5.1.1.3", "10")]

    result = topology_module.build_port_vlan_labels(pvid_entries, [])

    assert result == {"3": "10"}




def test_cred_cache_round_trip(topology_module, tmp_path):
    path = tmp_path / "creds.json"
    topology_module.save_cred_cache(path, {"192.168.1.1": {"version": "2c", "community": "public"}})

    loaded = topology_module.load_cred_cache(path)

    assert loaded == {"192.168.1.1": {"version": "2c", "community": "public"}}


def test_cred_cache_missing_file_returns_empty(topology_module, tmp_path):
    assert topology_module.load_cred_cache(tmp_path / "missing.json") == {}


def test_cred_cache_corrupt_file_returns_empty(topology_module, tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("not json", encoding="utf-8")

    assert topology_module.load_cred_cache(path) == {}


def test_probe_snmp_credential_uses_cache_first(topology_module, monkeypatch):
    calls = []

    def fake_snmp_get(ip, community, oid, timeout, retries):
        calls.append(community)
        return "sysDescr" if community == "cached-community" else None

    monkeypatch.setattr(topology_module, "snmp_get", fake_snmp_get)

    cache = {"192.168.1.1": {"community": "cached-community"}}
    result = topology_module.probe_snmp_credential(
        "192.168.1.1", ["public", "private"], cache, timeout=1, retries=0,
        interactive=False, last_good=None,
    )

    assert result == "cached-community"
    assert calls == ["cached-community"]  # never fell through to the default list


def test_probe_snmp_credential_falls_through_default_list(topology_module, monkeypatch):
    def fake_snmp_get(ip, community, oid, timeout, retries):
        return "ok" if community == "private" else None

    monkeypatch.setattr(topology_module, "snmp_get", fake_snmp_get)

    cache = {}
    result = topology_module.probe_snmp_credential(
        "192.168.1.1", ["public", "private"], cache, timeout=1, retries=0,
        interactive=False, last_good=None,
    )

    assert result == "private"
    assert cache["192.168.1.1"]["community"] == "private"


def test_probe_snmp_credential_interactive_custom_community(topology_module, monkeypatch):
    monkeypatch.setattr(topology_module, "snmp_get", lambda *a, **k: None if a[1] != "custom-comm" else "ok")

    answers = iter(["y", "custom-comm"])
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))

    cache = {}
    result = topology_module.probe_snmp_credential(
        "192.168.1.1", ["public"], cache, timeout=1, retries=0,
        interactive=True, last_good=None,
    )

    assert result == "custom-comm"


def test_probe_snmp_credential_non_interactive_gives_up(topology_module, monkeypatch):
    monkeypatch.setattr(topology_module, "snmp_get", lambda *a, **k: None)

    result = topology_module.probe_snmp_credential(
        "192.168.1.1", ["public"], {}, timeout=1, retries=0,
        interactive=False, last_good=None,
    )

    assert result is None


def test_resolve_neighbor_ip_matches_by_sysname_or_hostname(topology_module):
    NodeRecord = topology_module.NodeRecord
    nodes = {
        "192.168.1.1": NodeRecord(ip="192.168.1.1", sysname="switch01"),
        "192.168.1.2": NodeRecord(ip="192.168.1.2", hostname="switch02.lan"),
    }

    assert topology_module._resolve_neighbor_ip("switch01", nodes) == "192.168.1.1"
    assert topology_module._resolve_neighbor_ip("switch02", nodes) == "192.168.1.2"
    assert topology_module._resolve_neighbor_ip("unknown-device", nodes) is None
