#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

# Check NS8 Samba file-share access auditing, through the module's Podman REST
# socket only (no subprocess, no NS8 API credentials needed).
#
# The NS8 samba module ships a dedicated TimescaleDB container for its audit
# log ("timescaledb.service - TimescaleDB for Samba Audit logs"), holding one
# row per audited operation:
#   samba_audit(time, proto, username, addr, share, op, result, path, aux)
#
# Why the coverage service is the important one:
# auditing is enabled PER SHARE. A share with auditing off produces no rows at
# all, so it is indistinguishable from a share nobody ever opened. This was
# verified rather than assumed: two shares were created on the reference node,
# one audited and one not, the same authenticated client listed both, and only
# the audited one produced rows. Any dashboard that just counts rows would have
# shown the unaudited share as quiet and safe.
#
# Two structural limits this check states out loud instead of hiding:
#   1. A REJECTED connection is never audited. full_audit is a VFS module that
#      is only loaded once the share connection has succeeded, so a denied
#      "tree connect" leaves no row. Verified: an anonymous smbclient attempt
#      was refused and the row count did not move (464 -> 464). Rejected share
#      access lives in the Samba log, not in this table.
#   2. NS8's own "basic audit log" records only
#      create_file/unlinkat/renameat/mkdirat/fsetxattr. It does NOT include
#      connect/disconnect, so without extra configuration there is no such
#      thing as a login or logout on a folder. Those two operations must be
#      added to full_audit:success/failure, and an "alter-share" from the NS8
#      interface rewrites the parameter and silently drops them again - which
#      is exactly why this check reads the EFFECTIVE Samba configuration
#      instead of trusting what NS8 was asked to do.
#
# Emitted services:
#   NS8.Samba.Audit.Coverage  [DE.CM-01] is folder access actually recorded
#   NS8.Samba.Sessions        [DE.CM-03] connects / disconnects (folder in-out)
#   NS8.Samba.Access.<share>  [DE.CM-03] recorded activity per audited share
#
# Compatible with Python 3.9+ (Rocky Linux 9).

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

VERSION = "1.0.0"

SVC_COVERAGE = "NS8.Samba.Audit.Coverage"
SVC_SESSIONS = "NS8.Samba.Sessions"
SVC_ACCESS = "NS8.Samba.Access"

CTRL_COVERAGE = "DE.CM-01"
CTRL_SESSIONS = "DE.CM-03"
CTRL_ACCESS = "DE.CM-03"

PODMAN = "/v5.0.0/libpod"
SAMBA_CONTAINER = os.environ.get("CHECK_NS8_SAMBA_CONTAINER", "samba-dc")
AUDIT_CONTAINER = os.environ.get("CHECK_NS8_SAMBA_AUDIT_CONTAINER", "timescaledb")
AUDIT_DB = os.environ.get("CHECK_NS8_SAMBA_AUDIT_DB", "samba_audit")
AUDIT_DB_USER = os.environ.get("CHECK_NS8_SAMBA_AUDIT_DB_USER", "postgres")
AUDIT_TABLE = "samba_audit"

WINDOW_HOURS = int(os.environ.get("CHECK_NS8_SAMBA_WINDOW_HOURS", "24"))
SOCKET_TIMEOUT = float(os.environ.get("CHECK_NS8_SAMBA_TIMEOUT", "20"))

# The two operations that make a folder "login/logout" exist at all.
SESSION_OPS = ("connect", "disconnect")

LOCAL_SECTION = "<<<local:sep(0)>>>"

RE_SAMBA_INSTANCE = re.compile(r"^samba\d+$")
RE_SHARE_HEADER = re.compile(r"^\[(?P<name>[^\]]+)\]\s*$")
RE_SHARE_PARAM = re.compile(r"^\s+(?P<key>[^=]+?)\s*=\s*(?P<value>.*)$")

# Shares Samba always defines for Active Directory; they are not file shares
# and their absence from the audit configuration is not a finding.
BUILTIN_SHARES = {"sysvol", "netlogon", "homes", "print$", "IPC$"}


def local_line(state, service, perfdata, message):
    """Build one CheckMK local-check line: state, service, metrics (or -), detail."""
    return "%d %s %s %s" % (state, service, perfdata or "-", message)


