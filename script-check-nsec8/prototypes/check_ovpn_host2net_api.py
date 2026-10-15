#!/usr/bin/python3
"""check_ovpn_host2net_api.py - NethSecurity OpenVPN road-warrior (host-to-net) servers for CheckMK, REST API only (PROTOTYPE)

CheckMK local check, to run ON the firewall. No subprocess, no UCI, no nethsec library, no /var/run: everything goes
through the firewall's own REST API on localhost (NSEC_API, default https://127.0.0.1:9090/api), logged in with a
dedicated account (NSEC_USER, default claude-ro; password in NSEC_PASSWORD_FILE, default /root/.nsec-ro-pass, mode
600). The calls are ubus read methods through POST /api/ubus/call:
- ns.ovpnrw list-instances        the road-warrior server instances;
- ns.ovpnrw get-configuration     enabled flag, port, protocol, VPN subnet;
- ns.ovpnrw list-users            the users, with their connected flag (the API reads the OpenVPN management socket);
- ns.dashboard service-status     {"service": "openvpn_rw"}: whether the server process is running (procd).

Service: OVPN.HostToNet.<instance>, one per road-warrior instance (instance name without the "ns_" prefix, e.g.
OVPN.HostToNet.roadwarrior1); with no instance configured, a single OVPN.HostToNet service, OK.
- instance disabled                                   OK
- instance enabled and the server process running     OK, with the connected users (names, at most MAX_NAMES)
- instance enabled and the server process NOT running CRIT: nobody can connect
- the state of the instance cannot be read            UNKNOWN
Perfdata: clients (connected users, maximum = enabled users), users (enabled users). Nobody has to be connected, so
the number of clients has no thresholds. The certificate expiry of the server and of the users is already checked by
VPN.Certificates (check_vpn_tunnels_api.py): not repeated here.

Corrections to the legacy check (check_ovpn_host2net.py), on purpose:
- an enabled instance that is not running was silently left out and the service said "OK - OpenVPN not configured or
  not running": now it is CRIT. "Running" was inferred from the existence of /var/run/openvpn_<instance>.socket, which
  stays on disk after the process has died (verified on the test VM: the socket of a stopped instance was still
  there); now it is the real procd state;
- clients that could not be read were counted as 0 (exception swallowed): now UNKNOWN;
- one service per instance instead of a single sum of every instance.

API ceiling (documented, not a bug): the "running" state is exposed by the API for the instance ns_roadwarrior1 only
(ns.dashboard hardcodes that name). For any other road-warrior instance the check reports the clients and says that
the running state is not available, state OK.

Security notes:
- The API does NOT enforce per-object permissions for /api/ubus/call (verified 2026-10-14 on NethSecurity 8.8.0): an
  account limited by an rpcd ACL group can still call any ubus object. claude-ro has a read-only ACL group
  (ns-check-reader) but must be treated as a full administrator account.
- ns.ovpnrw list-users returns the 2FA seed of every user: this check only reads name, connected and openvpn_enabled
  and never stores or prints the rest.
- TLS verification is off for the loopback connection only (the firewall's certificate is self-signed).

Cache: the API token and the last known instance names are kept in NSEC_OH_CACHE (default
/tmp/check_ovpn_host2net_api.cache, mode 600).

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
CACHE_FILE = os.environ.get("NSEC_OH_CACHE", "/tmp/check_ovpn_host2net_api.cache")
SERVICE = "OVPN.HostToNet"
RUN_STATE_INSTANCE = "ns_roadwarrior1"  # the only instance the API reports a running state for
MAX_NAMES = 5


# ---------------------------------------------------------------- REST API
class Api(object):
    def __init__(self, base=API):
        self.base = base
        self.token = ""
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE  # loopback, self-signed certificate

    def _post(self, path, body, token="", timeout=15):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=self.ctx) as r:
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

    def call(self, path, method, payload=None, timeout=15):
        """Returns (state, data); state is ok, denied, error or unreachable."""
        st, js = self._post("/ubus/call", {"path": path, "method": method, "payload": payload or {}}, self.token, timeout)
        if st == 0:
            return "unreachable", None
        if st in (401, 403):
            return "denied", None
        if st != 200 or not isinstance(js, dict) or js.get("code") != 200:
            return "error", None
        return "ok", js.get("data")


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


def open_session(api, cache):
    """Reuses the cached token while it is valid, otherwise logs in. Returns "" or an error text."""
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
        cache["token"] = api.token
        save_cache(cache)
    return err


# ---------------------------------------------------------------- data collection
def as_dict(v):
    return v if isinstance(v, dict) else {}


def as_list(v):
    return v if isinstance(v, list) else []


def truthy(v):
    return v is True or (isinstance(v, (int, float)) and not isinstance(v, bool) and v != 0) or (isinstance(v, str) and v.strip().lower() in ("1", "true", "yes", "on"))


def unwrap(data):
    """ns.dashboard results come back as {"result": ...}: return the inner value."""
    if isinstance(data, dict) and len(data) == 1 and next(iter(data)) in ("result", "values"):
        return next(iter(data.values()))
    return data


def label(inst):
    return inst[3:] if inst.startswith("ns_") else inst


def collect(api):
    """Returns (instances, error). instances: list of dicts {name, label, config_ok, enabled, running, users_ok,
    users, connected}; running is True, False or None (not exposed by the API for this instance). error is ""
    or a short text (cannot read the instance list)."""
    st, d = api.call("ns.ovpnrw", "list-instances")
    if st != "ok":
        return [], "cannot read the road-warrior instance list (%s)" % st
    names = [n for n in as_list(as_dict(d).get("instances")) if isinstance(n, str)]
    out = []
    for inst in names:
        x = {"name": inst, "label": label(inst), "config_ok": False, "enabled": False, "running": None,
             "users_ok": False, "users": 0, "connected": []}
        sc, conf = api.call("ns.ovpnrw", "get-configuration", {"instance": inst})
        if sc == "ok":
            c = as_dict(conf)
            x["config_ok"] = True
            x["enabled"] = truthy(c.get("enabled"))
            x["port"] = c.get("port") or ""
            x["proto"] = c.get("proto") or ""
        if x["config_ok"] and x["enabled"] and inst == RUN_STATE_INSTANCE:
            ss, sd = api.call("ns.dashboard", "service-status", {"service": "openvpn_rw"})
            if ss == "ok":
                status = as_dict(unwrap(sd)).get("status")
                x["running"] = status == "ok"  # enabled and not running comes back as null or "error"
            else:
                x["running"] = "unreadable"
        su, users = api.call("ns.ovpnrw", "list-users", {"instance": inst})
        if su == "ok":
            x["users_ok"] = True
            for u in as_list(as_dict(users).get("users")):
                u = as_dict(u)  # only these fields are read: the record also carries the 2FA seed
                if truthy(u.get("openvpn_enabled", "1")):
                    x["users"] += 1
                if truthy(u.get("connected")):
                    x["connected"].append(str(u.get("name") or "?"))
        out.append(x)
    return out, ""


# ---------------------------------------------------------------- evaluation
def line(state, name, perf, text):
    return "%d %s %s %s" % (state, name, perf or "-", text)


def evaluate_one(x):
    name = "%s.%s" % (SERVICE, x["label"])
    if not x["config_ok"]:
        return line(3, name, "-", "UNKNOWN - cannot read the configuration of the instance %s" % x["name"])
    where = "%s/%s" % (x.get("port") or "?", x.get("proto") or "?")
    if not x["enabled"]:
        return line(0, name, "-", "Disabled (%s)" % where)
    if x["running"] == "unreadable":
        return line(3, name, "-", "UNKNOWN - cannot read the state of the server process (%s)" % where)
    if x["running"] is False:
        return line(2, name, "-", "Enabled but the server is NOT running (%s): nobody can connect" % where)
    if not x["users_ok"]:
        return line(3, name, "-", "UNKNOWN - cannot read the users and the connected clients (%s)" % where)
    n = len(x["connected"])
    perf = "clients=%d;;;0;%d|users=%d" % (n, max(x["users"], n), x["users"])
    names = sorted(x["connected"])
    shown = ", ".join(names[:MAX_NAMES]) + (" +%d" % (n - MAX_NAMES) if n > MAX_NAMES else "")
    text = "%s, %s, %d client(s) connected%s, %d enabled user(s)" % (
        "Running" if x["running"] else "Enabled (running state not available from the API)", where, n,
        " (%s)" % shown if n else "", x["users"])
    return line(0, name, perf, text)


def evaluate(instances):
    if not instances:
        return [line(0, SERVICE, "-", "No road-warrior instance configured")]
    return [evaluate_one(x) for x in instances]


def unknown_lines(names, err):
    """The API is unreadable: keep the per-instance services alive as UNKNOWN."""
    if not names:
        return [line(3, SERVICE, "-", "UNKNOWN: %s" % err)]
    return [line(3, "%s.%s" % (SERVICE, label(n)), "-", "UNKNOWN - %s" % err) for n in names]


# ---------------------------------------------------------------- main
def run():
    cache = load_cache()
    api = Api()
    err = open_session(api, cache)
    if err:
        return unknown_lines(cache.get("names", []), err)
    instances, err = collect(api)
    if err:
        return unknown_lines(cache.get("names", []), err)
    cache["names"] = [x["name"] for x in instances]
    save_cache(cache)
    return evaluate(instances)


def self_test():
    failed, done = [], []

    def check(name, cond):
        done.append(name)
        print("%s %s" % ("ok  " if cond else "FAIL", name))
        if not cond:
            failed.append(name)

    def inst(name="ns_roadwarrior1", **kw):
        x = {"name": name, "label": label(name), "config_ok": True, "enabled": True, "running": True, "users_ok": True,
             "users": 3, "connected": [], "port": "1194", "proto": "udp"}
        x.update(kw)
        return x

    payload = base64.urlsafe_b64encode(json.dumps({"exp": 7}).encode()).decode().rstrip("=")
    check("jwt exp", jwt_exp("x.%s.y" % payload) == 7 and jwt_exp("bad") == 0)
    check("labels", label("ns_roadwarrior1") == "roadwarrior1" and label("custom") == "custom")
    check("unwrap", unwrap({"result": {"status": "ok"}}) == {"status": "ok"} and unwrap({"a": 1, "b": 2}) == {"a": 1, "b": 2})

    check("no instance -> OK", evaluate([]) == ["0 OVPN.HostToNet - No road-warrior instance configured"])
    ln = evaluate_one(inst(enabled=False, running=None))
    check("disabled -> OK", ln == "0 OVPN.HostToNet.roadwarrior1 - Disabled (1194/udp)")
    ln = evaluate_one(inst())
    check("running, nobody connected -> OK, perfdata, no thresholds", ln.startswith("0 OVPN.HostToNet.roadwarrior1 clients=0;;;0;3|users=3 Running, 1194/udp, 0 client(s) connected, 3 enabled user(s)"))
    ln = evaluate_one(inst(connected=["mario", "anna"]))
    check("connected users listed, sorted", "2 client(s) connected (anna, mario)" in ln and "clients=2;;;0;3" in ln and ln.startswith("0 "))
    ln = evaluate_one(inst(connected=["u%d" % i for i in range(8)], users=8))
    check("more than MAX_NAMES: truncated with a count", "(u0, u1, u2, u3, u4 +3)" in ln)
    ln = evaluate_one(inst(running=False))
    check("enabled but not running -> CRIT (was OK 'not running')", ln.startswith("2 OVPN.HostToNet.roadwarrior1 ") and "NOT running" in ln)
    ln = evaluate_one(inst(running="unreadable"))
    check("process state unreadable -> UNKNOWN", ln.startswith("3 "))
    ln = evaluate_one(inst(users_ok=False))
    check("users unreadable -> UNKNOWN (was counted as 0)", ln.startswith("3 ") and "cannot read the users" in ln)
    ln = evaluate_one(inst(config_ok=False))
    check("configuration unreadable -> UNKNOWN", ln.startswith("3 ") and "ns_roadwarrior1" in ln)
    ln = evaluate_one(inst("ns_roadwarrior2", running=None, connected=["x"]))
    check("instance without running state: OK, says so", ln.startswith("0 OVPN.HostToNet.roadwarrior2 clients=1") and "running state not available" in ln)
    out = evaluate([inst(), inst("ns_roadwarrior2", running=None)])
    check("two instances: two services", len(out) == 2 and out[1].startswith("0 OVPN.HostToNet.roadwarrior2 "))
    out = unknown_lines(["ns_roadwarrior1", "ns_roadwarrior2"], "login failed (HTTP 401)")
    check("API down with history: one UNKNOWN per instance", len(out) == 2 and out[0].startswith("3 OVPN.HostToNet.roadwarrior1 "))
    check("API down without history: one UNKNOWN service", unknown_lines([], "x") == ["3 OVPN.HostToNet - UNKNOWN: x"])

    class Fake(object):
        def __init__(self, data):
            self.data = data
            self.calls = []

        def call(self, path, method, payload=None, timeout=15):
            self.calls.append((path, method))
            v = self.data.get((path, method))
            return ("ok", v) if v is not None else ("error", None)

    base = {
        ("ns.ovpnrw", "list-instances"): {"instances": ["ns_roadwarrior1", "ns_roadwarrior2"]},
        ("ns.ovpnrw", "get-configuration"): {"enabled": "1", "port": "1194", "proto": "udp", "ns_user_db": ""},
        ("ns.dashboard", "service-status"): {"result": {"status": "ok"}},
        ("ns.ovpnrw", "list-users"): {"users": [
            {"name": "mario", "connected": True, "openvpn_enabled": "1", "2fa": "SECRET-SEED"},
            {"name": "anna", "connected": False, "openvpn_enabled": "1"},
            {"name": "old", "connected": False, "openvpn_enabled": "0"}]},
    }
    fk = Fake(base)
    ins, err = collect(fk)
    check("collect: two instances, running state only for roadwarrior1", err == "" and len(ins) == 2 and ins[0]["running"] is True and ins[1]["running"] is None)
    check("collect: enabled users and connected names", ins[0]["users"] == 2 and ins[0]["connected"] == ["mario"] and "SECRET-SEED" not in json.dumps(ins))
    check("collect: service-status asked once", fk.calls.count(("ns.dashboard", "service-status")) == 1)
    for status in ({"result": {"status": None}}, {"result": {"status": "error"}}):
        d2 = dict(base)
        d2[("ns.dashboard", "service-status")] = status
        ins, _ = collect(Fake(d2))
        check("collect: status %r -> not running" % (status["result"]["status"],), ins[0]["running"] is False)
    d2 = dict(base)
    del d2[("ns.dashboard", "service-status")]
    ins, _ = collect(Fake(d2))
    check("collect: service-status call fails -> unreadable", ins[0]["running"] == "unreadable")
    d2 = dict(base)
    d2[("ns.ovpnrw", "get-configuration")] = {"enabled": "0", "port": "1194", "proto": "udp"}
    fk = Fake(d2)
    ins, _ = collect(fk)
    check("collect: disabled instance -> service-status not asked", ins[0]["enabled"] is False and ins[0]["running"] is None and ("ns.dashboard", "service-status") not in fk.calls)
    ins, err = collect(Fake({}))
    check("collect: unreadable instance list gives an error", ins == [] and err.startswith("cannot read the road-warrior instance list"))

    global PASSWORD_FILE, CACHE_FILE
    saved = (PASSWORD_FILE, CACHE_FILE)
    PASSWORD_FILE, CACHE_FILE = "/nonexistent/pass", "/nonexistent/cache"
    try:
        lines = run()
    finally:
        PASSWORD_FILE, CACHE_FILE = saved
    check("no credentials and no history: one UNKNOWN service", len(lines) == 1 and lines[0].startswith("3 OVPN.HostToNet "))

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
