#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

# One CheckMK service per user account, gathering that person's logins and
# logouts across every NS8 channel that can actually be observed.
#
# Each service carries both halves of what an auditor asks for:
#   - metrics, so every counter is graphed and trended over time;
#   - a readable event log in the service's long output, so "who opened what,
#     when, and from where" can be read without leaving the monitoring system.
#
# Deliberately NOT using the NS8 task API. On the reference node every call to
# module/<id>/<action> leaked hundreds of Redis connections (one check measured
# at +706, a full agent run at +2532, growing ~1300/min until api-server hit
# maxclients and stopped authenticating) and raised a banner notification in
# the cluster interface for every single call. This check therefore reads only:
#   - the Loki HTTP API  (shell and interface access, and failures)
#   - the samba1 Podman socket (AD account list, and the folder audit database)
#   - the mattermost1 Podman socket (its own PostgreSQL login audit)
# None of those creates a task, and none of them leaks.
#
# What is honestly observable, per channel:
#   shell / interface : Loki category="security", 365d retention
#   folder access     : samba_audit, ONLY for shares with auditing enabled
#   Mattermost        : audits + sessions, LOCAL accounts only - Mattermost
#                       team edition has no AD/LDAP login at all, so a domain
#                       account can never appear there, and its absence is not
#                       evidence of anything.
#
# Emitted services:
#   NS8.User.<account>  [DE.CM-01/DE.CM-03] per-user access evidence
#
# Compatible with Python 3.9+ (Rocky Linux 9).

import base64
import datetime
import http.client
import json
import os
try:
    import pwd
except ImportError:
    pwd = None
import re
import socket
import struct
import sys
import urllib.error
import urllib.parse
import urllib.request

VERSION = "1.0.0"

SVC_PREFIX = "NS8.User"
CTRL = "DE.CM-01"

# --- Loki (shell, interface, failures) --------------------------------------
LOKI_ENV_FILE = os.environ.get(
    "CHECK_NS8_USER_LOKI_ENV", "/home/loki1/.config/state/environment"
)
LOKI_HOST = os.environ.get("CHECK_NS8_USER_LOKI_HOST", "127.0.0.1")
LOKI_SELECTOR = os.environ.get("CHECK_NS8_USER_SELECTOR", '{category="security"}')
LOKI_MAX_LINES = int(os.environ.get("CHECK_NS8_USER_MAX_LINES", "5000"))
LOKI_TIMEOUT = float(os.environ.get("CHECK_NS8_USER_LOKI_TIMEOUT", "25"))

# --- Podman-backed modules --------------------------------------------------
PODMAN = "/v5.0.0/libpod"
SOCKET_TIMEOUT = float(os.environ.get("CHECK_NS8_USER_TIMEOUT", "20"))
SAMBA_CONTAINER = os.environ.get("CHECK_NS8_USER_SAMBA_CONTAINER", "samba-dc")
SAMBA_AUDIT_CONTAINER = os.environ.get("CHECK_NS8_USER_AUDIT_CONTAINER", "timescaledb")
SAMBA_AUDIT_DB = os.environ.get("CHECK_NS8_USER_AUDIT_DB", "samba_audit")
SAMBA_AUDIT_DB_USER = os.environ.get("CHECK_NS8_USER_AUDIT_DB_USER", "postgres")
MM_CONTAINER = os.environ.get("CHECK_NS8_USER_MM_CONTAINER", "postgres-app")
MM_DB = os.environ.get("CHECK_NS8_USER_MM_DB", "mattermost")
MM_DB_USER = os.environ.get("CHECK_NS8_USER_MM_DB_USER", "mattuser")

WINDOW_HOURS = int(os.environ.get("CHECK_NS8_USER_WINDOW_HOURS", "24"))
LOG_LINES = int(os.environ.get("CHECK_NS8_USER_LOG_LINES", "15"))

# A real directory can hold thousands of accounts; one CheckMK service each
# would be unusable. The cap is explicit and reported rather than silent.
MAX_USERS = int(os.environ.get("CHECK_NS8_USER_MAX", "60"))

