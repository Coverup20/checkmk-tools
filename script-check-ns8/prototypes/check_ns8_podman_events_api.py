#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

"""check_ns8_podman_events_api.py - NS8 container lifecycle and crash event monitor (PROTOTYPE)

CheckMK local check querying Podman REST API over Unix domain sockets.
100% REST-only: no subprocess, no background daemon, no local log polling.
Queries GET /v5.0.0/libpod/events?since=<timestamp>&stream=false on root
and module Podman sockets to inspect container lifecycle events within a sliding window.

States:
  CRIT   Container OOM (Out Of Memory) or abnormal termination (exit code != 0)
  WARN   Container killed or warnings detected in event stream
  OK     Normal container lifecycle (start/stop/create/remove) with 0 crashes

Version: 0.1.0
"""

import http.client
import json
import os
try:
    import pwd
except ImportError:
    pwd = None
import socket
import sys
import time
import urllib.parse
from typing import Dict, List, Optional, Tuple

VERSION = "0.1.0"
SERVICE = "NS8.PodmanEvents.Status"
WINDOW_SECONDS = int(os.environ.get("NS8_EVENTS_WINDOW_SECONDS", "900"))  # 15 minutes
ROOT_PODMAN_SOCKET = os.environ.get("PODMAN_SOCKET", "/run/podman/podman.sock")
NODE_AGENT_ENV = "/var/lib/nethserver/node/state/agent.env"
CRITICAL_ACTIONS = {"oom", "died"}
WARNING_ACTIONS = {"kill"}


class UnixHTTPConnection(http.client.HTTPConnection):
    """HTTP client connection over Unix domain socket."""

    def __init__(self, path: str, timeout: float = 5.0):
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._path)


