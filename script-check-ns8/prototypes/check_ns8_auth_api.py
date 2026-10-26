#!/usr/bin/env python3
"""check_ns8_auth_api.py - NS8 mail authentication and mailbox monitoring for CheckMK, REST API only (PROTOTYPE)

CheckMK local check, to run ON the NS8 node. No subprocess: everything goes through REST.
- NS8 API (NS8_API, default http://127.0.0.1:9311/api), logged in with NS8_USER / NS8_PASSWORD_FILE
  (a reader account is enough, provided export-users on the AD module and authorize-metrics on the
  metrics module are granted to its role);
- Grafana -> Loki through the node's own Traefik (https://<node fqdn>/grafana/api/datasources/proxy/uid/loki/...,
  connect to 127.0.0.1:443 with SNI/Host = the node FQDN) for the Dovecot and Postfix log lines.

Services (one local-check line each):
- NS8.Auth.FailedLogins   failed mail logins in the last WINDOW_MIN minutes (IMAP/POP/submission/SMTP AUTH),
                          with the top IPs and users. WARN >= AUTH_WARN, CRIT >= AUTH_CRIT.
- NS8.Auth.StuckClients   users that keep failing and never succeed in the window (typically an old password
                          saved in a phone or mail program), plus failures of locked accounts and of accounts that
                          must change their password. WARN >= STUCK_WARN users, CRIT >= STUCK_CRIT.
- NS8.Mail.ImapSessions   open IMAP sessions per user (logins without a matching disconnect in the last
                          SESSION_LOOKBACK_MIN minutes, paired by Dovecot session id) and the highest count for one
                          user from one IP, against Dovecot's mail_max_userip_connections (default 20, read from the
                          log when it is hit). CRIT if the limit was hit in the window, else WARN >= IMAP_WARN,
                          CRIT >= IMAP_CRIT sessions from one user+IP.
- NS8.Mail.Quota          mailboxes over MAILBOX_WARN / MAILBOX_CRIT percent of their quota.

Known limits (what the REST API and the logs can and cannot say):
- an IMAP session opened before the lookback and still open is not counted (IDLE sessions can live for days);
- the last-password-change date is not exposed by the API, so password expiry cannot be monitored from here;
- WebTop does not log user logins (log.auth.target = none);
- Loki answers at most LOKI_LIMIT lines per query; if that is reached the text says the figure may be incomplete;
- a successful SMTP AUTH is only logged by Postfix when a message is submitted.

The NS8 API is shared with every other local check and can answer HTTP 503 when they all run together (Redis "max number
of clients reached"), so the check keeps NS8_AUTH_CACHE (default /var/lib/ns8-auth-cache.json, mode 600, holds the API
token): mail modules and node FQDN for NS8_CACHE_TTL seconds (3600), mailbox quotas for NS8_QUOTA_TTL (600), the login
token until it expires. A run with a warm cache and no failed logins makes no NS8 API call; logins are retried, and
if the API is down the cached data is used (the quota text then says how old it is). Failed-login details
(export-users) are always read live.

Output is piggybacked to the host NS8_PIGGYBACK_HOST (default NS8-RL98-MAIL), between <<<<HOST>>>> and <<<<>>>>.

Version: 0.2.0"""

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

VERSION = "0.2.1"
NS8_API = os.environ.get("NS8_API", "http://127.0.0.1:9311/api")
NS8_USER = os.environ.get("NS8_USER", "claude-ro")
NS8_PASSWORD_FILE = os.environ.get("NS8_PASSWORD_FILE", "/root/.ns8-ro-pass")
NODE_FQDN = os.environ.get("NS8_NODE_FQDN", "")
PIGGYBACK_HOST = os.environ.get("NS8_PIGGYBACK_HOST", "NS8-RL98-MAIL")  # same convention as the other NS8-RL98 local checks


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


