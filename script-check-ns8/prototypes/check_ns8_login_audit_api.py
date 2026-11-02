#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

# Check NS8 authentication evidence (logins and logouts), 100% REST-only:
# the only data source is the Loki HTTP API of the loki1 module.
#
# Why Loki and not journald:
# on the NS8 node tested, /var/log/journal does not exist, so journald runs in
# volatile mode and keeps its records in RAM only. The node had been up for
# three weeks while `journalctl` could only show the current day: once the RAM
# buffer fills, older records are dropped. A login audit built on journald
# would therefore silently lose most of its evidence and still look healthy.
# The loki1 module receives the full journal (job="loki.source.journal.journal")
# with retention_period 365d, and exposes a dedicated category="security"
# stream. That stream is the authoritative source, and this check reads it.
#
# What the security stream actually contains (counted over 25 days on the
# reference node), and which half of a session each line gives us:
#   sshd-session    Accepted <method> for <user> from <ip>          login
#   sshd-session    pam_unix(sshd:session): session opened/closed   login+logout
#   sshd-session    Disconnected from / Received disconnect         logout
#   systemd-logind  New session N / Session N logged out / Removed  login+logout
#   api-server      [AUTH] login-ok user=X source=IP 2fa=false      login only
#   api-server      [AUTH] ... authentication failed ... WRONGPASS  failure
#   runuser         pam_unix(runuser-l:session) for a module user   service
#
# Two traps this check exists to avoid:
#   1. Failed interface logins are NOT called "login-fail". They appear as
#      "[AUTH] redis authentication failed for user X: WRONGPASS". A check
#      looking for "login-fail" finds zero and reports "no failures": a lie.
#   2. On the reference node a single service account (the read-only API user
#      polled by monitoring) produced 4443 of 4443 interface logins, while the
#      only human login in the whole period was one. Without separating service
#      accounts from people, polling noise hides every real access.
#
# Emitted services:
#   NS8.Login.SSH      [DE.CM-01/DE.CM-03] shell access to the node
#   NS8.Login.UI       [DE.CM-01/DE.CM-03] NS8 cluster interface access
#   NS8.Login.Failed   [DE.CM-01/PR.AA-05] rejected authentication attempts
#   NS8.Login.Coverage [DE.CM-01]          is the evidence source trustworthy
#
# Compatible with Python 3.9+ (Rocky Linux 9). No subprocess, no classes.

import base64
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

VERSION = "1.0.0"

SVC_SSH = "NS8.Login.SSH"
SVC_UI = "NS8.Login.UI"
SVC_FAILED = "NS8.Login.Failed"
SVC_COVERAGE = "NS8.Login.Coverage"

CTRL_SSH = "DE.CM-01"
CTRL_UI = "DE.CM-01"
CTRL_FAILED = "PR.AA-05"
CTRL_COVERAGE = "DE.CM-01"

# The loki1 module writes its generated credentials and port here.
LOKI_ENV_FILE = os.environ.get(
    "CHECK_NS8_LOGIN_LOKI_ENV", "/home/loki1/.config/state/environment"
)
LOKI_HOST = os.environ.get("CHECK_NS8_LOGIN_LOKI_HOST", "127.0.0.1")
# Explicit overrides win over the module environment file.
LOKI_PORT_OVERRIDE = os.environ.get("CHECK_NS8_LOGIN_LOKI_PORT", "")
LOKI_USER_OVERRIDE = os.environ.get("CHECK_NS8_LOGIN_LOKI_USER", "")
LOKI_PASSWORD_OVERRIDE = os.environ.get("CHECK_NS8_LOGIN_LOKI_PASSWORD", "")

LOKI_SELECTOR = os.environ.get("CHECK_NS8_LOGIN_SELECTOR", '{category="security"}')
LOKI_TIMEOUT = float(os.environ.get("CHECK_NS8_LOGIN_TIMEOUT", "25"))
LOKI_MAX_LINES = int(os.environ.get("CHECK_NS8_LOGIN_MAX_LINES", "5000"))

# Reporting window for the three activity services.
WINDOW_HOURS = int(os.environ.get("CHECK_NS8_LOGIN_WINDOW_HOURS", "24"))

# Accounts that are machines, not people. They are counted and reported, but
# never mixed with human access, and never drive the state on their own.
DEFAULT_SERVICE_ACCOUNTS = "claude-ro"
SERVICE_ACCOUNTS = set(
    name.strip()
    for name in os.environ.get(
        "CHECK_NS8_LOGIN_SERVICE_ACCOUNTS", DEFAULT_SERVICE_ACCOUNTS
    ).split(",")
    if name.strip()
)