class UnixHTTPConnection(http.client.HTTPConnection):
    """HTTP over a unix socket, for the podman REST API."""

    def __init__(self, path, timeout=SOCKET_TIMEOUT):
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._path)


def find_samba_instances():
    """Module instances named samba1, samba2, ... that exist as system users."""
    if pwd is None:
        return []
    found = []
    try:
        for entry in pwd.getpwall():
            if RE_SAMBA_INSTANCE.match(entry.pw_name):
                found.append(entry.pw_name)
    except (KeyError, OSError):
        return []
    return sorted(found)


def podman_socket(instance):
    """Returns (error, socket path) for a module's podman API socket."""
    if pwd is None:
        return "no-pwd-module", ""
    try:
        uid = pwd.getpwnam(instance).pw_uid
    except KeyError:
        return "no-user", ""
    path = "/run/user/%d/podman/podman.sock" % uid
    if not os.path.exists(path):
        return "no-podman-socket", ""
    return "", path


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
    """Decode a podman exec stream (8-byte frame headers) into text.

    Frame: [stream type, 0, 0, 0, payload size as big-endian uint32] + payload.
    stream type 1 = stdout, 2 = stderr."""
    out = b""
    pos = 0
    while pos + 8 <= len(raw):
        stream_type = raw[pos]
        size = struct.unpack(">I", raw[pos + 4:pos + 8])[0]
        chunk = raw[pos + 8:pos + 8 + size]
        if stream_type in streams:
            out += chunk
        pos += 8 + size
    return out.decode("utf-8", errors="replace")


def exec_in_container(sock_path, container, cmd):
    """Run a command in a container through the podman API.

    Returns (exit code, stdout); exit code -1 means the exec never ran."""
    try:
        status, raw = podman_call(
            sock_path,
            "POST",
            "/containers/%s/exec" % container,
            {"Cmd": cmd, "AttachStdout": True, "AttachStderr": True},
        )
        if status not in (200, 201):
            return -1, ""
        exec_id = json.loads(raw.decode())["Id"]
        status, raw = podman_call(
            sock_path, "POST", "/exec/%s/start" % exec_id, {"Detach": False, "Tty": False}
        )
        if status != 200:
            return -1, ""
        stdout = demux_stream(raw)
        status, raw = podman_call(sock_path, "GET", "/exec/%s/json" % exec_id)
        exit_code = json.loads(raw.decode()).get("ExitCode", -1) if status == 200 else -1
        return exit_code, stdout
    except (OSError, ValueError, KeyError, http.client.HTTPException):
        return -1, ""


def parse_share_config(text):
    """Parse `net conf list` output into {share: {param: value}}.

    Reads the configuration Samba actually serves, not what NS8 was asked for:
    an interface action can rewrite full_audit and silently drop operations."""
    shares = {}
    current = None
    for raw in (text or "").splitlines():
        if not raw.strip():
            continue
        header = RE_SHARE_HEADER.match(raw)
        if header:
            current = header.group("name")
            shares.setdefault(current, {})
            continue
        if current is None:
            continue
        param = RE_SHARE_PARAM.match(raw)
        if param:
            shares[current][param.group("key").strip()] = param.group("value").strip()
    return shares


def audit_profile(params):
    """What auditing is effectively configured for one share.

    Returns (audited, ops, tracks_sessions)."""
    raw_ops = (params.get("full_audit:success") or "").strip()
    ops = [op for op in raw_ops.split() if op and op.lower() != "none"]
    audited = bool(ops)
    tracks_sessions = all(op in ops for op in SESSION_OPS)
    return audited, ops, tracks_sessions


def classify_shares(shares):
    """Split configured shares into file shares, audited ones, and gaps."""
    file_shares = {}
    for name, params in shares.items():
        if name in BUILTIN_SHARES:
            continue
        file_shares[name] = params

    audited = {}
    unaudited = []
    no_sessions = []
    for name, params in sorted(file_shares.items()):
        is_audited, ops, tracks = audit_profile(params)
        if is_audited:
            audited[name] = ops
            if not tracks:
                no_sessions.append(name)
        else:
            unaudited.append(name)
    return file_shares, audited, unaudited, no_sessions