WINDOW_MIN = env_int("WINDOW_MIN", 15)
SESSION_LOOKBACK_MIN = env_int("SESSION_LOOKBACK_MIN", 120)
AUTH_WARN, AUTH_CRIT = env_int("AUTH_WARN", 20), env_int("AUTH_CRIT", 100)
STUCK_WARN, STUCK_CRIT, STUCK_MIN_FAILS = env_int("STUCK_WARN", 1), env_int("STUCK_CRIT", 5), env_int("STUCK_MIN_FAILS", 3)
IMAP_WARN, IMAP_CRIT, IMAP_DEFAULT_LIMIT = env_int("IMAP_WARN", 14), env_int("IMAP_CRIT", 20), 20
MAILBOX_WARN, MAILBOX_CRIT = env_int("MAILBOX_WARN", 85), env_int("MAILBOX_CRIT", 95)
SESSION_STALE_MIN, STALE_WARN, SHARED_IP_USERS = env_int("SESSION_STALE_MIN", 60), env_int("STALE_WARN", 10), env_int("SHARED_IP_USERS", 3)
LOKI_LIMIT = 5000
LOKI_MAX_PAGES = 4
CACHE_FILE = os.environ.get("NS8_AUTH_CACHE", "/var/lib/ns8-auth-cache.json")  # 600, root: holds the API token like the password file does
CACHE_TTL = env_int("NS8_CACHE_TTL", 3600)    # modules, node FQDN
QUOTA_TTL = env_int("NS8_QUOTA_TTL", 600)     # mailbox quotas change slowly
LOGIN_TRIES = 3
SVC_FAILED, SVC_STUCK, SVC_IMAP, SVC_QUOTA = "NS8.Auth.FailedLogins", "NS8.Auth.StuckClients", "NS8.Mail.ImapSessions", "NS8.Mail.Quota"

# ---------------------------------------------------------------- NS8 REST API


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
            time.sleep(0.25)  # 400 "redis: nil" = still running (or a reader that is not allowed)
        return "timeout", None


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

    def lines(self, module_id, regex, minutes):
        """Log lines of a module matching a regex in the last N minutes: ([(datetime, message)], truncated, error)."""
        end_ns = int(time.time()) * 10 ** 9
        start_ns = end_ns - minutes * 60 * 10 ** 9
        q = '{module_id="%s"} |~ `%s`' % (module_id, regex)
        out, truncated = [], False
        for _ in range(LOKI_MAX_PAGES):
            path = "/grafana/api/datasources/proxy/uid/%s/loki/api/v1/query_range?query=%s&start=%d&end=%d&limit=%d&direction=forward" % (
                self.uid, urllib.parse.quote(q), start_ns, end_ns, LOKI_LIMIT)
            st, raw = self._get(path)
            if st != 200:
                return out, truncated, "Loki answered HTTP %s" % st if st else "Loki unreachable"
            page = []
            try:
                for s in json.loads(raw).get("data", {}).get("result", []):
                    for ts, line in s["values"]:
                        try:
                            msg = json.loads(line).get("MESSAGE", line)
                        except ValueError:
                            msg = line
                        page.append((int(ts), msg))
            except (ValueError, KeyError):
                return out, truncated, "unexpected Loki answer"
            page.sort(key=lambda x: x[0])
            out.extend(page)
            if len(page) < LOKI_LIMIT:
                break
            start_ns = page[-1][0] + 1
        else:
            truncated = True
        return [(datetime.datetime.fromtimestamp(t / 1e9, tz=datetime.timezone.utc), m) for t, m in out], truncated, ""


# ---------------------------------------------------------------- pure parsing and evaluation

RX_DOVECOT_FAIL = re.compile(r"(imap|pop3|submission|managesieve)-login: .*auth failed(?:, (\d+) attempts?)?.*?user=<([^>]*)>.*?rip=([0-9a-fA-F:.]+)")
RX_UNKNOWN_USER = re.compile(r"ldap\(([^,)]+),([0-9a-fA-F:.]+)[^)]*\): unknown user")
RX_SASL_FAIL = re.compile(r"warning: \S+\[([0-9a-fA-F:.]+)\]: SASL \w+ authentication failed: .*sasl_username=(\S+)")
RX_IMAP_LOGIN = re.compile(r"imap-login: Login: user=<([^>]*)>.*?rip=([0-9a-fA-F:.]+).*?session=<([^>]*)>")
RX_IMAP_DISC = re.compile(r"imap\(([^)]*)\)<\d+><([^>]*)>: Disconnected")
RX_IMAP_LIMIT = re.compile(r"imap-login: Disconnected: Maximum number of connections from user\+IP exceeded \(mail_max_userip_connections=(\d+)\): user=<([^>]*)>.*?rip=([0-9a-fA-F:.]+)")
RX_SMTP_OK = re.compile(r"client=\S+\[([0-9a-fA-F:.]+)\], sasl_method=\w+, sasl_username=(\S+)")
RX_ANY_LOGIN_OK = re.compile(r"(imap|pop3|managesieve|submission)-login: Login: user=<([^>]*)>.*?rip=([0-9a-fA-F:.]+)")