# PROVISIONAL thresholds. "Without undue delay" has not been turned into a
# number by the organisation yet, and neither has "how many rejected logins are
# normal here". These defaults are a placeholder, overridable by environment,
# and must not be presented to a customer as a policy.
FAILED_WARN = int(os.environ.get("CHECK_NS8_LOGIN_FAILED_WARN", "1"))
FAILED_CRIT = int(os.environ.get("CHECK_NS8_LOGIN_FAILED_CRIT", "10"))

# If the newest security event is older than this, the pipeline is suspect:
# a quiet node and a broken log shipper look identical from here.
STREAM_STALE_HOURS = int(os.environ.get("CHECK_NS8_LOGIN_STALE_HOURS", "25"))

# How far back the coverage service looks to prove the stream has real history.
HISTORY_PROBE_DAYS = int(os.environ.get("CHECK_NS8_LOGIN_HISTORY_DAYS", "7"))

LOCAL_SECTION = "<<<local:sep(0)>>>"

# --- message patterns -------------------------------------------------------

RE_SSH_ACCEPTED = re.compile(
    r"^Accepted (?P<method>\S+) for (?P<user>\S+) from (?P<addr>\S+)"
)
RE_SSH_FAILED = re.compile(
    r"^Failed (?P<method>\S+) for (?:invalid user )?(?P<user>\S+) from (?P<addr>\S+)"
)
RE_SSH_INVALID = re.compile(r"^Invalid user (?P<user>\S*) from (?P<addr>\S+)")
RE_PAM_SESSION = re.compile(
    r"^pam_unix\((?P<svc>[^:]+):session\): session (?P<verb>opened|closed) for user (?P<user>[^ (]+)"
)
RE_LOGIND_NEW = re.compile(r"^New session (?P<sid>\S+?) of user (?P<user>\S+?)\.?$")
RE_LOGIND_OUT = re.compile(r"^Session (?P<sid>\S+?) logged out")
RE_LOGIND_REMOVED = re.compile(r"^Removed session (?P<sid>\S+?)\.?$")
RE_UI_OK = re.compile(
    r"^\[AUTH\] login-ok user=(?P<user>\S+) source=(?P<addr>\S+)(?: (?P<fa>\S*fa)=(?P<fav>\S+))?"
)
RE_UI_FAIL = re.compile(
    r"^\[AUTH\] .*?(?:authentication failed|login-fail|invalid credentials|WRONGPASS)",
    re.IGNORECASE,
)
RE_UI_FAIL_USER = re.compile(r"for user (?P<user>[^\s:]+)")

# A rejected login and a platform fault arrive on the same log line shape but
# mean opposite things: "somebody used the wrong password" is a security
# signal, "the system could not authenticate anybody" is an availability
# fault. Counting them together lets a real brute-force attempt hide inside
# infrastructure noise - which happened here: an api-server Redis exhaustion
# was being reported as a rejected login attempt by the monitoring account.
RE_INFRA_FAILURE = re.compile(
    r"max number of clients|conn is in a bad state|connection refused|"
    r"i/o timeout|no such host|broken pipe",
    re.IGNORECASE,
)


def local_line(state, service, perfdata, message):
    """Build one CheckMK local-check line: state, service, metrics (or -), detail."""
    return "%d %s %s %s" % (state, service, perfdata or "-", message)


def read_env_file(path):
    """Parse a KEY=VALUE environment file into a dict. Missing file -> {}."""
    values = {}
    try:
        with open(path, encoding="utf-8") as handle:
            for raw in handle:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
    except OSError:
        return {}
    return values


def loki_config():
    """Resolve Loki base URL and credentials. Returns (base_url, user, pw, err)."""
    env = read_env_file(LOKI_ENV_FILE)
    port = LOKI_PORT_OVERRIDE or env.get("LOKI_HTTP_PORT") or env.get("TCP_PORT") or ""
    user = LOKI_USER_OVERRIDE or env.get("LOKI_API_AUTH_USERNAME") or ""
    password = LOKI_PASSWORD_OVERRIDE or env.get("LOKI_API_AUTH_PASSWORD") or ""
    if not port:
        return "", "", "", "loki-module-not-found"
    if not user or not password:
        # An unauthenticated Loki is possible; try anyway but say so.
        return "http://%s:%s" % (LOKI_HOST, port), user, password, "no-credentials"
    return "http://%s:%s" % (LOKI_HOST, port), user, password, ""


def loki_get(base_url, user, password, path, params, timeout=None):
    """GET a Loki API path with basic auth. Returns (parsed_json, error_string)."""
    url = "%s%s?%s" % (base_url.rstrip("/"), path, urllib.parse.urlencode(params))
    req = urllib.request.Request(url, method="GET")
    if user and password:
        token = base64.b64encode(
            ("%s:%s" % (user, password)).encode("utf-8")
        ).decode("ascii")
        req.add_header("Authorization", "Basic " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout or LOKI_TIMEOUT) as resp:
            return json.load(resp), ""
    except urllib.error.HTTPError as exc:
        return None, "loki-http-%d" % exc.code
    except (urllib.error.URLError, ValueError, OSError) as exc:
        return None, "loki-unreachable (%s)" % type(exc).__name__