# Accounts that are infrastructure, not people. Machine accounts end with "$".
DEFAULT_EXCLUDE = "krbtgt,Guest,ldapservice,DC1_"
EXCLUDE = set(
    name.strip().lower()
    for name in os.environ.get("CHECK_NS8_USER_EXCLUDE", DEFAULT_EXCLUDE).split(",")
    if name.strip()
)
# Accounts to always emit even if the directory does not list them (service
# accounts worth watching, for example the monitoring reader).
EXTRA_USERS = [
    name.strip()
    for name in os.environ.get("CHECK_NS8_USER_EXTRA", "root,admin").split(",")
    if name.strip()
]

LOCAL_SECTION = "<<<local:sep(0)>>>"

RE_SSH_ACCEPTED = re.compile(r"^Accepted (?P<method>\S+) for (?P<user>\S+) from (?P<addr>\S+)")
RE_SSH_FAILED = re.compile(r"^Failed (?P<method>\S+) for (?:invalid user )?(?P<user>\S+) from (?P<addr>\S+)")
RE_PAM_SESSION = re.compile(
    r"^pam_unix\((?P<svc>[^:]+):session\): session (?P<verb>opened|closed) for user (?P<user>[^ (]+)"
)
RE_UI_OK = re.compile(
    r"^\[AUTH\] login-ok user=(?P<user>\S+) source=(?P<addr>\S+)(?: \S*fa=(?P<fav>\S+))?"
)
RE_UI_FAIL = re.compile(
    r"^\[AUTH\] .*?(?:authentication failed|login-fail|WRONGPASS)", re.IGNORECASE
)
RE_UI_FAIL_USER = re.compile(r"for user (?P<user>[^\s:]+)")

# A rejected login and a platform fault arrive on the same log line shape, but
# they mean opposite things: one is "somebody used the wrong password" (a
# security signal), the other is "the system could not authenticate anybody"
# (an availability fault). Counting them together lets a real brute-force
# attempt hide inside infrastructure noise, so they are separated.
RE_INFRA_FAILURE = re.compile(
    r"max number of clients|conn is in a bad state|connection refused|"
    r"i/o timeout|no such host|broken pipe",
    re.IGNORECASE,
)


def local_line(state, service, perfdata, message):
    return "%d %s %s %s" % (state, service, perfdata or "-", message)


def normalise_user(name):
    """Strip a domain prefix and lowercase, so NETHLAB\\x and x are one person.

    "/" is deliberately NOT a separator: NS8 names its internal module accounts
    "module/<id>", and splitting on "/" turned them into plausible-looking
    people (a module appeared in the directory as the user "nextcloud1")."""
    if not name:
        return ""
    value = name.strip()
    if "\\" in value:
        value = value.rsplit("\\", 1)[1]
    if "@" in value:
        value = value.split("@", 1)[0]
    return value.lower()


def service_token(value):
    token = re.sub(r"[^A-Za-z0-9._-]+", "_", value or "").strip("_")
    return token or "unknown"


def is_excluded(name):
    """Machine and infrastructure accounts are not people."""
    if not name:
        return True
    low = name.lower()
    if low in EXCLUDE:
        return True
    if low.endswith("$"):          # Active Directory machine account
        return True
    if low.startswith("module/"):  # NS8 module authenticating to its own API
        return True
    return False


# --- Loki -------------------------------------------------------------------

def read_env_file(path):
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
    env = read_env_file(LOKI_ENV_FILE)
    port = env.get("LOKI_HTTP_PORT") or env.get("TCP_PORT") or ""
    if not port:
        return "", "", "", "loki-module-not-found"
    return (
        "http://%s:%s" % (LOKI_HOST, port),
        env.get("LOKI_API_AUTH_USERNAME", ""),
        env.get("LOKI_API_AUTH_PASSWORD", ""),
        "",
    )


def loki_query(base_url, user, password, start_dt, end_dt):
    params = {
        "query": LOKI_SELECTOR,
        "start": "%d" % int(start_dt.timestamp() * 1e9),
        "end": "%d" % int(end_dt.timestamp() * 1e9),
        "limit": str(LOKI_MAX_LINES),
        "direction": "backward",
    }
    url = "%s/loki/api/v1/query_range?%s" % (
        base_url.rstrip("/"),
        urllib.parse.urlencode(params),
    )
    req = urllib.request.Request(url, method="GET")
    if user and password:
        token = base64.b64encode(("%s:%s" % (user, password)).encode()).decode("ascii")
        req.add_header("Authorization", "Basic " + token)
    try:
        with urllib.request.urlopen(req, timeout=LOKI_TIMEOUT) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as exc:
        return [], "loki-http-%d" % exc.code
    except (urllib.error.URLError, ValueError, OSError):
        return [], "loki-unreachable"
    if payload.get("status") != "success":
        return [], "loki-bad-response"
    lines = []
    for stream in payload.get("data", {}).get("result", []):
        for value in stream.get("values", []):
            if len(value) >= 2:
                lines.append((value[0], value[1]))
    return lines, ""


