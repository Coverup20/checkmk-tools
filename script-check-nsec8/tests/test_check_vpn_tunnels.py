#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

"""Tests for check_vpn_tunnels.py.

Covers: the OpenVPN p2p-vs-subnet type-mismatch regression (client/outbound
instances were always queried with type="subnet", permanently reporting 0
active clients for real, healthy p2p tunnels), the WireGuard
handshake-freshness regression (previously "nonzero ever" = permanent
false-OK), the perfdata-placement regression, and the road-warrior-exclusion
fix (not yet promoted to full/ - see check_vpn_tunnels_wip.py in this same
directory; this test file intentionally imports that staged copy instead of
the production script in full/, whose hash must stay unchanged until the
fix is promoted).
"""

import importlib.machinery
import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

_WIP_PATH = Path(__file__).resolve().parent / "check_vpn_tunnels_wip.py"
_loader = importlib.machinery.SourceFileLoader("check_vpn_tunnels_wip", str(_WIP_PATH))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
vt = importlib.util.module_from_spec(_spec)
_loader.exec_module(vt)

from checkmk_format import graphed_metric_names, parse_perfdata, split_check_result


# --- count_openvpn_tunnels() -------------------------------------------------

def test_openvpn_p2p_client_instance_queried_as_p2p_not_subnet(fake_nethsec, fake_euci):
    # Regression: an outbound/client instance was always queried with
    # type="subnet" regardless of role - live-verified that a healthy,
    # ping-verified p2p tunnel returns {} for type="subnet" (CLIENT_LIST
    # rows only exist for routed/subnet servers), permanently reporting 0
    # active clients (false CRITICAL) for a fully working tunnel.
    instances = {"site_b": {"enabled": "1", "client": "1"}}
    utils = SimpleNamespace(get_all_by_type=lambda u, config, kind: instances)
    seen_types = []

    def fake_list_connected_clients(section, type):
        seen_types.append(type)
        return {"stats": {"bytes_received": 1000, "bytes_sent": 500}}

    ovpn = SimpleNamespace(list_connected_clients=fake_list_connected_clients)
    fake_nethsec.install(utils=utils, ovpn=ovpn)
    fake_euci(vt, uci_obj=MagicMock())

    total, active = vt.count_openvpn_tunnels()

    assert seen_types == ["p2p"]
    assert (total, active) == (1, 1)


def test_openvpn_p2p_requires_traffic_in_both_directions(fake_nethsec, fake_euci):
    instances = {"site_b": {"enabled": "1", "client": "1"}}
    utils = SimpleNamespace(get_all_by_type=lambda u, config, kind: instances)
    # Only one direction has traffic - must NOT count as active.
    ovpn = SimpleNamespace(list_connected_clients=lambda section, type: {"stats": {"bytes_received": 1000, "bytes_sent": 0}})
    fake_nethsec.install(utils=utils, ovpn=ovpn)
    fake_euci(vt, uci_obj=MagicMock())

    total, active = vt.count_openvpn_tunnels()

    assert (total, active) == (1, 0)


def test_openvpn_road_warrior_excluded_from_tunnel_count(fake_nethsec, fake_euci):
    # Regression: road warrior (host-to-net) servers were counted here too,
    # same as genuine site-to-site tunnels. They're identified by
    # 'ns_auth_mode' - the same field /usr/libexec/rpcd/ns.ovpntunnel's own
    # list_tunnels() checks to skip them ("skip road warrior servers").
    # check_ovpn_host2net.py already covers them, and treats 0 connected
    # clients as normal - counting them here too made a road warrior with no
    # client currently connected drag this check down to CRITICAL "All VPN
    # down" even when every real tunnel was healthy.
    instances = {"ns_roadwarrior1": {"enabled": "1", "ns_auth_mode": "certificate"}}
    utils = SimpleNamespace(get_all_by_type=lambda u, config, kind: instances)
    ovpn = SimpleNamespace(list_connected_clients=lambda section, type: {"peer1": {}, "peer2": {}})
    fake_nethsec.install(utils=utils, ovpn=ovpn)
    fake_euci(vt, uci_obj=MagicMock())

    total, active = vt.count_openvpn_tunnels()

    assert (total, active) == (0, 0)


def test_openvpn_net_to_net_subnet_server_queried_as_subnet(fake_nethsec, fake_euci):
    # A genuine site-to-site (net-to-net) server: no client/ns_client flag
    # and no ns_auth_mode - unlike a road warrior, this must be counted.
    instances = {"ns_site_b": {"enabled": "1"}}
    utils = SimpleNamespace(get_all_by_type=lambda u, config, kind: instances)
    seen_types = []

    def fake_list_connected_clients(section, type):
        seen_types.append(type)
        return {"peer1": {}, "peer2": {}}

    ovpn = SimpleNamespace(list_connected_clients=fake_list_connected_clients)
    fake_nethsec.install(utils=utils, ovpn=ovpn)
    fake_euci(vt, uci_obj=MagicMock())

    total, active = vt.count_openvpn_tunnels()

    assert seen_types == ["subnet"]
    assert (total, active) == (1, 2)  # 1 instance, 2 connected clients