def loki_query_range(
    base_url, user, password, query, start_dt, end_dt, limit=None, direction="backward"
):
    """Run a Loki query_range. Returns (list_of_raw_lines, error_string).

    `direction` matters when `limit` is small: "backward" returns the newest
    records, "forward" the oldest. Asking backward for one line and calling it
    the start of history is how this check first reported 0 days of history on
    a stream that held 24 days of it.
    """
    params = {
        "query": query,
        "start": "%d" % int(start_dt.timestamp() * 1e9),
        "end": "%d" % int(end_dt.timestamp() * 1e9),
        "limit": str(limit or LOKI_MAX_LINES),
        "direction": direction,
    }
    payload, err = loki_get(base_url, user, password, "/loki/api/v1/query_range", params)
    if err:
        return [], err
    if not isinstance(payload, dict) or payload.get("status") != "success":
        return [], "loki-bad-response"
    result = payload.get("data", {}).get("result", [])
    lines = []
    for stream in result:
        for value in stream.get("values", []):
            if len(value) >= 2:
                lines.append((value[0], value[1]))
    return lines, ""


def parse_journal_line(raw):
    """Loki stores each journal record as a JSON object. Returns (ident, message)."""
    try:
        record = json.loads(raw)
    except (ValueError, TypeError):
        return "", str(raw)
    if not isinstance(record, dict):
        return "", str(raw)
    return record.get("SYSLOG_IDENTIFIER", ""), record.get("MESSAGE", "") or ""


def is_service_account(user):
    """True for machine accounts that must not be counted as human access.

    Besides the configured names, NS8 authenticates its own modules to the
    cluster API as "module/<id>" (a freshly bound module starts doing this on
    its own). Those are machines by construction, and counting them as people
    inflates "human logins" with nobody having touched a keyboard.
    """
    if not user:
        return False
    if user in SERVICE_ACCOUNTS:
        return True
    return user.startswith("module/")


def classify_event(identifier, message):
    """Map one journal line to an audit event, or None if it is not one.

    Returns a dict with: channel (ssh|ui|module), kind (login|logout|failure),
    user, addr, and extra flags. Deliberately conservative: anything not
    recognised returns None rather than being guessed into a category.
    """
    msg = (message or "").strip()
    if not msg:
        return None

    # --- NS8 cluster interface ---
    if identifier == "api-server":
        match = RE_UI_OK.match(msg)
        if match:
            return {
                "channel": "ui",
                "kind": "login",
                "user": match.group("user"),
                "addr": match.group("addr"),
                "mfa": (match.group("fav") or "").lower() in ("true", "yes", "1"),
            }
        if RE_UI_FAIL.match(msg):
            who = RE_UI_FAIL_USER.search(msg)
            return {
                "channel": "ui",
                "kind": "infra_failure" if RE_INFRA_FAILURE.search(msg) else "failure",
                "user": who.group("user") if who else "",
                "addr": "",
            }
        return None

    # --- module service accounts opening a shell session (runuser) ---
    match = RE_PAM_SESSION.match(msg)
    if match:
        svc = match.group("svc")
        channel = "ssh" if svc == "sshd" else "module"
        return {
            "channel": channel,
            "kind": "login" if match.group("verb") == "opened" else "logout",
            "user": match.group("user"),
            "addr": "",
            "via": "pam",
        }

    # --- sshd ---
    match = RE_SSH_ACCEPTED.match(msg)
    if match:
        return {
            "channel": "ssh",
            "kind": "login",
            "user": match.group("user"),
            "addr": match.group("addr"),
            "method": match.group("method"),
            "via": "sshd",
        }
    match = RE_SSH_FAILED.match(msg)
    if match:
        return {
            "channel": "ssh",
            "kind": "failure",
            "user": match.group("user"),
            "addr": match.group("addr"),
            "via": "sshd",
        }
    match = RE_SSH_INVALID.match(msg)
    if match:
        return {
            "channel": "ssh",
            "kind": "failure",
            "user": match.group("user") or "(unknown)",
            "addr": match.group("addr"),
            "via": "sshd",
        }

    # --- logind: the only source that pairs a session id with its logout ---
    if identifier == "systemd-logind":
        match = RE_LOGIND_NEW.match(msg)
        if match:
            return {
                "channel": "ssh",
                "kind": "login",
                "user": match.group("user"),
                "addr": "",
                "via": "logind",
                "session": match.group("sid"),
            }
        # logind announces a logout twice: "Session N logged out. Waiting for
        # processes to exit." and then "Removed session N.". Only the second
        # one is final, so only that one is counted; the first is still
        # classified (it is a real audit record) but marked so the summary can
        # skip it, otherwise every session logs out twice.
        match = RE_LOGIND_REMOVED.match(msg)
        if match:
            return {
                "channel": "ssh",
                "kind": "logout",
                "user": "",
                "addr": "",
                "via": "logind",
                "session": match.group("sid"),
            }
        match = RE_LOGIND_OUT.match(msg)
        if match:
            return {
                "channel": "ssh",
                "kind": "logout",
                "user": "",
                "addr": "",
                "via": "logind-pending",
                "session": match.group("sid"),
            }
    return None


