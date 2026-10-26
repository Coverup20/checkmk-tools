#!/usr/bin/env python3
"""check_ns8_fileserver_api.py - NS8 file server (Samba shares) monitoring for CheckMK, REST API only (PROTOTYPE)

CheckMK local check, to run ON the NS8 node. No subprocess. Everything goes through REST:
- NS8 API (NS8_API, default http://127.0.0.1:9311/api), logged in with NS8_USER / NS8_PASSWORD_FILE:
  the Samba module instances (cluster list-installed-modules) and their shares (module list-shares: ACLs, audit,
  failed-event logging, recycle bin);
- Grafana -> the SambaAudit PostgreSQL data source through the node's own Traefik (connect to 127.0.0.1:443 with
  SNI/Host = the node FQDN, POST /grafana/api/ds/query): table samba_audit (time, proto, username, addr, share, op,
  result, path, aux), one row per file operation of every share that has the audit switched on.

Services (piggybacked to NS8_PIGGYBACK_HOST, default NS8-RL98-SAMBA):
- NS8.Files.FailedAccess  file operations refused in the last WINDOW_MIN minutes: access denied by the share ACLs
                          (the audit logs them as result "fail (Success)": the ACL refusal carries no errno),
                          unix permission errors, and storage errors (no space, quota, read-only, I/O error).
                          WARN >= ACCESS_WARN denied, CRIT >= ACCESS_CRIT denied or any storage error. Files that
                          do not exist ("No such file or directory") are normal application probing: counted in the
                          perfdata only. Top users and shares are in the text.
- NS8.Files.BlockedUsers  users refused at least BLOCK_MIN_FAILS times on a share in the window without a single
                          successful operation there (typically "I cannot open the network folder"): WARN >=
                          BLOCK_WARN users, CRIT >= BLOCK_CRIT.
- NS8.Files.Shares        the shares of every Samba instance: how many, which ones have no audit (their failed
                          accesses are invisible to the two checks above), audit without failed-event logging, no
                          recycle bin. Informational (OK) unless SHARES_AUDIT_STATE is set to 1 or 2.

What was verified on the lab node and what was not:
- verified: allowed and refused accesses from an SMB client against two audited shares (refused = result "fail
  (Success)", missing file = "fail (No such file or directory)"), a wrong password (not in the share audit at all: it
  is an authentication failure, see check_ns8_auth_api.py for mail), the SQL path through Grafana, the audit-off case;
- NOT verified (not provoked): the errno wording for storage errors and unix permission errors, which are recognised by
  the standard glibc texts; a share that is full.

Known limits: shares without audit are blind; file operations by the Samba service account over loopback are ignored;
the audit table is only as old as the retention of the audit database.

The NS8 API token, the share list (SHARES_TTL seconds, default 300), the Samba module list and the audit data source id
are cached in NS8_FILES_CACHE (default /var/lib/ns8-files-cache.json, mode 600), like the other API checks.

Version: 0.1.0"""

import base64
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
PIGGYBACK_HOST = os.environ.get("NS8_PIGGYBACK_HOST", "NS8-RL98-SAMBA")


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


WINDOW_MIN = env_int("WINDOW_MIN", 15)
ACCESS_WARN, ACCESS_CRIT = env_int("ACCESS_WARN", 10), env_int("ACCESS_CRIT", 100)
BLOCK_MIN_FAILS = env_int("BLOCK_MIN_FAILS", 3)
BLOCK_WARN, BLOCK_CRIT = env_int("BLOCK_WARN", 1), env_int("BLOCK_CRIT", 5)
SHARES_AUDIT_STATE = env_int("SHARES_AUDIT_STATE", 0)
SHARES_TTL = env_int("SHARES_TTL", 300)
DISC_TTL = env_int("NS8_CACHE_TTL", 3600)
CACHE_FILE = os.environ.get("NS8_FILES_CACHE", "/var/lib/ns8-files-cache.json")
LOGIN_TRIES = 3
SVC_FAILED, SVC_BLOCKED, SVC_SHARES = "NS8.Files.FailedAccess", "NS8.Files.BlockedUsers", "NS8.Files.Shares"
SERVICES = [SVC_FAILED, SVC_BLOCKED, SVC_SHARES]

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



# ---------------------------------------------------------------- Grafana (SambaAudit PostgreSQL data source)

