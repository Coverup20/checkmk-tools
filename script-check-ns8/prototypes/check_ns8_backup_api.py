#!/usr/bin/env python3
"""check_ns8_backup_api.py - NS8 backup monitoring for CheckMK, REST API only (PROTOTYPE)

CheckMK local check, to run ON the NS8 node. No subprocess. Everything goes through REST:
- NS8 API (NS8_API, default http://127.0.0.1:9311/api), logged in with NS8_USER / NS8_PASSWORD_FILE:
  cluster list-backups (every backup, its instances and their last run: start, end, success, size, files,
  snapshots; status is null until the first run) and list-backup-repositories;
- Grafana -> Loki through the node's own Traefik (connect to 127.0.0.1:443 with SNI/Host = the node FQDN) for the
  backup errors the node agent writes to the journal.

Services (local check on the agent host, or piggybacked when NS8_PIGGYBACK_HOST is set):
- NS8.Backup.<backup>.<module>  one service per protected instance: when it last completed, how long it took, files,
                                size, snapshots. WARN if it never ran, the backup is disabled, or the last success is
                                older than 1.5 x the scheduled interval (+1 h); CRIT if the last run failed or the last
                                success is older than 3 x the interval (+2 h); WARN while the node agent is retrying
                                against the destination (the cause is in the text).
- NS8.Backup.Unprotected        module instances that are in no backup (WARN, BACKUP_UNPROTECTED_STATE=0 to only report).
- NS8.Backup.Destinations       backup repositories and the errors seen talking to them in the last WINDOW_MIN minutes:
                                CRIT when the upload of the cluster backup failed, WARN while restic is retrying,
                                with the cause: destination unreachable, credentials/permissions, no space, HTTP error.

What was verified on the lab node and what was not:
- verified: successful runs, never-run backups, destination unreachable (the rclone gateway stopped: NS8 retries on its own
  and the run completes when the destination is back, so a short outage is only seen in the log lines and as a stale status),
  the log lines "returned error, retrying", "upload of cluster backup GPG file failed", "(retry)", HTTP 500 from the gateway;
- NOT verified (no way to provoke it on the lab): the exact log wording for wrong credentials and for a full destination;
  those causes are recognised by pattern (401/403/permission denied/logon failure; no space left/quota/507) and anything
  else is shown as "other" with the first error line;
- status.success=false is handled but was not seen either: NS8 retries first.

The same API cache as check_ns8_auth_api.py: NS8_BACKUP_CACHE (default /var/lib/ns8-backup-cache.json, mode 600): API token
until it expires, list-backups for BACKUP_TTL seconds (300), node FQDN once.

Version: 0.1.0"""

import base64
import datetime
import http.client
import json
import os
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

VERSION = "0.1.1"
NS8_API = os.environ.get("NS8_API", "http://127.0.0.1:9311/api")
NS8_USER = os.environ.get("NS8_USER", "claude-ro")
NS8_PASSWORD_FILE = os.environ.get("NS8_PASSWORD_FILE", "/root/.ns8-ro-pass")
NODE_FQDN = os.environ.get("NS8_NODE_FQDN", "")
PIGGYBACK_HOST = os.environ.get("NS8_PIGGYBACK_HOST", "")  # empty: plain local-check lines for the agent host itself


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


WINDOW_MIN = env_int("WINDOW_MIN", 30)
BACKUP_TTL = env_int("BACKUP_TTL", 300)
UNPROTECTED_STATE = env_int("BACKUP_UNPROTECTED_STATE", 1)
WARN_FACTOR, CRIT_FACTOR, WARN_GRACE_H, CRIT_GRACE_H = 1.5, 3.0, 1.0, 2.0
CACHE_FILE = os.environ.get("NS8_BACKUP_CACHE", "/var/lib/ns8-backup-cache.json")
LOGIN_TRIES = 3
LOKI_LIMIT = 2000
SVC_UNPROTECTED, SVC_DEST = "NS8.Backup.Unprotected", "NS8.Backup.Destinations"
# Loki filters the RAW journal line: no angle brackets, and brackets in character classes only
LOKI_BACKUP_ERRORS = r"(?i)returned error, retrying|upload of cluster backup GPG file failed|backup [0-9]+ failed|backup [0-9]+ completed [(]retry[)]|[[]ERROR[]].*backup"

