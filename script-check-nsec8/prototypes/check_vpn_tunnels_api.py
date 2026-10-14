#!/usr/bin/python3
"""check_vpn_tunnels_api.py - NethSecurity VPN monitoring for CheckMK, REST API only (PROTOTYPE)

CheckMK local check, to run ON the firewall. No subprocess, no UCI, no nethsec library: everything goes through the
firewall's own REST API on localhost (NSEC_API, default https://127.0.0.1:9090/api), logged in with a dedicated account
(NSEC_USER, default claude-ro; password in NSEC_PASSWORD_FILE, default /root/.nsec-ro-pass, mode 600). The calls are
ubus read methods through POST /api/ubus/call: ns.ovpntunnel list-tunnels, ns.ovpnrw list-instances / get-configuration /
list-users, ns.wireguard list-tunnels, ns.ipsectunnel list-tunnels.

Services:
- VPN.Tunnels       same name, same perfdata (total/active/inactive) and same state rules as check_vpn_tunnels.py:
                    no tunnel configured = OK, none connected = CRIT, some down = WARN, all connected = OK.
                    Differences from the legacy check, on purpose:
                    * "total" and "active" count the same thing, tunnels: site-to-site OpenVPN servers and clients,
                      WireGuard tunnels, IPsec tunnels. The legacy check counted road-warrior CLIENTS as active but
                      INSTANCES as total (mixed units).
                    * a road-warrior server with no client connected is not a failure (nobody has to be connected):
                      the number of connected road-warrior users is only reported as perfdata (rw_clients).
                    * IPsec tunnels are included (the legacy check ignores them).
- VPN.Certificates  expiry of the OpenVPN certificates: CA and server of every road-warrior instance and of every
                    site-to-site tunnel, and the certificate of every enabled road-warrior user. CRIT when a
                    certificate is expired or expires within CERT_CRIT_DAYS (default 7), WARN within CERT_WARN_DAYS
                    (default 30). Perfdata: min_days_left, certs.

Security notes:
- The API does NOT enforce per-object permissions for /api/ubus/call (verified 2026-10-14 on NethSecurity 8.8.0):
  an account limited by an rpcd ACL group can still call any ubus object. claude-ro has a read-only ACL group
  (ns-check-reader) but must be treated as a full administrator account.
- Some of the methods used return secrets (road-warrior users: the 2FA seed; WireGuard tunnels: private and
  pre-shared keys). This check only reads the fields it needs and never stores or prints the rest.
- TLS verification is off for the loopback connection only (the firewall's certificate is self-signed).

What was verified and what was not: see the notes in the repository commit. The "connected" states are computed by the
API itself (OpenVPN: the same rule the legacy check re-implemented; WireGuard: peer handshake; IPsec: swanctl SA).

Cache: the API token is kept in NSEC_CACHE (default /tmp/check_vpn_tunnels_api.cache, mode 600) until a minute before it
expires, so a normal run is one login every few hours.

Version: 0.1.0"""

import base64
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

VERSION = "0.1.0"
API = os.environ.get("NSEC_API", "https://127.0.0.1:9090/api")
USER = os.environ.get("NSEC_USER", "claude-ro")
PASSWORD_FILE = os.environ.get("NSEC_PASSWORD_FILE", "/root/.nsec-ro-pass")
CACHE_FILE = os.environ.get("NSEC_CACHE", "/tmp/check_vpn_tunnels_api.cache")


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


CERT_WARN_DAYS = env_int("CERT_WARN_DAYS", 30)
CERT_CRIT_DAYS = env_int("CERT_CRIT_DAYS", 7)
SVC_TUNNELS = "VPN.Tunnels"
SVC_CERTS = "VPN.Certificates"
DOWN_NAMES_SHOWN = 5
CERT_NAMES_SHOWN = 3

STATE_WORD = {0: "OK", 1: "WARN", 2: "CRIT", 3: "UNKNOWN"}