def parse_audit_rows(text):
    """Parse psql -tA -F| output of (share, username, op, result, count)."""
    rows = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or "|" not in line:
            continue
        parts = line.split("|")
        if len(parts) < 5:
            continue
        share, username, op, result = parts[0], parts[1], parts[2], parts[3]
        try:
            count = int(parts[4])
        except ValueError:
            continue
        rows.append(
            {
                "share": share,
                "username": username,
                "op": op,
                "result": result,
                "count": count,
            }
        )
    return rows


def summarize_rows(rows, known_shares):
    """Aggregate audit rows per share, keeping deleted shares visible."""
    per_share = {}
    orphans = {}
    for row in rows:
        bucket = per_share.setdefault(
            row["share"],
            {"events": 0, "users": {}, "ops": {}, "failures": 0,
             "connects": 0, "disconnects": 0},
        )
        bucket["events"] += row["count"]
        if row["username"]:
            bucket["users"][row["username"]] = (
                bucket["users"].get(row["username"], 0) + row["count"]
            )
        bucket["ops"][row["op"]] = bucket["ops"].get(row["op"], 0) + row["count"]
        if row["op"] == "connect":
            bucket["connects"] += row["count"]
        elif row["op"] == "disconnect":
            bucket["disconnects"] += row["count"]
        # psql prints the raw result column; anything not "ok" is a refusal.
        if row["result"] and row["result"].lower() != "ok":
            bucket["failures"] += row["count"]

    for name, bucket in per_share.items():
        if name not in known_shares:
            orphans[name] = bucket
    return per_share, orphans


def service_token(value):
    """Make a share name safe to use inside a CheckMK service name."""
    token = re.sub(r"[^A-Za-z0-9._-]+", "_", value or "").strip("_")
    return token or "unknown"


def top_names(counter, limit=3):
    if not counter:
        return "none"
    ordered = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    return ", ".join("%s(%d)" % (name, count) for name, count in ordered)


def evaluate_coverage(config_ok, file_shares, audited, unaudited, no_sessions, err=""):
    """The central guard: is folder access recorded at all?"""
    total = len(file_shares)
    perf = "shares=%d|audited=%d|unaudited=%d|without_session_tracking=%d" % (
        total,
        len(audited),
        len(unaudited),
        len(no_sessions),
    )
    if not config_ok:
        return (
            3,
            perf,
            "UNKNOWN [%s]: the effective Samba share configuration could not be "
            "read (%s), so audit coverage cannot be confirmed" % (CTRL_COVERAGE, err),
        )
    # A structural limit that is true in every case, so it is always stated.
    limit = (
        "note: a refused connection is never recorded here (full_audit only "
        "loads after a share connection succeeds)"
    )
    if total == 0:
        return (
            0,
            perf,
            "OK [%s]: no file shares are defined on this node, so there is no "
            "folder access to record; %s" % (CTRL_COVERAGE, limit),
        )
    if not audited:
        return (
            2,
            perf,
            "CRITICAL [%s]: none of the %d file shares has auditing enabled (%s) "
            "- accesses to them are not recorded at all, and an unaudited share "
            "is indistinguishable from an unused one; %s"
            % (CTRL_COVERAGE, total, ", ".join(sorted(unaudited)), limit),
        )
    notes = []
    state = 0
    if unaudited:
        state = max(state, 1)
        notes.append(
            "%d share(s) without auditing (%s): their activity is invisible, "
            "not absent" % (len(unaudited), ", ".join(sorted(unaudited)))
        )
    if no_sessions:
        state = max(state, 1)
        notes.append(
            "%d audited share(s) (%s) do not record connect/disconnect, so no "
            "folder login or logout exists for them" % (len(no_sessions), ", ".join(sorted(no_sessions)))
        )
    label = {0: "OK", 1: "WARNING", 2: "CRITICAL"}[state]
    message = "%s [%s]: %d of %d file shares audited" % (
        label,
        CTRL_COVERAGE,
        len(audited),
        total,
    )
    if notes:
        message += "; " + "; ".join(notes)
    message += "; " + limit
    return (state, perf, message)