STATE_WORD = {0: "OK", 1: "WARN", 2: "CRIT", 3: "UNKNOWN"}

# ---------------------------------------------------------------- NS8 REST API (same as check_ns8_auth_api.py)


class Api(object):
    def __init__(self, base=NS8_API):
        self.base = base
        self.token = ""

    def _req(self, method, path, body=None):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(self.base + path, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, json.loads(r.read().decode("utf-8", "replace") or "{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode("utf-8", "replace") or "{}")
            except ValueError:
                return e.code, {}
        except (urllib.error.URLError, OSError, ValueError):
            return 0, {}

    def login(self, user, password):
        st, js = self._req("POST", "/login", json.dumps({"username": user, "password": password}).encode())
        data = js.get("data")
        tok = data.get("token") if isinstance(data, dict) else js.get("token")
        if st == 200 and tok:
            self.token = tok
            return ""
        return "login failed (HTTP %s)" % st if st else "NS8 API unreachable at %s" % self.base

    def task(self, agent, action, data=None, timeout=20):
        """Run an action; returns (state, output) with state ok|denied|validation|timeout|error."""
        st, js = self._req("POST", "/%s/tasks" % agent, json.dumps({"action": action, "data": data, "parent": "", "extra": {}}).encode())
        if st in (401, 403):
            return "denied", None
        tid = (js.get("data") or {}).get("id") if isinstance(js.get("data"), dict) else None
        if not tid:
            return "error", None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            st, js = self._req("GET", "/%s/task/%s/status" % (agent, tid))
            if st == 200:
                d = js.get("data") or {}
                out = d.get("output")
                if isinstance(out, str):
                    try:
                        out = json.loads(out)
                    except ValueError:
                        pass
                ec = d.get("exit_code")
                return ("ok" if ec == 0 else "validation" if ec == 2 else "error"), out
            if st in (401, 403):
                return "denied", None
            time.sleep(0.25)  # 400 "redis: nil" = still running
        return "timeout", None


def jwt_exp(token):
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        return int(json.loads(base64.urlsafe_b64decode(part.encode())).get("exp", 0))
    except (IndexError, ValueError, TypeError):
        return 0


def load_cache():
    try:
        with open(CACHE_FILE, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cache(d):
    try:
        tmp = CACHE_FILE + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(d, fh)
        os.replace(tmp, CACHE_FILE)
    except OSError:
        pass


class Session(object):
    """One NS8 API login per run, none when a still-valid token is cached; login retried on HTTP 503."""

    def __init__(self, user, password, cache):
        self.api, self.user, self.password, self.cache = Api(), user, password, cache
        self.ready = self.fresh = False

    def _login(self):
        err = ""
        for attempt in range(LOGIN_TRIES):
            err = self.api.login(self.user, self.password)
            if not err:
                break
            time.sleep(2 * (attempt + 1))
        if not err:
            self.cache["token"], self.cache["token_exp"] = self.api.token, jwt_exp(self.api.token)
            self.fresh = self.ready = True
        return err

    def task(self, agent, action, data=None, timeout=20):
        if not self.ready:
            tok = self.cache.get("token")
            if tok and self.cache.get("token_exp", 0) > time.time() + 120:
                self.api.token, self.ready = tok, True
            else:
                err = self._login()
                if err:
                    return err, None
        st, out = self.api.task(agent, action, data, timeout)
        if st == "denied" and not self.fresh:
            err = self._login()
            if err:
                return err, None
            st, out = self.api.task(agent, action, data, timeout)
        return st, out


# ---------------------------------------------------------------- Grafana -> Loki

class LocalHttps(http.client.HTTPSConnection):
    """Connects to 127.0.0.1:443 but presents the node FQDN (SNI and Host), like a browser would."""

    def __init__(self, sni):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE  # self-signed certificate, local connection
        http.client.HTTPSConnection.__init__(self, "127.0.0.1", 443, context=ctx, timeout=30)
        self._sni = sni

    def connect(self):
        sock = socket.create_connection(("127.0.0.1", 443), 30)
        self.sock = self._context.wrap_socket(sock, server_hostname=self._sni)


class Loki(object):
    def __init__(self, fqdn, user, password):
        self.fqdn = fqdn
        self.auth = "Basic " + base64.b64encode(("%s:%s" % (user, password)).encode()).decode()
        self.uid = None

    def _get(self, path):
        c = LocalHttps(self.fqdn)
        try:
            c.request("GET", path, headers={"Host": self.fqdn, "Authorization": self.auth, "Accept": "application/json"})
            r = c.getresponse()
            return r.status, r.read().decode("utf-8", "replace")
        except (OSError, ssl.SSLError, http.client.HTTPException):
            return 0, ""
        finally:
            c.close()

    def open(self):
        st, raw = self._get("/grafana/api/datasources")
        if st != 200:
            return "Grafana answered HTTP %s" % st if st else "Grafana unreachable"
        try:
            self.uid = next((d["uid"] for d in json.loads(raw) if d.get("type") == "loki"), None)
        except (ValueError, KeyError):
            self.uid = None
        return "" if self.uid else "no Loki data source in Grafana"

    def lines(self, regex, minutes):
        """Journal lines (any module or node service) matching a regex in the last N minutes: ([(epoch, message)], error)."""
        end_ns = int(time.time()) * 10 ** 9
        q = '{job=~".+"} |~ `%s`' % regex
        path = "/grafana/api/datasources/proxy/uid/%s/loki/api/v1/query_range?query=%s&start=%d&end=%d&limit=%d&direction=forward" % (
            self.uid, urllib.parse.quote(q), end_ns - minutes * 60 * 10 ** 9, end_ns, LOKI_LIMIT)
        st, raw = self._get(path)
        if st != 200:
            return [], "Loki answered HTTP %s" % st if st else "Loki unreachable"
        out = []
        try:
            for s in json.loads(raw).get("data", {}).get("result", []):
                for ts, ln in s["values"]:
                    try:
                        msg = json.loads(ln).get("MESSAGE", ln)
                    except ValueError:
                        msg = ln
                    if "/grafana/api/datasources" in msg:  # Grafana's own access log echoes our query
                        continue
                    out.append((int(ts) / 1e9, msg))
        except (ValueError, KeyError):
            return [], "unexpected Loki answer"
        return sorted(out), ""


# ---------------------------------------------------------------- pure logic

DOW = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def expected_interval_h(schedule):
    """Longest expected gap in hours between two runs of a systemd calendar expression; (hours, understood)."""
    s = (schedule or "").strip().lower()
    named = {"minutely": 1 / 60.0, "hourly": 1, "daily": 24, "weekly": 168, "monthly": 31 * 24, "quarterly": 92 * 24, "yearly": 366 * 24, "annually": 366 * 24}
    if s in named:
        return float(named[s]), True
    if not s:
        return 48.0, False
    days = None
    date_tok = time_tok = None
    for tok in s.split():
        if re.match(r"^[a-z]{3}", tok) and re.match(r"^[a-z,.\-]+$", tok):
            sel = set()
            for part in tok.split(","):
                if ".." in part or "-" in part:
                    a, b = re.split(r"\.\.|-", part, 1)
                    if a[:3] in DOW and b[:3] in DOW:
                        i = DOW[a[:3]]
                        while True:
                            sel.add(i)
                            if i == DOW[b[:3]]:
                                break
                            i = (i + 1) % 7
                elif part[:3] in DOW:
                    sel.add(DOW[part[:3]])
            days = sel or days
        elif re.match(r"^[0-9*]+-[0-9*]+-[0-9*,.]+$|^[0-9*]+-[0-9*,.]+$", tok):
            date_tok = tok
        elif ":" in tok:
            time_tok = tok
    hours_gap = 24.0
    if time_tok:
        hh = time_tok.split(":")[0]
        if hh == "*" or "/" in hh or "," in hh:
            hours_gap = 1.0 if hh == "*" or "/" in hh else 24.0
            if "," in hh:
                try:
                    hs = sorted(int(x) for x in hh.split(","))
                    hours_gap = max([b - a for a, b in zip(hs, hs[1:])] + [24 - hs[-1] + hs[0]])
                except ValueError:
                    hours_gap = 24.0
    if date_tok:
        dom = date_tok.split("-")[-1]
        if dom not in ("*", "*/1"):
            return 31 * 24.0, True
    if days:
        ds = sorted(days)
        gap = max([b - a for a, b in zip(ds, ds[1:])] + [7 - ds[-1] + ds[0]]) if len(ds) > 1 else 7
        return gap * 24.0, True
    if time_tok or date_tok:
        return hours_gap, True
    return 48.0, False


def human_bytes(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return ("%d %s" % (n, unit)) if unit == "B" else "%.1f %s" % (n, unit)
        n /= 1024.0


def human_age(sec):
    sec = max(0, int(sec))
    if sec < 3600:
        return "%d min" % (sec // 60)
    if sec < 86400:
        return "%.1f h" % (sec / 3600.0)
    return "%.1f days" % (sec / 86400.0)


CAUSES = (
    ("destination unreachable", re.compile(r"connection refused|no route to host|max retries exceeded|dial tcp|read timed out|i/o timeout|timed out|no such host|name or service not known|network is unreachable|unexpected eof", re.I)),
    ("credentials or permissions", re.compile(r"\b40[13]\b|unauthorized|forbidden|permission denied|access denied|logon.failure|authentication failed|invalid (credentials|password|access key)|accessdenied|signaturedoesnotmatch", re.I)),
    ("no space on the destination", re.compile(r"no space left|quota exceeded|insufficient storage|\b507\b|disk full|storagefull", re.I)),
)


def classify(msg):
    for name, rx in CAUSES:
        if rx.search(msg):
            return name
    m = re.search(r"HTTP response \((\d{3})\)", msg)
    if m:
        return "destination answered HTTP %s" % m.group(1)
    return "other"


def sanitize(name):
    name = re.sub(r"[^a-zA-Z0-9]", ".", name or "")
    return re.sub(r"\.{2,}", ".", name).strip(".") or "backup"


def module_of(msg):
    m = re.search(r"module/([A-Za-z0-9_-]+):", msg) or re.search(r"\b([a-z][a-z0-9-]*[0-9]+): backup [0-9]+", msg)
    return m.group(1) if m else ""


def eval_instance(bk, inst, now, retries):
    """-> (state, text, perf). retries: list of (epoch, message) error lines that mention this module."""
    interval, known = expected_interval_h(bk.get("schedule", ""))
    sched = "schedule '%s'%s" % (bk.get("schedule", ""), "" if known else " (not understood, assuming 48 h)")
    st = inst.get("status")
    notes, recovered = [], ""
    errs = [r for r in retries if not re.search(r"completed [(]retry[)]", r[1], re.I)]
    last_end = (st or {}).get("end") or 0
    if errs and errs[-1][0] > last_end:
        notes.append("destination errors in the last %d min (%s), NS8 is retrying" % (WINDOW_MIN, classify(errs[-1][1])))
    elif errs and last_end:
        recovered = " (recovered: completed after %d destination errors)" % len(errs)
    if not bk.get("enabled", True):
        return 1, "backup '%s' is disabled; %s" % (bk.get("name", ""), sched), "-"
    if not st:
        return 1, "never ran yet; %s" % sched, "-"
    end, start = st.get("end") or 0, st.get("start") or 0
    age = now - end
    perf = "backup_age_s=%d;%d;%d;0;|backup_duration_s=%d;;;0;|backup_size_bytes=%d;;;0;|backup_files=%d;;;0;|backup_snapshots=%d;;;0;" % (
        age, int((interval * WARN_FACTOR + WARN_GRACE_H) * 3600), int((interval * CRIT_FACTOR + CRIT_GRACE_H) * 3600),
        max(0, end - start), st.get("total_size") or 0, st.get("total_file_count") or 0, st.get("snapshots_count") or 0)
    detail = "%s ago, took %d s, %d files, %s, %d snapshots; %s" % (human_age(age), max(0, end - start), st.get("total_file_count") or 0,
                                                                   human_bytes(st.get("total_size")), st.get("snapshots_count") or 0, sched)
    if st.get("success") is False:
        return 2, "last run FAILED %s" % detail + ("; " + "; ".join(notes) if notes else ""), perf
    warn_s, crit_s = (interval * WARN_FACTOR + WARN_GRACE_H) * 3600, (interval * CRIT_FACTOR + CRIT_GRACE_H) * 3600
    if age > crit_s:
        return 2, "last success %s, too old (expected every ~%s)" % (detail, human_age(interval * 3600)) + ("; " + "; ".join(notes) if notes else ""), perf
    if age > warn_s:
        return 1, "last success %s, overdue (expected every ~%s)" % (detail, human_age(interval * 3600)) + ("; " + "; ".join(notes) if notes else ""), perf
    if notes:
        return 1, "last success %s; %s" % (detail, "; ".join(notes)), perf
    return 0, "last success %s%s" % (detail, recovered), perf


def eval_unprotected(unconf):
    ids = sorted(i.get("id", "?") for i in unconf)
    if not ids:
        return 0, "every module instance is in a backup", "unprotected=0;;;0;"
    return UNPROTECTED_STATE, "%d module instances in no backup: %s" % (len(ids), ", ".join(ids)), "unprotected=%d;;;0;" % len(ids)


def eval_destinations(repos, error_lines, ends=None):
    """repos: [{name, provider}], error_lines: [(epoch, message)], ends: {module: end of its last run} ->
    (state, text, perf). An error line is resolved when its module completed a run after it; a line without a module
    (HTTP errors, the cluster backup upload) when any instance completed after it."""
    ends = ends or {}
    names = ", ".join("%s (%s)" % (r.get("name", "?"), r.get("provider", "?")) for r in repos) or "none"
    if not repos:
        return 1, "no backup destination configured", "destinations=0;;;0;|dest_errors=0;;;0;"
    newest = max([v for v in ends.values() if v] or [0])  # any run that completed after a line proves the destination works
    is_err = re.compile(r"upload of cluster backup GPG file failed|returned error, retrying", re.I)
    errs = [(t, m) for t, m in error_lines if is_err.search(m)]
    live = [(t, m) for t, m in errs if not ((ends.get(module_of(m)) or newest) >= t)]
    perf = "destinations=%d;;;0;|dest_errors=%d;;;0;" % (len(repos), len(errs))
    upload_fail = [m for t, m in live if re.search(r"upload of cluster backup GPG file failed", m, re.I)]
    retrying = [m for t, m in live if not re.search(r"upload of cluster backup GPG file failed", m, re.I)]
    if upload_fail:
        return 2, "upload to the destination failed in the last %d min (%s); destinations: %s" % (WINDOW_MIN, classify(upload_fail[-1]), names), perf
    if retrying:
        causes = sorted(set(classify(m) for m in retrying))
        return 1, "restic is retrying against the destination (%s), %d error lines in the last %d min; destinations: %s" % (", ".join(causes), len(retrying), WINDOW_MIN, names), perf
    if errs:
        return 0, "recovered: %d destination errors until %s, the backups completed afterwards; destinations: %s" % (
            len(errs), time.strftime("%H:%M", time.localtime(max(t for t, _ in errs))), names), perf
    return 0, "%d destinations, no errors in the last %d min: %s" % (len(repos), WINDOW_MIN, names), perf


def line(state, name, text, perf="-"):
    return "%d %s %s %s: %s" % (state, name, perf or "-", STATE_WORD[state], text.replace("\n", " "))


def emit_local(text):
    if PIGGYBACK_HOST:
        print("<<<<%s>>>>" % PIGGYBACK_HOST)
        print("<<<local:sep(0)>>>")
        print(text)
        print("<<<<>>>>")
    else:
        # the other local checks close their piggyback block with <<<<>>>>, after which the agent host has no open section
        print("<<<local:sep(0)>>>")
        print(text)


# ---------------------------------------------------------------- self test

def self_test():
    fails, count = [], [0]

    def check(name, cond):
        count[0] += 1
        if not cond:
            fails.append(name)
    check("daily", expected_interval_h("*-*-* 02:00:00") == (24.0, True))
    check("weekdays", expected_interval_h("Mon..Fri *-*-* 02:00:00") == (72.0, True))
    check("weekly list", expected_interval_h("Mon,Thu *-*-* 03:00:00") == (96.0, True))
    check("monthly", expected_interval_h("*-*-01 04:00:00") == (744.0, True))
    check("hourly", expected_interval_h("*:00:00") == (1.0, True))
    check("keyword", expected_interval_h("weekly") == (168.0, True))
    check("unknown", expected_interval_h("") == (48.0, False))
    check("classify refused", classify('Head "http://x@127.0.0.1:4694/c": dial tcp 127.0.0.1:4694: connect: connection refused') == "destination unreachable")
    check("classify timeout", classify("upload failed: Read timed out. (read timeout=10)") == "destination unreachable")
    check("classify auth", classify("NT_STATUS_LOGON_FAILURE") == "credentials or permissions")
    check("classify space", classify("write: no space left on device") == "no space on the destination")
    check("classify http", classify("unexpected HTTP response (500): 500 Internal Server Error") == "destination answered HTTP 500")
    check("classify other", classify("something odd") == "other")
    check("module of", module_of('Head "http://module/metrics1:***@127.0.0.1:4694/x"') == "metrics1" and module_of("traefik1: backup 1 completed (retry)") == "traefik1")
    now = 1_000_000_000
    bk = {"name": "lab", "enabled": True, "schedule": "*-*-* 02:00:00"}
    ok = {"status": {"start": now - 3700, "end": now - 3600, "success": True, "total_size": 22589, "total_file_count": 33, "snapshots_count": 1}}
    check("ok", eval_instance(bk, ok, now, [])[0] == 0)
    old = {"status": dict(ok["status"], end=now - 40 * 3600, start=now - 40 * 3600 - 10)}
    check("overdue warn", eval_instance(bk, old, now, [])[0] == 1)
    vold = {"status": dict(ok["status"], end=now - 80 * 3600, start=now - 80 * 3600 - 10)}
    check("too old crit", eval_instance(bk, vold, now, [])[0] == 2)
    check("failed crit", eval_instance(bk, {"status": dict(ok["status"], success=False)}, now, [])[0] == 2)
    check("never ran warn", eval_instance(bk, {"status": None}, now, [])[0] == 1)
    check("disabled warn", eval_instance(dict(bk, enabled=False), ok, now, [])[0] == 1)
    check("retry warn", eval_instance(bk, ok, now, [(now, "Stat(<config/>) returned error, retrying: dial tcp: connection refused")])[0] == 1)
    check("unprotected ok", eval_unprotected([])[0] == 0 and eval_unprotected([{"id": "mail1"}])[0] == UNPROTECTED_STATE)
    repos = [{"name": "r", "provider": "smb"}]
    check("dest ok", eval_destinations(repos, [])[0] == 0)
    check("dest retry warn", eval_destinations(repos, [(1, "Stat(<config/>) returned error, retrying after 1s: dial tcp 127.0.0.1:4694: connection refused")])[0] == 1)
    check("dest upload crit", eval_destinations(repos, [(1, "[ERROR] upload of cluster backup GPG file failed: Read timed out")])[0] == 2)
    check("dest none warn", eval_destinations([], [])[0] == 1)
    check("dest recovered ok", eval_destinations(repos, [(100, "[ERROR] upload of cluster backup GPG file failed: Read timed out")], {"x": 200})[0] == 0)
    check("dest still failing", eval_destinations(repos, [(300, "[ERROR] upload of cluster backup GPG file failed: Read timed out")], {"x": 200})[0] == 2)
    check("dest line without module resolved by any later run", eval_destinations(repos, [(150, "Save(<index/x>) returned error, retrying after 1s: unexpected HTTP response (500)")], {"m1": 200})[0] == 0)
    check("dest line without module still open", eval_destinations(repos, [(250, "Save(<index/x>) returned error, retrying after 1s: unexpected HTTP response (500)")], {"m1": 200})[0] == 1)
    check("dest per module", eval_destinations(repos, [(150, 'Head "http://module/m1:***@127.0.0.1:4694/x": dial tcp: connection refused returned error, retrying')], {"m1": 100, "m2": 300})[0] == 1)
    check("dest per module resolved", eval_destinations(repos, [(150, 'Head "http://module/m1:***@127.0.0.1:4694/x": dial tcp: connection refused returned error, retrying')], {"m1": 200, "m2": 300})[0] == 0)
    check("instance recovered ok", eval_instance(bk, ok, now, [(now - 7200, "Stat(<config/>) returned error, retrying: dial tcp: connection refused")])[0] == 0)
    check("instance cause", "destination unreachable" in eval_instance(bk, ok, now, [(now - 60, "Stat(<config/>) returned error, retrying: dial tcp: connection refused"), (now - 10, "traefik1: backup 1 completed (retry)")])[1])
    if fails:
        print("SELF-TEST FAILED: " + ", ".join(fails))
        return 1
    print("self-test ok (%d checks)" % count[0])
    return 0


# ---------------------------------------------------------------- main

def main():
    if "--self-test" in sys.argv:
        return self_test()
    cache = load_cache()
    try:
        return run(cache)
    finally:
        save_cache(cache)


def run(cache):
    try:
        with open(NS8_PASSWORD_FILE, encoding="utf-8") as fh:
            password = fh.read().strip()
    except OSError as exc:
        emit_local(line(3, "NS8.Backup.Unprotected", "cannot read the password file %s: %s" % (NS8_PASSWORD_FILE, exc.strerror)))
        return 0
    api = Session(NS8_USER, password, cache)
    now = time.time()
    out = []

    lb = cache.get("backups") or {}
    if lb.get("data") is not None and now - lb.get("ts", 0) <= BACKUP_TTL:
        data, repos, stale = lb["data"], lb.get("repos", []), ""
    else:
        st, data = api.task("cluster", "list-backups", None, timeout=25)
        s2, rep = api.task("cluster", "list-backup-repositories", None, timeout=25)
        if st == "ok" and isinstance(data, dict):
            repos = [{"name": r.get("name"), "provider": r.get("provider")} for r in (rep.get("repositories", []) if s2 == "ok" and isinstance(rep, dict) else lb.get("repos", []))]
            cache["backups"] = {"ts": now, "data": data, "repos": repos}
            stale = ""
        elif lb.get("data") is not None:
            data, repos = lb["data"], lb.get("repos", [])
            stale = " (data from %d min ago: list-backups %s)" % ((now - lb.get("ts", 0)) // 60, st)
        else:
            emit_local("\n".join([line(3, SVC_UNPROTECTED, "list-backups: %s" % st), line(3, SVC_DEST, "list-backups: %s" % st)]))
            return 0

    fqdn = NODE_FQDN or cache.get("fqdn", "")
    if not fqdn:  # the node FQDN never changes in practice: asked once, then cached
        s5, cl = api.task("cluster", "get-cluster-status")
        url = (cl.get("leader_url") or (cl.get("cluster") or {}).get("leader_url")) if s5 == "ok" and isinstance(cl, dict) else None
        if url:
            fqdn = cache["fqdn"] = urllib.parse.urlparse(url).hostname or ""
    lines, lerr = [], ""
    if fqdn:
        loki = Loki(fqdn, NS8_USER, password)
        lerr = loki.open()
        if not lerr:
            lines, lerr = loki.lines(LOKI_BACKUP_ERRORS, WINDOW_MIN)
    else:
        lerr = "cannot work out the node FQDN (set NS8_NODE_FQDN)"
    by_module = {}
    for ts, msg in lines:
        mod = module_of(msg)
        if mod:
            by_module.setdefault(mod, []).append((ts, msg))

    for bk in data.get("backups", []):
        for inst in bk.get("instances", []):
            s_, t_, p_ = eval_instance(bk, inst, now, by_module.get(inst.get("module_id"), []))
            out.append(line(s_, "NS8.Backup.%s.%s" % (sanitize(bk.get("name")), inst.get("module_id")), t_ + stale, p_))
    s_, t_, p_ = eval_unprotected(data.get("unconfigured_instances", []))
    out.append(line(s_, SVC_UNPROTECTED, t_ + stale, p_))
    if lerr:
        out.append(line(3, SVC_DEST, "logs unavailable: %s" % lerr))
    else:
        ends = dict((i.get("module_id"), (i.get("status") or {}).get("end")) for bk in data.get("backups", []) for i in bk.get("instances", []))
        s_, t_, p_ = eval_destinations(repos, lines, ends)
        out.append(line(s_, SVC_DEST, t_, p_))
    emit_local("\n".join(sorted(out, key=lambda x: x.split(" ", 2)[1])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
