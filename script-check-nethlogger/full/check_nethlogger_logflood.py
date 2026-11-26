#!/usr/bin/python3
#
# Copyright (C) 2025 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

"""check_nethlogger_logflood - report the hosts that produce the most logs and why.

Ranks the monitored assets by log volume in a time window and, for the busiest
ones, groups the most recent messages to name the actual program and message
pattern behind the flood. A short remediation hint is attached when the pattern
is a known one (indexer loops, corrupted local databases, chatty agents).

The transport and the analysis live in nl_common.py, shared with nl-toolkit.py
so the two cannot drift apart. This file keeps what belongs to the check: the
thresholds, the state mapping and the CheckMK output format.

Two transports are used:

  * API key (required) - POST /adm/bulllog/api/noauth_getstats/ gives the log
    counters per asset for the window. Counters are debug/info/warning/err.
  * UI session (optional) - POST /adm/auth/login/ then POST /adm/bulllog/reports/
    and POST /adm/bulllog/ajax_json_reports/ return the individual messages.
    Without it the check still reports volumes, only without the reason.

Environment:
  NETHLOGGER_ENV            env file with the settings below (default /opt/nethlogger-toolkit/.env)
  NETHLOGGER_URL            appliance base URL, e.g. https://nethlogger.example.com
  NETHLOGGER_APIKEY_FILE    file holding the API key (default /root/.netlogger-apikey)
  NETHLOGGER_APIKEY         API key in the environment (takes precedence over the file)
  NETHLOGGER_UI_USER        UI user name (optional, enables the reason lookup)
  NETHLOGGER_UI_PASS_FILE   file holding the UI password (default /root/.netlogger-uipass)
  NETHLOGGER_UI_PASS        UI password in the environment (takes precedence over the file)
  NETHLOGGER_UI_PASS_KEY    key to extract from the password file (default NETHLOGGER_PASS)
  NETHLOGGER_LOCATION       opaque location token used by the search form
  NETHLOGGER_WINDOW_HOURS   look-back window in hours (default 24)
  NETHLOGGER_WARN_LOGS      WARNING threshold on logs per window (default 1000000)
  NETHLOGGER_CRIT_LOGS      CRITICAL threshold on logs per window (default 10000000)
  NETHLOGGER_TOP_HOSTS      how many assets to report (default 5)
  NETHLOGGER_SAMPLE_ROWS    messages sampled per host to find the pattern (default 500)
  NETHLOGGER_INSECURE       set to 1 to skip TLS verification (self-signed appliance)

Usage:
  check_nethlogger_logflood.py             normal run (CheckMK local check)
  check_nethlogger_logflood.py --self-test offline assertions, no network

Version: 1.0.1
"""

import os
import sys

# The check runs from /opt/nethlogger-toolkit but may be reached through a
# symlink placed in the site's local checks: both lookups have to work.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/opt/nethlogger-toolkit")

import nl_common as nl

VERSION = "1.0.1"

ENV_FILE = os.environ.get("NETHLOGGER_ENV", "/opt/nethlogger-toolkit/.env")
nl.load_env(ENV_FILE)

BASE_URL = os.environ.get("NETHLOGGER_URL", "").rstrip("/")
WINDOW_HOURS = int(os.environ.get("NETHLOGGER_WINDOW_HOURS", "24"))
WARN_LOGS = int(os.environ.get("NETHLOGGER_WARN_LOGS", "1000000"))
CRIT_LOGS = int(os.environ.get("NETHLOGGER_CRIT_LOGS", "10000000"))
TOP_HOSTS = int(os.environ.get("NETHLOGGER_TOP_HOSTS", "5"))
SAMPLE_ROWS = int(os.environ.get("NETHLOGGER_SAMPLE_ROWS", "500"))

LEVELS = nl.LEVELS


## Check output

def state_for(total):
    return nl.state_for(total, WARN_LOGS, CRIT_LOGS)


def format_counters(counters):
    parts = ["%s=%d" % (level, int(counters.get(level) or 0)) for level in LEVELS
             if int(counters.get(level) or 0) > 0]
    return " ".join(parts) if parts else "none"


def host_line(host, patterns, reason_error):
    state = state_for(host["total"])
    message = "%d logs/%dh (%s)" % (host["total"], WINDOW_HOURS, format_counters(host["counters"]))
    if patterns:
        top = patterns[0]
        message += '; top: %s %.0f%% "%s"' % (top["program"], top["program_share"], top["pattern"][:90])
        message += " | solution: " + nl.remediation(top["program"], top["pattern"])
    elif reason_error:
        message += "; reason unavailable: %s" % reason_error
    message = message.replace("\n", " ")
    return "%d %s.%s - %s" % (state, "NethLogger", host["name"], message)