# ---------------------------------------------------------------- REST API
class Api(object):
    def __init__(self, base=API):
        self.base = base
        self.token = ""
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE  # loopback, self-signed certificate

    def _post(self, path, body, token=""):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15, context=self.ctx) as r:
                return r.status, json.loads(r.read().decode("utf-8", "replace") or "{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode("utf-8", "replace") or "{}")
            except ValueError:
                return e.code, {}
        except (urllib.error.URLError, OSError, ValueError):
            return 0, {}

    def login(self, user, password):
        """Returns "" on success, otherwise a short error text."""
        st, js = self._post("/login", {"username": user, "password": password})
        tok = js.get("token") if isinstance(js, dict) else None
        if st == 200 and tok:
            self.token = tok
            return ""
        return "login failed (HTTP %s)" % st if st else "NSEC API unreachable at %s" % self.base

    def call(self, path, method, payload=None):
        """Returns (state, data); state is ok, denied, error or unreachable."""
        st, js = self._post("/ubus/call", {"path": path, "method": method, "payload": payload or {}}, self.token)
        if st == 0:
            return "unreachable", None
        if st in (401, 403):
            return "denied", None
        if st != 200 or not isinstance(js, dict) or js.get("code") != 200:
            return "error", None
        return "ok", unwrap(js.get("data"))


def unwrap(data):
    """ubus list results come back as {"values": [...]}: return the inner value."""
    if isinstance(data, dict) and set(data.keys()) == {"values"}:
        return data["values"]
    return data


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
        tmp = "%s.%d.tmp" % (CACHE_FILE, os.getpid())
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(d, fh)
        os.replace(tmp, CACHE_FILE)
    except OSError:
        pass


def open_session(api):
    """Reuses the cached token while it is valid, otherwise logs in. Returns "" or an error text."""
    cache = load_cache()
    tok = cache.get("token", "")
    if tok and jwt_exp(tok) - time.time() > 60:
        api.token = tok
        return ""
    try:
        with open(PASSWORD_FILE, encoding="utf-8") as fh:
            password = fh.read().strip()
    except OSError:
        return "cannot read the password file %s" % PASSWORD_FILE
    err = api.login(USER, password)
    if not err:
        save_cache({"token": api.token})
    return err


# ---------------------------------------------------------------- data collection
def as_list(x):
    return x if isinstance(x, list) else []


def as_dict(x):
    return x if isinstance(x, dict) else {}


def truthy(v):
    return v is True or str(v).lower() in ("1", "true", "yes")


def collect(api):
    """Reads every source once. Returns (tunnels, rw_clients, certs, errors).

    tunnels: list of dicts {kind, name, enabled, connected}
    certs:   list of (label, epoch)
    errors:  list of source names that could not be read"""
    tunnels, certs, errors = [], [], []
    rw_clients = 0

    st, d = api.call("ns.ovpntunnel", "list-tunnels")
    if st != "ok":
        errors.append("ns.ovpntunnel")
    else:
        d = as_dict(d)
        for role in ("servers", "clients"):
            for t in as_list(d.get(role)):
                t = as_dict(t)
                name = t.get("ns_name") or t.get("id") or "?"
                tunnels.append({"kind": "openvpn", "name": name, "enabled": truthy(t.get("enabled")), "connected": truthy(t.get("connected"))})
                for key, val in as_dict(t.get("certificates")).items():
                    if isinstance(val, (int, float)) and val > 0:
                        certs.append(("openvpn tunnel %s %s" % (name, key), int(val)))

    st, d = api.call("ns.wireguard", "list-tunnels")
    if st != "ok":
        errors.append("ns.wireguard")
    else:
        for t in as_list(d):
            t = as_dict(t)
            tunnels.append({"kind": "wireguard", "name": t.get("name") or t.get("id") or "?",
                            "enabled": truthy(t.get("enabled")), "connected": truthy(t.get("active"))})

    st, d = api.call("ns.ipsectunnel", "list-tunnels")
    if st != "ok":
        errors.append("ns.ipsectunnel")
    else:
        for t in as_list(as_dict(d).get("tunnels")):
            t = as_dict(t)
            tunnels.append({"kind": "ipsec", "name": t.get("name") or t.get("id") or "?",
                            "enabled": truthy(t.get("enabled")), "connected": truthy(t.get("connected"))})

    st, d = api.call("ns.ovpnrw", "list-instances")
    if st != "ok":
        errors.append("ns.ovpnrw")
    else:
        for inst in as_list(as_dict(d).get("instances")):
            sc, conf = api.call("ns.ovpnrw", "get-configuration", {"instance": inst})
            if sc != "ok":
                errors.append("ns.ovpnrw get-configuration")
            else:
                for key, val in as_dict(as_dict(conf).get("certificates")).items():
                    if isinstance(val, (int, float)) and val > 0:
                        certs.append(("road warrior %s %s" % (inst, key), int(val)))
            su, users = api.call("ns.ovpnrw", "list-users", {"instance": inst})
            if su != "ok":
                errors.append("ns.ovpnrw list-users")
                continue
            for u in as_list(as_dict(users).get("users")):
                u = as_dict(u)  # only these fields are read: the record also carries the 2FA seed
                if truthy(u.get("connected")):
                    rw_clients += 1
                exp = u.get("expiration")
                if truthy(u.get("openvpn_enabled", "1")) and isinstance(exp, (int, float)) and exp > 0:
                    certs.append(("user %s" % (u.get("name") or "?"), int(exp)))
    return tunnels, rw_clients, certs, sorted(set(errors))


# ---------------------------------------------------------------- evaluation
def line(state, name, perf, text):
    return "%d %s %s %s" % (state, name, perf or "-", text)


def eval_tunnels(tunnels, rw_clients, errors):
    if errors:
        return line(3, SVC_TUNNELS, "-", "UNKNOWN: cannot read %s" % ", ".join(errors))
    enabled = [t for t in tunnels if t["enabled"]]
    total = len(enabled)
    up = [t for t in enabled if t["connected"]]
    down = [t for t in enabled if not t["connected"]]
    active = len(up)
    perf = "total=%d|active=%d|inactive=%d|rw_clients=%d" % (total, active, total - active, rw_clients)
    rw = ", %d road-warrior client(s) connected" % rw_clients if rw_clients else ""
    if total == 0:
        return line(0, SVC_TUNNELS, perf, "No VPN tunnel configured%s" % rw)
    names = ", ".join("%s (%s)" % (t["name"], t["kind"]) for t in down[:DOWN_NAMES_SHOWN])
    if len(down) > DOWN_NAMES_SHOWN:
        names += ", +%d more" % (len(down) - DOWN_NAMES_SHOWN)
    if active == 0:
        return line(2, SVC_TUNNELS, perf, "CRITICAL - All VPN down: %s%s" % (names, rw))
    if active < total:
        return line(1, SVC_TUNNELS, perf, "WARNING - Some VPN down: %s (%d/%d active)%s" % (names, active, total, rw))
    return line(0, SVC_TUNNELS, perf, "OK - All VPN active (%d/%d)%s" % (active, total, rw))


def days_left(epoch, now):
    return int((epoch - now) // 86400)


def eval_certs(certs, errors, now):
    if any(e.startswith("ns.ovpn") for e in errors):
        return line(3, SVC_CERTS, "-", "UNKNOWN: cannot read %s" % ", ".join(e for e in errors if e.startswith("ns.ovpn")))
    if not certs:
        return line(0, SVC_CERTS, "certs=0", "No OpenVPN certificate to check")
    rows = sorted((days_left(e, now), label, e) for label, e in certs)
    worst = rows[0][0]
    expired = [r for r in rows if r[0] < 0]
    crit = [r for r in rows if r[0] <= CERT_CRIT_DAYS]
    warn = [r for r in rows if r[0] <= max(CERT_WARN_DAYS, CERT_CRIT_DAYS)]
    perf = "min_days_left=%d;%d;%d|certs=%d|expiring=%d" % (worst, CERT_WARN_DAYS, CERT_CRIT_DAYS, len(rows), len(warn))
    when = lambda r: "%s %s (%s)" % (r[1], "EXPIRED %d days ago" % -r[0] if r[0] < 0 else "in %d days" % r[0], time.strftime("%Y-%m-%d", time.gmtime(r[2])))
    if crit:
        shown = "; ".join(when(r) for r in crit[:CERT_NAMES_SHOWN])
        more = " (+%d more)" % (len(crit) - CERT_NAMES_SHOWN) if len(crit) > CERT_NAMES_SHOWN else ""
        word = "CRITICAL - %d certificate(s) expired" % len(expired) if expired else "CRITICAL - certificate(s) expiring within %d days" % CERT_CRIT_DAYS
        return line(2, SVC_CERTS, perf, "%s: %s%s" % (word, shown, more))
    if warn:
        shown = "; ".join(when(r) for r in warn[:CERT_NAMES_SHOWN])
        more = " (+%d more)" % (len(warn) - CERT_NAMES_SHOWN) if len(warn) > CERT_NAMES_SHOWN else ""
        return line(1, SVC_CERTS, perf, "WARNING - certificate(s) expiring within %d days: %s%s" % (CERT_WARN_DAYS, shown, more))
    return line(0, SVC_CERTS, perf, "OK - %d certificates, the nearest expires %s" % (len(rows), when(rows[0])))


# ---------------------------------------------------------------- main
def run():
    api = Api()
    err = open_session(api)
    if err:
        return [line(3, SVC_TUNNELS, "-", "UNKNOWN: %s" % err), line(3, SVC_CERTS, "-", "UNKNOWN: %s" % err)]
    tunnels, rw_clients, certs, errors = collect(api)
    return [eval_tunnels(tunnels, rw_clients, errors), eval_certs(certs, errors, time.time())]


def self_test():
    failed, done = [], []

    def check(name, cond):
        done.append(name)
        print("%s %s" % ("ok  " if cond else "FAIL", name))
        if not cond:
            failed.append(name)

    now = 1_800_000_000
    day = 86400
    t = lambda n, e=True, c=True, k="openvpn": {"kind": k, "name": n, "enabled": e, "connected": c}

    check("unwrap values", unwrap({"values": [1]}) == [1] and unwrap({"a": 1}) == {"a": 1})
    payload = base64.urlsafe_b64encode(json.dumps({"exp": 1234}).encode()).decode().rstrip("=")
    check("jwt exp", jwt_exp("x.%s.y" % payload) == 1234 and jwt_exp("garbage") == 0)
    check("truthy", truthy("1") and truthy(True) and not truthy("0") and not truthy(None) and not truthy(False))

    s = eval_tunnels([], 0, [])
    check("no tunnel -> OK", s.startswith("0 VPN.Tunnels total=0|active=0|inactive=0|rw_clients=0 No VPN tunnel"))
    s = eval_tunnels([t("a"), t("b", c=False, k="ipsec")], 0, [])
    check("some down -> WARN, names the down one", s.startswith("1 VPN.Tunnels total=2|active=1|inactive=1") and "b (ipsec)" in s)
    s = eval_tunnels([t("a", c=False), t("b", c=False)], 0, [])
    check("none up -> CRIT", s.startswith("2 VPN.Tunnels total=2|active=0|inactive=2"))
    s = eval_tunnels([t("a"), t("b")], 0, [])
    check("all up -> OK", s.startswith("0 VPN.Tunnels total=2|active=2|inactive=0"))
    s = eval_tunnels([t("a"), t("off", e=False, c=False)], 0, [])
    check("disabled tunnels are not counted", "total=1|active=1" in s and s.startswith("0 "))
    s = eval_tunnels([], 4, [])
    check("road-warrior clients alone: OK and only perfdata", s.startswith("0 VPN.Tunnels total=0|active=0|inactive=0|rw_clients=4") and "4 road-warrior" in s)
    s = eval_tunnels([t("a")], 3, [])
    check("road-warrior clients do not change active/total", "total=1|active=1|inactive=0|rw_clients=3" in s)
    s = eval_tunnels([t("n%d" % i, c=False) for i in range(8)], 0, [])
    check("down names are truncated", "+3 more" in s)
    s = eval_tunnels([t("a")], 0, ["ns.wireguard"])
    check("read error -> UNKNOWN", s.startswith("3 VPN.Tunnels") and "ns.wireguard" in s)

    certs = [("ca", now + 3000 * day), ("srv", now + 100 * day)]
    s = eval_certs(certs, [], now)
    check("certs far away -> OK", s.startswith("0 VPN.Certificates min_days_left=100;30;7|certs=2|expiring=0"))
    s = eval_certs(certs + [("user bob", now + 20 * day)], [], now)
    check("within 30 days -> WARN", s.startswith("1 VPN.Certificates min_days_left=20;30;7") and "user bob in 20 days" in s)
    s = eval_certs(certs + [("user bob", now + 5 * day)], [], now)
    check("within 7 days -> CRIT", s.startswith("2 VPN.Certificates min_days_left=5;30;7") and "within 7 days" in s)
    s = eval_certs(certs + [("old", now - 3 * day)], [], now)
    check("expired -> CRIT and says so", s.startswith("2 ") and "EXPIRED 3 days ago" in s and "1 certificate(s) expired" in s)
    s = eval_certs(certs + [("a", now + 2 * day), ("b", now + 3 * day), ("c", now + 4 * day), ("d", now + 5 * day)], [], now)
    check("many critical -> shows 3 and the rest", "+1 more" in s)
    check("no certs -> OK", eval_certs([], [], now).startswith("0 VPN.Certificates certs=0"))
    check("ovpn read error -> UNKNOWN", eval_certs(certs, ["ns.ovpnrw"], now).startswith("3 VPN.Certificates"))
    check("wireguard error does not hide the certificates", eval_certs(certs, ["ns.wireguard"], now).startswith("0 VPN.Certificates"))
    global PASSWORD_FILE, CACHE_FILE
    saved = (PASSWORD_FILE, CACHE_FILE)
    PASSWORD_FILE, CACHE_FILE = "/nonexistent/pass", "/nonexistent/cache"
    try:
        lines = run()
    finally:
        PASSWORD_FILE, CACHE_FILE = saved
    check("no credentials: both services still produced, both UNKNOWN",
          len(lines) == 2 and lines[0].startswith("3 VPN.Tunnels") and lines[1].startswith("3 VPN.Certificates"))

    class Fake(object):
        def __init__(self, data):
            self.data = data

        def call(self, path, method, payload=None):
            v = self.data.get((path, method))
            return ("ok", v) if v is not None else ("error", None)

    fake = Fake({
        ("ns.ovpntunnel", "list-tunnels"): {"servers": [{"id": "ns_x", "ns_name": "x", "enabled": True, "connected": False, "certificates": {"server": now + 40 * day, "CA": now + 900 * day}}], "clients": []},
        ("ns.wireguard", "list-tunnels"): [{"id": "wg1", "name": "wg", "enabled": True, "active": True, "peer_private_key": "SECRET"}],
        ("ns.ipsectunnel", "list-tunnels"): {"tunnels": [{"id": "i1", "name": "ipsec1", "enabled": "1", "connected": False}]},
        ("ns.ovpnrw", "list-instances"): {"instances": ["rw1"]},
        ("ns.ovpnrw", "get-configuration"): {"certificates": {"CA": now + 800 * day, "server": now + 60 * day}},
        ("ns.ovpnrw", "list-users"): {"users": [
            {"name": "alice", "connected": True, "openvpn_enabled": "1", "expiration": now + 10 * day, "openvpn_2fa": "SECRETSEED"},
            {"name": "bob", "connected": False, "openvpn_enabled": "0", "expiration": now + 1 * day}]},
    })
    tunnels, rw, certs2, errors = collect(fake)
    check("collect: 3 tunnels from 3 kinds", len(tunnels) == 3 and {x["kind"] for x in tunnels} == {"openvpn", "wireguard", "ipsec"})
    check("collect: ipsec enabled '1' is true, wireguard active is connected", [x for x in tunnels if x["kind"] == "ipsec"][0]["enabled"] and [x for x in tunnels if x["kind"] == "wireguard"][0]["connected"])
    check("collect: road-warrior clients counted", rw == 1)
    check("collect: disabled road-warrior user is ignored, enabled one kept", any(c[0] == "user alice" for c in certs2) and not any(c[0] == "user bob" for c in certs2))
    check("collect: no secrets in the collected data", "SECRET" not in json.dumps([tunnels, certs2]))
    check("collect: no read errors", errors == [])
    out = eval_tunnels(tunnels, rw, errors)
    check("collect + eval: 1 of 3 up -> WARN", out.startswith("1 VPN.Tunnels total=3|active=1|inactive=2|rw_clients=1"))
    out = eval_certs(certs2, errors, now)
    check("collect + eval: nearest is the user at 10 days -> WARN", out.startswith("1 VPN.Certificates min_days_left=10;30;7") and "user alice" in out)

    print("\nSelf-test: %d/%d passed." % (len(done) - len(failed), len(done)))
    return 1 if failed else 0


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        return self_test()
    for ln in run():
        print(ln)
    return 0


if __name__ == "__main__":
    sys.exit(main())