def loki_events(lines):
    """Turn journal records into per-user events: (ts_ns, channel, kind, text)."""
    events = []
    for ts, raw in lines:
        try:
            record = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if not isinstance(record, dict):
            continue
        ident = record.get("SYSLOG_IDENTIFIER", "")
        msg = (record.get("MESSAGE") or "").strip()
        if not msg:
            continue

        if ident == "api-server":
            match = RE_UI_OK.match(msg)
            if match:
                events.append((ts, normalise_user(match.group("user")), "ui", "login",
                               "interface login from %s%s" % (
                                   match.group("addr"),
                                   "" if (match.group("fav") or "").lower() in ("true", "yes", "1")
                                   else " (no second factor)")))
                continue
            if RE_UI_FAIL.match(msg):
                who = RE_UI_FAIL_USER.search(msg)
                if RE_INFRA_FAILURE.search(msg):
                    events.append((ts, normalise_user(who.group("user") if who else ""),
                                   "ui", "infra_failure",
                                   "authentication could not be completed "
                                   "(platform fault, not a wrong password)"))
                else:
                    events.append((ts, normalise_user(who.group("user") if who else ""),
                                   "ui", "failure", "interface login REJECTED "
                                   "(wrong credentials)"))
                continue
            continue

        match = RE_SSH_ACCEPTED.match(msg)
        if match:
            events.append((ts, normalise_user(match.group("user")), "ssh", "login",
                           "shell login from %s (%s)" % (match.group("addr"), match.group("method"))))
            continue
        match = RE_SSH_FAILED.match(msg)
        if match:
            events.append((ts, normalise_user(match.group("user")), "ssh", "failure",
                           "shell login REJECTED from %s" % match.group("addr")))
            continue
        match = RE_PAM_SESSION.match(msg)
        if match and match.group("svc") == "sshd" and match.group("verb") == "closed":
            events.append((ts, normalise_user(match.group("user")), "ssh", "logout",
                           "shell session closed"))
            continue
    return events


# --- Podman -----------------------------------------------------------------

class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path, timeout=SOCKET_TIMEOUT):
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._path)


def podman_socket(instance):
    if pwd is None:
        return ""
    try:
        uid = pwd.getpwnam(instance).pw_uid
    except KeyError:
        return ""
    path = "/run/user/%d/podman/podman.sock" % uid
    return path if os.path.exists(path) else ""


def podman_call(sock_path, method, path, body=None):
    conn = UnixHTTPConnection(sock_path)
    try:
        payload = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"} if payload is not None else {}
        conn.request(method, PODMAN + path, body=payload, headers=headers)
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


def demux_stream(raw, streams=(1,)):
    out = b""
    pos = 0
    while pos + 8 <= len(raw):
        stream_type = raw[pos]
        size = struct.unpack(">I", raw[pos + 4:pos + 8])[0]
        if stream_type in streams:
            out += raw[pos + 8:pos + 8 + size]
        pos += 8 + size
    return out.decode("utf-8", errors="replace")


def exec_in_container(sock_path, container, cmd):
    try:
        status, raw = podman_call(
            sock_path, "POST", "/containers/%s/exec" % container,
            {"Cmd": cmd, "AttachStdout": True, "AttachStderr": True},
        )
        if status not in (200, 201):
            return -1, ""
        exec_id = json.loads(raw.decode())["Id"]
        status, raw = podman_call(
            sock_path, "POST", "/exec/%s/start" % exec_id,
            {"Detach": False, "Tty": False},
        )
        if status != 200:
            return -1, ""
        stdout = demux_stream(raw)
        status, raw = podman_call(sock_path, "GET", "/exec/%s/json" % exec_id)
        code = json.loads(raw.decode()).get("ExitCode", -1) if status == 200 else -1
        return code, stdout
    except (OSError, ValueError, KeyError, http.client.HTTPException):
        return -1, ""