def summarize(lines):
    """Turn raw Loki lines into per-channel counters. Pure, so it is testable."""
    summary = {
        "parsed": 0,
        "recognised": 0,
        "ssh": {
            "logins": 0,
            "logouts": 0,
            "users": {},
            "addrs": {},
            "root_logins": 0,
            "methods": {},
        },
        "ui": {
            "logins": 0,
            "human_logins": 0,
            "service_logins": 0,
            "users": {},
            "addrs": {},
            "no_mfa": 0,
        },
        "module": {"logins": 0, "logouts": 0, "users": {}},
        "failures": {"total": 0, "ssh": 0, "ui": 0, "users": {}, "addrs": {}},
        "infra_failures": {"total": 0, "users": {}},
    }

    for _ts, raw in lines:
        summary["parsed"] += 1
        identifier, message = parse_journal_line(raw)
        event = classify_event(identifier, message)
        if not event:
            continue
        summary["recognised"] += 1
        channel = event["channel"]
        kind = event["kind"]
        user = event.get("user") or ""
        addr = event.get("addr") or ""

        if kind == "infra_failure":
            summary["infra_failures"]["total"] += 1
            if user:
                summary["infra_failures"]["users"][user] = (
                    summary["infra_failures"]["users"].get(user, 0) + 1
                )
            continue

        if kind == "failure":
            summary["failures"]["total"] += 1
            if channel in ("ssh", "ui"):
                summary["failures"][channel] += 1
            if user:
                summary["failures"]["users"][user] = (
                    summary["failures"]["users"].get(user, 0) + 1
                )
            if addr:
                summary["failures"]["addrs"][addr] = (
                    summary["failures"]["addrs"].get(addr, 0) + 1
                )
            continue

        if channel == "ssh":
            bucket = summary["ssh"]
            if kind == "login":
                # sshd, pam and logind all announce the same login. Count only
                # the sshd line (it carries user, method and source), otherwise
                # one real session is counted three times.
                if event.get("via") not in ("logind", "pam"):
                    bucket["logins"] += 1
                    if user:
                        bucket["users"][user] = bucket["users"].get(user, 0) + 1
                        if user == "root":
                            bucket["root_logins"] += 1
                    if addr:
                        bucket["addrs"][addr] = bucket["addrs"].get(addr, 0) + 1
                    method = event.get("method")
                    if method:
                        bucket["methods"][method] = bucket["methods"].get(method, 0) + 1
            else:
                # Same reasoning in reverse: logind "Removed session" is the
                # canonical logout, pam "session closed" duplicates it, and
                # "Session N logged out" duplicates it again.
                if event.get("via") == "logind" and event.get("session"):
                    bucket["logouts"] += 1
        elif channel == "ui":
            bucket = summary["ui"]
            bucket["logins"] += 1
            if is_service_account(user):
                bucket["service_logins"] += 1
            else:
                bucket["human_logins"] += 1
            if user:
                bucket["users"][user] = bucket["users"].get(user, 0) + 1
            if addr:
                bucket["addrs"][addr] = bucket["addrs"].get(addr, 0) + 1
            if not event.get("mfa"):
                bucket["no_mfa"] += 1
        elif channel == "module":
            bucket = summary["module"]
            if kind == "login":
                bucket["logins"] += 1
                if user:
                    bucket["users"][user] = bucket["users"].get(user, 0) + 1
            else:
                bucket["logouts"] += 1
    return summary


def top_names(counter, limit=3):
    """Render the busiest few entries of a {name: count} dict, for messages."""
    if not counter:
        return "none"
    ordered = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    return ", ".join("%s(%d)" % (name, count) for name, count in ordered)