class Grafana(object):
    def __init__(self, fqdn, user, password):
        self.fqdn = fqdn
        self.auth = "Basic " + base64.b64encode(("%s:%s" % (user, password)).encode()).decode()

    def _req(self, method, path, body=None):
        c = LocalHttps(self.fqdn)
        try:
            headers = {"Host": self.fqdn, "Authorization": self.auth, "Accept": "application/json"}
            if body is not None:
                headers["Content-Type"] = "application/json"
            c.request(method, path, body=body, headers=headers)
            r = c.getresponse()
            return r.status, r.read().decode("utf-8", "replace")
        except (OSError, ssl.SSLError, http.client.HTTPException):
            return 0, ""
        finally:
            c.close()

    def audit_sources(self):
        """The SambaAudit data sources: ([{uid, name, module}], error)."""
        st, raw = self._req("GET", "/grafana/api/datasources")
        if st != 200:
            return [], "Grafana answered HTTP %s" % st if st else "Grafana unreachable"
        try:
            found = []
            for d in json.loads(raw):
                if str(d.get("name", "")).startswith("SambaAudit"):
                    m = re.search(r"[(]([A-Za-z0-9_-]+)[)]\s*$", d["name"])
                    found.append({"uid": d["uid"], "name": d["name"], "module": m.group(1) if m else ""})
            return found, ""
        except (ValueError, KeyError, TypeError):
            return [], "unexpected Grafana answer"

    def sql(self, uid, query):
        """Run a SQL query on a data source: ([ {column: value} ], error)."""
        body = json.dumps({"queries": [{"refId": "A", "datasource": {"uid": uid, "type": "grafana-postgresql-datasource"},
                                        "rawSql": query, "format": "table", "rawQuery": True}], "from": "now-1h", "to": "now"}).encode()
        st, raw = self._req("POST", "/grafana/api/ds/query", body)
        if st != 200:
            return [], "Grafana answered HTTP %s" % st if st else "Grafana unreachable"
        try:
            res = json.loads(raw).get("results", {}).get("A", {})
            if res.get("error"):
                return [], "audit query failed: %s" % str(res["error"])[:120]
            frames = res.get("frames") or []
            if not frames:
                return [], ""
            names = [f["name"] for f in frames[0].get("schema", {}).get("fields", [])]
            cols = frames[0].get("data", {}).get("values", [])
            return [dict(zip(names, row)) for row in zip(*cols)] if cols else [], ""
        except (ValueError, KeyError, TypeError):
            return [], "unexpected Grafana answer"


# ---------------------------------------------------------------- pure logic

def state_for(value, warn, crit):
    return 2 if value >= crit else 1 if value >= warn else 0


def line(state, name, text, perf="-"):
    return "%d %s %s %s: %s" % (state, name, perf or "-", STATE_WORD[state], text.replace("\n", " "))


def emit_local(text):
    if PIGGYBACK_HOST:
        print("<<<<%s>>>>" % PIGGYBACK_HOST)
        print("<<<local:sep(0)>>>")
        print(text)
        print("<<<<>>>>")
    else:
        print("<<<local:sep(0)>>>")
        print(text)


def unknown_all(reason):
    return [line(3, n, reason) for n in SERVICES]


def classify_result(result):
    """Class of one audit row: ok | notfound | denied | storage | other."""
    r = (result or "").strip().lower()
    if r == "ok":
        return "ok"
    if "no such file" in r or "not a directory" in r:
        return "notfound"
    if r in ("fail", "fail (success)") or "permission denied" in r or "operation not permitted" in r or "access denied" in r:
        return "denied"  # an ACL refusal is logged without errno: "fail (Success)"
    if re.search(r"no space left|quota exceeded|read-only file system|input/output error", r):
        return "storage"
    return "other"


def user_key(name):
    return str(name or "").split("\\")[-1].lower()


def top(counts, n=3):
    best = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
    return ", ".join("%s (%d)" % (k, v) for k, v in best)