def list_directory_users(sock_path):
    """AD account list, straight from the domain controller container."""
    code, out = exec_in_container(sock_path, SAMBA_CONTAINER, ["samba-tool", "user", "list"])
    if code != 0:
        return [], "directory-unreadable"
    names = [line.strip() for line in out.splitlines() if line.strip()]
    return names, ""


def query_samba_events(sock_path, window_hours):
    """Per-user folder audit rows in the window: time, user, share, op, result."""
    sql = (
        "SELECT to_char(time,'YYYY-MM-DD HH24:MI:SS'), username, share, op, result "
        "FROM samba_audit WHERE time > now() - interval '%d hours' "
        "ORDER BY time DESC LIMIT 2000;" % window_hours
    )
    code, out = exec_in_container(
        sock_path, SAMBA_AUDIT_CONTAINER,
        ["psql", "-U", SAMBA_AUDIT_DB_USER, "-d", SAMBA_AUDIT_DB,
         "-t", "-A", "-F", "|", "-c", sql],
    )
    if code != 0:
        return [], "samba-audit-unreachable"
    rows = []
    for raw in out.splitlines():
        parts = raw.strip().split("|")
        if len(parts) < 5:
            continue
        rows.append(
            {"time": parts[0], "user": normalise_user(parts[1]),
             "share": parts[2], "op": parts[3], "result": parts[4]}
        )
    return rows, ""


def query_mattermost_events(sock_path, window_hours):
    """Mattermost login audit rows. Local accounts only, by product design."""
    sql = (
        "SELECT to_char(to_timestamp(a.createat/1000),'YYYY-MM-DD HH24:MI:SS'), "
        "COALESCE(u.username,''), a.ipaddress, left(a.extrainfo,40) "
        "FROM audits a LEFT JOIN users u ON u.id=a.userid "
        "WHERE a.action LIKE '%%login%%' "
        "AND a.createat > (extract(epoch from now())-%d*3600)*1000 "
        "ORDER BY a.createat DESC LIMIT 500;" % window_hours
    )
    code, out = exec_in_container(
        sock_path, MM_CONTAINER,
        ["psql", "-U", MM_DB_USER, "-d", MM_DB, "-t", "-A", "-F", "|", "-c", sql],
    )
    if code != 0:
        return [], "mattermost-unreachable"
    rows = []
    for raw in out.splitlines():
        parts = raw.strip().split("|")
        if len(parts) < 4:
            continue
        rows.append(
            {"time": parts[0], "user": normalise_user(parts[1]),
             "addr": parts[2], "info": parts[3]}
        )
    return rows, ""


# --- aggregation ------------------------------------------------------------

def new_bucket():
    return {
        "ssh_logins": 0, "ssh_logouts": 0, "ui_logins": 0,
        "samba_connects": 0, "samba_disconnects": 0, "samba_ops": 0,
        "app_logins": 0, "failures": 0, "infra_failures": 0, "log": [],
    }