LOKI_FAILURES = r"auth failed|SASL \w+ authentication failed|unknown user"
LOKI_SESSIONS = r"imap-login: Login:|imap\([^)]*\).*: Disconnected|Maximum number of connections"  # Loki filters the RAW line, where angle brackets are JSON-escaped: no < or > in the filter
LOKI_SUCCESS = r"-login: Login: user=|sasl_method=\w+, sasl_username="


def norm_user(u):
    return u.split("@")[0].strip().lower()


def parse_failures(lines):
    """[(time, user, ip, proto, count)]; Postfix logs one line per mechanism tried, so repeats within 3 s count once."""
    out, seen = [], set()
    for ts, msg in lines:
        m = RX_DOVECOT_FAIL.search(msg)
        if m:
            out.append((ts, norm_user(m.group(3)), m.group(4), m.group(1), int(m.group(2) or 1)))
            continue
        if RX_UNKNOWN_USER.search(msg):
            continue  # it accompanies the "auth failed" line of the same attempt: counted there, see parse_unknown()
        m = RX_SASL_FAIL.search(msg)
        if m:
            key = (m.group(1), norm_user(m.group(2)), int(ts.timestamp()) // 3)
            if key not in seen:
                seen.add(key)
                out.append((ts, norm_user(m.group(2)), m.group(1), "smtp", 1))
    return out


def parse_unknown(lines):
    """Users Dovecot could not find in the directory (a wrong user name, not a wrong password)."""
    return {norm_user(m.group(1)) for _, msg in lines for m in [RX_UNKNOWN_USER.search(msg)] if m}


def parse_successes(lines):
    """{user: last success time} from Dovecot logins and Postfix SASL successes."""
    ok = {}
    for ts, msg in lines:
        m = RX_ANY_LOGIN_OK.search(msg)
        u = norm_user(m.group(2)) if m else None
        if not m:
            m2 = RX_SMTP_OK.search(msg)
            u = norm_user(m2.group(2)) if m2 else None
        if u and (u not in ok or ts > ok[u]):
            ok[u] = ts
    return ok


def open_sessions(lines):
    """Open IMAP sessions [(user, ip, opened)] and Dovecot limit events. Pairs logins and disconnects by session id."""
    logins, closed, limit_events, limit_value = {}, set(), [], None
    for ts, msg in lines:
        m = RX_IMAP_LOGIN.search(msg)
        if m:
            logins[m.group(3)] = (norm_user(m.group(1)), m.group(2), ts)
            continue
        m = RX_IMAP_DISC.search(msg)
        if m:
            closed.add(m.group(2))
            continue
        m = RX_IMAP_LIMIT.search(msg)
        if m:
            limit_value = int(m.group(1))
            limit_events.append((ts, norm_user(m.group(2)), m.group(3)))
    return [v for sid, v in logins.items() if sid not in closed], limit_events, limit_value


def state_for(value, warn, crit):
    return 2 if value >= crit else 1 if value >= warn else 0


def top(counter, n=3):
    return sorted(counter.items(), key=lambda kv: -kv[1])[:n]


def eval_failed(fails):
    total = sum(f[4] for f in fails)
    by_ip, by_user = {}, {}
    for ts, u, ip, proto, n in fails:
        by_ip[ip] = by_ip.get(ip, 0) + n
        by_user[u] = by_user.get(u, 0) + n
    st = state_for(total, AUTH_WARN, AUTH_CRIT)
    detail = "; top IPs: %s; top users: %s" % (", ".join("%s (%d)" % kv for kv in top(by_ip)) or "-", ", ".join("%s (%d)" % kv for kv in top(by_user)) or "-") if total else ""
    perf = "failed=%d;%d;%d;0;|ips=%d;;;0;|users=%d;;;0;" % (total, AUTH_WARN, AUTH_CRIT, len(by_ip), len(by_user))
    return st, "%d failed mail logins in the last %d min from %d IPs / %d users%s" % (total, WINDOW_MIN, len(by_ip), len(by_user), detail), perf


def eval_stuck(fails, successes, accounts, unknown=None):
    """Users failing with no success in the window, or failing while locked / forced to change password."""
    per = {}
    for ts, u, ip, proto, n in fails:
        d = per.setdefault(u, {"fails": 0, "ips": set()})
        d["fails"] += n
        d["ips"].add(ip)
    stuck = []
    for u, d in per.items():
        acc = (accounts or {}).get(u) or {}
        reason = None
        if acc.get("locked"):
            reason = "account locked"
        elif acc.get("must_change_password"):
            reason = "must change password"
        elif d["fails"] >= STUCK_MIN_FAILS and u not in successes:
            reason = "user not found by Dovecot (wrong user name)" if u in (unknown or ()) else "no successful login"
        if reason:
            stuck.append((u, d["fails"], sorted(d["ips"]), reason))
    stuck.sort(key=lambda x: -x[1])
    st = state_for(len(stuck), STUCK_WARN, STUCK_CRIT)
    text = "%d users failing without recovering in the last %d min" % (len(stuck), WINDOW_MIN)
    if stuck:
        text += ": " + "; ".join("%s (%d failures from %s, %s)" % (u, f, "/".join(ips[:2]), why) for u, f, ips, why in stuck[:5])
    return st, text, "stuck_users=%d;%d;%d;0;" % (len(stuck), STUCK_WARN, STUCK_CRIT)


def eval_imap(sessions, limit_events, limit_value, truncated, now):
    """Open sessions per user+IP (Dovecot limits per user+IP), the oldest ones, and IPs shared by several users.
    WebTop opens every user's IMAP connections from ONE address, and shared folders/mailboxes and heavy searches multiply
    them, so a high count from a shared address is the typical case of a hung WebTop tree, not a misbehaving client."""
    per, stale, users_by_ip, ages = {}, {}, {}, []
    for u, ip, opened in sessions:
        age = max(0, int((now - opened).total_seconds() // 60))
        ages.append(age)
        per[(u, ip)] = per.get((u, ip), 0) + 1
        users_by_ip.setdefault(ip, set()).add(u)
        if age >= SESSION_STALE_MIN:
            stale[(u, ip)] = stale.get((u, ip), 0) + 1
    users = {}
    for (u, ip), n in per.items():
        users[u] = users.get(u, 0) + n
    worst = max(per.items(), key=lambda kv: kv[1]) if per else None
    worst_n = worst[1] if worst else 0
    worst_stale = max(stale.items(), key=lambda kv: kv[1]) if stale else None
    limit = limit_value or IMAP_DEFAULT_LIMIT
    st = state_for(worst_n, IMAP_WARN, IMAP_CRIT)
    if worst_stale and worst_stale[1] >= STALE_WARN:
        st = max(st, 1)
    if limit_events:
        st = 2
    shared = lambda ip: len(users_by_ip.get(ip, ())) >= SHARED_IP_USERS
    text = "%d open IMAP sessions for %d users (opened in the last %d min)" % (len(sessions), len(users), SESSION_LOOKBACK_MIN)
    if worst:
        (u, ip), n = worst
        text += "; most from one user+IP: %s from %s%s with %d (Dovecot limit %d per user+IP)" % (u, ip, " (shared by %d users, probably WebTop)" % len(users_by_ip[ip]) if shared(ip) else "", n, limit)
    if worst_stale:
        (u, ip), n = worst_stale
        text += "; %d sessions older than %d min for %s from %s, oldest %d min (possibly hung)" % (n, SESSION_STALE_MIN, u, ip, max(ages))
    if users:
        text += "; top users: " + ", ".join("%s (%d)" % kv for kv in top(users))
    if limit_events:
        text += "; LIMIT HIT %d times in the last %d min by: %s" % (len(limit_events), WINDOW_MIN, ", ".join(sorted({e[1] for e in limit_events})[:5]))
    if truncated:
        text += "; log truncated, the count may be incomplete"
    perf = "imap_open_sessions=%d;;;0;|imap_users=%d;;;0;|imap_max_per_user_ip=%d;%d;%d;0;|imap_stale_sessions=%d;;;0;|imap_oldest_min=%d;;;0;|imap_limit_hits=%d;;1;0;" % (
        len(sessions), len(users), worst_n, IMAP_WARN, IMAP_CRIT, sum(stale.values()), max(ages) if ages else 0, len(limit_events))
    return st, text, perf


def eval_quota(boxes):
    bad, crit, warn, limited = [], [], [], 0
    for b in boxes or []:
        q = b.get("quota") or {}
        if not q.get("limit"):
            continue
        limited += 1
        pct = q.get("percent") or 0
        if pct >= MAILBOX_CRIT:
            crit.append((b.get("user"), pct))
        elif pct >= MAILBOX_WARN:
            warn.append((b.get("user"), pct))
    st = 2 if crit else 1 if warn else 0
    text = "%d of %d mailboxes with a quota are at or above %d%%" % (len(crit) + len(warn), limited, MAILBOX_WARN)
    over = sorted(crit + warn, key=lambda x: -x[1])[:5]
    if over:
        text += ": " + ", ".join("%s %d%%" % kv for kv in over)
    if not limited:
        text = "no mailbox has a quota set (%d mailboxes)" % len(boxes or [])
    perf = "mailboxes_warn=%d;;;0;|mailboxes_crit=%d;;;0;" % (len(warn), len(crit))
    return st, text, perf


# ---------------------------------------------------------------- output

def emit_local(text):
    """Piggyback the local-check lines to the module host, like the other NS8-RL98 checks do."""
    print("<<<<%s>>>>" % PIGGYBACK_HOST)
    print("<<<local:sep(0)>>>")
    print(text)
    print("<<<<>>>>")


STATE_WORD = {0: "OK", 1: "WARN", 2: "CRIT", 3: "UNKNOWN"}


def line(state, name, text, perf="-"):
    return "%d %s %s %s: %s" % (state, name, perf or "-", STATE_WORD[state], text.replace("\n", " "))


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
    """One NS8 API login per run, and none when a still-valid token is cached by an earlier run.

    The NS8 API can be saturated by the other local checks (Redis 'max number of clients reached' -> HTTP 503),
    so a login is retried, and a cached token that the API no longer accepts is replaced once."""

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
        """Like Api.task, but logs in on demand. A login failure comes back as (error text, None)."""
        if not self.ready:
            tok = self.cache.get("token")
            if tok and self.cache.get("token_exp", 0) > time.time() + 120:
                self.api.token, self.ready = tok, True
            else:
                err = self._login()
                if err:
                    return err, None
        st, out = self.api.task(agent, action, data, timeout)
        if st == "denied" and not self.fresh:  # the cached token is no longer accepted
            err = self._login()
            if err:
                return err, None
            st, out = self.api.task(agent, action, data, timeout)
        return st, out


def unknown_all(reason, names):
    return [line(3, n, reason) for n in names]


def self_test():
    fails_, now = [], datetime.datetime.now(datetime.timezone.utc)
    d = datetime.timedelta

    def check(name, cond):
        print("  %-70s %s" % (name, "ok" if cond else "FAILED"))
        if not cond:
            fails_.append(name)
    L = [
        (now, "imap-login: Disconnected: Connection closed (auth failed, 3 attempts in 4 secs): user=<mario@esempio.it>, method=PLAIN, rip=203.0.113.7, lip=10.0.0.1, TLS"),
        (now, "warning: h[203.0.113.7]: SASL PLAIN authentication failed: (reason unavailable), sasl_username=mario"),
        (now, "warning: h[203.0.113.7]: SASL LOGIN authentication failed: (reason unavailable), sasl_username=mario"),
        (now + d(seconds=30), "warning: h[198.51.100.4]: SASL PLAIN authentication failed: x, sasl_username=anna@esempio.it"),
        (now, "auth-worker(1): ldap(bob,192.0.2.50,<s>): unknown user"),
        (now, "imap-login: Disconnected: auth failed, 1 attempts: user=<marione>, rip=203.0.113.9"),
    ]
    f = parse_failures(L)
    check("failures: dovecot attempts counted, postfix PLAIN+LOGIN counted once", sum(x[4] for x in f if x[1] == "mario") == 4)
    check("failures: other users recognised, domain stripped; 'unknown user' is not a second failure", {x[1] for x in f} == {"mario", "anna", "marione"} and parse_unknown(L) == {"bob"})
    st, text, perf = eval_failed(f)
    check("FailedLogins: total 6 -> OK below AUTH_WARN", st == 0 and "6 failed" in text)
    big = [(now, "imap-login: Disconnected: Connection closed (auth failed, 120 attempts in 9 secs): user=<x>, method=PLAIN, rip=1.2.3.4, lip=1.1.1.1, TLS")]
    check("FailedLogins: 120 attempts -> CRIT", eval_failed(parse_failures(big))[0] == 2)
    succ = parse_successes([(now, "imap-login: Login: user=<anna>, method=PLAIN, rip=198.51.100.4, lip=1.1.1.1, TLS, session=<s>"), (now, "A1: client=h[1.1.1.1], sasl_method=PLAIN, sasl_username=mario@esempio.it")])
    st, text, perf = eval_stuck(f, succ, {})
    check("Stuck: mario failed 4 times but had a success -> not stuck", "mario" not in text)
    st, text, perf = eval_stuck(f, {}, {})
    check("Stuck: mario (4 failures, no success) is stuck", st >= 1 and "mario" in text)
    st, text, perf = eval_stuck([(now, "zed", "9.9.9.9", "imap", 1)], {}, {"zed": {"must_change_password": True}})
    check("Stuck: one failure of a must-change-password user counts", st == 1 and "must change password" in text)
    st, text, perf = eval_stuck([(now, "ghost", "9.9.9.9", "imap", 5)], {}, {}, {"ghost"})
    check("Stuck: a user Dovecot cannot find is reported as a wrong user name", st == 1 and "wrong user name" in text)
    st, text, perf = eval_stuck([(now, "lou", "9.9.9.9", "imap", 1)], {}, {"lou": {"locked": True}})
    check("Stuck: a failure of a locked account counts", st == 1 and "locked" in text)
    S = []
    for i in range(16):
        S.append((now, "imap-login: Login: user=<ugo>, method=PLAIN, rip=10.1.1.1, lip=1.1.1.1, mpid=1, TLS, session=<s%d>" % i))
    for i in range(6):
        S.append((now, "imap(ugo)<1><s%d>: Disconnected: Logged out in=1 out=2" % i))
    sess, ev, lv = open_sessions(S)
    check("IMAP sessions: 16 logins - 6 disconnects = 10 open, paired by session id", len(sess) == 10 and {(u, ip) for u, ip, _ in sess} == {("ugo", "10.1.1.1")})
    check("IMAP sessions: 10 open -> OK below IMAP_WARN", eval_imap(sess, ev, lv, False, now)[0] == 0)
    sess2, _, _ = open_sessions(S[:16])
    check("IMAP sessions: 16 open from one IP -> WARN", eval_imap(sess2, [], None, False, now)[0] == 1)
    S.append((now, "imap-login: Disconnected: Maximum number of connections from user+IP exceeded (mail_max_userip_connections=20): user=<ugo>, method=PLAIN, rip=10.1.1.1, lip=1.1.1.1, TLS, session=<z>"))
    sess3, ev3, lv3 = open_sessions(S)
    check("IMAP sessions: limit-exceeded event -> CRIT and limit 20 read from the log", eval_imap(sess3, ev3, lv3, False, now)[0] == 2 and lv3 == 20)
    check("IMAP sessions: truncated log is declared", "truncated" in eval_imap(sess, [], None, True, now)[1])
    old_s = [("ugo", "10.1.1.1", now - d(minutes=90)) for _ in range(11)]
    st, text, perf = eval_imap(old_s, [], None, False, now)
    check("IMAP sessions: 11 sessions older than 60 min -> WARN, flagged as possibly hung with the oldest age", st == 1 and "possibly hung" in text and "oldest 90 min" in text)
    web = [("u%d" % i, "10.0.2.100", now) for i in range(5)] + [("zed", "10.0.2.100", now)] * 2
    st, text, perf = eval_imap(web, [], None, False, now)
    check("IMAP sessions: an address used by 6 users is shown as shared (probably WebTop)", "shared by 6 users, probably WebTop" in text)
    check("IMAP sessions: no sessions at all -> OK, zero counters", eval_imap([], [], None, False, now)[0] == 0 and "imap_open_sessions=0" in eval_imap([], [], None, False, now)[2])
    L2 = [(now, 'x\\u003ctest'), (now, "imap-login: Login: user=<a>, method=PLAIN, rip=1.1.1.1, lip=2.2.2.2, mpid=1, TLS, session=<q1>"), (now, "imap(a)<1><q1>: Disconnected: Logged out")]
    sess4, _, _ = open_sessions(L2)
    check("IMAP sessions: a login followed by its disconnect leaves no open session", sess4 == [])
    boxes = [{"user": "a", "quota": {"limit": 1000, "percent": 50, "value": 500}}, {"user": "b", "quota": {"limit": 1000, "percent": 88, "value": 880}},
             {"user": "c", "quota": {"limit": 1000, "percent": 97, "value": 970}}, {"user": "d", "quota": {"limit": 0, "percent": 0, "value": 5}}]
    st, text, perf = eval_quota(boxes)
    check("Quota: 97% -> CRIT, 88% -> counted, no-limit mailbox ignored", st == 2 and "c 97%" in text and "b 88%" in text and "of 3 mailboxes" in text)
    check("Quota: no limits at all -> OK with a clear text", eval_quota([{"user": "d", "quota": {"limit": 0}}])[0] == 0)
    check("output line format", line(0, "NS8.X", "t", "a=1;;;0;").startswith("0 NS8.X a=1;;;0; OK: t"))
    print("self-test: %s" % ("ALL OK" if not fails_ else "%d FAILED" % len(fails_)))
    return 0 if not fails_ else 1


def main():
    if "--self-test" in sys.argv:
        return self_test()
    cache = load_cache()
    try:
        return run(cache)
    finally:
        save_cache(cache)


def run(cache):
    names = [SVC_FAILED, SVC_STUCK, SVC_IMAP, SVC_QUOTA]
    try:
        with open(NS8_PASSWORD_FILE, encoding="utf-8") as fh:
            password = fh.read().strip()
    except OSError as exc:
        emit_local("\n".join(unknown_all("cannot read the password file %s: %s" % (NS8_PASSWORD_FILE, exc.strerror), names)))
        return 0
    api = Session(NS8_USER, password, cache)
    out = []
    now = time.time()

    # --- mail modules, node FQDN (cached: they almost never change)
    if not cache.get("mail_mods") or now - cache.get("disc_ts", 0) > CACHE_TTL:
        st, mods = api.task("cluster", "list-installed-modules")
        found = sorted(i["id"] for src, insts in (mods.items() if st == "ok" and isinstance(mods, dict) else []) for i in insts if src.rstrip("/").endswith("/mail"))
        if found:
            cache["mail_mods"], cache["disc_ts"] = found, now
            if not NODE_FQDN:
                s5, cl = api.task("cluster", "get-cluster-status")
                url = (cl.get("leader_url") or (cl.get("cluster") or {}).get("leader_url")) if s5 == "ok" and isinstance(cl, dict) else None
                if url:
                    cache["fqdn"] = urllib.parse.urlparse(url).hostname or ""
        elif not cache.get("mail_mods") or st == "ok":  # no cache to fall back on, or the API says there is no mail module
            emit_local("\n".join(unknown_all("no mail module found (list-installed-modules: %s)" % st, names)))
            return 0
        # else: the API is saturated or down, keep working with the cached (older) discovery
    mail_mods = cache["mail_mods"]
    fqdn = NODE_FQDN or cache.get("fqdn", "")

    # --- quota (independent of the logs; cached for QUOTA_TTL seconds)
    q = cache.get("quota") or {}
    boxes, stale = None, ""
    if q.get("boxes") is not None and now - q.get("ts", 0) <= QUOTA_TTL:
        boxes = q["boxes"]
    else:
        boxes, qerr = [], ""
        for mm in mail_mods:
            s, res = api.task("module/%s" % mm, "list-user-mailboxes", None, timeout=20)
            if s == "ok" and isinstance(res, dict):
                boxes.extend(res.get("user_mailboxes") or [])
            else:
                qerr = "list-user-mailboxes on %s: %s" % (mm, s)
                boxes = None
                break
        if boxes is not None:
            cache["quota"] = {"ts": now, "boxes": boxes}
        elif q.get("boxes") is not None:
            boxes, stale = q["boxes"], " (data from %d min ago: %s)" % ((now - q.get("ts", 0)) // 60, qerr)
        else:
            out.append(line(3, SVC_QUOTA, qerr))
    if boxes is not None:
        s_, t_, p_ = eval_quota(boxes)
        out.append(line(s_, SVC_QUOTA, t_ + stale, p_))

    # --- logs
    loki = Loki(fqdn, NS8_USER, password) if fqdn else None
    err = ("cannot work out the node FQDN (set NS8_NODE_FQDN)" if not fqdn else loki.open())
    if err:
        out.extend(unknown_all("logs unavailable: " + err, [SVC_FAILED, SVC_STUCK, SVC_IMAP]))
        emit_local("\n".join(sorted(out, key=lambda x: x.split(" ", 2)[1])))
        return 0
    fail_lines, sess_lines, ok_lines, trunc, lerr = [], [], [], False, ""
    for mm in mail_mods:
        a, ta, e1 = loki.lines(mm, LOKI_FAILURES, WINDOW_MIN)
        b, tb, e2 = loki.lines(mm, LOKI_SESSIONS, SESSION_LOOKBACK_MIN)
        c, tc, e3 = loki.lines(mm, LOKI_SUCCESS, WINDOW_MIN)
        lerr = lerr or e1 or e2 or e3
        fail_lines += a
        sess_lines += b
        ok_lines += c
        trunc = trunc or tb
    if lerr:
        out.extend(unknown_all("logs unavailable: " + lerr, [SVC_FAILED, SVC_STUCK, SVC_IMAP]))
        emit_local("\n".join(sorted(out, key=lambda x: x.split(" ", 2)[1])))
        return 0
    fails = parse_failures(fail_lines)
    s_, t_, p_ = eval_failed(fails)
    out.append(line(s_, SVC_FAILED, t_, p_))

    accounts = None
    if fails:  # account state is only needed to explain failures
        accounts = {}
        sd, doms = api.task("cluster", "list-user-domains")
        for dom in (doms.get("domains", []) if sd == "ok" and isinstance(doms, dict) else []):
            for prov in [p.get("id") for p in dom.get("providers", []) if p.get("id")]:
                s, exp = api.task("module/%s" % prov, "export-users", None, timeout=10)
                if s == "ok" and isinstance(exp, dict):
                    for r in exp.get("records", []):
                        accounts[str(r.get("user", "")).lower()] = {"locked": r.get("locked"), "must_change_password": r.get("must_change_password")}
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=WINDOW_MIN)
    recent_sessions = [(t, m) for t, m in sess_lines if t >= cutoff]  # the session query looks back further than the failure window
    s_, t_, p_ = eval_stuck(fails, parse_successes(ok_lines + recent_sessions), accounts, parse_unknown(fail_lines))
    if fails and not accounts:
        t_ += " (account state unavailable: export-users not allowed or too slow)"
    out.append(line(s_, SVC_STUCK, t_, p_))
    sessions, lim_ev, lim_val = open_sessions(sess_lines)
    lim_ev = [e for e in lim_ev if e[0] >= cutoff]  # limit hits count only inside the failure window
    s_, t_, p_ = eval_imap(sessions, lim_ev, lim_val, trunc, datetime.datetime.now(datetime.timezone.utc))
    out.append(line(s_, SVC_IMAP, t_, p_))
    emit_local("\n".join(sorted(out, key=lambda x: x.split(" ", 2)[1])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