def evaluate_ssh(summary, window_hours):
    """Shell access to the node. Reports, and stays quiet unless blind."""
    ssh = summary["ssh"]
    perf = "logins=%d|logouts=%d|root_logins=%d|distinct_users=%d|distinct_sources=%d" % (
        ssh["logins"],
        ssh["logouts"],
        ssh["root_logins"],
        len(ssh["users"]),
        len(ssh["addrs"]),
    )
    if ssh["logins"] == 0 and ssh["logouts"] == 0:
        return (
            0,
            perf,
            "OK [%s]: no shell logins in the last %dh" % (CTRL_SSH, window_hours),
        )
    unmatched = ssh["logins"] - ssh["logouts"]
    tail = ""
    if unmatched > 0:
        # Not an anomaly by itself: a session still open, or one opened before
        # the window started, both look like this. Say so instead of implying
        # that something is wrong.
        tail = ", %d without a logout in window (still open, or opened earlier)" % unmatched
    elif unmatched < 0:
        tail = ", %d logouts belong to sessions opened before the window" % (-unmatched)
    return (
        0,
        perf,
        "OK [%s]: %d shell logins / %d logouts in %dh; users %s; sources %s%s"
        % (
            CTRL_SSH,
            ssh["logins"],
            ssh["logouts"],
            window_hours,
            top_names(ssh["users"]),
            top_names(ssh["addrs"]),
            tail,
        ),
    )


def evaluate_ui(summary, window_hours):
    """NS8 interface access, with people and machines kept apart."""
    ui = summary["ui"]
    perf = "logins=%d|human_logins=%d|service_logins=%d|distinct_users=%d|without_mfa=%d" % (
        ui["logins"],
        ui["human_logins"],
        ui["service_logins"],
        len(ui["users"]),
        ui["no_mfa"],
    )
    if ui["logins"] == 0:
        return (
            0,
            perf,
            "OK [%s]: no interface logins in the last %dh" % (CTRL_UI, window_hours),
        )
    human_part = "%d human" % ui["human_logins"] if ui["human_logins"] else "no human"
    detail = (
        "%d interface logins in %dh (%s, %d by service accounts); users %s"
        % (
            ui["logins"],
            window_hours,
            human_part,
            ui["service_logins"],
            top_names(ui["users"]),
        )
    )
    # The interface emits no logout event at all, so never let a reader assume
    # these sessions were closed.
    detail += "; no logout events exist for this channel"
    if ui["no_mfa"] >= ui["logins"]:
        return (
            1,
            perf,
            "WARNING [%s]: %s; every login was without a second factor"
            % (CTRL_UI, detail),
        )
    if ui["no_mfa"]:
        return (
            1,
            perf,
            "WARNING [%s]: %s; %d without a second factor"
            % (CTRL_UI, detail, ui["no_mfa"]),
        )
    return (0, perf, "OK [%s]: %s" % (CTRL_UI, detail))


def evaluate_failed(summary, window_hours):
    """Rejected authentication attempts, from every channel at once."""
    failures = summary["failures"]
    infra = summary.get("infra_failures", {"total": 0, "users": {}})
    total = failures["total"]
    perf = (
        "failures=%d|ssh_failures=%d|ui_failures=%d|distinct_sources=%d|"
        "platform_faults=%d"
        % (
            total,
            failures["ssh"],
            failures["ui"],
            len(failures["addrs"]),
            infra["total"],
        )
    )
    # Platform faults are never counted as rejected credentials, but they are
    # never hidden either: they say the audit channel itself was degraded.
    infra_note = ""
    if infra["total"]:
        infra_note = (
            "; %d authentication(s) failed for a platform fault, not a bad "
            "password (accounts %s)" % (infra["total"], top_names(infra["users"]))
        )
    if total == 0:
        return (
            0,
            perf,
            "OK [%s]: no rejected authentication attempts in the last %dh%s"
            % (CTRL_FAILED, window_hours, infra_note),
        )
    detail = "%d rejected attempts in %dh (ssh %d, interface %d); accounts %s; sources %s" % (
        total,
        window_hours,
        failures["ssh"],
        failures["ui"],
        top_names(failures["users"]),
        top_names(failures["addrs"]),
    )
    if total >= FAILED_CRIT:
        return (2, perf, "CRITICAL [%s]: %s (threshold %d, PROVISIONAL)%s"
                % (CTRL_FAILED, detail, FAILED_CRIT, infra_note))
    if total >= FAILED_WARN:
        return (1, perf, "WARNING [%s]: %s (threshold %d, PROVISIONAL)%s"
                % (CTRL_FAILED, detail, FAILED_WARN, infra_note))
    return (0, perf, "OK [%s]: %s%s" % (CTRL_FAILED, detail, infra_note))


