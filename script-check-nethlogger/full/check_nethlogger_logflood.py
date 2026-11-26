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

Version: 1.0.0
"""

import http.cookiejar
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

VERSION = "1.0.0"

ENV_FILE = os.environ.get("NETHLOGGER_ENV", "/opt/nethlogger-toolkit/.env")


def load_env(path):
    """Populate os.environ from a KEY=VALUE file without overriding the real env."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name.startswith("export "):
            name = name[len("export "):].strip()
        os.environ.setdefault(name, value.strip().strip('"').strip("'"))


load_env(ENV_FILE)

BASE_URL = os.environ.get("NETHLOGGER_URL", "").rstrip("/")
APIKEY_FILE = os.environ.get("NETHLOGGER_APIKEY_FILE", "/root/.netlogger-apikey")
APIKEY = os.environ.get("NETHLOGGER_APIKEY", "")
UI_USER = os.environ.get("NETHLOGGER_UI_USER", "")
UI_PASS_FILE = os.environ.get("NETHLOGGER_UI_PASS_FILE", "/root/.netlogger-uipass")
UI_PASS_KEY = os.environ.get("NETHLOGGER_UI_PASS_KEY", "NETHLOGGER_PASS")
UI_PASS = os.environ.get("NETHLOGGER_UI_PASS", "")
LOCATION = os.environ.get("NETHLOGGER_LOCATION", "")
WINDOW_HOURS = int(os.environ.get("NETHLOGGER_WINDOW_HOURS", "24"))
WARN_LOGS = int(os.environ.get("NETHLOGGER_WARN_LOGS", "1000000"))
CRIT_LOGS = int(os.environ.get("NETHLOGGER_CRIT_LOGS", "10000000"))
TOP_HOSTS = int(os.environ.get("NETHLOGGER_TOP_HOSTS", "5"))
SAMPLE_ROWS = int(os.environ.get("NETHLOGGER_SAMPLE_ROWS", "500"))
INSECURE = os.environ.get("NETHLOGGER_INSECURE", "") == "1"
TIMEOUT = 90

LEVELS = ("err", "warning", "info", "debug")


## Helpers

def ssl_context():
    ctx = ssl.create_default_context()
    if INSECURE:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def read_secret(path, key=None):
    with open(path, "r", encoding="utf-8") as handle:
        content = handle.read()
    if key:
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() == key:
                return value.strip().strip('"').strip("'")
    return content.strip()


def multipart(fields):
    boundary = "----nethlogger%d" % int(time.time() * 1000)
    lines = []
    for name, value in fields:
        lines.append("--%s\r\n" % boundary)
        lines.append("Content-Disposition: form-data; name=\"%s\"\r\n\r\n" % name)
        lines.append("%s\r\n" % value)
    lines.append("--%s--\r\n" % boundary)
    body = "".join(lines).encode("utf-8")
    return body, "multipart/form-data; boundary=%s" % boundary


def http_post(url, fields, opener=None, form=False):
    if form:
        body = urllib.parse.urlencode(fields).encode("utf-8")
        content_type = "application/x-www-form-urlencoded"
    else:
        body, content_type = multipart(fields)
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": content_type, "Accept": "application/json, text/html"},
    )
    if opener:
        with opener.open(request, timeout=TIMEOUT) as response:
            return response.read()
    with urllib.request.urlopen(request, timeout=TIMEOUT, context=ssl_context()) as response:
        return response.read()


def window():
    end = datetime.now()
    start = end - timedelta(hours=WINDOW_HOURS)
    return start, end


def api_stamp(moment):
    return moment.strftime("%Y%m%d%H%M")


def ui_stamp(moment):
    return moment.strftime("%d/%m/%Y %H:%M")


## Transport: API key

def fetch_stats(apikey, start, end):
    fields = [
        ("APIKEY", apikey),
        ("DATE_START", api_stamp(start)),
        ("DATE_END", api_stamp(end)),
    ]
    raw = http_post(BASE_URL + "/adm/bulllog/api/noauth_getstats/", fields)
    text = raw.decode("utf-8", "replace").strip()
    if not text.startswith("{"):
        raise RuntimeError("stats endpoint returned: %s" % text[:120])
    return json.loads(text)


