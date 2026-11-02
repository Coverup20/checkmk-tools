#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

# Network exposure: which listening sockets can be reached from outside the host?
#
# Maps to NIS base measure DE.CM-01: the network and its services are monitored
# to detect potentially adverse events. A listener only matters if someone
# outside the host can reach it, so every socket is classified by crossing its
# bind address with the firewall, not by counting open ports.
#
#   bind 127.0.0.0/8 or ::1                   -> LOOPBACK
#   bind 0.0.0.0 / ::, port blocked by fw     -> FILTERED  (not a problem)
#   bind 0.0.0.0 / ::, port admitted by fw    -> EXPOSED
#   bind a specific address                   -> same rule, on that address
#   firewall unreadable                       -> UNKNOWN   (not knowing != protected)
#   no active firewall                        -> EXPOSED for every non-loopback bind
#
# Firewall rules are not tracked per interface here, so a specific-address bind
# is judged by the same rule set as a wildcard bind.
#
# Emitted services:
#   Network.Exposure    [DE.CM-01] counts, group A exposures (CRIT), new
#                                  exposures vs baseline (WARN)
#   Network.Listeners   [DE.CM-01] listener set vs baseline: new (WARN) or
#                                  vanished (WARN) sockets
#   Network.Firewall    [DE.CM-01] INPUT policy and whether a firewall is active
#
# Baseline: /var/lib/check_mk_agent/network_exposure_baseline.json. It is NEVER
# updated automatically. A baseline that refreshed itself would let a malicious
# listener become "normal" on the next run and silence the check. The only way to
# write it is the explicit --accept-baseline flag, run by an operator who has
# reviewed the current listeners.
#
# Source of truth for group A: each port carries the source that justifies it.
# Groups B and C are not sourced: see the comments at their definitions.
#
# Compatible with Python 3.9+, the oldest interpreter in the fleet.

import datetime
import json
import os
import re
import subprocess
import sys

SERVICE_EXPOSURE = "Network.Exposure"
SERVICE_LISTENERS = "Network.Listeners"
SERVICE_FIREWALL = "Network.Firewall"
CONTROL = "DE.CM-01"
VERSION = "1.0.1"

BASELINE_PATH = "/var/lib/check_mk_agent/network_exposure_baseline.json"

# A baseline older than this cannot confirm that the listener set is still normal.
BASELINE_MAX_AGE_DAYS = int(os.environ.get("CHECK_NETWORK_BASELINE_MAX_AGE_DAYS", "90"))

LOOPBACK_PREFIX = "127."
LOOPBACK_V6 = ("::1",)
WILDCARD = ("0.0.0.0", "::", "*")

# Group A: an EXPOSED listener here is CRITICAL. Each row cites its source.
# Only sources named here are used; they are not extended from memory.
GROUP_A_TABLE = [
    ((445, 139, 137, 138), "SMB/NetBIOS",
     "Microsoft SMB lateral movement guidance; CISA #StopRansomware"),
    ((3389,), "RDP", "CISA #StopRansomware; CISA BOD 23-02; ACN BL01/250626"),
    ((tuple(range(5900, 5906)), tuple(range(5800, 5806))), "VNC",
     "ACN BL01/260416 (2026-04-16); CISA BOD 23-02"),
    ((22,), "SSH", "ACN BL01/250626; CISA BOD 23-02"),
    ((2375,), "Docker API", "Shadowserver (CRITICAL)"),
    ((5555,), "Android Debug Bridge", "Shadowserver (CRITICAL)"),
    ((4786,), "Cisco Smart Install", "Shadowserver (CRITICAL); CISA Edge Device Security"),
    ((3306,), "MySQL", "Shadowserver (HIGH)"),
    ((5432,), "PostgreSQL", "Shadowserver (HIGH)"),
    ((27017,), "MongoDB", "Shadowserver (HIGH)"),
    ((6379,), "Redis", "Shadowserver (HIGH)"),
    ((9200,), "Elasticsearch", "Shadowserver (HIGH)"),
    ((5984,), "CouchDB", "Shadowserver (HIGH)"),
    ((11211,), "Memcached", "Shadowserver (HIGH); CISA TA14-017A"),
    ((6443,), "Kubernetes API", "Shadowserver (HIGH)"),
    ((161,), "SNMP", "CISA BOD 23-02; ACN BL01/250626"),
    ((389, 636), "LDAP/LDAPS", "CISA Edge Device Security"),
    ((135,), "MS-RPC", "CISA Edge Device Security; ACN BL01/250626"),
    ((5985, 5986), "WinRM", "CISA Edge Device Security"),
    ((23,), "Telnet", "CISA BOD 23-02; ACN BL01/250626"),
    ((21,), "FTP", 'ACN BL01/250626 ("tassativamente"); CISA BOD 23-02'),
    ((69,), "TFTP", "CISA BOD 23-02; CISA Edge Device Security"),
    ((623,), "IPMI/BMC", "Shadowserver (HIGH); CISA BOD 23-02"),
    ((502, 20000, 47808), "Modbus/DNP3/BACnet", "Shadowserver (CRITICAL); ACN BL01/250626"),
    ((1434,), "MSSQL Browser", "Shadowserver (HIGH)"),
]

GROUP_A = {}
for _ports_spec, _name, _source in GROUP_A_TABLE:
    for _sub in _ports_spec:
        if isinstance(_sub, (list, tuple, range)):
            for _p in _sub:
                GROUP_A[_p] = (_name, _source)
        else:
            GROUP_A[_sub] = (_name, _source)