def evaluate_sessions(db_ok, per_share, audited, window_hours, orphans, err=""):
    """Folder logins and logouts, across every audited share."""
    connects = sum(b["connects"] for name, b in per_share.items() if name in audited)
    disconnects = sum(
        b["disconnects"] for name, b in per_share.items() if name in audited
    )
    users = {}
    for name, bucket in per_share.items():
        if name not in audited:
            continue
        for user, count in bucket["users"].items():
            users[user] = users.get(user, 0) + count
    perf = "connects=%d|disconnects=%d|distinct_users=%d|audited_shares=%d" % (
        connects,
        disconnects,
        len(users),
        len(audited),
    )
    if not db_ok:
        return (
            3,
            perf,
            "UNKNOWN [%s]: the Samba audit database could not be queried (%s) - "
            "this is not evidence that nobody opened a folder"
            % (CTRL_SESSIONS, err),
        )
    if not audited:
        return (
            3,
            perf,
            "UNKNOWN [%s]: no share records connect/disconnect, so folder "
            "logins and logouts cannot be reported" % CTRL_SESSIONS,
        )
    tail = ""
    if orphans:
        tail = "; %d share(s) in the audit history no longer exist (%s)" % (
            len(orphans),
            ", ".join(sorted(orphans)),
        )
    if connects == 0 and disconnects == 0:
        return (
            0,
            perf,
            "OK [%s]: no folder logins in the last %dh on %d audited share(s)%s"
            % (CTRL_SESSIONS, window_hours, len(audited), tail),
        )
    still_open = connects - disconnects
    open_note = ""
    if still_open > 0:
        open_note = ", %d still connected (or connected before the window)" % still_open
    elif still_open < 0:
        open_note = ", %d disconnects belong to sessions opened earlier" % (-still_open)
    return (
        0,
        perf,
        "OK [%s]: %d folder logins / %d logouts in %dh; users %s%s%s"
        % (
            CTRL_SESSIONS,
            connects,
            disconnects,
            window_hours,
            top_names(users),
            open_note,
            tail,
        ),
    )


def evaluate_share(name, ops, bucket, window_hours):
    """One audited share: what was recorded on it."""
    if bucket is None:
        bucket = {"events": 0, "users": {}, "ops": {}, "failures": 0,
                  "connects": 0, "disconnects": 0}
    perf = "events=%d|connects=%d|disconnects=%d|failures=%d|distinct_users=%d" % (
        bucket["events"],
        bucket["connects"],
        bucket["disconnects"],
        bucket["failures"],
        len(bucket["users"]),
    )
    tracks = all(op in ops for op in SESSION_OPS)
    scope = "auditing %s" % ", ".join(ops[:6]) if ops else "auditing nothing"
    if bucket["events"] == 0:
        detail = (
            "OK [%s]: no recorded activity in the last %dh (%s)"
            % (CTRL_ACCESS, window_hours, scope)
        )
        if not tracks:
            detail += "; connect/disconnect are not audited, so an open folder would not appear here"
        return (0, perf, detail)
    message = (
        "OK [%s]: %d recorded operations in %dh (%d logins / %d logouts); "
        "users %s; operations %s"
        % (
            CTRL_ACCESS,
            bucket["events"],
            window_hours,
            bucket["connects"],
            bucket["disconnects"],
            top_names(bucket["users"]),
            top_names(bucket["ops"]),
        )
    )
    if not tracks:
        message += "; connect/disconnect are not audited on this share"
    if bucket["failures"]:
        return (
            1,
            perf,
            message.replace("OK [", "WARNING [", 1)
            + "; %d operation(s) were refused" % bucket["failures"],
        )
    return (0, perf, message)


def query_audit(sock_path, window_hours):
    """Fetch the windowed aggregate from the audit database."""
    sql = (
        "SELECT share, username, op, result, count(*) FROM %s "
        "WHERE time > now() - interval '%d hours' "
        "GROUP BY 1,2,3,4;" % (AUDIT_TABLE, window_hours)
    )
    code, out = exec_in_container(
        sock_path,
        AUDIT_CONTAINER,
        ["psql", "-U", AUDIT_DB_USER, "-d", AUDIT_DB, "-t", "-A", "-F", "|", "-c", sql],
    )
    if code != 0:
        return None, "audit-db-unreachable"
    return parse_audit_rows(out), ""