def evaluate_coverage(
    reachable,
    err,
    recognised,
    parsed,
    newest_age_hours,
    history_days,
    journal_persistent,
):
    """The guard: can this evidence be trusted at all?

    A quiet node and a dead log pipeline produce the same empty result, so an
    empty answer must never be reported as OK.
    """
    perf = "recognised_events=%d|parsed_lines=%d|history_days=%d" % (
        recognised,
        parsed,
        history_days,
    )
    if not reachable:
        return (
            3,
            perf,
            "UNKNOWN [%s]: the Loki audit source is unreachable (%s) - login "
            "evidence cannot be verified, this is not the same as 'no logins'"
            % (CTRL_COVERAGE, err or "unknown error"),
        )
    if parsed == 0:
        return (
            3,
            perf,
            "UNKNOWN [%s]: the security stream returned no records at all - "
            "a silent log shipper looks exactly like a quiet node" % CTRL_COVERAGE,
        )
    notes = []
    state = 0
    if newest_age_hours is not None and newest_age_hours > STREAM_STALE_HOURS:
        state = max(state, 3)
        notes.append(
            "newest record is %.1fh old (over %dh): the pipeline is probably stopped"
            % (newest_age_hours, STREAM_STALE_HOURS)
        )
    if recognised == 0:
        state = max(state, 3)
        notes.append(
            "%d records were read but none matched a known authentication "
            "pattern - the log format may have changed" % parsed
        )
    if history_days < 1:
        state = max(state, 1)
        notes.append(
            "less than a day of history is queryable, so trends and retention "
            "claims are not yet supported by data"
        )
    if not journal_persistent:
        notes.append(
            "journald on this node is volatile (no /var/log/journal), so Loki "
            "is the only durable copy of this evidence"
        )
    label = {0: "OK", 1: "WARNING", 2: "CRITICAL", 3: "UNKNOWN"}[state]
    # history_days is a floor, not a measurement: the probe only looks back
    # HISTORY_PROBE_DAYS, so a stream holding a year still reports the probe
    # window. Say "at least" rather than implying the retention was measured.
    base = (
        "%s [%s]: audit source reachable, %d/%d records recognised, at least %d "
        "days of history (probe window %dd)"
        % (
            label,
            CTRL_COVERAGE,
            recognised,
            parsed,
            history_days,
            HISTORY_PROBE_DAYS,
        )
    )
    if notes:
        base += "; " + "; ".join(notes)
    return (state, perf, base)


def journal_is_persistent():
    """A node with no /var/log/journal keeps its journal in RAM only."""
    return os.path.isdir("/var/log/journal")


def measure_history_days(base_url, user, password, now):
    """How far back the security stream actually goes, capped at the probe."""
    start = now - datetime.timedelta(days=HISTORY_PROBE_DAYS)
    lines, err = loki_query_range(
        base_url, user, password, LOKI_SELECTOR, start, now, limit=1,
        direction="forward",
    )
    if err or not lines:
        return 0
    try:
        oldest_ns = min(int(ts) for ts, _ in lines)
    except (TypeError, ValueError):
        return 0
    age = now - datetime.datetime.fromtimestamp(oldest_ns / 1e9, datetime.timezone.utc)
    return max(0, age.days)


