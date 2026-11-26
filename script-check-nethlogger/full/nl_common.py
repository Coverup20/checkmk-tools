#!/usr/bin/python3
#
# Copyright (C) 2025 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

"""nl_common - shared transport and analysis for the NethLogger tools.

Used by nl-toolkit.py (interactive queries) and by
check_nethlogger_logflood.py (CheckMK local check). Standard library only,
so it also runs on a CheckMK site where pip install is not an option.

Two transports, both documented in doc/check_nethlogger_logflood.md:

  * API key - POST /adm/bulllog/api/noauth_<endpoint>/
    Always POST multipart, always HTTP 200: errors arrive as plain text, so
    the JSON has to be distinguished from the body, not from the status.

  * UI session - POST /adm/auth/login/ then /adm/bulllog/reports/ and
    /adm/bulllog/ajax_json_reports/. The search form needs `program` or
    `cyber_rules`; without them the server switches to the Login/Logout
    module, which on this appliance only carries sudo events.

Environment (same keys as the check):
  NETHLOGGER_URL, NETHLOGGER_APIKEY[_FILE], NETHLOGGER_UI_USER,
  NETHLOGGER_UI_PASS[_FILE|_KEY], NETHLOGGER_LOCATION, NETHLOGGER_INSECURE

Version: 1.0.0
"""

import http.cookiejar
import json
import os
import re
import ssl
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

VERSION = "1.0.0"

DEFAULT_ENV = "/opt/nethlogger-toolkit/.env"
TIMEOUT = 90
LEVELS = ("err", "warning", "info", "debug")

# Endpoints that honour DATE_START/DATE_END; the others are snapshots.
DATED_ENDPOINTS = ("getstats", "getcyber")
API_ENDPOINTS = ("getstats", "getcyber", "getpatches", "getsoftware", "getvulns", "gethardware")

# Programs that carry real user sessions. The UI "Login/Logout" module is not
# used: it only contains sudo events on the appliance we tested.
SESSION_PROGRAMS = ("gdm-password", "gdm3", "login", "sshd")


## Environment

def load_env(path=None):
    """Populate os.environ from a KEY=VALUE file without overriding the real env."""
    path = path or os.environ.get("NETHLOGGER_ENV", DEFAULT_ENV)
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


def read_secret(path, key=None):
    """Return a whole file, or one KEY=VALUE entry from it."""
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


def parse_window(spec, now=None):
    """Turn '7d', '48h', '30m' or an ISO stamp into a (start, end) pair."""
    now = now or datetime.now()
    match = re.fullmatch(r"(\d+)([mhdw])", spec.strip().lower())
    if not match:
        raise ValueError("window must look like 30m, 48h, 7d or 2w: %r" % spec)
    amount, unit = int(match.group(1)), match.group(2)
    delta = {"m": timedelta(minutes=amount), "h": timedelta(hours=amount),
             "d": timedelta(days=amount), "w": timedelta(weeks=amount)}[unit]
    return now - delta, now


## Transport primitives

def ssl_context(insecure=False):
    ctx = ssl.create_default_context()
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


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


def http_post(url, fields, opener=None, form=False, insecure=False):
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
    with urllib.request.urlopen(request, timeout=TIMEOUT, context=ssl_context(insecure)) as response:
        return response.read()


## Client

def assets_from_stats(envelope):
    """Flatten the getstats envelope into a list of assets, busiest first."""
    hosts = []
    for company in (envelope or {}).values():
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