def read_share_config(sock_path):
    """Fetch the effective share configuration from the Samba registry."""
    code, out = exec_in_container(
        sock_path, SAMBA_CONTAINER, ["net", "conf", "list"]
    )
    if code != 0:
        return None, "samba-config-unreadable"
    return parse_share_config(out), ""


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

    sample = """[nis-audited]
\tpath = /srv/shares/nis-audited
\tcomment = audited share
\tfull_audit:success = connect disconnect create_file mkdirat
\tfull_audit:failure = connect disconnect create_file mkdirat

[nis-unaudited]
\tpath = /srv/shares/nis-unaudited
\tcomment = control share

[legacy-noconnect]
\tpath = /srv/shares/legacy
\tfull_audit:success = create_file unlinkat renameat mkdirat fsetxattr

[sysvol]
\tpath = /var/lib/samba/sysvol
"""

    shares = parse_share_config(sample)
    expect("share configuration is parsed into shares and parameters",
           set(shares) == {"nis-audited", "nis-unaudited", "legacy-noconnect", "sysvol"},
           str(sorted(shares)))
    expect("share parameters are read",
           shares["nis-audited"]["path"] == "/srv/shares/nis-audited",
           str(shares["nis-audited"]))

    file_shares, audited, unaudited, no_sessions = classify_shares(shares)
    expect("Active Directory built-in shares are not treated as file shares",
           "sysvol" not in file_shares, str(sorted(file_shares)))
    expect("an audited share is detected from the effective configuration",
           "nis-audited" in audited, str(sorted(audited)))
    expect("a share without full_audit is reported as unaudited",
           unaudited == ["nis-unaudited"], str(unaudited))
    expect("an audited share lacking connect/disconnect is flagged separately",
           no_sessions == ["legacy-noconnect"], str(no_sessions))

    # The reason this check exists.
    st, _perf, msg = evaluate_coverage(True, file_shares, audited, unaudited, no_sessions)
    expect("an unaudited share warns and is named",
           st == 1 and "nis-unaudited" in msg, msg)
    expect("the message says invisible, not absent",
           "invisible, not absent" in msg, msg)
    expect("the refused-connection limit is always stated",
           "refused connection is never recorded" in msg, msg)
    expect("a share without connect/disconnect is called out",
           "no folder login or logout exists" in msg, msg)

    st, _perf, msg = evaluate_coverage(True, {"a": {}, "b": {}}, {}, ["a", "b"], [])
    expect("no auditing at all on existing shares is CRITICAL",
           st == 2 and "indistinguishable from an unused one" in msg, msg)

    st, _perf, msg = evaluate_coverage(True, {}, {}, [], [])
    expect("a node with no file shares is OK, not a failure",
           st == 0 and "no file shares are defined" in msg, msg)

    st, _perf, msg = evaluate_coverage(False, {}, {}, [], [], err="samba-config-unreadable")
    expect("an unreadable configuration is UNKNOWN, never OK",
           st == 3 and "cannot be confirmed" in msg, msg)

    # --- audit rows ---
    raw = (
        "nis-audited|NETHLAB\\nistest03|connect|ok|2\n"
        "nis-audited|NETHLAB\\nistest03|disconnect|ok|2\n"
        "nis-audited|NETHLAB\\nistest03|create_file|ok|5\n"
        "nis-audited|NETHLAB\\nistest03|create_file|fail (Success)|1\n"
        "audittest|NETHLAB\\DC1_|create_file|ok|7\n"
    )
    rows = parse_audit_rows(raw)
    expect("audit rows are parsed", len(rows) == 5, str(rows))

    per_share, orphans = summarize_rows(rows, {"nis-audited"})
    expect("events are aggregated per share",
           per_share["nis-audited"]["events"] == 10, str(per_share["nis-audited"]))
    expect("connects and disconnects are counted",
           per_share["nis-audited"]["connects"] == 2
           and per_share["nis-audited"]["disconnects"] == 2,
           str(per_share["nis-audited"]))
    expect("a non-ok result counts as a refused operation",
           per_share["nis-audited"]["failures"] == 1, str(per_share["nis-audited"]))
    expect("history from a deleted share is kept separate, not attributed",
           set(orphans) == {"audittest"}, str(sorted(orphans)))

    st, _perf, msg = evaluate_sessions(
        True, per_share, {"nis-audited": ["connect", "disconnect"]}, 24, orphans
    )
    expect("folder logins and logouts are reported",
           st == 0 and "2 folder logins / 2 logouts" in msg, msg)
    expect("deleted shares are disclosed, not silently dropped",
           "no longer exist" in msg and "audittest" in msg, msg)

    st, _perf, msg = evaluate_sessions(False, {}, {"x": []}, 24, {}, err="audit-db-unreachable")
    expect("an unreachable audit database is UNKNOWN, never OK",
           st == 3 and "not evidence that nobody opened a folder" in msg, msg)

    st, _perf, msg = evaluate_sessions(True, {}, {}, 24, {})
    expect("with nothing recording sessions the result is UNKNOWN",
           st == 3 and "cannot be reported" in msg, msg)

    st, _perf, msg = evaluate_sessions(
        True, {}, {"nis-audited": ["connect", "disconnect"]}, 24, {}
    )
    expect("an audited but quiet share reports no logins as OK",
           st == 0 and "no folder logins" in msg, msg)

    # --- per share ---
    st, perf, msg = evaluate_share(
        "nis-audited", ["connect", "disconnect", "create_file"],
        per_share["nis-audited"], 24
    )
    expect("a share with refused operations warns",
           st == 1 and "refused" in msg, msg)
    expect("per-share perfdata is emitted",
           "connects=2" in perf and "events=10" in perf, perf)

    st, _perf, msg = evaluate_share("quiet", ["connect", "disconnect"], None, 24)
    expect("an audited share with no activity is OK and says so",
           st == 0 and "no recorded activity" in msg, msg)

    st, _perf, msg = evaluate_share("legacy", ["create_file"], None, 24)
    expect("a share not auditing sessions warns the reader in the message",
           "would not appear here" in msg, msg)

    expect("share names are made safe for service names",
           service_token("my share/one") == "my_share_one",
           service_token("my share/one"))

    print("")
    print("%d/%d checks passed" % (ran - failures, ran))
    sys.exit(1 if failures else 0)


