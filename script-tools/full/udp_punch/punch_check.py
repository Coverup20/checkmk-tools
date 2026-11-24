#!/usr/bin/env python3
"""CheckMK datasource program: expose the UDP punch status as local checks.

Reads the JSON snapshot written by punch_dashboard.py and prints one local
check per tunnel instance plus a summary. It runs as the CheckMK site user,
which cannot read the system journal, so the snapshot is the only data source.
A missing, stale or unreadable snapshot is reported as UNKNOWN, so a dead feed
is visible in the monitoring instead of silently showing stale green.

Usage:
    punch_check.py --status-file /var/lib/cmk-punch-dashboard/status.json
    punch_check.py --self-test
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time

VERSION = "1.1.0"
STATUS_FILE = "/var/lib/cmk-punch-dashboard/status.json"
MAX_AGE_S = 300

STATE_OF = {"up": 0, "restarting": 1, "down": 2}


def read_status(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def age_text(seconds):
    if not isinstance(seconds, int):
        return "no session"
    if seconds < 90:
        return "%ds" % seconds
    if seconds < 5400:
        return "%dm" % (seconds // 60)
    return "%dh" % (seconds // 3600)


def render(data):
    """Local check lines for a status snapshot."""
    lines = []
    states = []
    up = 0
    rows = data.get("instances", [])
    for row in rows:
        state = STATE_OF.get(row.get("status"), 3)
        states.append(state)
        if state == 0:
            up += 1
        peer = row.get("real_ip") or row.get("peer") or "-"
        session_age = row.get("handshake_ago")
        restarts = row.get("restarts")
        perf_age = session_age if isinstance(session_age, int) else -1
        perf_restarts = restarts if isinstance(restarts, int) else -1
        message = "peer %s, session %s, restarts %s" % (
            peer, age_text(session_age),
            restarts if isinstance(restarts, int) else "-")
        lines.append('%d "UDP punch %s" session_age=%d restarts=%d %s'
                     % (state, row.get("instance"), perf_age,
                        perf_restarts, message))
    worst = max(states) if states else 3
    lines.append('%d "UDP punch summary" - %d of %d up'
                 % (worst, up, len(rows)))
    return lines


def main_lines(path, max_age, now=None):
    """Local check lines for the snapshot at path, including feed health.

    The feed line is emitted on every run, healthy or not: a service that only
    appears when the snapshot is stale is never discovered, so a dead writer
    would leave the tunnel services stale-but-green instead of alarming.
    """
    now = time.time() if now is None else now
    try:
        age = int(now - os.path.getmtime(path))
    except OSError:
        return ['3 "UDP punch feed" - status snapshot missing']
    if age > max_age:
        return ['3 "UDP punch feed" - status snapshot stale, %ds old' % age]
    try:
        data = read_status(path)
    except (OSError, ValueError) as exc:
        return ['3 "UDP punch feed" - status snapshot unreadable: %s' % exc]
    return (['0 "UDP punch feed" age=%d snapshot %ds old' % (age, age)]
            + render(data))


def self_test():
    rows = {"instances": [
        {"instance": "a", "status": "up", "real_ip": "192.0.2.10",
         "handshake_ago": 3600, "restarts": 1},
        {"instance": "b", "status": "down", "real_ip": "192.0.2.11",
         "handshake_ago": None, "restarts": 4},
    ]}
    lines = render(rows)
    assert lines[0].startswith('0 "UDP punch a" session_age=3600 restarts=1 '), lines
    assert lines[1].startswith('2 "UDP punch b" session_age=-1 restarts=4 '), lines
    assert lines[2] == '2 "UDP punch summary" - 1 of 2 up', lines
    assert render({"instances": []}) == ['3 "UDP punch summary" - 0 of 0 up']
    assert age_text(None) == "no session" and age_text(30) == "30s"
    assert age_text(7200) == "2h" and age_text(120) == "2m"
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "status.json")
        missing = main_lines(path, 300)
        assert missing == ['3 "UDP punch feed" - status snapshot missing'], missing
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(rows, fh)
        fresh = main_lines(path, 300, now=time.time())
        assert len(fresh) == 4, fresh
        assert fresh[0].startswith('0 "UDP punch feed" age='), fresh
        assert fresh[3] == '2 "UDP punch summary" - 1 of 2 up', fresh
        stale = main_lines(path, 300, now=time.time() + 400)
        assert "stale" in stale[0], stale
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        broken = main_lines(path, 300)
        assert "unreadable" in broken[0], broken
    print("SELFTEST PASS")
    return 0


def main():
    parser = argparse.ArgumentParser(description="UDP punch CheckMK checks")
    parser.add_argument("--status-file", default=STATUS_FILE)
    parser.add_argument("--max-age", type=int, default=MAX_AGE_S)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        sys.exit(self_test())
    print("<<<local>>>")
    for line in main_lines(args.status_file, args.max_age):
        print(line)


if __name__ == "__main__":
    main()