def self_test():
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

    def line(identifier, message):
        return ("0", json.dumps({"SYSLOG_IDENTIFIER": identifier, "MESSAGE": message}))

    # --- classification ---
    ev = classify_event(
        "sshd-session",
        "Accepted publickey for root from 10.0.0.9 port 43238 ssh2: ED25519 SHA256:x",
    )
    expect("ssh: Accepted is a login with user, source and method",
           ev and ev["channel"] == "ssh" and ev["kind"] == "login"
           and ev["user"] == "root" and ev["addr"] == "10.0.0.9"
           and ev["method"] == "publickey", str(ev))

    ev = classify_event("systemd-logind", "Removed session 260.")
    expect("logind: Removed session is a logout",
           ev and ev["kind"] == "logout" and ev["session"] == "260", str(ev))

    ev = classify_event("systemd-logind", "New session 260 of user root.")
    expect("logind: New session is a login",
           ev and ev["kind"] == "login" and ev["user"] == "root", str(ev))

    ev = classify_event("api-server", "[AUTH] login-ok user=admin source=10.0.0.5 2fa=false")
    expect("ui: login-ok is parsed with user, source and MFA flag",
           ev and ev["channel"] == "ui" and ev["kind"] == "login"
           and ev["user"] == "admin" and ev["mfa"] is False, str(ev))

    ev = classify_event("api-server", "[AUTH] login-ok user=admin source=10.0.0.5 2fa=true")
    expect("ui: a second factor is detected when present", ev and ev["mfa"] is True, str(ev))

    # The trap this check was written for.
    ev = classify_event(
        "api-server",
        "[AUTH] redis authentication failed for user admin: WRONGPASS invalid username-password pair",
    )
    expect("ui: a WRONGPASS line counts as a failure, not as nothing",
           ev and ev["kind"] == "failure" and ev["user"] == "admin", str(ev))

    ev = classify_event(
        "sshd-session", "Failed password for invalid user oracle from 203.0.113.7 port 1234 ssh2"
    )
    expect("ssh: Failed password is a failure with the attempted account",
           ev and ev["kind"] == "failure" and ev["user"] == "oracle"
           and ev["addr"] == "203.0.113.7", str(ev))

    ev = classify_event(
        "runuser", "pam_unix(runuser-l:session): session opened for user samba1(uid=1004) by root"
    )
    expect("module service account is its own channel, not shell access",
           ev and ev["channel"] == "module" and ev["kind"] == "login", str(ev))

    ev = classify_event("systemd", "podman.service: Consumed 1.389s CPU time.")
    expect("unrelated lines are ignored rather than guessed", ev is None, str(ev))

    # --- no triple counting of a single SSH session ---
    session = [
        line("sshd-session", "Accepted publickey for root from 10.0.0.9 port 1 ssh2: ED25519 SHA256:x"),
        line("systemd-logind", "New session 7 of user root."),
        line("sshd-session", "pam_unix(sshd:session): session opened for user root(uid=0) by root(uid=0)"),
        line("sshd-session", "pam_unix(sshd:session): session closed for user root"),
        line("systemd-logind", "Session 7 logged out. Waiting for processes to exit."),
        line("systemd-logind", "Removed session 7."),
    ]
    summary = summarize(session)
    expect("one real SSH session counts as exactly one login",
           summary["ssh"]["logins"] == 1, str(summary["ssh"]))
    expect("one real SSH session counts as exactly one logout",
           summary["ssh"]["logouts"] == 1, str(summary["ssh"]))
    expect("root logins are counted separately",
           summary["ssh"]["root_logins"] == 1, str(summary["ssh"]))

    # --- service accounts must not drown human access ---
    noisy = [line("api-server", "[AUTH] login-ok user=claude-ro source=127.0.0.1 2fa=false")] * 50
    noisy.append(line("api-server", "[AUTH] login-ok user=admin source=10.0.0.5 2fa=false"))
    summary = summarize(noisy)
    expect("polling by a service account is separated from human logins",
           summary["ui"]["service_logins"] == 50 and summary["ui"]["human_logins"] == 1,
           str(summary["ui"]))

    # Found only by running against the real node: NS8 modules authenticate to
    # the cluster API as "module/<id>", and were being counted as people.
    expect("an NS8 module account is a machine, not a person",
           is_service_account("module/nextcloud1") is True, "")
    expect("a named service account is still recognised",
           is_service_account("claude-ro") is True, "")
    expect("an ordinary account is not mistaken for a service",
           is_service_account("admin") is False, "")

    mixed = [
        line("api-server", "[AUTH] login-ok user=module/nextcloud1 source=127.0.0.1 2fa=false"),
        line("api-server", "[AUTH] login-ok user=admin source=10.0.0.5 2fa=false"),
    ]
    expect("module logins do not inflate the human count",
           summarize(mixed)["ui"]["human_logins"] == 1, str(summarize(mixed)["ui"]))

    st, _perf, msg = evaluate_ui(summary, 24)
    expect("the single human login is still visible in the message", "admin" in msg, msg)
    expect("logins without a second factor raise a warning",
           st == 1 and "second factor" in msg, msg)
    expect("the interface is never implied to have logouts",
           "no logout events exist" in msg, msg)

    # --- failures ---
    summary = summarize([])
    st, _perf, msg = evaluate_failed(summary, 24)
    expect("no failures is OK", st == 0 and "no rejected" in msg, msg)

    summary = summarize(
        [line("sshd-session", "Failed password for root from 203.0.113.7 port 1 ssh2")]
    )
    st, _perf, msg = evaluate_failed(summary, 24)
    expect("a single rejected attempt warns and names the source",
           st == 1 and "203.0.113.7" in msg, msg)
    expect("the provisional threshold is declared in the message", "PROVISIONAL" in msg, msg)

    summary = summarize(
        [line("sshd-session", "Failed password for root from 203.0.113.7 port 1 ssh2")] * 12
    )
    st, _perf, _msg = evaluate_failed(summary, 24)
    expect("many rejected attempts escalate to CRITICAL", st == 2, str(st))

    # A Redis exhaustion in api-server was being reported as a rejected login.
    infra_line = line(
        "api-server",
        "[AUTH] redis authentication failed for user claude-ro: redis: Conn is "
        "in a bad state: ERR max number of clients reached",
    )
    summary = summarize([infra_line])
    st, perf, msg = evaluate_failed(summary, 24)
    expect("a platform fault is not counted as a rejected credential",
           st == 0 and "no rejected authentication attempts" in msg, msg)
    expect("but the platform fault is still disclosed",
           "platform fault, not a bad password" in msg and "claude-ro" in msg, msg)
    expect("platform faults are graphed separately",
           "failures=0" in perf and "platform_faults=1" in perf, perf)

    # --- coverage: the anti-false-green guard ---
    st, _perf, msg = evaluate_coverage(False, "loki-unreachable", 0, 0, None, 0, True)
    expect("an unreachable audit source is UNKNOWN, never OK",
           st == 3 and "not the same as 'no logins'" in msg, msg)

    st, _perf, msg = evaluate_coverage(True, "", 0, 0, 0.5, 7, True)
    expect("an empty stream is UNKNOWN, not a quiet node",
           st == 3 and "silent log shipper" in msg, msg)

    st, _perf, msg = evaluate_coverage(True, "", 0, 40, 0.5, 7, True)
    expect("records that match no known pattern are UNKNOWN",
           st == 3 and "log format may have changed" in msg, msg)

    st, _perf, msg = evaluate_coverage(True, "", 10, 40, 99.0, 7, True)
    expect("a stale newest record is UNKNOWN, not OK",
           st == 3 and "pipeline is probably stopped" in msg, msg)

    st, _perf, msg = evaluate_coverage(True, "", 10, 40, 1.0, 7, False)
    expect("volatile journald is reported as a dependency on Loki",
           st == 0 and "only durable copy" in msg, msg)

    st, _perf, msg = evaluate_coverage(True, "", 10, 40, 1.0, 0, True)
    expect("too little history warns instead of claiming retention",
           st == 1 and "less than a day" in msg, msg)

    st, _perf, msg = evaluate_coverage(True, "", 10, 40, 1.0, 24, True)
    expect("a healthy source is OK", st == 0 and msg.startswith("OK"), msg)

    # --- ssh reporting ---
    summary = summarize([])
    st, _perf, msg = evaluate_ssh(summary, 24)
    expect("no shell logins is OK and says so plainly",
           st == 0 and "no shell logins" in msg, msg)

    summary = summarize(session)
    st, perf, msg = evaluate_ssh(summary, 24)
    expect("shell activity reports users and sources",
           st == 0 and "root" in msg and "10.0.0.9" in msg, msg)
    expect("perfdata is emitted for trending",
           "logins=1" in perf and "root_logins=1" in perf, perf)

    # An open session must not be described as an anomaly.
    summary = summarize(
        [line("sshd-session", "Accepted publickey for root from 10.0.0.9 port 1 ssh2: x")]
    )
    _st, _perf, msg = evaluate_ssh(summary, 24)
    expect("an unmatched login is explained, not flagged as a fault",
           "still open, or opened earlier" in msg, msg)

    # --- env file parsing ---
    expect("a missing environment file yields no credentials",
           read_env_file("/nonexistent/ns8/loki/environment") == {}, "")

    print("")
    print("%d/%d checks passed" % (ran - failures, ran))
    sys.exit(1 if failures else 0)