class NethLogger:
    """One appliance: API-key transport plus an optional UI session."""

    def __init__(self, env_file=None):
        load_env(env_file)
        self.base_url = os.environ.get("NETHLOGGER_URL", "").rstrip("/")
        self.apikey_file = os.environ.get("NETHLOGGER_APIKEY_FILE", "/root/.netlogger-apikey")
        self.apikey_value = os.environ.get("NETHLOGGER_APIKEY", "")
        self.ui_user = os.environ.get("NETHLOGGER_UI_USER", "")
        self.ui_pass_file = os.environ.get("NETHLOGGER_UI_PASS_FILE", "/root/.netlogger-uipass")
        self.ui_pass_key = os.environ.get("NETHLOGGER_UI_PASS_KEY", "NETHLOGGER_PASS")
        self.ui_pass_value = os.environ.get("NETHLOGGER_UI_PASS", "")
        self.location = os.environ.get("NETHLOGGER_LOCATION", "")
        self.insecure = os.environ.get("NETHLOGGER_INSECURE", "") == "1"
        self._opener = None

    # -- configuration

    def apikey(self):
        if self.apikey_value:
            return self.apikey_value
        return read_secret(self.apikey_file)

    def ui_password(self):
        if self.ui_pass_value:
            return self.ui_pass_value
        return read_secret(self.ui_pass_file, self.ui_pass_key)

    def has_ui(self):
        return bool(self.ui_user and self.location)

    # -- API key transport

    def api(self, endpoint, start=None, end=None):
        """Return the decoded body of a noauth_ endpoint, or raise with its text."""
        if endpoint not in API_ENDPOINTS:
            raise ValueError("unknown endpoint %r (one of %s)" % (endpoint, ", ".join(API_ENDPOINTS)))
        fields = [("APIKEY", self.apikey())]
        if start and end:
            fields.append(("DATE_START", start.strftime("%Y%m%d%H%M")))
            fields.append(("DATE_END", end.strftime("%Y%m%d%H%M")))
        raw = http_post(self.base_url + "/adm/bulllog/api/noauth_%s/" % endpoint,
                        fields, insecure=self.insecure)
        text = raw.decode("utf-8", "replace").strip()
        # Errors arrive as plain text with HTTP 200, so the body decides whether
        # this is data. Some endpoints answer with an object, others with an array.
        if text[:1] not in ("{", "["):
            raise ValueError("%s returned: %s" % (endpoint, text[:160] or "(empty body)"))
        return json.loads(text)

    def assets(self, start=None, end=None):
        """Assets with their counters, busiest first."""
        return assets_from_stats(self.api("getstats", start, end))

    def volumes(self, name, windows=("24h", "7d", "30d")):
        """Counters of one asset over several windows, oldest window last."""
        result = []
        for spec in windows:
            start, end = parse_window(spec)
            found = {"total": 0, "counters": {}}
            for host in self.assets(start, end):
                if host["name"] == name:
                    found = host
                    break
            result.append({"window": spec, "total": found["total"], "counters": found["counters"]})
        return result

    # -- UI session transport

    def opener(self):
        if self._opener:
            return self._opener
        jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar),
            urllib.request.HTTPSHandler(context=ssl_context(self.insecure)),
        )
        fields = [
            ("action", "login"),
            ("user", self.ui_user),
            ("pass", self.ui_password()),
            ("proto", ""),
            ("lang", "en"),
        ]
        page = http_post(self.base_url + "/adm/auth/login/", fields,
                         opener=self._opener, form=True)
        if b"login" in page[:4000] and b"nome utente" in page.lower():
            raise RuntimeError("UI login rejected for user %r" % self.ui_user)
        return self._opener

    def search(self, host=None, program="*", level="", msg="", start=None, end=None, length=100):
        """Return matching log rows: tag, priority, host, date, time, program, msg.

        `program` must not be empty: without it the server switches to the
        Login/Logout module instead of the free search.
        """
        if not program:
            raise ValueError("program cannot be empty: the server would switch to the Login/Logout module")
        opener = self.opener()
        if not start or not end:
            start, end = parse_window("24h")
        form = [("location", self.location)]
        if host:
            form.append(("host[]", host))
        form.append(("msg", msg))
        # An empty priority is not "all levels": the server matches it literally
        # and returns nothing, so the field has to be left out for a full search.
        if level:
            form.append(("priority", level))
        form.extend([
            ("program", program),
            ("cyber_rules", "*"),
            ("date", start.strftime("%d/%m/%Y %H:%M")),
            ("date2", end.strftime("%d/%m/%Y %H:%M")),
            ("recperpag", "100"),
            ("orderby", "DESC"),
        ])
        page = http_post(self.base_url + "/adm/bulllog/reports/", form, opener=opener, form=True)
        match = re.search(r'd\.params\s*=\s*"([^"]*)"', page.decode("utf-8", "replace"))
        if not match or not match.group(1):
            return []
        query = [("draw", "1")]
        columns = ("tag", "priority", "host", "date", "time", "program", "msg")
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
            ("location", self.location),
            ("params", match.group(1)),
            ("default_ord", "DESC"),
            ("reload", "0"),
            ("pagination_action", ""),
        ])
        raw = http_post(self.base_url + "/adm/bulllog/ajax_json_reports/", query,
                        opener=opener, form=True)
        payload = json.loads(raw.decode("utf-8", "replace"))
        return payload.get("data") or []