def run():
    if not BASE_URL:
        print("3 NethLogger.Config - NETHLOGGER_URL is not set")
        return 1

    client = nl.NethLogger(ENV_FILE)
    try:
        apikey = client.apikey()
    except OSError as error:
        print("3 NethLogger.Config - cannot read API key: %s" % error)
        return 1
    if not apikey:
        print("3 NethLogger.Config - the API key is empty")
        return 1

    start, end = nl.parse_window("%dh" % WINDOW_HOURS)
    try:
        hosts = client.assets(start, end)
    except Exception as error:
        print("3 NethLogger.API - %s" % error)
        return 1

    selected = hosts[:TOP_HOSTS]
    if not selected:
        print("0 NethLogger.Summary - no assets returned")
        return 0

    opener = None
    reason_error = ""
    if client.has_ui() and (client.ui_pass_value or os.path.exists(client.ui_pass_file)):
        try:
            opener = client.opener()
        except Exception as error:
            reason_error = "login failed: %s" % error
    else:
        reason_error = "no UI credentials"

    critical = 0
    warning = 0
    for host in selected:
        patterns = []
        if opener and host["total"] >= WARN_LOGS:
            try:
                rows = client.search(host=host["name"], program="*", level="err",
                                     start=start, end=end, length=SAMPLE_ROWS)
                patterns = nl.top_patterns(rows)
            except Exception as error:
                reason_error = "search failed: %s" % error
        if state_for(host["total"]) == 2:
            critical += 1
        elif state_for(host["total"]) == 1:
            warning += 1
        print(host_line(host, patterns, reason_error))

    worst = selected[0]
    summary = "%d hosts above WARNING, %d above CRITICAL; worst %s with %d logs/%dh" % (
        warning + critical, critical, worst["name"], worst["total"], WINDOW_HOURS)
    summary_state = 2 if critical else (1 if warning else 0)
    print("%d NethLogger.Summary - %s" % (summary_state, summary))
    return 0


## Self-test

def self_test():
    failures = 0
    total = 0

    def expect(name, got, want):
        nonlocal failures, total
        total += 1
        if got == want:
            print("PASS %s" % name)
        else:
            failures += 1
            print("FAIL %s (got %r, want %r)" % (name, got, want))

    expect("normalize strips process prefix",
           nl.normalize_message("(tracker-extract-3:4231): Tracker-WARNING **: failed"),
           "Tracker-WARNING **: failed")
    expect("normalize collapses numbers",
           nl.normalize_message("error 42 at 15:25:11 on port 8080"),
           "error N at N:N:N on port N")
    expect("normalize replaces quoted paths",
           nl.normalize_message("cannot read '/home/user/a.csv.tmp'"),
           "cannot read <value>")

    rows = [
        {"program": "tracker-miner-fs-3", "msg": "(tracker-extract-3:1): ambiguous column name: ROWID"},
        {"program": "tracker-miner-fs-3", "msg": "(tracker-extract-3:2): ambiguous column name: ROWID"},
        {"program": "cupsd", "msg": "printer offline"},
    ]
    patterns = nl.top_patterns(rows)
    expect("top pattern picks majority", patterns[0]["program"], "tracker-miner-fs-3")
    expect("top pattern count", patterns[0]["count"], 2)
    expect("program share", round(patterns[0]["program_share"]), 67)

    expect("remediation for tracker",
           "Tracker" in nl.remediation("tracker-miner-fs-3", "ambiguous column name: ROWID"), True)
    expect("remediation for systemd cycling",
           "restart loop" in nl.remediation("systemd", "Stopped target basic.target - Basic System."), True)
    expect("remediation fallback",
           nl.remediation("foo", "bar").startswith("process retry loop"), True)

    stats = {"000000": {"display_name": "x", "assets": {
        "a": {"alias": "", "counters": {"err": 5, "total": 5}},
        "b": {"alias": "", "counters": {"info": 50, "total": 50}},
        "c": {"alias": "", "counters": {"total": 0}},
    }}}
    ranked = nl.assets_from_stats(stats)
    expect("ranking is descending", [item["name"] for item in ranked], ["b", "a", "c"])

    global WARN_LOGS, CRIT_LOGS
    saved = (WARN_LOGS, CRIT_LOGS)
    WARN_LOGS, CRIT_LOGS = 10, 100
    expect("state ok", state_for(5), 0)
    expect("state warning", state_for(50), 1)
    expect("state critical", state_for(500), 2)

    line = host_line({"name": "h", "total": 200, "counters": {"total": 200, "err": 200}},
                     [{"program": "p", "pattern": "boom", "program_share": 100.0}], "")
    expect("line starts with state", line.split(" ")[0], "2")
    expect("line has service name", line.split(" ")[1], "NethLogger.h")
    expect("line carries solution", "solution:" in line, True)
    WARN_LOGS, CRIT_LOGS = saved

    print("Self-test: %d/%d passed" % (total - failures, total))
    return 0 if failures == 0 else 1


if "--self-test" in sys.argv:
    sys.exit(self_test())
sys.exit(run())
