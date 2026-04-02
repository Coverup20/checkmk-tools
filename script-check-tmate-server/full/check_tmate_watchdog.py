#!/usr/bin/python3
#
# Copyright (C) 2025 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

# Monitor tmate-ssh-server for unauthorized connection attempts
# Detects: "Spawning pty client" without subsequent "Client joined" (key check failed)
# Reports as CheckMK local check service Tmate.AuthWatchdog

import subprocess
import sys
import re
import time
import json
import os
import datetime

VERSION = "1.0.0"
SERVICE = "Tmate.AuthWatchdog"
STATE_FILE = "/var/tmp/check_tmate_watchdog_state.json"
GRACE_SECONDS = 20    # ignore very recent "Spawning" entries (client may still be authenticating)
WARN_THRESHOLD = 1    # WARN if >= 1 new failed attempt
CRIT_THRESHOLD = 5    # CRIT if >= 5 failed attempts in last hour

## Utils

def run(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return p.returncode, p.stdout, p.stderr
    except Exception as e:
        return 1, "", str(e)

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except:
        return {"seen": {}}

def save_state(s):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(s, f)
    except:
        pass

def parse_ts(iso_str):
    try:
        # journalctl short-iso: 2026-04-02T13:02:33+0000
        dt = datetime.datetime.fromisoformat(iso_str.replace("+0000", "+00:00"))
        return dt.timestamp()
    except:
        return time.time()

## Check

def check():
    now = time.time()

    rc, out, _ = run([
        "journalctl", "-u", "tmate-ssh-server",
        "--since", "2 hours ago",
        "--no-pager", "--output=short-iso"
    ])
    if rc != 0:
        print(f"3 {SERVICE} - UNKNOWN: journalctl failed")
        return

    re_ts = re.compile(r'^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{4})')
    re_spawn = re.compile(r'\[(\w{4})\.\.\.\] Spawning pty client ip=(\S+)')
    re_join = re.compile(r'\[(\w{4})\.\.\.\] Client joined')

    spawning = {}  # token4 -> {"ip": ip, "ts": float}
    joined = set()
    cur_ts = now

    for line in out.splitlines():
        m = re_ts.match(line)
        if m:
            cur_ts = parse_ts(m.group(1))

        m = re_spawn.search(line)
        if m:
            tok, ip = m.group(1), m.group(2)
            spawning[tok] = {"ip": ip, "ts": cur_ts}
            continue

        m = re_join.search(line)
        if m:
            joined.add(m.group(1))

    state = load_state()
    seen = state.get("seen", {})

    # Purge seen entries older than 25 hours
    seen = {k: v for k, v in seen.items() if now - v.get("ts", 0) < 90000}

    # Detect new failures: spawning without join, past grace period, not already seen
    new_failures = []
    for tok, info in spawning.items():
        if tok in joined:
            continue
        if now - info["ts"] < GRACE_SECONDS:
            continue
        key = f"{tok}_{int(info['ts'])}"
        if key in seen:
            continue
        new_failures.append({"tok": tok, "ip": info["ip"], "ts": info["ts"], "key": key})

    # All failures in last hour (from state)
    recent = [v for v in seen.values() if now - v.get("ts", 0) < 3600]
    total = len(recent) + len(new_failures)

    # Persist new failures
    for f in new_failures:
        seen[f["key"]] = {"ts": f["ts"], "ip": f["ip"]}
    state["seen"] = seen
    save_state(state)

    if total == 0:
        print(f"0 {SERVICE} - OK: no unauthorized attempts in last hour")
        return

    new_ips = list({f["ip"] for f in new_failures})
    all_ips = list({v["ip"] for v in seen.values() if now - v.get("ts", 0) < 3600})
    msg = f"{total} failed attempt(s) in last hour | IPs: {', '.join(all_ips)}"
    if new_failures:
        msg += f" | NEW: {', '.join(new_ips)}"

    state_code = 2 if total >= CRIT_THRESHOLD else 1
    print(f"{state_code} {SERVICE} - {'CRIT' if state_code == 2 else 'WARN'}: {msg}")

check()