def assets_from_stats(stats):
    hosts = []
    for company in stats.values():
        for name, asset in (company.get("assets") or {}).items():
            counters = asset.get("counters") or {}
            hosts.append({
                "name": name,
                "alias": asset.get("alias") or "",
                "counters": counters,
                "total": int(counters.get("total") or 0),
            })
    hosts.sort(key=lambda item: item["total"], reverse=True)
    return hosts


## Transport: UI session

def ui_login():
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar),
        urllib.request.HTTPSHandler(context=ssl_context()),
    )
    fields = [
        ("action", "login"),
        ("user", UI_USER),
        ("pass", UI_PASS or read_secret(UI_PASS_FILE, UI_PASS_KEY)),
        ("proto", ""),
        ("lang", "en"),
    ]
    page = http_post(BASE_URL + "/adm/auth/login/", fields, opener=opener, form=True)
    if b"login" in page[:4000] and b"nome utente" in page.lower():
        raise RuntimeError("UI login rejected")
    return opener


def search_messages(opener, host, level, start, end, length):
    form = [
        ("location", LOCATION),
        ("host[]", host),
        ("msg", ""),
        ("priority", level),
        ("program", "*"),
        ("cyber_rules", "*"),
        ("date", ui_stamp(start)),
        ("date2", ui_stamp(end)),
        ("recperpag", "100"),
        ("orderby", "DESC"),
    ]
    page = http_post(BASE_URL + "/adm/bulllog/reports/", form, opener=opener, form=True)
    text = page.decode("utf-8", "replace")
    match = re.search(r'd\.params\s*=\s*"([^"]*)"', text)
    if not match or not match.group(1):
        return []
    columns = ("tag", "priority", "host", "date", "time", "program", "msg")
    query = [("draw", "1")]
    for index, name in enumerate(columns):
        query.append(("columns[%d][data]" % index, name))
        query.append(("columns[%d][name]" % index, ""))
        query.append(("columns[%d][searchable]" % index, "false" if index == 0 else "true"))
        query.append(("columns[%d][orderable]" % index, "false"))
        query.append(("columns[%d][search][value]" % index, ""))
        query.append(("columns[%d][search][regex]" % index, "false"))
    query.extend([
        ("start", "0"),
        ("length", str(length)),
        ("search[value]", ""),
        ("search[regex]", "false"),
        ("location", LOCATION),
        ("params", match.group(1)),
        ("default_ord", "DESC"),
        ("reload", "0"),
        ("pagination_action", ""),
    ])
    raw = http_post(BASE_URL + "/adm/bulllog/ajax_json_reports/", query, opener=opener, form=True)
    payload = json.loads(raw.decode("utf-8", "replace"))
    return payload.get("data") or []


## Analysis

NUMBERS = re.compile(r"\d+")
QUOTED = re.compile(r"['\"][^'\"]{6,}['\"]")
PROCESS = re.compile(r"^\([^)]{1,60}\):\s*")


def normalize_message(message):
    text = PROCESS.sub("", message or "")
    text = QUOTED.sub("<value>", text)
    text = NUMBERS.sub("N", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:120]


def top_patterns(rows):
    """Return the dominant program and its most frequent message pattern.

    The share that matters is the program share: one faulty service usually
    emits several wording variants of the same error, so counting exact
    messages would split the flood across near-duplicates.
    """
    if not rows:
        return []
    total = len(rows)
    programs = {}
    for row in rows:
        name = row.get("program") or "?"
        programs[name] = programs.get(name, 0) + 1
    program, program_count = max(programs.items(), key=lambda item: item[1])
    subset = [row for row in rows if (row.get("program") or "?") == program]
    patterns = {}
    for row in subset:
        key = normalize_message(row.get("msg") or "")
        patterns[key] = patterns.get(key, 0) + 1
    pattern, count = max(patterns.items(), key=lambda item: item[1])
    return [{
        "program": program,
        "program_share": 100.0 * program_count / total,
        "pattern": pattern,
        "count": count,
        "share": 100.0 * count / len(subset),
    }]


