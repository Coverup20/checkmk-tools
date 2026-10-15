#!/usr/bin/python3
"""check_dhcp_leases_api.py - NethSecurity DHCP lease usage for CheckMK, REST API only (PROTOTYPE)

CheckMK local check, to run ON the firewall. No subprocess, no UCI, no nethsec library, no lease file: everything goes
through the firewall's own REST API on localhost (NSEC_API, default https://127.0.0.1:9090/api), logged in with a
dedicated account (NSEC_USER, default claude-ro; password in NSEC_PASSWORD_FILE, default /root/.nsec-ro-pass, mode
600). The calls are ubus read methods through POST /api/ubus/call:
- ns.dhcp list-interfaces      per interface: DHCP active or not, and its address ranges (first, last);
- ns.dhcp list-active-leases   the active leases (static reservations are already left out by the API), each with its
                               interface, address and expiry.

Service, one per interface with an active DHCP pool: DHCP.Leases.<interface>
  "Leases active: N/capacity (P%) - STATE (R range(s))", WARN at 80% and CRIT at 90% of the capacity of that pool
  (the same thresholds and perfdata names as check_dhcp_leases.py: active with levels, percent, plus ranges).
  Without any active pool: DHCP.Leases, OK, "No active DHCP pool found".

Corrections to the legacy check, on purpose:
- one service per pool: the legacy check summed the capacity of every pool and counted every lease of the file, so a
  full pool hid behind an empty one;
- only the leases inside the pool ranges are counted (the legacy check also counted leases of reservations and of other
  ranges, inflating the percentage); the ones outside are reported in the perfdata (outside) and, when there are any, in
  the text;
- when the data cannot be read the result is UNKNOWN. The legacy check answered OK "No active DHCP pool found" when
  its UCI library was missing or failed, which hides the failure. OK is kept only for "really no active pool";
- no lease file lookup (it moved between /tmp and /mnt/data in the legacy code): the API knows where it is;
- the perfdata expired and total are gone: the API returns only the active leases and they never fed a threshold.

When the API cannot be read, the interfaces seen on the previous successful run (kept in the cache file) are reported
as UNKNOWN, so the per-pool services do not vanish from CheckMK; with no history, one DHCP.Leases service is UNKNOWN.

Security notes:
- The API does NOT enforce per-object permissions for /api/ubus/call (verified 2026-10-14 on NethSecurity 8.8.0): an
  account limited by an rpcd ACL group can still call any ubus object. claude-ro has a read-only ACL group
  (ns-check-reader) but must be treated as a full administrator account.
- TLS verification is off for the loopback connection only (the firewall's certificate is self-signed).
- The check only reads. It never enables a DHCP server.

Cache: the API token and the last known interfaces are kept in NSEC_DHCP_CACHE (default
/tmp/check_dhcp_leases_api.cache, mode 600).

Version: 0.1.0"""

import base64
import ipaddress
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
CACHE_FILE = os.environ.get("NSEC_DHCP_CACHE", "/tmp/check_dhcp_leases_api.cache")
SERVICE = "DHCP.Leases"
PCT_WARN = 80
PCT_CRIT = 90
STATE_WORD = {0: "OK", 1: "WARNING", 2: "CRITICAL"}


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
def ip_int(text):
    try:
        return int(ipaddress.IPv4Address(text))
    except (ipaddress.AddressValueError, ValueError, TypeError):
        return None


def collect(api):
    """Returns (pools, leases, error). pools: {interface: [(first_int, last_int), ...]} for the interfaces with an
    active DHCP pool. leases: list of {interface, ip, expiry}. error is "" or a short text."""
    st, d = api.call("ns.dhcp", "list-interfaces")
    if st != "ok" or not isinstance(d, dict):
        return {}, [], "cannot read the DHCP interfaces (%s)" % st
    pools = {}
    for name, rec in d.items():
        if not isinstance(rec, dict) or not rec.get("active"):
            continue
        ranges = []
        for r in rec.get("ranges") or []:
            f, l = ip_int((r or {}).get("first")), ip_int((r or {}).get("last"))
            if f is not None and l is not None and l >= f:
                ranges.append((f, l))
        if ranges:
            pools[name] = ranges
    leases = []
    if pools:
        sl, ld = api.call("ns.dhcp", "list-active-leases")
        if sl != "ok" or not isinstance(ld, dict):
            return {}, [], "cannot read the active leases (%s)" % sl
        for x in ld.get("leases") or []:
            if not isinstance(x, dict):
                continue
            try:
                expiry = int(x.get("timestamp"))
            except (TypeError, ValueError):
                expiry = -1
            leases.append({"interface": x.get("interface"), "ip": ip_int(x.get("ipaddr")), "expiry": expiry})
    return pools, leases, ""