def eval_failed_access(rows):
    """rows: refused audit rows [{username, share, op, result, n}] -> (state, text, perf)."""
    totals = {"denied": 0, "storage": 0, "other": 0, "notfound": 0}
    by_user, by_share, storage = {}, {}, {}
    for r in rows:
        cls = classify_result(r.get("result"))
        n = int(r.get("n") or 0)
        if cls not in totals:
            continue
        totals[cls] += n
        if cls == "denied":
            by_user[user_key(r.get("username"))] = by_user.get(user_key(r.get("username")), 0) + n
            by_share[r.get("share")] = by_share.get(r.get("share"), 0) + n
        elif cls == "storage":
            storage[str(r.get("result"))] = storage.get(str(r.get("result")), 0) + n
    perf = "denied=%d;%d;%d;0;|storage_errors=%d;;1;0;|other_errors=%d;;;0;|missing_file=%d;;;0;" % (
        totals["denied"], ACCESS_WARN, ACCESS_CRIT, totals["storage"], totals["other"], totals["notfound"])
    state = 2 if totals["storage"] else state_for(totals["denied"], ACCESS_WARN, ACCESS_CRIT)
    if not (totals["denied"] or totals["storage"] or totals["other"]):
        return 0, "no refused file access in the last %d min (%d missing-file probes ignored)" % (WINDOW_MIN, totals["notfound"]), perf
    parts = ["%d refused accesses in the last %d min: %d denied by the share permissions" % (totals["denied"] + totals["storage"] + totals["other"], WINDOW_MIN, totals["denied"])]
    if totals["storage"]:
        parts.append("%d STORAGE errors (%s)" % (totals["storage"], top(storage)))
    if totals["other"]:
        parts.append("%d other errors" % totals["other"])
    if by_user:
        parts.append("top users: " + top(by_user))
    if by_share:
        parts.append("top shares: " + top(by_share))
    return state, "; ".join(parts), perf


def eval_blocked(fail_rows, ok_rows):
    """Users refused >= BLOCK_MIN_FAILS times on a share with no successful operation there in the window."""
    ok = set()
    for r in ok_rows:
        if int(r.get("n") or 0) > 0:
            ok.add((user_key(r.get("username")), r.get("share")))
    denied = {}
    for r in fail_rows:
        if classify_result(r.get("result")) == "denied":
            k = (user_key(r.get("username")), r.get("share"))
            denied[k] = denied.get(k, 0) + int(r.get("n") or 0)
    blocked = sorted(((n, u, s) for (u, s), n in denied.items() if n >= BLOCK_MIN_FAILS and (u, s) not in ok), reverse=True)
    perf = "blocked_users=%d;%d;%d;0;" % (len(blocked), BLOCK_WARN, BLOCK_CRIT)
    if not blocked:
        return 0, "no user is being refused without any success in the last %d min" % WINDOW_MIN, perf
    txt = "%d users refused on a share with no successful access in the last %d min: %s" % (
        len(blocked), WINDOW_MIN, "; ".join("%s on %s (%d refusals)" % (u, s, n) for n, u, s in blocked[:5]))
    return state_for(len(blocked), BLOCK_WARN, BLOCK_CRIT), txt, perf


def eval_shares(shares):
    """shares: [{name, enable_audit, log_failed_events, enable_recycle}] of every Samba instance."""
    total = len(shares)
    if not total:
        return 0, "no share defined", "shares=0;;;0;|shares_without_audit=0;;;0;"
    no_audit = sorted(s["name"] for s in shares if not s.get("enable_audit"))
    no_failed = sorted(s["name"] for s in shares if s.get("enable_audit") and not s.get("log_failed_events"))
    no_recycle = sorted(s["name"] for s in shares if not s.get("enable_recycle"))
    parts = ["%d shares" % total]
    if no_audit:
        parts.append("no audit on %d (%s): refused accesses there are invisible" % (len(no_audit), ", ".join(no_audit[:6])))
    if no_failed:
        parts.append("audit without failed-event logging on %d (%s)" % (len(no_failed), ", ".join(no_failed[:6])))
    if no_recycle:
        parts.append("no recycle bin on %d (%s)" % (len(no_recycle), ", ".join(no_recycle[:6])))
    state = SHARES_AUDIT_STATE if (no_audit or no_failed) else 0
    if len(parts) == 1:
        parts.append("all audited with failed events and a recycle bin")
    perf = "shares=%d;;;0;|shares_without_audit=%d;;;0;|shares_without_failed_events=%d;;;0;|shares_without_recycle=%d;;;0;" % (
        total, len(no_audit), len(no_failed), len(no_recycle))
    return state, "; ".join(parts), perf


def sql_refused(minutes):
    return ("SELECT username, share, op, result, count(*) AS n FROM samba_audit WHERE time > now() - interval '%d minutes' "
            "AND result <> 'ok' AND addr NOT IN ('127.0.0.1', '::1') GROUP BY username, share, op, result" % int(minutes))