def test_openvpn_disabled_instances_not_counted(fake_nethsec, fake_euci):
    instances = {"old": {"enabled": "0"}}
    utils = SimpleNamespace(get_all_by_type=lambda u, config, kind: instances)
    fake_nethsec.install(utils=utils, ovpn=SimpleNamespace(list_connected_clients=lambda *a, **k: {}))
    fake_euci(vt, uci_obj=MagicMock())

    assert vt.count_openvpn_tunnels() == (0, 0)


def test_openvpn_empty_without_library(monkeypatch):
    monkeypatch.setattr(vt, "EUCI_AVAILABLE", False)

    assert vt.count_openvpn_tunnels() == (0, 0)


# --- list_openvpn_tunnels() (per-tunnel identification) ---------------------

def test_list_tunnels_names_which_one_is_down_when_several_configured(fake_nethsec, fake_euci):
    # The whole point of this function: with 2+ net-to-net tunnels, the
    # aggregate count_openvpn_tunnels() can only say "1 of 2 down" - it
    # can't say which. list_openvpn_tunnels() must name it.
    instances = {
        "ns_site_a": {"enabled": "1"},   # connected
        "ns_site_b": {"enabled": "1"},   # not connected
    }
    utils = SimpleNamespace(get_all_by_type=lambda u, config, kind: instances)

    def fake_list_connected_clients(section, type):
        return {"peer1": {}} if section == "ns_site_a" else {}

    ovpn = SimpleNamespace(list_connected_clients=fake_list_connected_clients)
    fake_nethsec.install(utils=utils, ovpn=ovpn)
    fake_euci(vt, uci_obj=MagicMock())

    details = {d["name"]: d for d in vt.list_openvpn_tunnels()}

    assert details["ns_site_a"]["up"] is True
    assert details["ns_site_a"]["clients"] == 1
    assert details["ns_site_b"]["up"] is False
    assert details["ns_site_b"]["clients"] == 0


def test_list_tunnels_excludes_road_warrior(fake_nethsec, fake_euci):
    instances = {"ns_roadwarrior1": {"enabled": "1", "ns_auth_mode": "certificate"}}
    utils = SimpleNamespace(get_all_by_type=lambda u, config, kind: instances)
    ovpn = SimpleNamespace(list_connected_clients=lambda section, type: {"peer1": {}})
    fake_nethsec.install(utils=utils, ovpn=ovpn)
    fake_euci(vt, uci_obj=MagicMock())

    assert vt.list_openvpn_tunnels() == []


def test_list_tunnels_p2p_client_up_requires_traffic_both_directions(fake_nethsec, fake_euci):
    instances = {"ns_client_a": {"enabled": "1", "client": "1"}}
    utils = SimpleNamespace(get_all_by_type=lambda u, config, kind: instances)
    ovpn = SimpleNamespace(list_connected_clients=lambda section, type: {"stats": {"bytes_received": 10, "bytes_sent": 0}})
    fake_nethsec.install(utils=utils, ovpn=ovpn)
    fake_euci(vt, uci_obj=MagicMock())

    details = vt.list_openvpn_tunnels()

    assert details == [{"name": "ns_client_a", "up": False, "label": "ns_client_a", "clients": 0}]


def test_count_openvpn_tunnels_derived_from_list(fake_nethsec, fake_euci):
    # count_openvpn_tunnels() must agree with list_openvpn_tunnels() - it's
    # meant to be a pure aggregation of the same data, not a second query.
    instances = {
        "ns_site_a": {"enabled": "1"},
        "ns_site_b": {"enabled": "1"},
    }
    utils = SimpleNamespace(get_all_by_type=lambda u, config, kind: instances)

    def fake_list_connected_clients(section, type):
        return {"peer1": {}} if section == "ns_site_a" else {}

    ovpn = SimpleNamespace(list_connected_clients=fake_list_connected_clients)
    fake_nethsec.install(utils=utils, ovpn=ovpn)
    fake_euci(vt, uci_obj=MagicMock())

    total, active = vt.count_openvpn_tunnels()

    assert (total, active) == (2, 1)


# --- main(): per-tunnel service lines ----------------------------------------

def test_main_prints_one_service_line_per_tunnel(monkeypatch, capsys):
    monkeypatch.setattr(vt, "list_openvpn_tunnels", lambda: [
        {"name": "ns_site_a", "up": True, "label": "ns_site_a", "clients": 1},
        {"name": "ns_site_b", "up": False, "label": "ns_site_b", "clients": 0},
    ])
    monkeypatch.setattr(vt, "count_wireguard_tunnels", lambda: (0, 0))

    vt.main()
    lines = capsys.readouterr().out.strip().splitlines()

    assert split_check_result(lines[0])[:2] == ("0", "VPN.Tunnel.ns_site_a")
    assert split_check_result(lines[1])[:2] == ("2", "VPN.Tunnel.ns_site_b")
    # WireGuard aggregate line still present (unaffected by OpenVPN state -
    # no WireGuard peers configured here).
    assert split_check_result(lines[2])[:2] == ("0", "VPN.Tunnel")