def remediation(program, pattern):
    text = ("%s %s" % (program, pattern)).lower()
    if "ambiguous column name" in text or "tracker-miner" in text or "tracker-extract" in text:
        return ("GNOME Tracker indexer loop: reset the index on the host "
                "(tracker3 reset -s -r for the affected user) or mask "
                "tracker-miner-fs-3 and tracker-extract-3")
    if "no such file or directory" in text and "tmp" in text:
        return ("the process retries a temporary file that no longer exists: "
                "find the producer of the file and stop the loop")
    if "stopped target basic.target" in text or "starting basic.target" in text:
        return ("systemd is cycling through its targets: the host is likely in a "
                "restart loop (check journalctl -b -1, the watchdog and any unit "
                "with Restart=always that keeps failing)")
    if "cups" in text or "printer" in text:
        return "printing subsystem retry loop: check the printer queue on the host"
    if "dhcp" in text and "decline" in text:
        return "duplicate DHCP leases: check the client and the DHCP server"
    return "process retry loop: identify the program on the host and stop the loop"


def state_for(total):
    if total >= CRIT_LOGS:
        return 2
    if total >= WARN_LOGS:
        return 1
    return 0


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
        message += " | solution: " + remediation(top["program"], top["pattern"])
    elif reason_error:
        message += "; reason unavailable: %s" % reason_error
    message = message.replace("\n", " ")
    return "%d %s.%s - %s" % (state, "NethLogger", host["name"], message)


## Check

def run():
    if not BASE_URL:
        print("3 NethLogger.Config - NETHLOGGER_URL is not set")
        return 1
    try:
        apikey = APIKEY or read_secret(APIKEY_FILE)
    except OSError as error:
        print("3 NethLogger.Config - cannot read API key: %s" % error)
        return 1

    start, end = window()
    try:
        hosts = assets_from_stats(fetch_stats(apikey, start, end))
    except Exception as error:
        print("3 NethLogger.API - %s" % error)
        return 1

    selected = hosts[:TOP_HOSTS]
    if not selected:
        print("0 NethLogger.Summary - no assets returned")
        return 0

    opener = None
    reason_error = ""
    if UI_USER and LOCATION and (UI_PASS or os.path.exists(UI_PASS_FILE)):
        try:
            opener = ui_login()
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
                rows = search_messages(opener, host["name"], "err", start, end, SAMPLE_ROWS)
                patterns = top_patterns(rows)
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
           normalize_message("(tracker-extract-3:4231): Tracker-WARNING **: failed"),
           "Tracker-WARNING **: failed")
    expect("normalize collapses numbers",
           normalize_message("error 42 at 15:25:11 on port 8080"),
           "error N at N:N:N on port N")
    expect("normalize replaces quoted paths",
           normalize_message("cannot read '/home/user/a.csv.tmp'"),
           "cannot read <value>")

    rows = [
        {"program": "tracker-miner-fs-3", "msg": "(tracker-extract-3:1): ambiguous column name: ROWID"},
        {"program": "tracker-miner-fs-3", "msg": "(tracker-extract-3:2): ambiguous column name: ROWID"},
        {"program": "cupsd", "msg": "printer offline"},
    ]
    patterns = top_patterns(rows)
    expect("top pattern picks majority", patterns[0]["program"], "tracker-miner-fs-3")
    expect("top pattern count", patterns[0]["count"], 2)
    expect("program share", round(patterns[0]["program_share"]), 67)

    expect("remediation for tracker",
           "Tracker" in remediation("tracker-miner-fs-3", "ambiguous column name: ROWID"), True)
    expect("remediation for systemd cycling",
           "restart loop" in remediation("systemd", "Stopped target basic.target - Basic System."), True)
    expect("remediation fallback",
           remediation("foo", "bar").startswith("process retry loop"), True)

    stats = {"000000": {"display_name": "x", "assets": {
        "a": {"alias": "", "counters": {"err": 5, "total": 5}},
        "b": {"alias": "", "counters": {"info": 50, "total": 50}},
        "c": {"alias": "", "counters": {"total": 0}},
    }}}
    ranked = assets_from_stats(stats)
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