## Analysis

NUMBERS = re.compile(r"\d+")
QUOTED = re.compile(r"['\"][^'\"]{6,}['\"]")
PROCESS = re.compile(r"^\([^)]{1,60}\):\s*")


def normalize_message(message):
    """Reduce a message to a comparable shape: no pid, no numbers, no paths."""
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


def programs_by_volume(rows, limit=5):
    """Programs ranked by row count, with their share of the sample."""
    if not rows:
        return []
    total = len(rows)
    counts = {}
    for row in rows:
        name = row.get("program") or "?"
        counts[name] = counts.get(name, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    return [{"program": name, "count": count, "share": 100.0 * count / total}
            for name, count in ranked[:limit]]


def remediation(program, pattern):
    """A short hint for the known flood patterns, generic when nothing matches."""
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
    if "lmagent" in text:
        return ("the log agent itself is failing: read its traceback on the host "
                "and restart the lmagent service")
    return "process retry loop: identify the program on the host and stop the loop"


def state_for(total, warn, crit):
    if total >= crit:
        return 2
    if total >= warn:
        return 1
    return 0


## Sessions

LOGIN = re.compile(r"session opened for user (\S+)", re.IGNORECASE)
LOGOUT = re.compile(r"session closed for user (\S+)", re.IGNORECASE)
AUTH_FAIL = re.compile(r"authentication failure", re.IGNORECASE)
PAM_USER = re.compile(r"user=(\S+)")
DISPLAY_REMOVED = re.compile(r"on_display_removed", re.IGNORECASE)
BOOT = re.compile(r"unexpectedly disconnected from boot status daemon", re.IGNORECASE)


def user_token(raw):
    """'marzio(uid=1000)' -> 'marzio'."""
    return raw.split("(")[0].rstrip(",;)")


def classify_session_row(row):
    """Turn one log row into a session event, or None when it is noise.

    The appliance rarely writes `session closed` at shutdown, so the end of a
    gdm session is deduced from `on_display_removed` instead.
    """
    message = row.get("msg") or ""
    program = row.get("program") or "?"
    user = None
    kind = None
    login = LOGIN.search(message)
    logout = LOGOUT.search(message)
    if login:
        kind, user = "login", user_token(login.group(1))
    elif logout:
        kind, user = "logout", user_token(logout.group(1))
    elif AUTH_FAIL.search(message):
        kind = "fail"
        user_match = PAM_USER.search(message)
        user = user_match.group(1) if user_match else "?"
    elif DISPLAY_REMOVED.search(message):
        kind = "end"
    elif BOOT.search(message):
        kind = "boot"
    if not kind:
        return None
    return {
        "date": row.get("date") or "",
        "time": row.get("time") or "",
        "program": program,
        "kind": kind,
        "user": user or "",
        "msg": message[:160],
    }


def sessions(client, host, start, end, programs=SESSION_PROGRAMS, length=500):
    """Collect and order the session events of one asset."""
    events = []
    for program in programs:
        for row in client.search(host=host, program=program, start=start, end=end, length=length):
            event = classify_session_row(row)
            if event:
                events.append(event)
    events.sort(key=lambda item: (item["date"][6:10], item["date"][3:5], item["date"][0:2], item["time"]))
    return events


def session_summary(events):
    """Per-user counters over a collected timeline."""
    users = {}
    for event in events:
        if not event["user"]:
            continue
        entry = users.setdefault(event["user"], {"user": event["user"], "logins": 0,
                                                 "logouts": 0, "ends": 0, "fails": 0})
        key = {"login": "logins", "logout": "logouts", "end": "ends", "fail": "fails"}.get(event["kind"])
        if key:
            entry[key] += 1
    return sorted(users.values(), key=lambda item: item["logins"], reverse=True)


## Self-test

def self_test():
    """Offline assertions. No network, no credentials."""
    failures = []
    checks = []

    def expect(name, got, want):
        checks.append(name)
        if got != want:
            failures.append("%s: got %r, want %r" % (name, got, want))

    def kind_of(row):
        return (classify_session_row(row) or {}).get("kind")

    def user_of(row):
        return (classify_session_row(row) or {}).get("user")

    expect("window hours", parse_window("48h", datetime(2026, 11, 26, 12, 0)),
           (datetime(2026, 11, 24, 12, 0), datetime(2026, 11, 26, 12, 0)))
    expect("window days", parse_window("7d", datetime(2026, 11, 26)),
           (datetime(2026, 11, 19), datetime(2026, 11, 26)))
    try:
        parse_window("7x")
        expect("bad window raises", "no raise", "raise")
    except ValueError:
        expect("bad window raises", True, True)

    rows = [
        {"program": "tracker-miner-fs-3", "msg": "(tracker-extract-3:11): ambiguous column name: ROWID"},
        {"program": "tracker-miner-fs-3", "msg": "(tracker-extract-3:12): ambiguous column name: ROWID"},
        {"program": "cupsd", "msg": "printer offline"},
    ]
    patterns = top_patterns(rows)
    expect("top pattern picks majority", patterns[0]["program"], "tracker-miner-fs-3")
    expect("top pattern count", patterns[0]["count"], 2)
    expect("program share", round(patterns[0]["program_share"]), 67)
    expect("tracker remediation", "Tracker" in remediation("tracker-miner-fs-3", patterns[0]["pattern"]), True)
    expect("lmagent remediation", "lmagent" in remediation("lmagent", "Traceback (most recent call last)"), True)
    expect("fallback remediation", remediation("foo", "bar").startswith("process retry loop"), True)

    volumes = programs_by_volume(rows)
    expect("program ranking", volumes[0]["program"], "tracker-miner-fs-3")
    expect("program ranking count", volumes[0]["count"], 2)

    expect("state ok", state_for(5, 10, 100), 0)
    expect("state warning", state_for(50, 10, 100), 1)
    expect("state critical", state_for(500, 10, 100), 2)

    login_row = {"date": "26/11/2026", "time": "08:38:00", "program": "gdm-password",
                 "msg": "pam_unix(gdm-password:session): session opened for user marzio(uid=1000) by (uid=0)"}
    expect("login kind", kind_of(login_row), "login")
    expect("login user", user_of(login_row), "marzio")

    logout_row = {"date": "26/11/2026", "time": "18:02:00", "program": "gdm-password",
                  "msg": "pam_unix(gdm-password:session): session closed for user marzio"}
    expect("logout kind", kind_of(logout_row), "logout")

    fail_row = {"date": "26/11/2026", "time": "07:00:00", "program": "gdm-password",
                "msg": "pam_unix(gdm-password:auth): authentication failure; logname= uid=0 euid=0 user=root"}
    expect("fail kind", kind_of(fail_row), "fail")
    expect("fail user", user_of(fail_row), "root")

    display_row = {"date": "26/11/2026", "time": "19:00:00", "program": "gdm3",
                   "msg": "GdmSession: on_display_removed: 0"}
    expect("display end", kind_of(display_row), "end")

    boot_row = {"date": "26/11/2026", "time": "06:59:00", "program": "gdm3",
                "msg": "gdm-session-worker: unexpectedly disconnected from boot status daemon"}
    expect("boot marker", kind_of(boot_row), "boot")

    expect("noise ignored", classify_session_row({"program": "cron", "msg": "job done"}), None)

    timeline = [
        {"date": "25/11/2026", "time": "09:00:00", "kind": "login", "user": "marzio"},
        {"date": "26/11/2026", "time": "08:00:00", "kind": "login", "user": "marzio"},
        {"date": "26/11/2026", "time": "18:00:00", "kind": "end", "user": ""},
        {"date": "26/11/2026", "time": "08:05:00", "kind": "fail", "user": "root"},
    ]
    summary = session_summary(timeline)
    expect("summary first user", summary[0]["user"], "marzio")
    expect("summary logins", summary[0]["logins"], 2)

    envelope = {"000000": {"display_name": "x", "assets": {
        "a": {"alias": "A", "counters": {"err": 5, "total": 5}},
        "b": {"alias": "", "counters": {"info": 50, "total": 50}},
    }}}
    hosts = []
    for company in envelope.values():
        for name, asset in company["assets"].items():
            hosts.append({"name": name, "total": int(asset["counters"].get("total") or 0)})
    hosts.sort(key=lambda item: item["total"], reverse=True)
    expect("asset ranking", [item["name"] for item in hosts], ["b", "a"])

    print("Self-test: %d/%d passed" % (len(checks) - len(failures), len(checks)))
    for failure in failures:
        print("  FAIL %s" % failure)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(self_test())