# --- count_wireguard_tunnels() ----------------------------------------------

def test_wireguard_active_requires_fresh_handshake(fake_nethsec, fake_euci, monkeypatch):
    # Regression: the old logic counted a peer active if its handshake
    # timestamp was ever nonzero - a peer that handshaked once and went
    # silent stayed "active" forever. Now it must be within the 180s window.
    wg_facts = {"servers": {"wg0": {"peers": 2}}}
    inventory = SimpleNamespace(fact_wireguard=lambda u: wg_facts)
    fake_nethsec.install(inventory=inventory)
    fake_euci(vt, uci_obj=MagicMock())
    monkeypatch.setattr(vt.time, "time", lambda: 1_000_000)
    monkeypatch.setattr(vt.shutil, "which", lambda name: "/usr/bin/wg")

    now = 1_000_000
    fresh_ts = now - 60          # within window -> active
    stale_ts = now - 99999999    # ancient handshake, once nonzero -> must NOT count

    def fake_run(cmd, **kwargs):
        if cmd[1:3] == ["show", "interfaces"]:
            return MagicMock(stdout="wg0\n")
        if cmd[1:3] == ["show", "wg0"]:
            return MagicMock(stdout=f"peerA\t{fresh_ts}\npeerB\t{stale_ts}\n")
        raise AssertionError(f"unexpected command {cmd}")

    monkeypatch.setattr(subprocess, "run", fake_run)

    total, active = vt.count_wireguard_tunnels()

    assert (total, active) == (2, 1)


def test_wireguard_total_and_active_are_both_peer_level(fake_nethsec, fake_euci, monkeypatch):
    # Regression: the old code derived "total" from interface count and
    # "active" from a per-peer check across interfaces, so active > total
    # was possible whenever one interface had multiple peers.
    wg_facts = {"servers": {"wg0": {"peers": 3}}}
    fake_nethsec.install(inventory=SimpleNamespace(fact_wireguard=lambda u: wg_facts))
    fake_euci(vt, uci_obj=MagicMock())
    monkeypatch.setattr(vt.shutil, "which", lambda name: None)  # wg binary unavailable

    total, active = vt.count_wireguard_tunnels()

    assert total == 3
    assert active <= total


def test_wireguard_zero_peers_configured(fake_nethsec, fake_euci):
    fake_nethsec.install(inventory=SimpleNamespace(fact_wireguard=lambda u: {"servers": {}}))
    fake_euci(vt, uci_obj=MagicMock())

    assert vt.count_wireguard_tunnels() == (0, 0)


# --- main(): perfdata + state thresholds ------------------------------------

def test_main_no_vpn_configured(monkeypatch, capsys):
    monkeypatch.setattr(vt, "list_openvpn_tunnels", lambda: [])
    monkeypatch.setattr(vt, "count_wireguard_tunnels", lambda: (0, 0))

    vt.main()
    line = capsys.readouterr().out.strip()

    state, service, perf, text = split_check_result(line)
    assert state == "0"
    assert service == "VPN.Tunnel"
    assert "No WireGuard peers configured" in text
    # Regression: perfdata was previously placed after the label text, so
    # field3 was just "-" and nothing was graphed.
    assert graphed_metric_names(line) == {"total", "active", "inactive"}


def test_main_wireguard_all_active_is_ok(monkeypatch, capsys):
    # The aggregate service is WireGuard-only now (OpenVPN tunnels get their
    # own per-tunnel VPN.Tunnel.<label> service instead - see
    # test_main_prints_one_service_line_per_tunnel).
    monkeypatch.setattr(vt, "list_openvpn_tunnels", lambda: [])
    monkeypatch.setattr(vt, "count_wireguard_tunnels", lambda: (2, 2))

    vt.main()
    line = capsys.readouterr().out.strip().splitlines()[-1]

    assert split_check_result(line)[0] == "0"
    assert dict(parse_perfdata(split_check_result(line)[2])) == {"total": 2.0, "active": 2.0, "inactive": 0.0}


def test_main_wireguard_some_down_is_warning(monkeypatch, capsys):
    monkeypatch.setattr(vt, "list_openvpn_tunnels", lambda: [])
    monkeypatch.setattr(vt, "count_wireguard_tunnels", lambda: (2, 1))

    vt.main()
    line = capsys.readouterr().out.strip().splitlines()[-1]

    assert split_check_result(line)[0] == "1"


def test_main_wireguard_all_down_is_critical(monkeypatch, capsys):
    monkeypatch.setattr(vt, "list_openvpn_tunnels", lambda: [])
    monkeypatch.setattr(vt, "count_wireguard_tunnels", lambda: (2, 0))

    vt.main()
    line = capsys.readouterr().out.strip().splitlines()[-1]

    assert split_check_result(line)[0] == "2"