def build_users(directory, loki_evts, samba_rows, mm_rows):
    """One bucket per account, plus anyone seen acting who is not in the list."""
    users = {}
    for name in directory:
        if is_excluded(name):
            continue
        users[normalise_user(name)] = new_bucket()
    for name in EXTRA_USERS:
        if not is_excluded(name):
            users.setdefault(normalise_user(name), new_bucket())

    def bucket_for(name):
        if not name or is_excluded(name):
            return None
        # Someone acting who is not in the directory still deserves a service:
        # an unknown account doing things is the interesting case, not noise.
        return users.setdefault(name, new_bucket())

    for ts, user, channel, kind, text in loki_evts:
        bucket = bucket_for(user)
        if bucket is None:
            continue
        if kind == "failure":
            bucket["failures"] += 1
        elif kind == "infra_failure":
            bucket["infra_failures"] += 1
        elif channel == "ssh" and kind == "login":
            bucket["ssh_logins"] += 1
        elif channel == "ssh" and kind == "logout":
            bucket["ssh_logouts"] += 1
        elif channel == "ui" and kind == "login":
            bucket["ui_logins"] += 1
        stamp = ""
        try:
            stamp = datetime.datetime.fromtimestamp(
                int(ts) / 1e9, datetime.timezone.utc
            ).strftime("%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            stamp = "?"
        bucket["log"].append((stamp, text))

    for row in samba_rows:
        bucket = bucket_for(row["user"])
        if bucket is None:
            continue
        bucket["samba_ops"] += 1
        if row["op"] == "connect":
            bucket["samba_connects"] += 1
            bucket["log"].append(
                (row["time"], "folder login on '%s'" % row["share"])
            )
        elif row["op"] == "disconnect":
            bucket["samba_disconnects"] += 1
            bucket["log"].append(
                (row["time"], "folder logout from '%s'" % row["share"])
            )
        elif row["result"] and row["result"].lower() != "ok":
            bucket["failures"] += 1
            bucket["log"].append(
                (row["time"], "folder operation %s REFUSED on '%s'" % (row["op"], row["share"]))
            )

    for row in mm_rows:
        bucket = bucket_for(row["user"])
        if bucket is None:
            continue
        info = (row.get("info") or "").lower()
        if info.startswith("success"):
            bucket["app_logins"] += 1
            bucket["log"].append(
                (row["time"], "Mattermost login from %s" % row["addr"])
            )
    return users


def evaluate_user(name, bucket, sources, window_hours):
    """One account's access evidence, as metrics plus a readable log."""
    total_logins = (
        bucket["ssh_logins"] + bucket["ui_logins"]
        + bucket["samba_connects"] + bucket["app_logins"]
    )
    perf = (
        "logins=%d|ssh_logins=%d|ui_logins=%d|folder_logins=%d|app_logins=%d|"
        "logouts=%d|folder_logouts=%d|failures=%d|platform_faults=%d"
        % (
            total_logins,
            bucket["ssh_logins"],
            bucket["ui_logins"],
            bucket["samba_connects"],
            bucket["app_logins"],
            bucket["ssh_logouts"],
            bucket["samba_disconnects"],
            bucket["failures"],
            bucket["infra_failures"],
        )
    )

    unreadable = [label for label, ok in sources.items() if not ok]
    if len(unreadable) == len(sources):
        return (
            3,
            perf,
            "UNKNOWN [%s]: no audit source could be read for %s (%s) - this is "
            "not evidence that the account was idle"
            % (CTRL, name, ", ".join(sorted(unreadable))),
        )

    if total_logins == 0 and bucket["failures"] == 0 and not bucket["infra_failures"]:
        summary = "no recorded access in the last %dh" % window_hours
    else:
        parts = []
        if bucket["ssh_logins"]:
            parts.append("%d shell" % bucket["ssh_logins"])
        if bucket["ui_logins"]:
            parts.append("%d interface" % bucket["ui_logins"])
        if bucket["samba_connects"]:
            parts.append("%d folder" % bucket["samba_connects"])
        if bucket["app_logins"]:
            parts.append("%d Mattermost" % bucket["app_logins"])
        summary = "%d logins in %dh (%s), %d logouts" % (
            total_logins,
            window_hours,
            ", ".join(parts) if parts else "none",
            bucket["ssh_logouts"] + bucket["samba_disconnects"],
        )

    state = 0
    label = "OK"
    if bucket["failures"]:
        state = 1
        label = "WARNING"
        summary += "; %d rejected attempt(s) with wrong credentials" % bucket["failures"]
    if bucket["infra_failures"]:
        # Reported, but never as a credential problem: blaming the account for
        # a platform fault would send someone hunting the wrong thing.
        summary += (
            "; %d authentication(s) failed for a platform fault, not a bad "
            "password" % bucket["infra_failures"]
        )

    message = "%s [%s]: %s - %s" % (label, CTRL, name, summary)
    if unreadable:
        message += "; sources not readable: %s" % ", ".join(sorted(unreadable))

    # Long output: the event log, newest first. "\n" is the local-check
    # convention for extra lines, and is what makes this readable as a log.
    log = sorted(bucket["log"], reverse=True)[:LOG_LINES]
    if log:
        message += "\\n" + "\\n".join("%s  %s" % (stamp, text) for stamp, text in log)
    elif total_logins == 0:
        message += "\\n(no events recorded in this window)"
    return (state, perf, message)


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

    # --- identity normalisation ---
    expect("a domain-prefixed account is the same person as the bare name",
           normalise_user("NETHLAB\\nistest03") == "nistest03",
           normalise_user("NETHLAB\\nistest03"))
    expect("a UPN is reduced to the account name",
           normalise_user("nistest05@nethlab.it") == "nistest05", "")
    expect("case does not create a second person",
           normalise_user("Marzio") == normalise_user("marzio"), "")

    expect("an AD machine account is not a person", is_excluded("DC1$") is True, "")
    expect("an NS8 module account is not a person",
           is_excluded("module/nextcloud1") is True, "")
    # Found by running against the real node: normalising before excluding
    # turned "module/nextcloud1" into a user called "nextcloud1".
    expect("a module account survives normalisation and stays excluded",
           normalise_user("module/nextcloud1") == "module/nextcloud1"
           and is_excluded(normalise_user("module/nextcloud1")) is True,
           normalise_user("module/nextcloud1"))
    expect("krbtgt is excluded by default", is_excluded("krbtgt") is True, "")
    expect("a real account is kept", is_excluded("nistest01") is False, "")

    # --- Loki parsing ---
    def jline(ident, msg, ts="1793368809000000000"):
        return (ts, json.dumps({"SYSLOG_IDENTIFIER": ident, "MESSAGE": msg}))

    evts = loki_events([
        jline("sshd-session", "Accepted publickey for root from 10.0.0.9 port 1 ssh2: x"),
        jline("sshd-session", "pam_unix(sshd:session): session closed for user root"),
        jline("api-server", "[AUTH] login-ok user=admin source=10.0.0.5 2fa=false"),
        jline("api-server", "[AUTH] redis authentication failed for user admin: WRONGPASS"),
        jline("sshd-session", "Failed password for oracle from 203.0.113.7 port 1 ssh2"),
    ])
    kinds = sorted((u, c, k) for _t, u, c, k, _x in evts)
    expect("shell login, logout, interface login and both failures are extracted",
           len(evts) == 5 and ("admin", "ui", "failure") in kinds
           and ("root", "ssh", "logout") in kinds, str(kinds))

    # --- aggregation ---
    directory = ["nistest01", "nistest03", "krbtgt", "DC1$", "marzio"]
    samba = [
        {"time": "2026-10-30 14:09:16", "user": "nistest03", "share": "nis-audited",
         "op": "connect", "result": "ok"},
        {"time": "2026-10-30 14:09:17", "user": "nistest03", "share": "nis-audited",
         "op": "disconnect", "result": "ok"},
        {"time": "2026-10-30 14:09:18", "user": "nistest03", "share": "nis-audited",
         "op": "create_file", "result": "fail (Access denied)"},
    ]
    mm = [{"time": "2026-10-09 08:56:51", "user": "marzio", "addr": "10.0.0.1",
           "info": "success session_user=abc"}]
    users = build_users(directory, evts, samba, mm)

    expect("every directory account gets a service, even with no activity",
           "nistest01" in users, str(sorted(users)))
    expect("excluded accounts get no service",
           "krbtgt" not in users and "dc1$" not in users, str(sorted(users)))
    expect("an account seen acting but absent from the directory still appears",
           "oracle" in users, str(sorted(users)))
    expect("folder logins and logouts are counted per user",
           users["nistest03"]["samba_connects"] == 1
           and users["nistest03"]["samba_disconnects"] == 1,
           str(users["nistest03"]))
    expect("a refused folder operation counts as a failure",
           users["nistest03"]["failures"] == 1, str(users["nistest03"]))
    expect("a Mattermost login is attributed to the right person",
           users["marzio"]["app_logins"] == 1, str(users["marzio"]))

    sources = {"Loki": True, "folder audit": True, "Mattermost": True}

    # --- per-user service output ---
    st, perf, msg = evaluate_user("nistest03", users["nistest03"], sources, 24)
    expect("a user with refused operations warns", st == 1 and "rejected" in msg, msg)
    expect("metrics are emitted so every counter can be graphed",
           "folder_logins=1" in perf and "failures=1" in perf, perf)
    expect("the event log is attached as long output",
           "\\n" in msg and "folder login on 'nis-audited'" in msg, msg)

    st, _perf, msg = evaluate_user("nistest01", users["nistest01"], sources, 24)
    expect("an account with no activity is OK and says so",
           st == 0 and "no recorded access" in msg, msg)
    expect("an empty log is stated rather than left blank",
           "no events recorded" in msg, msg)

    st, _perf, msg = evaluate_user("admin", users["admin"], sources, 24)
    expect("interface logins are reported per user",
           "1 interface" in msg, msg)
    expect("a wrong password is called a credential failure",
           "wrong credentials" in msg, msg)

    # A platform fault must not be reported as somebody's failed login.
    infra = loki_events([
        jline("api-server",
              "[AUTH] redis authentication failed for user claude-ro: redis: Conn "
              "is in a bad state: ERR max number of clients reached"),
    ])
    expect("a max-clients fault is classified as infrastructure, not a login failure",
           infra and infra[0][3] == "infra_failure", str(infra))
    iu = build_users(["claude-ro"], infra, [], [])
    expect("the account is not charged with a failed login attempt",
           iu["claude-ro"]["failures"] == 0 and iu["claude-ro"]["infra_failures"] == 1,
           str(iu["claude-ro"]))
    st, perf, msg = evaluate_user("claude-ro", iu["claude-ro"], sources, 24)
    expect("a platform fault alone does not raise a security warning",
           st == 0 and "platform fault" in msg, msg)
    expect("platform faults are graphed separately from credential failures",
           "failures=0|platform_faults=1" in perf, perf)

    # --- source failures must never read as "nobody logged in" ---
    st, _perf, msg = evaluate_user(
        "nistest01", new_bucket(),
        {"Loki": False, "folder audit": False, "Mattermost": False}, 24
    )
    expect("all sources unreadable is UNKNOWN, never OK",
           st == 3 and "not evidence that the account was idle" in msg, msg)

    st, _perf, msg = evaluate_user(
        "nistest01", new_bucket(),
        {"Loki": True, "folder audit": False, "Mattermost": True}, 24
    )
    expect("a partially readable picture names what is missing",
           st == 0 and "sources not readable: folder audit" in msg, msg)

    expect("account names are made safe for service names",
           service_token("NETHLAB\\user") == "NETHLAB_user",
           service_token("NETHLAB\\user"))

    print("")
    print("%d/%d checks passed" % (ran - failures, ran))
    sys.exit(1 if failures else 0)


def check():
    now = datetime.datetime.now(datetime.timezone.utc)
    start = now - datetime.timedelta(hours=WINDOW_HOURS)

    sources = {}

    base_url, luser, lpass, lerr = loki_config()
    loki_evts = []
    if base_url:
        lines, err = loki_query(base_url, luser, lpass, start, now)
        sources["Loki"] = not err
        if not err:
            loki_evts = loki_events(lines)
    else:
        sources["Loki"] = False

    samba_sock = podman_socket("samba1")
    directory = []
    samba_rows = []
    if samba_sock:
        directory, derr = list_directory_users(samba_sock)
        samba_rows, serr = query_samba_events(samba_sock, WINDOW_HOURS)
        sources["folder audit"] = not serr
    else:
        sources["folder audit"] = False

    mm_sock = podman_socket("mattermost1")
    mm_rows = []
    if mm_sock:
        mm_rows, merr = query_mattermost_events(mm_sock, WINDOW_HOURS)
        sources["Mattermost"] = not merr
    else:
        sources["Mattermost"] = False

    users = build_users(directory, loki_evts, samba_rows, mm_rows)

    print(LOCAL_SECTION)
    names = sorted(users)
    truncated = []
    if len(names) > MAX_USERS:
        # Keep the busiest accounts rather than an alphabetical accident.
        names = sorted(
            users,
            key=lambda n: (
                -(users[n]["failures"] * 1000
                  + users[n]["ssh_logins"] + users[n]["ui_logins"]
                  + users[n]["samba_connects"] + users[n]["app_logins"]),
                n,
            ),
        )
        truncated = names[MAX_USERS:]
        names = sorted(names[:MAX_USERS])

    for name in names:
        state, perf, message = evaluate_user(name, users[name], sources, WINDOW_HOURS)
        print(local_line(state, "%s.%s" % (SVC_PREFIX, service_token(name)), perf, message))

    if truncated:
        print(
            local_line(
                1,
                "%s.Coverage" % SVC_PREFIX,
                "accounts=%d|reported=%d|omitted=%d"
                % (len(users), len(names), len(truncated)),
                "WARNING [%s]: %d accounts exist but only %d are reported "
                "(limit CHECK_NS8_USER_MAX=%d); %d accounts have no service and "
                "their activity is therefore unmonitored"
                % (CTRL, len(users), len(names), MAX_USERS, len(truncated)),
            )
        )


if "--self-test" in sys.argv:
    self_test()
else:
    check()