def get_local_node_id() -> str:
    """Reads local node ID from agent.env."""
    try:
        with open(NODE_AGENT_ENV, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("AGENT_ID=node/"):
                    return line.strip().split("/", 1)[1]
    except OSError:
        pass
    return ""


def discover_sockets() -> List[Tuple[str, str]]:
    """Discovers available Podman sockets: returns [(label, socket_path)]."""
    sockets = []
    if os.path.exists(ROOT_PODMAN_SOCKET):
        sockets.append(("root", ROOT_PODMAN_SOCKET))

    # Scan for rootless module users in /run/user/<uid>/podman/podman.sock
    run_user_dir = "/run/user"
    if os.path.isdir(run_user_dir):
        try:
            for entry in os.listdir(run_user_dir):
                if entry.isdigit():
                    uid = int(entry)
                    sock_path = os.path.join(run_user_dir, entry, "podman", "podman.sock")
                    if os.path.exists(sock_path):
                        try:
                            username = pwd.getpwuid(uid).pw_name
                        except (KeyError, AttributeError):
                            username = f"uid-{uid}"
                        sockets.append((username, sock_path))
        except OSError:
            pass
    return sockets


def parse_event_payload(payload_bytes: bytes) -> List[dict]:
    """Parses Podman events payload supporting NDJSON or JSON array."""
    events = []
    text = payload_bytes.decode("utf-8", errors="replace").strip()
    if not text:
        return events

    if text.startswith("[") and text.endswith("]"):
        try:
            arr = json.loads(text)
            if isinstance(arr, list):
                return arr
        except ValueError:
            pass

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                events.append(obj)
        except ValueError:
            continue
    return events


def query_podman_events(sock_path: str, since_epoch: int) -> Tuple[Optional[str], List[dict]]:
    """Queries Podman REST API for container events with stream=false."""
    if not os.path.exists(sock_path):
        return "socket-not-found", []

    filters = json.dumps({"type": ["container"]})
    params = urllib.parse.urlencode({
        "since": str(since_epoch),
        "stream": "false",
        "filters": filters
    })
    path = f"/v5.0.0/libpod/events?{params}"

    try:
        conn = UnixHTTPConnection(sock_path, timeout=5.0)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        if resp.status != 200:
            return f"http-{resp.status}", []
        return None, parse_event_payload(body)
    except (OSError, http.client.HTTPException, ValueError) as exc:
        return f"conn-error-{type(exc).__name__}", []


def evaluate_events(all_events: List[Tuple[str, dict]]) -> Tuple[int, str, str]:
    """Evaluates collected container events across all sockets.

    Returns (state, text, perfdata).
    """
    total_events = len(all_events)
    oom_events = []
    crash_events = []
    kill_events = []

    for source, ev in all_events:
        action = str(ev.get("Action", "")).lower()
        actor = ev.get("Actor", {}) or {}
        attrs = actor.get("Attributes", {}) or {}
        name = attrs.get("name") or actor.get("ID", "?")[:12]

        if action == "oom":
            oom_events.append(f"{source}:{name}(OOM)")
        elif action in ("die", "died"):
            raw_exit = attrs.get("exitCode", "0")
            try:
                exit_code = int(raw_exit)
            except (ValueError, TypeError):
                exit_code = 0
            if exit_code != 0:
                crash_events.append(f"{source}:{name}(exit={exit_code})")
        elif action == "kill":
            kill_events.append(f"{source}:{name}")

    fatal_count = len(oom_events) + len(crash_events)
    warn_count = len(kill_events)

    perf = f"events={total_events}|crashes={fatal_count};0;1|kills={warn_count}"

    window_min = WINDOW_SECONDS // 60
    if fatal_count > 0:
        details = ", ".join(oom_events + crash_events)
        msg = f"CRITICAL: {fatal_count} container failure(s) in last {window_min}m: {details}"
        return 2, msg, perf

    if warn_count > 0:
        details = ", ".join(kill_events)
        msg = f"WARNING: {warn_count} container kill event(s) in last {window_min}m: {details}"
        return 1, msg, perf

    msg = f"OK: 0 crashes across all modules in last {window_min}m ({total_events} events total)"
    return 0, msg, perf


def check():
    sockets = discover_sockets()
    if not sockets:
        print(f"0 {SERVICE} - OK: no active Podman sockets discovered on host")
        return

    since_epoch = int(time.time()) - WINDOW_SECONDS
    all_events: List[Tuple[str, dict]] = []
    socket_errors: List[str] = []

    for label, sock_path in sockets:
        err, events = query_podman_events(sock_path, since_epoch)
        if err:
            socket_errors.append(f"{label}:{err}")
        else:
            for ev in events:
                all_events.append((label, ev))

    state, text, perf = evaluate_events(all_events)
    if socket_errors and state == 0:
        text += f" (socket warnings: {', '.join(socket_errors)})"

    print(f"{state} {SERVICE} {perf} {text}")


def self_test():
    cases_passed = 0
    cases_total = 0

    def assert_case(desc: str, condition: bool):
        nonlocal cases_passed, cases_total
        cases_total += 1
        if condition:
            cases_passed += 1
            print(f"PASS: {desc}")
        else:
            print(f"FAIL: {desc}")

    # Case 1: Empty event stream
    st, txt, perf = evaluate_events([])
    assert_case("Empty events returns OK", st == 0 and "crashes=0" in perf)

    # Case 2: Normal start/stop events
    normal_events = [
        ("root", {"Action": "start", "Actor": {"Attributes": {"name": "c1"}}}),
        ("mail1", {"Action": "stop", "Actor": {"Attributes": {"name": "c2"}}}),
    ]
    st, txt, perf = evaluate_events(normal_events)
    assert_case("Normal start/stop returns OK", st == 0 and "crashes=0" in perf)

    # Case 3: Container OOM event
    oom_events = [
        ("nextcloud1", {"Action": "oom", "Actor": {"Attributes": {"name": "app"}}})
    ]
    st, txt, perf = evaluate_events(oom_events)
    assert_case("Container OOM returns CRITICAL", st == 2 and "OOM" in txt)

    # Case 4: Container non-zero exit code
    crash_events = [
        ("samba1", {"Action": "die", "Actor": {"Attributes": {"name": "smbd", "exitCode": "137"}}})
    ]
    st, txt, perf = evaluate_events(crash_events)
    assert_case("Container die with exit 137 returns CRITICAL", st == 2 and "exit=137" in txt)

    # Case 5: Container zero exit code (normal shutdown)
    clean_exit = [
        ("mail1", {"Action": "die", "Actor": {"Attributes": {"name": "worker", "exitCode": "0"}}})
    ]
    st, txt, perf = evaluate_events(clean_exit)
    assert_case("Container die with exit 0 returns OK", st == 0 and "crashes=0" in perf)

    # Case 6: Kill action triggers WARNING
    kill_events = [
        ("webtop1", {"Action": "kill", "Actor": {"Attributes": {"name": "webtop"}}})
    ]
    st, txt, perf = evaluate_events(kill_events)
    assert_case("Container kill triggers WARNING", st == 1 and "kill" in txt)

    # Case 7: NDJSON parser test
    ndjson_data = b'{"Action":"start","Actor":{"Attributes":{"name":"t1"}}}\n{"Action":"stop","Actor":{"Attributes":{"name":"t1"}}}\n'
    parsed = parse_event_payload(ndjson_data)
    assert_case("NDJSON parsed accurately", len(parsed) == 2 and parsed[0]["Action"] == "start")

    # Case 8: JSON Array parser test
    json_arr_data = b'[{"Action":"create","Actor":{"Attributes":{"name":"t2"}}}]'
    parsed_arr = parse_event_payload(json_arr_data)
    assert_case("JSON array parsed accurately", len(parsed_arr) == 1 and parsed_arr[0]["Action"] == "create")

    print(f"\nSelf-test results: {cases_passed}/{cases_total} passed")
    if cases_passed != cases_total:
        sys.exit(1)


if "--self-test" in sys.argv:
    self_test()
else:
    check()