# ---------------------------------------------------------------- evaluation
def line(state, name, perf, text):
    return "%d %s %s %s" % (state, name, perf or "-", text)


def is_active(lease, now):
    return lease["expiry"] == 0 or lease["expiry"] > now


def evaluate(pools, leases, now):
    if not pools:
        return [line(0, SERVICE, "-", "No active DHCP pool found")]
    out = []
    for name in sorted(pools):
        ranges = pools[name]
        capacity = sum(l - f + 1 for f, l in ranges)
        mine = [x for x in leases if x["interface"] == name and is_active(x, now)]
        inside = [x for x in mine if x["ip"] is not None and any(f <= x["ip"] <= l for f, l in ranges)]
        outside = len(mine) - len(inside)
        active = len(inside)
        pct = active / capacity * 100 if capacity else 0.0
        state = 2 if pct >= PCT_CRIT else (1 if pct >= PCT_WARN else 0)
        # levels as decimals: truncating to integers made warn and crit equal on small pools (4 and 4 for 5 addresses)
        perf = "active=%d;%g;%g;0;%d|percent=%.0f;%d;%d;0;100|ranges=%d|outside=%d" % (
            active, capacity * PCT_WARN / 100, capacity * PCT_CRIT / 100, capacity, pct, PCT_WARN, PCT_CRIT, len(ranges), outside)
        extra = ", %d lease(s) outside the range" % outside if outside else ""
        out.append(line(state, "%s.%s" % (SERVICE, name), perf, "Leases active: %d/%d (%.0f%%) - %s (%d range(s))%s" % (
            active, capacity, pct, STATE_WORD[state], len(ranges), extra)))
    return out


def unknown_lines(names, err):
    """The data is unreadable: keep the per-pool services alive as UNKNOWN."""
    if not names:
        return [line(3, SERVICE, "-", "UNKNOWN: %s" % err)]
    return [line(3, "%s.%s" % (SERVICE, n), "-", "UNKNOWN - %s" % err) for n in names]


# ---------------------------------------------------------------- main
def run():
    cache = load_cache()
    api = Api()
    err = open_session(api, cache)
    if err:
        return unknown_lines(cache.get("pools", []), err)
    pools, leases, err = collect(api)
    if err:
        return unknown_lines(cache.get("pools", []), err)
    cache["pools"] = sorted(pools)
    save_cache(cache)
    return evaluate(pools, leases, time.time())