def check():
    instances = find_samba_instances()
    if not instances:
        # No samba module on this node: emit nothing rather than invent
        # services that would then go stale.
        return

    print(LOCAL_SECTION)
    for instance in instances:
        prefix = "" if len(instances) == 1 else "%s." % instance
        err, sock_path = podman_socket(instance)
        if err:
            unknown = (
                "UNKNOWN: the podman API socket of module %s is not available "
                "(%s), so Samba auditing cannot be inspected" % (instance, err)
            )
            print(local_line(3, prefix + SVC_COVERAGE, "-", unknown))
            print(local_line(3, prefix + SVC_SESSIONS, "-", unknown))
            continue

        shares, cfg_err = read_share_config(sock_path)
        config_ok = shares is not None
        file_shares, audited, unaudited, no_sessions = classify_shares(shares or {})

        st, perf, msg = evaluate_coverage(
            config_ok, file_shares, audited, unaudited, no_sessions, err=cfg_err
        )
        print(local_line(st, prefix + SVC_COVERAGE, perf, msg))

        rows, db_err = query_audit(sock_path, WINDOW_HOURS)
        db_ok = rows is not None
        per_share, orphans = summarize_rows(rows or [], set(file_shares))

        st, perf, msg = evaluate_sessions(
            db_ok, per_share, audited, WINDOW_HOURS, orphans, err=db_err
        )
        print(local_line(st, prefix + SVC_SESSIONS, perf, msg))

        if not db_ok:
            continue
        for name in sorted(audited):
            st, perf, msg = evaluate_share(
                name, audited[name], per_share.get(name), WINDOW_HOURS
            )
            print(
                local_line(
                    st,
                    "%s%s.%s" % (prefix, SVC_ACCESS, service_token(name)),
                    perf,
                    msg,
                )
            )


if "--self-test" in sys.argv:
    self_test()
else:
    check()