def sql_ok(minutes):
    return ("SELECT username, share, count(*) AS n FROM samba_audit WHERE time > now() - interval '%d minutes' "
            "AND result = 'ok' AND addr NOT IN ('127.0.0.1', '::1') GROUP BY username, share" % int(minutes))


# ---------------------------------------------------------------- self test

def self_test():
    fails, count = [], [0]

    def check(name, cond):
        count[0] += 1
        if not cond:
            fails.append(name)
    check("class ok", classify_result("ok") == "ok")
    check("class acl denied", classify_result("fail (Success)") == "denied")
    check("class unix denied", classify_result("fail (Permission denied)") == "denied")
    check("class missing", classify_result("fail (No such file or directory)") == "notfound")
    check("class space", classify_result("fail (No space left on device)") == "storage")
    check("class quota", classify_result("fail (Disk quota exceeded)") == "storage")
    check("class other", classify_result("fail (Device or resource busy)") == "other")
    rows = [{"username": "NETHLAB\\test-diag", "share": "denytest", "op": "create_file", "result": "fail (Success)", "n": 3},
            {"username": "NETHLAB\\test-diag", "share": "audittest", "op": "create_file", "result": "fail (No such file or directory)", "n": 1}]
    s, t, p = eval_failed_access(rows)
    check("failed access low is ok", s == 0 and "test-diag (3)" in t and "missing_file=1" in p)
    rows2 = [{"username": "a\\u1", "share": "s1", "op": "create_file", "result": "fail (Success)", "n": ACCESS_WARN}]
    check("failed access warn", eval_failed_access(rows2)[0] == 1)
    rows3 = [{"username": "a\\u1", "share": "s1", "op": "create_file", "result": "fail (Success)", "n": ACCESS_CRIT}]
    check("failed access crit", eval_failed_access(rows3)[0] == 2)
    rows4 = [{"username": "a\\u1", "share": "s1", "op": "write", "result": "fail (No space left on device)", "n": 1}]
    check("storage error crit", eval_failed_access(rows4)[0] == 2)
    check("none", eval_failed_access([])[0] == 0)
    check("missing only is ok", eval_failed_access([{"username": "u", "share": "s", "op": "o", "result": "fail (No such file or directory)", "n": 500}])[0] == 0)
    s, t, p = eval_blocked(rows, [])
    check("blocked user", s == state_for(1, BLOCK_WARN, BLOCK_CRIT) and "test-diag on denytest (3 refusals)" in t)
    check("blocked cleared by success", eval_blocked(rows, [{"username": "NETHLAB\\test-diag", "share": "denytest", "n": 1}])[0] == 0)
    check("blocked needs min fails", eval_blocked([{"username": "u", "share": "s", "op": "o", "result": "fail (Success)", "n": BLOCK_MIN_FAILS - 1}], [])[0] == 0)
    check("blocked other share success does not clear", eval_blocked(rows, [{"username": "NETHLAB\\test-diag", "share": "audittest", "n": 9}])[0] >= 1)
    sh = [{"name": "a", "enable_audit": True, "log_failed_events": True, "enable_recycle": True},
          {"name": "b", "enable_audit": False, "log_failed_events": False, "enable_recycle": False},
          {"name": "c", "enable_audit": True, "log_failed_events": False, "enable_recycle": True}]
    s, t, p = eval_shares(sh)
    check("shares info only", s == 0 and "no audit on 1 (b)" in t and "audit without failed-event logging on 1 (c)" in t)
    check("shares all good", eval_shares(sh[:1])[0] == 0 and "all audited" in eval_shares(sh[:1])[1])
    check("shares none", eval_shares([])[0] == 0)
    check("sql refused", "interval '15 minutes'" in sql_refused(15) and "result <> 'ok'" in sql_refused(15))
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
        emit_local("\n".join(unknown_all("cannot read the password file %s: %s" % (NS8_PASSWORD_FILE, exc.strerror))))
        return 0
    api = Session(NS8_USER, password, cache)
    now = time.time()

    # --- Samba instances, node FQDN (cached: they almost never change)
    d = cache.get("disc") or {}
    if not d.get("samba") or now - d.get("ts", 0) > DISC_TTL:
        st, mods = api.task("cluster", "list-installed-modules")
        found = sorted(i["id"] for src, insts in (mods.items() if st == "ok" and isinstance(mods, dict) else []) for i in insts if src.rstrip("/").split(":")[0].endswith("/samba"))
        if found:
            fqdn = NODE_FQDN or d.get("fqdn", "")
            if not fqdn:
                s5, cl = api.task("cluster", "get-cluster-status")
                url = (cl.get("leader_url") or (cl.get("cluster") or {}).get("leader_url")) if s5 == "ok" and isinstance(cl, dict) else None
                fqdn = urllib.parse.urlparse(url).hostname or "" if url else ""
            d = cache["disc"] = {"ts": now, "samba": found, "fqdn": fqdn, "sources": d.get("sources", [])}
        elif st == "ok":
            emit_local("\n".join(unknown_all("no Samba module found on this node")))
            return 0
        elif not d.get("samba"):
            emit_local("\n".join(unknown_all("list-installed-modules: %s" % st)))
            return 0
    samba, fqdn = d["samba"], NODE_FQDN or d.get("fqdn", "")

    # --- shares (cached for SHARES_TTL seconds)
    sc = cache.get("shares") or {}
    stale = ""
    if sc.get("data") is not None and now - sc.get("ts", 0) <= SHARES_TTL:
        shares = sc["data"]
    else:
        shares, serr = {}, ""
        for mod in samba:
            s, res = api.task("module/%s" % mod, "list-shares", None, timeout=25)
            if s == "ok" and isinstance(res, dict):
                shares[mod] = [{k: sh.get(k) for k in ("name", "enable_audit", "log_failed_events", "enable_recycle")} for sh in res.get("shares", [])]
            else:
                serr = "list-shares on %s: %s" % (mod, s)
                break
        if serr:
            if sc.get("data") is not None:
                shares, stale = sc["data"], " (data from %d min ago: %s)" % ((now - sc.get("ts", 0)) // 60, serr)
            else:
                shares = None
        else:
            cache["shares"] = {"ts": now, "data": shares}
    out = []
    if shares is None:
        out.append(line(3, SVC_SHARES, serr))
        all_shares = []
    else:
        all_shares = [sh for mod in samba for sh in shares.get(mod, [])]
        s_, t_, p_ = eval_shares(all_shares)
        out.append(line(s_, SVC_SHARES, t_ + stale, p_))

    # --- audit database
    if not fqdn:
        out += [line(3, SVC_FAILED, "cannot work out the node FQDN (set NS8_NODE_FQDN)"), line(3, SVC_BLOCKED, "cannot work out the node FQDN (set NS8_NODE_FQDN)")]
        emit_local("\n".join(sorted(out, key=lambda x: x.split(" ", 2)[1])))
        return 0
    graf = Grafana(fqdn, NS8_USER, password)
    sources, err = graf.audit_sources()
    if err:
        out += [line(3, SVC_FAILED, "audit unavailable: " + err), line(3, SVC_BLOCKED, "audit unavailable: " + err)]
        emit_local("\n".join(sorted(out, key=lambda x: x.split(" ", 2)[1])))
        return 0
    audited = [sh for sh in all_shares if sh.get("enable_audit")]
    if not sources or (shares is not None and not audited):
        why = "no share has the audit switched on" if sources else "no SambaAudit data source in Grafana"
        for n in (SVC_FAILED, SVC_BLOCKED):
            out.append(line(0, n, "%s: refused accesses are not recorded (see %s)" % (why, SVC_SHARES)))
        emit_local("\n".join(sorted(out, key=lambda x: x.split(" ", 2)[1])))
        return 0
    refused, okrows, qerr = [], [], ""
    for src in sources:
        r1, e1 = graf.sql(src["uid"], sql_refused(WINDOW_MIN))
        r2, e2 = graf.sql(src["uid"], sql_ok(WINDOW_MIN))
        qerr = qerr or e1 or e2
        refused += r1
        okrows += r2
    if qerr:
        out += [line(3, SVC_FAILED, qerr), line(3, SVC_BLOCKED, qerr)]
    else:
        s_, t_, p_ = eval_failed_access(refused)
        out.append(line(s_, SVC_FAILED, t_, p_))
        s_, t_, p_ = eval_blocked(refused, okrows)
        out.append(line(s_, SVC_BLOCKED, t_, p_))
    emit_local("\n".join(sorted(out, key=lambda x: x.split(" ", 2)[1])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