def self_test():
    failed, done = [], []

    def check(name, cond):
        done.append(name)
        print("%s %s" % ("ok  " if cond else "FAIL", name))
        if not cond:
            failed.append(name)

    now = 1_800_000_000
    ip = lambda s: ip_int(s)
    lease = lambda iface, addr, exp=now + 3600: {"interface": iface, "ip": ip(addr), "expiry": exp}
    pool = {"lan": [(ip("192.168.1.100"), ip("192.168.1.149"))]}

    check("ip_int parses and rejects", ip("10.0.0.1") == 167772161 and ip_int("x") is None and ip_int(None) is None)
    payload = base64.urlsafe_b64encode(json.dumps({"exp": 5}).encode()).decode().rstrip("=")
    check("jwt exp", jwt_exp("x.%s.y" % payload) == 5 and jwt_exp("bad") == 0)

    out = evaluate({}, [], now)
    check("no active pool: OK, one DHCP.Leases line", out == ["0 DHCP.Leases - No active DHCP pool found"])
    out = evaluate(pool, [], now)
    check("empty pool: OK 0/50 with levels in the perfdata", out[0].startswith("0 DHCP.Leases.lan active=0;40;45;0;50|percent=0;80;90;0;100|ranges=1|outside=0 Leases active: 0/50 (0%) - OK (1 range(s))"))
    out = evaluate(pool, [lease("lan", "192.168.1.%d" % (100 + i)) for i in range(40)], now)
    check("80% -> WARN", out[0].startswith("1 DHCP.Leases.lan active=40;") and "(80%) - WARNING" in out[0])
    out = evaluate(pool, [lease("lan", "192.168.1.%d" % (100 + i)) for i in range(45)], now)
    check("90% -> CRIT", out[0].startswith("2 ") and "(90%) - CRITICAL" in out[0])
    out = evaluate(pool, [lease("lan", "192.168.1.%d" % (100 + i)) for i in range(39)], now)
    check("just under 80% -> OK", out[0].startswith("0 ") and "(78%)" in out[0])
    out = evaluate(pool, [lease("lan", "192.168.1.5"), lease("lan", "192.168.1.200")], now)
    check("leases outside the range are not counted, reported as outside", out[0].startswith("0 ") and "active=0;" in out[0] and "outside=2" in out[0] and "2 lease(s) outside the range" in out[0])
    out = evaluate(pool, [lease("lan", "192.168.1.100", exp=now - 10), lease("lan", "192.168.1.101", exp=0)], now)
    check("expired lease ignored, infinite lease (0) counted", "active=1;" in out[0] and "outside=0" in out[0])
    out = evaluate(pool, [lease("other", "192.168.1.100")], now)
    check("a lease of another interface is not counted", "active=0;" in out[0])
    two = {"lan": [(ip("192.168.1.100"), ip("192.168.1.109"))], "guest": [(ip("10.0.0.10"), ip("10.0.0.19"))]}
    out = evaluate(two, [lease("guest", "10.0.0.%d" % (10 + i)) for i in range(10)], now)
    check("two pools: the full one is CRIT, the empty one stays OK", out[0].startswith("2 DHCP.Leases.guest ") and out[1].startswith("0 DHCP.Leases.lan "))
    multi = {"lan": [(ip("192.168.1.100"), ip("192.168.1.109")), (ip("192.168.1.200"), ip("192.168.1.209"))]}
    out = evaluate(multi, [lease("lan", "192.168.1.205")], now)
    check("two ranges on one interface: capacity adds up, a lease in the second counts", "1/20" in out[0] and "(2 range(s))" in out[0])
    out = unknown_lines(["lan", "guest"], "login failed (HTTP 401)")
    check("API down with history: one UNKNOWN per pool", len(out) == 2 and all(o.startswith("3 DHCP.Leases.") for o in out))
    check("API down without history: one UNKNOWN service", unknown_lines([], "x") == ["3 DHCP.Leases - UNKNOWN: x"])

    class Fake(object):
        def __init__(self, data):
            self.data = data

        def call(self, path, method, payload=None, timeout=15):
            v = self.data.get((path, method))
            return ("ok", v) if v is not None else ("error", None)

    fake = Fake({
        ("ns.dhcp", "list-interfaces"): {
            "LAN": {"active": False, "ranges": []},
            "lan2": {"active": True, "ranges": [{"first": "10.99.99.98", "last": "10.99.99.102"}]},
            "off": {"active": False, "ranges": [{"first": "1.1.1.1", "last": "1.1.1.9"}]}},
        ("ns.dhcp", "list-active-leases"): {"leases": [
            {"timestamp": "1900000000", "macaddr": "aa", "ipaddr": "10.99.99.101", "hostname": "h", "interface": "lan2", "device": "eth3"},
            {"timestamp": "oops", "macaddr": "bb", "ipaddr": "10.99.99.100", "hostname": "", "interface": "lan2", "device": "eth3"}]},
    })
    pools, leases, err = collect(fake)
    check("collect: only the active interface, its range, both leases", err == "" and list(pools) == ["lan2"] and pools["lan2"] == [(ip("10.99.99.98"), ip("10.99.99.102"))] and len(leases) == 2)
    out = evaluate(pools, leases, now)
    check("collect + evaluate: an unreadable expiry is not counted", out[0].startswith("0 DHCP.Leases.lan2 ") and "1/5 (20%)" in out[0])
    pools, leases, err = collect(Fake({}))
    check("collect: unreadable interfaces -> error (never an OK)", pools == {} and err.startswith("cannot read the DHCP interfaces"))
    half = Fake({("ns.dhcp", "list-interfaces"): {"lan2": {"active": True, "ranges": [{"first": "10.99.99.98", "last": "10.99.99.102"}]}}})
    pools, leases, err = collect(half)
    check("collect: unreadable leases -> error (never counted as zero)", pools == {} and err.startswith("cannot read the active leases"))
    quiet = Fake({("ns.dhcp", "list-interfaces"): {"LAN": {"active": False, "ranges": []}}})
    pools, leases, err = collect(quiet)
    check("collect: no active pool and a readable API is not an error", err == "" and pools == {} and evaluate(pools, leases, now) == ["0 DHCP.Leases - No active DHCP pool found"])

    global PASSWORD_FILE, CACHE_FILE
    saved = (PASSWORD_FILE, CACHE_FILE)
    PASSWORD_FILE, CACHE_FILE = "/nonexistent/pass", "/nonexistent/cache"
    try:
        lines = run()
    finally:
        PASSWORD_FILE, CACHE_FILE = saved
    check("no credentials and no history: one UNKNOWN service", len(lines) == 1 and lines[0].startswith("3 DHCP.Leases "))

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