def check():
    print(LOCAL_SECTION)
    now = datetime.datetime.now(datetime.timezone.utc)
    start = now - datetime.timedelta(hours=WINDOW_HOURS)

    base_url, user, password, cfg_err = loki_config()
    if not base_url:
        message = (
            "UNKNOWN: the loki1 module was not found on this node (%s), so there "
            "is no durable source of login evidence" % cfg_err
        )
        for service in (SVC_SSH, SVC_UI, SVC_FAILED, SVC_COVERAGE):
            print(local_line(3, service, "-", message))
        return

    lines, err = loki_query_range(base_url, user, password, LOKI_SELECTOR, start, now)

    if err:
        unknown = (
            "UNKNOWN: the Loki audit source could not be queried (%s) - this is "
            "not evidence that nobody logged in" % err
        )
        print(local_line(3, SVC_SSH, "-", unknown))
        print(local_line(3, SVC_UI, "-", unknown))
        print(local_line(3, SVC_FAILED, "-", unknown))
        st, perf, msg = evaluate_coverage(
            False, err, 0, 0, None, 0, journal_is_persistent()
        )
        print(local_line(st, SVC_COVERAGE, perf, msg))
        return

    summary = summarize(lines)

    newest_age_hours = None
    if lines:
        try:
            newest_ns = max(int(ts) for ts, _ in lines)
            newest_age_hours = (
                now - datetime.datetime.fromtimestamp(
                    newest_ns / 1e9, datetime.timezone.utc
                )
            ).total_seconds() / 3600.0
        except (TypeError, ValueError):
            newest_age_hours = None

    history_days = measure_history_days(base_url, user, password, now)

    st, perf, msg = evaluate_ssh(summary, WINDOW_HOURS)
    print(local_line(st, SVC_SSH, perf, msg))

    st, perf, msg = evaluate_ui(summary, WINDOW_HOURS)
    print(local_line(st, SVC_UI, perf, msg))

    st, perf, msg = evaluate_failed(summary, WINDOW_HOURS)
    print(local_line(st, SVC_FAILED, perf, msg))

    st, perf, msg = evaluate_coverage(
        True,
        cfg_err,
        summary["recognised"],
        summary["parsed"],
        newest_age_hours,
        history_days,
        journal_is_persistent(),
    )
    print(local_line(st, SVC_COVERAGE, perf, msg))


if "--self-test" in sys.argv:
    self_test()
else:
    check()