# Group B: WARNING only, never CRITICAL, when exposed. 1433 and 2049 are here
# because no official source names them: that is NOT evidence they are safe.
GROUP_B = {
    1433: "MSSQL",
    2049: "NFS",
    2376: "Docker TLS",
    10250: "kubelet",
    873: "rsync",
    111: "portmapper",
    123: "NTP",
    53: "DNS",
    5060: "SIP",
    1080: "proxy",
    3128: "proxy",
    8080: "proxy",
    1883: "MQTT",
    5683: "CoAP",
}

# Group C: web and mail services. Exposure alone is not an alarm.
GROUP_C = {80, 443, 25, 465, 587, 110, 995, 143, 993}

# Other checks on the same host may close a piggyback block with <<<<>>>>,
# which leaves no section open. Emitting our own header keeps these lines
# inside the local section regardless of what ran before us.
LOCAL_SECTION = "<<<local:sep(0)>>>"


def local_line(state, service, perfdata, message):
    """Build one CheckMK local-check line: state, service, metrics (or -), detail."""
    return "%s %s %s %s" % (state, service, perfdata or "-", message)


def run(cmd, timeout=30):
    """Run a command and return (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return 1, "", "command timed out"
    except FileNotFoundError:
        return 127, "", "command not found"
    except PermissionError:
        return 126, "", "command not executable"
    except Exception as exc:  # noqa: BLE001 - a check must never raise
        return 1, "", str(exc)


def group_of(port):
    """Return (group, name, source) for a port. Unlisted ports return ('-', None, None)."""
    if port in GROUP_A:
        name, source = GROUP_A[port]
        return "A", name, source
    if port in GROUP_B:
        return "B", GROUP_B[port], None
    if port in GROUP_C:
        return "C", None, None
    return "-", None, None


## Parsing

def split_endpoint(text):
    """Split 'addr:port' into (addr, port). Handles [v6]:port, addr%iface:port, *:port."""
    raw = (text or "").strip()
    addr, _, port = raw.rpartition(":")
    addr = addr.strip("[]").split("%")[0]
    try:
        return addr, int(port)
    except ValueError:
        return addr, None


PROCESS_RE = re.compile(r'users:\(\("([^"]+)",pid=(\d+)')


def parse_ss(text):
    """Parse `ss -tulnp` output into listener dicts."""
    listeners = []
    for raw in (text or "").splitlines():
        cols = raw.split()
        if len(cols) < 5 or cols[0] not in ("tcp", "udp"):
            continue
        proto, state, local = cols[0], cols[1], cols[4]
        if proto == "tcp" and state != "LISTEN":
            continue
        bind, port = split_endpoint(local)
        if port is None:
            continue
        match = PROCESS_RE.search(raw)
        listeners.append({
            "proto": proto,
            "bind": bind,
            "port": port,
            "process": match.group(1) if match else None,
        })
    return listeners


def parse_netstat(text):
    """Parse `netstat -tulnp` output into listener dicts (fallback when ss is absent)."""
    listeners = []
    for raw in (text or "").splitlines():
        cols = raw.split()
        if len(cols) < 4 or not cols[0].startswith(("tcp", "udp")):
            continue
        proto = "tcp" if cols[0].startswith("tcp") else "udp"
        if proto == "tcp" and "LISTEN" not in cols:
            continue
        bind, port = split_endpoint(cols[3])
        if port is None:
            continue
        process = None
        if len(cols) >= 7 and "/" in cols[-1]:
            process = cols[-1].split("/", 1)[1] or None
        listeners.append({
            "proto": proto,
            "bind": bind,
            "port": port,
            "process": process,
        })
    return listeners


UFW_ALLOW_RE = re.compile(r"^(\d+)(?:/(tcp|udp))?\s+ALLOW", re.MULTILINE)
IPT_ACCEPT_RE = re.compile(
    r"^-A INPUT .*?-p (tcp|udp) .*?--dport (\d+) .*?-j ACCEPT", re.MULTILINE
)
NFT_ACCEPT_RE = re.compile(r"(tcp|udp) dport (\d+).*?\baccept\b")


def read_firewall():
    """Return the firewall picture: readable, source, active, input_policy,
    admitted ({(port, proto or None)}), rules.

    Order: ufw (if active), then nft input hook, then iptables -S. A firewall
    that cannot be read is reported as readable=False, never as 'no firewall'."""
    fw = {
        "readable": False,
        "source": None,
        "active": False,
        "input_policy": None,
        "admitted": set(),
        "rules": 0,
        "error": None,
    }

    # 1. UFW: check status
    code, out, err = run(["ufw", "status"], timeout=20)
    if code == 0 and "Status: active" in out:
        fw.update(readable=True, source="ufw", active=True, input_policy="DROP")
        for port, proto in UFW_ALLOW_RE.findall(out):
            fw["admitted"].add((int(port), proto or None))
        fw["rules"] = len(fw["admitted"])
        return fw

    # 2. NFT: check ruleset
    code, out, err = run(["nft", "list", "ruleset"], timeout=20)
    if code == 0:
        fw["readable"] = True
        fw["source"] = "nft"
        for line in out.splitlines():
            if "hook input" in line:
                policy = re.search(r"policy (accept|drop)", line)
                if policy:
                    fw["input_policy"] = policy.group(1).upper()
        for proto, port in NFT_ACCEPT_RE.findall(out):
            fw["admitted"].add((int(port), proto))
        fw["rules"] = len(fw["admitted"])
        if fw["input_policy"] is not None:
            fw["active"] = fw["input_policy"] == "DROP"
            return fw

    # 3. iptables -S
    code, out, err = run(["iptables", "-S"], timeout=20)
    if code == 0:
        fw["readable"] = True
        fw["source"] = "iptables"
        policy = re.search(r"^-P INPUT (\w+)", out, re.MULTILINE)
        fw["input_policy"] = policy.group(1) if policy else None
        for proto, port in IPT_ACCEPT_RE.findall(out):
            fw["admitted"].add((int(port), proto))
        fw["rules"] = len(fw["admitted"])
        fw["active"] = fw["input_policy"] in ("DROP", "REJECT")
        return fw

    # Neither could be read successfully
    fw["error"] = (err or "").strip() or "no firewall tool readable"
    return fw


## Classification

def classify(bind, port, proto, fw):
    """Classify one listener against the firewall picture.

    Returns LOOPBACK, FILTERED, EXPOSED or UNKNOWN. Pure function."""
    if bind.startswith(LOOPBACK_PREFIX) or bind in LOOPBACK_V6:
        return "LOOPBACK"
    if not fw.get("readable"):
        return "UNKNOWN"
    if fw.get("active"):
        admitted = fw.get("admitted", set())
        if (port, proto) in admitted or (port, None) in admitted:
            return "EXPOSED"
        return "FILTERED"
    # Firewall not active or input policy ACCEPT -> non-loopback is reachable
    return "EXPOSED"


def listener_key(item):
    """Stable baseline key for a listener: proto:bind:port."""
    return "%s:%s:%d" % (item["proto"], item["bind"], item["port"])


def perfdata_string(total, exposed, filtered, loopback, new_since, rules):
    """Format perfdata line according to brief:
    listeners_total|exposed|filtered|loopback|new_since_baseline|firewall_rules"""
    return (
        "listeners_total=%d|exposed=%d|filtered=%d|loopback=%d|"
        "new_since_baseline=%d|firewall_rules=%d"
        % (total, exposed, filtered, loopback, new_since, rules)
    )


## Baseline I/O

def load_baseline(path=BASELINE_PATH):
    """Load baseline file if it exists, returning dict or None."""
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def save_baseline(listeners, fw, today, path=BASELINE_PATH):
    """Write current listeners to the baseline file."""
    data = {
        "created": today.isoformat(),
        "listeners": {},
    }
    for item in listeners:
        k = listener_key(item)
        cl = classify(item["bind"], item["port"], item["proto"], fw)
        data["listeners"][k] = {
            "proto": item["proto"],
            "bind": item["bind"],
            "port": item["port"],
            "process": item.get("process"),
            "classification": cl,
            "first_seen": today.isoformat(),
        }
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)


def family_of(bind):
    """Address family label for a bind address: IPv6 when it contains a colon."""
    return "IPv6" if ":" in bind else "IPv4"


def port_names(entries, classified):
    """Collapse EXPOSED sockets into one text entry per (port, proto, service).

    entries:    (item, name, source) for each EXPOSED socket in group A or B.
    classified: (item, classification) for every socket, used to see whether all
                sockets of a port/proto agree. Pure function.

    A dual-stack port (same port on IPv4 and IPv6, all of them EXPOSED) is named
    once. If any socket of that port/proto is not EXPOSED, each exposed address
    family is labelled instead, so a difference in classification stays visible.
    This only shapes the text: callers keep counting real sockets.
    Returns (port, proto, name, source, family_tag) tuples ordered by port, proto, name, family.
    """
    all_cls = {}
    for item, cl in classified:
        all_cls.setdefault((item["port"], item["proto"]), set()).add(cl)
    groups = {}
    for item, name, source in entries:
        key = (item["port"], item["proto"], name, source)
        groups.setdefault(key, set()).add(family_of(item["bind"]))
    out = []
    for key in sorted(groups, key=lambda k: (k[0], k[1], k[2] or "")):
        port, proto, name, source = key
        mixed = all_cls.get((port, proto), set()) != {"EXPOSED"}
        if mixed:
            for fam in sorted(groups[key]):
                out.append((port, proto, name, source, fam))
        else:
            out.append((port, proto, name, source, None))
    return out


def format_port_names(rows, with_source):
    """Render port_names() rows as 'port/proto Service (family) [source]', comma-joined."""
    parts = []
    for port, proto, name, source, tag in rows:
        text = "%d/%s %s" % (port, proto, name)
        if tag:
            text += " (%s)" % tag
        if with_source and source:
            text += " [%s]" % source
        parts.append(text)
    return ", ".join(parts)


## Evaluation

def evaluate_exposure(listeners, fw, baseline, today, max_age_days=BASELINE_MAX_AGE_DAYS):
    """Evaluate Network.Exposure. Pure function.

    Returns (state, perfdata, message)."""
    if listeners is None:
        return 3, "-", "UNKNOWN [%s]: listener list could not be retrieved" % CONTROL

    counts = {"LOOPBACK": 0, "FILTERED": 0, "EXPOSED": 0, "UNKNOWN": 0}
    classified = []
    group_a_exposed = []
    group_b_exposed = []

    for item in listeners:
        cl = classify(item["bind"], item["port"], item["proto"], fw)
        counts[cl] = counts.get(cl, 0) + 1
        classified.append((item, cl))
        if cl == "EXPOSED":
            grp, name, source = group_of(item["port"])
            if grp == "A":
                group_a_exposed.append((item, name, source))
            elif grp == "B":
                group_b_exposed.append((item, name, None))

    rules_count = fw.get("rules", 0)

    # First run without baseline: WARNING, never OK
    if baseline is None:
        perf = perfdata_string(
            len(listeners), counts["EXPOSED"], counts["FILTERED"],
            counts["LOOPBACK"], counts["EXPOSED"], rules_count
        )
        if group_a_exposed:
            details = format_port_names(port_names(group_a_exposed, classified), with_source=True)
            return 2, perf, (
                "CRITICAL [%s]: group A listener(s) exposed: %s" % (CONTROL, details)
            )
        return 1, perf, (
            "WARNING [%s]: no baseline found (%s) - first run on this host, "
            "cannot determine which exposures are expected; run with "
            "--accept-baseline to establish baseline (%d exposed, %d filtered, "
            "%d loopback)"
            % (CONTROL, BASELINE_PATH, counts["EXPOSED"], counts["FILTERED"], counts["LOOPBACK"])
        )

    # Compare against baseline
    baseline_listeners = baseline.get("listeners", {})
    new_exposed = []
    for item, cl in classified:
        if cl == "EXPOSED":
            k = listener_key(item)
            b_entry = baseline_listeners.get(k)
            if not b_entry or b_entry.get("classification") != "EXPOSED":
                new_exposed.append(item)

    perf = perfdata_string(
        len(listeners), counts["EXPOSED"], counts["FILTERED"],
        counts["LOOPBACK"], len(new_exposed), rules_count
    )

    # CRIT if any Group A listener is EXPOSED
    if group_a_exposed:
        details = format_port_names(port_names(group_a_exposed, classified), with_source=True)
        return 2, perf, (
            "CRITICAL [%s]: group A listener(s) exposed: %s" % (CONTROL, details)
        )

    # WARN if new EXPOSED listener not in baseline
    if new_exposed:
        summary = ", ".join(
            "%d/%s (%s)" % (i["port"], i["proto"], i["bind"]) for i in new_exposed
        )
        return 1, perf, (
            "WARNING [%s]: %d new exposed listener(s) not in baseline: %s"
            % (CONTROL, len(new_exposed), summary)
        )

    # WARN if group B listener is exposed (even if in baseline)
    if group_b_exposed:
        summary = format_port_names(port_names(group_b_exposed, classified), with_source=False)
        return 1, perf, (
            "WARNING [%s]: group B service(s) exposed: %s (non-critical list)"
            % (CONTROL, summary)
        )

    # Check baseline age
    baseline_date_str = baseline.get("created")
    age_days = 0
    if baseline_date_str:
        try:
            b_date = datetime.date.fromisoformat(baseline_date_str)
            age_days = (today - b_date).days
        except (ValueError, TypeError):
            age_days = 0

    if age_days > max_age_days:
        return 3, perf, (
            "UNKNOWN [%s]: baseline is %d days old (limit %d); "
            "cannot confirm exposure posture is still trusted - "
            "re-evaluate and run with --accept-baseline"
            % (CONTROL, age_days, max_age_days)
        )

    # OK: no group A exposed, no new exposures
    detail = "%d exposed, %d filtered, %d loopback" % (
        counts["EXPOSED"], counts["FILTERED"], counts["LOOPBACK"]
    )
    return 0, perf, "OK [%s]: no unauthorized exposures (%s)" % (CONTROL, detail)


def evaluate_listeners(listeners, baseline, today, max_age_days=BASELINE_MAX_AGE_DAYS):
    """Evaluate Network.Listeners. Pure function.

    Returns (state, perfdata, message)."""
    if listeners is None:
        return 3, "-", "UNKNOWN [%s]: listener list could not be retrieved" % CONTROL

    if baseline is None:
        return 1, "-", (
            "WARNING [%s]: no baseline found - %d listeners currently active; "
            "run with --accept-baseline to establish baseline"
            % (CONTROL, len(listeners))
        )

    current_keys = {listener_key(i): i for i in listeners}
    baseline_listeners = baseline.get("listeners", {})
    baseline_keys = set(baseline_listeners.keys())

    new_keys = set(current_keys.keys()) - baseline_keys
    vanished_keys = baseline_keys - set(current_keys.keys())

    if new_keys or vanished_keys:
        parts = []
        if new_keys:
            parts.append("%d new (%s)" % (
                len(new_keys), ", ".join(sorted(new_keys)[:5])
            ))
        if vanished_keys:
            parts.append("%d vanished (%s)" % (
                len(vanished_keys), ", ".join(sorted(vanished_keys)[:5])
            ))
        return 1, "-", (
            "WARNING [%s]: listener set differs from baseline: %s"
            % (CONTROL, "; ".join(parts))
        )

    # Baseline age check
    baseline_date_str = baseline.get("created")
    age_days = 0
    if baseline_date_str:
        try:
            b_date = datetime.date.fromisoformat(baseline_date_str)
            age_days = (today - b_date).days
        except (ValueError, TypeError):
            age_days = 0

    if age_days > max_age_days:
        return 3, "-", (
            "UNKNOWN [%s]: baseline is %d days old (limit %d) - "
            "review and refresh with --accept-baseline"
            % (CONTROL, age_days, max_age_days)
        )

    return 0, "-", "OK [%s]: %d listeners match baseline (0 changed)" % (
        CONTROL, len(listeners)
    )


def evaluate_firewall(fw):
    """Evaluate Network.Firewall. Pure function.

    Returns (state, perfdata, message)."""
    if not fw.get("readable"):
        err = fw.get("error") or "missing permission or command"
        return 3, "-", (
            "UNKNOWN [%s]: firewall status could not be read (%s)" % (CONTROL, err)
        )

    input_policy = fw.get("input_policy")
    source = fw.get("source")
    rules = fw.get("rules", 0)

    # CRIT if default policy of INPUT chain is ACCEPT
    if input_policy == "ACCEPT":
        return 2, "-", (
            "CRITICAL [%s]: firewall default INPUT policy is ACCEPT (%s) - "
            "host has no inbound packet filtering" % (CONTROL, source)
        )

    # WARN if no active firewall detected
    if not fw.get("active"):
        return 1, "-", (
            "WARNING [%s]: no active firewall detected (ufw inactive, "
            "no restrictive INPUT rules in nft/iptables)" % CONTROL
        )

    # OK if active with restrictive policy
    return 0, "-", (
        "OK [%s]: active firewall (%s, %d admitted rule%s, policy %s)"
        % (CONTROL, source, rules, "" if rules == 1 else "s", input_policy or "DROP")
    )


## Self-test

def self_test():
    """Exercise evaluate functions against known data and report PASS/FAIL per case."""
    today = datetime.date(2026, 11, 2)
    failures = 0
    ran = 0

    def expect(name, cond, detail=""):
        nonlocal failures, ran
        ran += 1
        if not cond:
            failures += 1
        print("%s  %s" % ("PASS" if cond else "FAIL", name))
        if not cond and detail:
            print("      %s" % detail)

    fw_active_drop = {
        "readable": True, "source": "ufw", "active": True,
        "input_policy": "DROP", "admitted": {(443, "tcp")}, "rules": 1,
    }
    fw_inactive_accept = {
        "readable": True, "source": "iptables", "active": False,
        "input_policy": "ACCEPT", "admitted": set(), "rules": 0,
    }
    fw_unreadable = {
        "readable": False, "source": None, "active": False,
        "input_policy": None, "admitted": set(), "rules": 0,
        "error": "permission denied",
    }
    fw_inactive_no_rules = {
        "readable": True, "source": "ufw", "active": False,
        "input_policy": None, "admitted": set(), "rules": 0,
    }

    clean_listeners = [
        {"proto": "tcp", "bind": "127.0.0.1", "port": 53, "process": "systemd-resolved"},
        {"proto": "tcp", "bind": "0.0.0.0", "port": 443, "process": "nginx"},
        {"proto": "tcp", "bind": "0.0.0.0", "port": 16568, "process": "frps"},
    ]

    base_clean = {
        "created": today.isoformat(),
        "listeners": {
            "tcp:127.0.0.1:53": {"proto": "tcp", "bind": "127.0.0.1", "port": 53,
                                 "classification": "LOOPBACK", "first_seen": today.isoformat()},
            "tcp:0.0.0.0:443": {"proto": "tcp", "bind": "0.0.0.0", "port": 443,
                                "classification": "EXPOSED", "first_seen": today.isoformat()},
            "tcp:0.0.0.0:16568": {"proto": "tcp", "bind": "0.0.0.0", "port": 16568,
                                  "classification": "FILTERED", "first_seen": today.isoformat()},
        },
    }

    # 1. Clean host with coherent baseline -> Exposure OK
    st, perf, msg = evaluate_exposure(clean_listeners, fw_active_drop, base_clean, today)
    expect("1. clean host with baseline gives Exposure OK",
           st == 0 and "no unauthorized exposures" in msg, msg)

    # 2. Clean host with coherent baseline -> Listeners OK
    st, _, msg = evaluate_listeners(clean_listeners, base_clean, today)
    expect("2. clean host with baseline gives Listeners OK",
           st == 0 and "3 listeners match baseline" in msg, msg)

    # 3. Active firewall with DROP policy -> Firewall OK
    st, _, msg = evaluate_firewall(fw_active_drop)
    expect("3. active firewall gives Firewall OK",
           st == 0 and "active firewall" in msg, msg)

    # 4. Listener new -> Listeners WARN
    listeners_with_new = list(clean_listeners) + [
        {"proto": "tcp", "bind": "0.0.0.0", "port": 9999, "process": "testapp"}
    ]
    st, _, msg = evaluate_listeners(listeners_with_new, base_clean, today)
    expect("4. new listener gives Listeners WARN",
           st == 1 and "1 new" in msg and "tcp:0.0.0.0:9999" in msg, msg)

    # 5. Listener vanished -> Listeners WARN
    listeners_missing_one = clean_listeners[:2]
    st, _, msg = evaluate_listeners(listeners_missing_one, base_clean, today)
    expect("5. vanished listener gives Listeners WARN",
           st == 1 and "1 vanished" in msg and "tcp:0.0.0.0:16568" in msg, msg)

    # 6. New exposed listener not in baseline -> Exposure WARN
    fw_allowing_9999 = dict(fw_active_drop)
    fw_allowing_9999["admitted"] = {(443, "tcp"), (9999, "tcp")}
    st, perf, msg = evaluate_exposure(listeners_with_new, fw_allowing_9999, base_clean, today)
    expect("6. new exposed listener gives Exposure WARN",
           st == 1 and "1 new exposed listener" in msg and "9999/tcp" in msg, msg)

    # 7. Group A port exposed (3389 RDP) -> Exposure CRIT with citation
    listeners_rdp = [
        {"proto": "tcp", "bind": "0.0.0.0", "port": 3389, "process": "xrdp"}
    ]
    fw_allowing_rdp = dict(fw_active_drop)
    fw_allowing_rdp["admitted"] = {(3389, "tcp")}
    st, perf, msg = evaluate_exposure(listeners_rdp, fw_allowing_rdp, base_clean, today)
    expect("7. exposed 3389 RDP gives CRITICAL with citation",
           st == 2 and "3389/tcp RDP [CISA #StopRansomware" in msg, msg)

    # 8. Group A port exposed (22 SSH) -> Exposure CRIT with citation
    listeners_ssh_exposed = [
        {"proto": "tcp", "bind": "0.0.0.0", "port": 22, "process": "sshd"}
    ]
    fw_allowing_ssh = dict(fw_active_drop)
    fw_allowing_ssh["admitted"] = {(22, "tcp")}
    st, perf, msg = evaluate_exposure(listeners_ssh_exposed, fw_allowing_ssh, None, today)
    expect("8. exposed 22 SSH gives CRITICAL with citation",
           st == 2 and "22/tcp SSH [ACN BL01/250626; CISA BOD 23-02]" in msg, msg)

    # 9. Group A port exposed (445 SMB) -> Exposure CRIT with citation
    listeners_smb = [
        {"proto": "tcp", "bind": "0.0.0.0", "port": 445, "process": "smbd"}
    ]
    fw_allowing_smb = dict(fw_active_drop)
    fw_allowing_smb["admitted"] = {(445, "tcp")}
    st, perf, msg = evaluate_exposure(listeners_smb, fw_allowing_smb, base_clean, today)
    expect("9. exposed 445 SMB gives CRITICAL with citation",
           st == 2 and "445/tcp SMB/NetBIOS [Microsoft SMB lateral movement" in msg, msg)

    # 10. Group A port but FILTERED (22 SSH not in admitted set) -> Exposure OK
    listeners_ssh = [
        {"proto": "tcp", "bind": "0.0.0.0", "port": 22, "process": "sshd"}
    ]
    fw_blocking_all = dict(fw_active_drop)
    fw_blocking_all["admitted"] = set()
    base_ssh_filtered = {
        "created": today.isoformat(),
        "listeners": {
            "tcp:0.0.0.0:22": {"proto": "tcp", "bind": "0.0.0.0", "port": 22,
                               "classification": "FILTERED", "first_seen": today.isoformat()}
        },
    }
    st, perf, msg = evaluate_exposure(listeners_ssh, fw_blocking_all, base_ssh_filtered, today)
    expect("10. Group A port but FILTERED gives OK",
           st == 0 and "no unauthorized exposures" in msg, msg)

    # 11. Port 16568 frps FILTERED by firewall -> OK (real case of frps)
    listeners_frps = [
        {"proto": "tcp", "bind": "0.0.0.0", "port": 16568, "process": "frps"}
    ]
    base_frps_filtered = {
        "created": today.isoformat(),
        "listeners": {
            "tcp:0.0.0.0:16568": {"proto": "tcp", "bind": "0.0.0.0", "port": 16568,
                                  "classification": "FILTERED", "first_seen": today.isoformat()}
        },
    }
    st, perf, msg = evaluate_exposure(listeners_frps, fw_blocking_all, base_frps_filtered, today)
    expect("11. port 16568 FILTERED gives OK",
           st == 0 and "0 exposed, 1 filtered" in msg, msg)

    # 12. Group B port exposed (1433 MSSQL) -> WARN (not CRIT)
    listeners_mssql = [
        {"proto": "tcp", "bind": "0.0.0.0", "port": 1433, "process": "sqlservr"}
    ]
    fw_allowing_mssql = dict(fw_active_drop)
    fw_allowing_mssql["admitted"] = {(1433, "tcp")}
    base_mssql = {
        "created": today.isoformat(),
        "listeners": {
            "tcp:0.0.0.0:1433": {"proto": "tcp", "bind": "0.0.0.0", "port": 1433,
                                 "classification": "EXPOSED", "first_seen": today.isoformat()}
        },
    }
    st, perf, msg = evaluate_exposure(listeners_mssql, fw_allowing_mssql, base_mssql, today)
    expect("12. Group B port 1433 exposed gives WARN (not CRIT)",
           st == 1 and "1433/tcp MSSQL" in msg and "(non-critical list)" in msg, msg)

    # 13. Group B port exposed (2049 NFS) -> WARN (not CRIT)
    listeners_nfs = [
        {"proto": "tcp", "bind": "0.0.0.0", "port": 2049, "process": "nfsd"}
    ]
    fw_allowing_nfs = dict(fw_active_drop)
    fw_allowing_nfs["admitted"] = {(2049, "tcp")}
    base_nfs = {
        "created": today.isoformat(),
        "listeners": {
            "tcp:0.0.0.0:2049": {"proto": "tcp", "bind": "0.0.0.0", "port": 2049,
                                 "classification": "EXPOSED", "first_seen": today.isoformat()}
        },
    }
    st, perf, msg = evaluate_exposure(listeners_nfs, fw_allowing_nfs, base_nfs, today)
    expect("13. Group B port 2049 exposed gives WARN (not CRIT)",
           st == 1 and "2049/tcp NFS" in msg, msg)

    # 14. Group C port exposed (80 HTTP) -> OK
    listeners_http = [
        {"proto": "tcp", "bind": "0.0.0.0", "port": 80, "process": "nginx"}
    ]
    fw_allowing_http = dict(fw_active_drop)
    fw_allowing_http["admitted"] = {(80, "tcp")}
    base_http = {
        "created": today.isoformat(),
        "listeners": {
            "tcp:0.0.0.0:80": {"proto": "tcp", "bind": "0.0.0.0", "port": 80,
                               "classification": "EXPOSED", "first_seen": today.isoformat()}
        },
    }
    st, perf, msg = evaluate_exposure(listeners_http, fw_allowing_http, base_http, today)
    expect("14. Group C port 80 exposed gives OK",
           st == 0 and "no unauthorized exposures" in msg, msg)

    # 15. Group C port exposed (443 HTTPS) -> OK
    listeners_https = [
        {"proto": "tcp", "bind": "0.0.0.0", "port": 443, "process": "nginx"}
    ]
    fw_allowing_https = dict(fw_active_drop)
    fw_allowing_https["admitted"] = {(443, "tcp")}
    base_https = {
        "created": today.isoformat(),
        "listeners": {
            "tcp:0.0.0.0:443": {"proto": "tcp", "bind": "0.0.0.0", "port": 443,
                                "classification": "EXPOSED", "first_seen": today.isoformat()}
        },
    }
    st, perf, msg = evaluate_exposure(listeners_https, fw_allowing_https, base_https, today)
    expect("15. Group C port 443 exposed gives OK",
           st == 0 and "no unauthorized exposures" in msg, msg)

    # 16. Firewall inactive -> Firewall WARN
    st, _, msg = evaluate_firewall(fw_inactive_no_rules)
    expect("16. inactive firewall gives Firewall WARN",
           st == 1 and "no active firewall detected" in msg, msg)

    # 17. Firewall INPUT policy ACCEPT -> Firewall CRIT
    st, _, msg = evaluate_firewall(fw_inactive_accept)
    expect("17. INPUT policy ACCEPT gives Firewall CRIT",
           st == 2 and "default INPUT policy is ACCEPT" in msg, msg)

    # 18. Firewall unreadable -> Firewall UNKNOWN
    st, _, msg = evaluate_firewall(fw_unreadable)
    expect("18. unreadable firewall gives Firewall UNKNOWN",
           st == 3 and "firewall status could not be read" in msg, msg)

    # 19. Firewall unreadable -> Exposure UNKNOWN for non-loopback listeners
    st, _, msg = evaluate_exposure(clean_listeners, fw_unreadable, base_clean, today)
    expect("19. unreadable firewall classifies as UNKNOWN not FILTERED",
           classify("0.0.0.0", 22, "tcp", fw_unreadable) == "UNKNOWN", "")

    # 20. Baseline absent (first run) without Group A exposed -> Exposure WARN (never OK)
    listeners_no_group_a = [
        {"proto": "tcp", "bind": "127.0.0.1", "port": 8080, "process": "proxy"}
    ]
    st, perf, msg = evaluate_exposure(listeners_no_group_a, fw_active_drop, None, today)
    expect("20. first run without baseline gives Exposure WARN",
           st == 1 and "first run on this host" in msg, msg)

    # 21. Baseline absent (first run) -> Listeners WARN
    st, _, msg = evaluate_listeners(clean_listeners, None, today)
    expect("21. first run without baseline gives Listeners WARN",
           st == 1 and "no baseline found" in msg, msg)

    # 22. Stale baseline (>90 days) downgrades Exposure OK to UNKNOWN
    old_base_clean = dict(base_clean)
    old_base_clean["created"] = (today - datetime.timedelta(days=120)).isoformat()
    st, perf, msg = evaluate_exposure(clean_listeners, fw_active_drop, old_base_clean, today)
    expect("22. stale baseline downgrades Exposure OK to UNKNOWN",
           st == 3 and "baseline is 120 days old" in msg, msg)

    # 23. Stale baseline leaves CRITICAL untouched
    st, perf, msg = evaluate_exposure(listeners_rdp, fw_allowing_rdp, old_base_clean, today)
    expect("23. stale baseline leaves CRITICAL untouched",
           st == 2 and "CRITICAL" in msg, msg)

    # 24. Stale baseline leaves WARNING untouched
    st, perf, msg = evaluate_exposure(listeners_with_new, fw_allowing_9999, old_base_clean, today)
    expect("24. stale baseline leaves WARNING untouched",
           st == 1 and "WARNING" in msg, msg)

    # 25. Stale baseline downgrades Listeners OK to UNKNOWN
    st, _, msg = evaluate_listeners(clean_listeners, old_base_clean, today)
    expect("25. stale baseline downgrades Listeners OK to UNKNOWN",
           st == 3 and "baseline is 120 days old" in msg, msg)

    # 26. IPv6 ::1 loopback -> LOOPBACK
    expect("26. IPv6 ::1 classifies as LOOPBACK",
           classify("::1", 323, "udp", fw_inactive_accept) == "LOOPBACK", "")

    # 27. IPv6 :: wildcard -> EXPOSED when firewall inactive
    expect("27. IPv6 :: classifies as EXPOSED when firewall inactive",
           classify("::", 22, "tcp", fw_inactive_accept) == "EXPOSED", "")

    # 28. IPv4 127.0.0.53 loopback -> LOOPBACK
    expect("28. 127.0.0.53 classifies as LOOPBACK",
           classify("127.0.0.53", 53, "udp", fw_inactive_accept) == "LOOPBACK", "")

    # 29. Missing process names (non-root run) parses safely
    ss_sample = (
        "Netid State  Recv-Q Send-Q  Local Address:Port  Peer Address:PortProcess\n"
        "tcp   LISTEN 0      128          0.0.0.0:22         0.0.0.0:*\n"
    )
    parsed = parse_ss(ss_sample)
    expect("29. unprivileged ss output parses with process=None",
           len(parsed) == 1 and parsed[0]["process"] is None and parsed[0]["port"] == 22,
           str(parsed))

    # 30. ss absent, netstat fallback works
    netstat_sample = (
        "Proto Recv-Q Send-Q Local Address           Foreign Address         State       PID/Program name\n"
        "tcp        0      0 0.0.0.0:22              0.0.0.0:*               LISTEN      1033/sshd\n"
    )
    parsed_ns = parse_netstat(netstat_sample)
    expect("30. netstat output parses correctly as fallback",
           len(parsed_ns) == 1 and parsed_ns[0]["port"] == 22 and parsed_ns[0]["process"] == "sshd",
           str(parsed_ns))

    # 31. Neither ss nor netstat available -> UNKNOWN
    st_exp, _, msg_exp = evaluate_exposure(None, fw_active_drop, base_clean, today)
    st_lis, _, msg_lis = evaluate_listeners(None, base_clean, today)
    expect("31. missing network tools gives UNKNOWN for both services",
           st_exp == 3 and st_lis == 3 and "could not be retrieved" in msg_exp,
           msg_exp)

    # 32. Perfdata matches required format
    perf_test = perfdata_string(10, 2, 3, 5, 1, 4)
    expect("32. perfdata string format conforms to brief",
           perf_test == "listeners_total=10|exposed=2|filtered=3|loopback=5|new_since_baseline=1|firewall_rules=4",
           perf_test)

    # 33. Dual-stack group A port (22 SSH on IPv4 and IPv6, both EXPOSED): named once, counted twice
    listeners_dual_ssh = [
        {"proto": "tcp", "bind": "0.0.0.0", "port": 22, "process": "sshd"},
        {"proto": "tcp", "bind": "::", "port": 22, "process": "sshd"},
    ]
    fw_allowing_dual_ssh = dict(fw_active_drop)
    fw_allowing_dual_ssh["admitted"] = {(22, "tcp")}
    st, perf, msg = evaluate_exposure(listeners_dual_ssh, fw_allowing_dual_ssh, None, today)
    expect("dual-stack group A port is named once but counted twice",
           st == 2 and msg.count("22/tcp SSH") == 1 and "exposed=2" in perf
           and "IPv4" not in msg and "IPv6" not in msg,
           msg + " | " + perf)

    # 34. Same port: IPv4 EXPOSED and IPv6 LOOPBACK -> not merged, IPv4 labelled
    listeners_mixed_ssh = [
        {"proto": "tcp", "bind": "0.0.0.0", "port": 22, "process": "sshd"},
        {"proto": "tcp", "bind": "::1", "port": 22, "process": "sshd"},
    ]
    st, perf, msg = evaluate_exposure(listeners_mixed_ssh, fw_allowing_dual_ssh, None, today)
    expect("same port EXPOSED on IPv4 and LOOPBACK on IPv6 stays distinct",
           st == 2 and "22/tcp SSH (IPv4) [ACN BL01/250626; CISA BOD 23-02]" in msg
           and "22/tcp SSH [" not in msg and "exposed=1" in perf and "loopback=1" in perf,
           msg + " | " + perf)

    print("\n%d/%d passed" % (ran - failures, ran))
    sys.exit(1 if failures else 0)


## Check execution

def check():
    print(LOCAL_SECTION)
    today = datetime.date.today()

    # 1. Listeners collection: ss preferred, netstat fallback
    listeners = None
    code, out, _ = run(["ss", "-tulnp"], timeout=20)
    if code == 0:
        listeners = parse_ss(out)
    else:
        code_ns, out_ns, _ = run(["netstat", "-tulnp"], timeout=20)
        if code_ns == 0:
            listeners = parse_netstat(out_ns)

    # 2. Firewall reading
    fw = read_firewall()

    # 3. Handle --accept-baseline flag
    if "--accept-baseline" in sys.argv:
        if listeners is None:
            print("ERROR: cannot accept baseline when listeners cannot be collected",
                  file=sys.stderr)
            sys.exit(2)
        save_baseline(listeners, fw, today, BASELINE_PATH)
        print("Baseline accepted with %d listeners saved to %s"
              % (len(listeners), BASELINE_PATH))
        return

    # 4. Load baseline
    baseline = load_baseline(BASELINE_PATH)

    # 5. Service 1: Network.Exposure
    st_exp, perf_exp, msg_exp = evaluate_exposure(listeners, fw, baseline, today)
    print(local_line(st_exp, SERVICE_EXPOSURE, perf_exp, msg_exp))

    # 6. Service 2: Network.Listeners
    st_lis, perf_lis, msg_lis = evaluate_listeners(listeners, baseline, today)
    print(local_line(st_lis, SERVICE_LISTENERS, perf_lis, msg_lis))

    # 7. Service 3: Network.Firewall
    st_fw, perf_fw, msg_fw = evaluate_firewall(fw)
    print(local_line(st_fw, SERVICE_FIREWALL, perf_fw, msg_fw))


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        check()
