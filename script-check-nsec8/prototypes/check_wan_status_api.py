#!/usr/bin/python3
"""check_wan_status_api.py - NethSecurity WAN status for CheckMK, REST API only (PROTOTYPE)

CheckMK local check, to run ON the firewall. No subprocess, no UCI, no nethsec library: everything goes through the
firewall's own REST API on localhost (NSEC_API, default https://127.0.0.1:9090/api), logged in with a dedicated account
(NSEC_USER, default claude-ro; password in NSEC_PASSWORD_FILE, default /root/.nsec-ro-pass, mode 600). The calls are
ubus read methods through POST /api/ubus/call:
- ns.dashboard list-wans                    the WAN interfaces (name and device), as the web UI lists them;
- network.interface dump                    interface up/down and its default gateway (the API refuses the per-interface
                                            "status" call, HTTP 403);
- ns.dashboard service-status internet      the firewall's own "Internet" indicator.

Services:
- WAN.Interface.<label>  one per WAN, same as check_wan_status.py: the interface itself is up (OK) or down (CRIT).
- WAN.Internet           one for the firewall: does it reach the internet. OK when it does; WARN when it does not
                         although some WAN is up (likely an upstream/ISP issue, the gateways are in the text); CRIT when
                         it does not and no WAN is up.
- WAN.Metrics            same perfdata as check_wan_status.py: total, up, down, degraded (WANs that are up while the
                         internet check fails).
- WAN.Internet only      when no WAN is configured: OK, "No WAN interfaces found".

Differences from check_wan_status.py, on purpose:
- the legacy check had WAN.Status.<label> on top of WAN.Interface.<label>: it pinged four hosts through each WAN device
  (ping -I) and so told apart "interface down" from "up but no internet" per WAN. The API has no per-WAN test: it only
  offers the firewall's own "Internet" indicator (the same four hosts, 2 of 4 must answer), run over the default route.
  A per-WAN service would repeat the interface state and the same global verdict, so the verdict is one service,
  WAN.Internet, that says what is really measured.
- the internet probe has no ping timeout inside the firewall: when nothing answers it hangs (verified by blocking
  outgoing ICMP, the API answers "Request timed out"). The check waits at most INTERNET_TIMEOUT (12) seconds for it and
  treats "did not finish" as "no internet" (WARN, with a text that says so), so the agent run never stalls.

When the API cannot be read, the WANs seen on the previous successful run (kept in the cache file) are reported as
UNKNOWN, so the per-WAN services do not vanish from CheckMK; with no history, one WAN.Internet service is UNKNOWN.

Security notes:
- The API does NOT enforce per-object permissions for /api/ubus/call (verified 2026-10-14 on NethSecurity 8.8.0): an
  account limited by an rpcd ACL group can still call any ubus object. claude-ro has a read-only ACL group
  (ns-check-reader) but must be treated as a full administrator account.
- TLS verification is off for the loopback connection only (the firewall's certificate is self-signed).

Cache: the API token and the last known WAN labels are kept in NSEC_WAN_CACHE (default /tmp/check_wan_status_api.cache,
mode 600).

Version: 0.2.0"""

import base64
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

VERSION = "0.2.0"
API = os.environ.get("NSEC_API", "https://127.0.0.1:9090/api")
USER = os.environ.get("NSEC_USER", "claude-ro")
PASSWORD_FILE = os.environ.get("NSEC_PASSWORD_FILE", "/root/.nsec-ro-pass")
CACHE_FILE = os.environ.get("NSEC_WAN_CACHE", "/tmp/check_wan_status_api.cache")
SVC_INTERNET = "WAN.Internet"


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


def unwrap(data):
    """ns.* results come back as {"result": ...} or {"values": ...}: return the inner value."""
    if isinstance(data, dict) and len(data) == 1 and next(iter(data)) in ("result", "values"):
        return next(iter(data.values()))
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
def gateway_of(status):
    for route in status.get("route") or []:
        if isinstance(route, dict) and route.get("target") == "0.0.0.0":
            return route.get("nexthop")
    return None


INTERNET_TIMEOUT = 12  # seconds; the firewall's own internet probe hangs (4 pings, no -W) when nothing answers


def collect(api, clock=time.monotonic):
    """Returns (wans, internet, error). wans: list of {label, device, up, gateway} ; up is None when unreadable.
    internet is True, False, "timeout" (the probe did not finish in INTERNET_TIMEOUT seconds: with every ping
    unanswered it hangs, as verified by blocking outgoing ICMP) or None (unreadable). error is "" or a short text."""
    st, d = api.call("ns.dashboard", "list-wans")
    if st != "ok":
        return [], None, "cannot read the WAN list (%s)" % st
    rows = unwrap(d)
    # One call for all interfaces: the API refuses "network.interface.<name> status" (HTTP 403, method not allowed)
    # but allows "network.interface dump".
    dst, dump = api.call("network.interface", "dump")
    by_name = {}
    if dst == "ok" and isinstance(dump, dict):
        for i in dump.get("interface") or []:
            if isinstance(i, dict) and i.get("interface"):
                by_name[i["interface"]] = i
    wans = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        label = r.get("iface") or r.get("device") or "?"
        status = by_name.get(label)
        up, gw = None, None
        if status is not None:
            up = bool(status.get("up"))
            gw = gateway_of(status)
        wans.append({"label": label, "device": r.get("device") or "", "up": up, "gateway": gw})
    internet = None
    started = clock()
    ist, idata = api.call("ns.dashboard", "service-status", {"service": "internet"}, INTERNET_TIMEOUT)
    if ist == "ok":
        res = unwrap(idata)
        internet = isinstance(res, dict) and res.get("status") == "ok"
    elif ist in ("unreachable", "error") and clock() - started >= INTERNET_TIMEOUT - 1:
        internet = "timeout"
    return wans, internet, ""


# ---------------------------------------------------------------- evaluation
def line(state, name, perf, text):
    return "%d %s %s %s" % (state, name, perf or "-", text)


def eval_internet(wans, internet, up_wans, unknown):
    """The verdict service. up_wans: the WANs that are up."""
    if internet is True:
        return line(0, SVC_INTERNET, "-", "OK - the firewall reaches the internet (checked from the firewall, not per WAN)")
    if internet is None:
        return line(3, SVC_INTERNET, "-", "UNKNOWN - the internet check could not be read")
    how = "the internet check did not finish in %d s" % INTERNET_TIMEOUT if internet == "timeout" else "no internet reachability"
    if not up_wans and not unknown:
        return line(2, SVC_INTERNET, "-", "CRITICAL - %s and no WAN is up" % how)
    gws = ", ".join("%s via %s" % (w["label"], w["gateway"]) if w["gateway"] else w["label"] for w in up_wans)
    return line(1, SVC_INTERNET, "-", "WARNING - %s although %s up (%s), likely an upstream/ISP issue (checked from the firewall, not per WAN)" % (
        how, "a WAN is" if len(up_wans) == 1 else "%d WANs are" % len(up_wans), gws) if up_wans else
        "WARNING - %s and the state of some WAN is unknown" % how)


def evaluate(wans, internet):
    if not wans:
        return [line(0, SVC_INTERNET, "-", "No WAN interfaces found")]
    out = []
    up_wans = [w for w in wans if w["up"] is True]
    down = [w for w in wans if w["up"] is False]
    unknown = [w for w in wans if w["up"] is None]
    for w in wans:
        name = "WAN.Interface.%s" % w["label"]
        if w["up"] is None:
            out.append(line(3, name, "-", "UNKNOWN - cannot read the interface status"))
        else:
            out.append(line(0 if w["up"] else 2, name, "-", "UP" if w["up"] else "DOWN"))
    out.append(eval_internet(wans, internet, up_wans, unknown))
    degraded = len(up_wans) if internet is not True and internet is not None else 0
    perf = "total=%d|up=%d|down=%d|degraded=%d" % (len(wans), len(up_wans), len(down), degraded)
    out.append(line(3 if unknown else 0, "WAN.Metrics", perf, "Total=%d Up=%d Down=%d Degraded=%d%s" % (
        len(wans), len(up_wans), len(down), degraded, " Unknown=%d" % len(unknown) if unknown else "")))
    return out


def unknown_lines(labels, err):
    """The API is unreadable: keep the per-WAN services alive as UNKNOWN."""
    out = [line(3, "WAN.Interface.%s" % label, "-", "UNKNOWN - %s" % err) for label in labels]
    out.append(line(3, SVC_INTERNET, "-", "UNKNOWN: %s" % err))
    if labels:
        out.append(line(3, "WAN.Metrics", "-", "UNKNOWN - %s" % err))
    return out


# ---------------------------------------------------------------- main
def run():
    cache = load_cache()
    api = Api()
    err = open_session(api, cache)
    if err:
        return unknown_lines(cache.get("labels", []), err)
    wans, internet, err = collect(api)
    if err:
        return unknown_lines(cache.get("labels", []), err)
    cache["labels"] = [w["label"] for w in wans]
    save_cache(cache)
    return evaluate(wans, internet)


def self_test():
    failed, done = [], []

    def check(name, cond):
        done.append(name)
        print("%s %s" % ("ok  " if cond else "FAIL", name))
        if not cond:
            failed.append(name)

    w = lambda label, up=True, gw="10.0.0.1": {"label": label, "device": "eth" + label[-1:], "up": up, "gateway": gw}

    check("unwrap result/values", unwrap({"result": [1]}) == [1] and unwrap({"values": 2}) == 2 and unwrap({"a": 1, "b": 2}) == {"a": 1, "b": 2})
    payload = base64.urlsafe_b64encode(json.dumps({"exp": 99}).encode()).decode().rstrip("=")
    check("jwt exp", jwt_exp("x.%s.y" % payload) == 99 and jwt_exp("bad") == 0)
    check("gateway from routes", gateway_of({"route": [{"target": "10.0.0.0", "nexthop": "0.0.0.0"}, {"target": "0.0.0.0", "nexthop": "192.168.1.1"}]}) == "192.168.1.1")
    check("no default route -> no gateway", gateway_of({"route": []}) is None and gateway_of({}) is None)

    out = evaluate([], True)
    check("no WAN -> one OK WAN.Internet line", out == ["0 WAN.Internet - No WAN interfaces found"])
    out = evaluate([w("wan")], True)
    check("one WAN up, internet ok: interface, WAN.Internet, metrics, all OK", [o.split()[0] for o in out] == ["0", "0", "0"] and out[0] == "0 WAN.Interface.wan - UP" and out[1].startswith("0 WAN.Internet - OK"))
    check("there is no WAN.Status.<label> service any more", not any("WAN.Status" in o for o in out))
    check("metrics perfdata like the legacy check", out[2] == "0 WAN.Metrics total=1|up=1|down=0|degraded=0 Total=1 Up=1 Down=0 Degraded=0")
    out = evaluate([w("wan", up=False)], False)
    check("only WAN down and no internet: interface CRIT, WAN.Internet CRIT", out[0].startswith("2 WAN.Interface.wan - DOWN") and out[1].startswith("2 WAN.Internet - CRITICAL") and "no WAN is up" in out[1])
    check("WAN down counted as down, not degraded", "total=1|up=0|down=1|degraded=0" in out[2])
    out = evaluate([w("wan")], False)
    check("up without internet: interface OK, WAN.Internet WARN with the gateway", out[0].startswith("0 ") and out[1].startswith("1 WAN.Internet") and "wan via 10.0.0.1" in out[1] and "not per WAN" in out[1])
    check("degraded counted", "total=1|up=1|down=0|degraded=1" in out[2])
    out = evaluate([w("wan", gw=None)], False)
    check("no gateway: only the label in the text", "(wan)" in out[1] and "via" not in out[1])
    out = evaluate([w("wan"), w("wan2", up=False)], True)
    check("two WANs, one down, internet ok: interface CRIT only on the down one, WAN.Internet OK", out[0].startswith("0 WAN.Interface.wan ") and out[1].startswith("2 WAN.Interface.wan2") and out[2].startswith("0 WAN.Internet") and "total=2|up=1|down=1|degraded=0" in out[3])
    out = evaluate([w("wan"), w("wan2")], False)
    check("two WANs up, no internet: WARN names both", out[2].startswith("1 WAN.Internet") and "2 WANs are up" in out[2] and "wan via 10.0.0.1, wan2 via 10.0.0.1" in out[2] and "degraded=2" in out[3])
    out = evaluate([w("wan", up=False), w("wan2", up=False)], False)
    check("every WAN down and no internet: CRIT", out[2].startswith("2 WAN.Internet - CRITICAL"))
    out = evaluate([w("wan"), w("wan2")], None)
    check("internet unreadable: UNKNOWN verdict, interfaces still OK, metrics OK", out[0].startswith("0 ") and out[2].startswith("3 WAN.Internet") and out[3].startswith("0 WAN.Metrics") and "degraded=0" in out[3])
    out = evaluate([{"label": "wan", "device": "eth1", "up": None, "gateway": None}], False)
    check("interface unreadable: UNKNOWN interface, WARN (not CRIT) verdict, metrics UNKNOWN", out[0].startswith("3 WAN.Interface.wan") and out[1].startswith("1 WAN.Internet") and "unknown" in out[1] and out[2].startswith("3 WAN.Metrics") and "Unknown=1" in out[2])
    out = evaluate([w("wan")], "timeout")
    check("timeout -> WARN that says the check did not finish", out[1].startswith("1 WAN.Internet") and "did not finish in 12 s" in out[1])
    out = unknown_lines(["wan", "wan2"], "login failed (HTTP 401)")
    check("API down with history: interfaces, WAN.Internet and metrics UNKNOWN", len(out) == 4 and all(o.startswith("3 ") for o in out) and any("WAN.Interface.wan2" in o for o in out))
    out = unknown_lines([], "API unreachable")
    check("API down without history: one UNKNOWN service", out == ["3 WAN.Internet - UNKNOWN: API unreachable"])

    class Fake(object):
        def __init__(self, data):
            self.data = data

        def call(self, path, method, payload=None, timeout=15):
            v = self.data.get((path, method))
            return ("ok", v) if v is not None else ("error", None)

    fake = Fake({
        ("ns.dashboard", "list-wans"): {"result": [{"iface": "wan", "device": "eth1"}, {"iface": "wan2", "device": "eth2"}]},
        ("network.interface", "dump"): {"interface": [
            {"interface": "LAN", "up": True, "route": []},
            {"interface": "wan", "up": True, "route": [{"target": "0.0.0.0", "nexthop": "192.168.124.1"}]},
            {"interface": "wan2", "up": False, "route": []}]},
        ("ns.dashboard", "service-status"): {"result": {"status": "ok"}},
    })
    wans, internet, err = collect(fake)
    check("collect: two WANs, gateway, up flags, internet ok", err == "" and [x["label"] for x in wans] == ["wan", "wan2"] and wans[0]["gateway"] == "192.168.124.1" and wans[0]["up"] and not wans[1]["up"] and internet is True)
    out = evaluate(wans, internet)
    check("collect + evaluate: wan OK, wan2 CRIT, internet OK", out[0].startswith("0 WAN.Interface.wan ") and out[1].startswith("2 WAN.Interface.wan2 ") and out[2].startswith("0 WAN.Internet"))
    wans, internet, err = collect(Fake({}))
    check("collect: unreadable WAN list gives an error", wans == [] and err.startswith("cannot read the WAN list"))
    fake.data[("ns.dashboard", "service-status")] = {"result": {"status": "error"}}
    check("collect: internet error is False, not None", collect(fake)[1] is False)

    ticks = iter([0, 12, 12, 12])
    slow = Fake({("ns.dashboard", "list-wans"): {"result": [{"iface": "wan", "device": "eth1"}]},
                 ("network.interface", "dump"): {"interface": [{"interface": "wan", "up": True, "route": []}]}})
    check("collect: a probe that hangs for the full timeout is 'timeout'", collect(slow, clock=lambda: next(ticks))[1] == "timeout")
    ticks = iter([0, 0, 0, 0])
    check("collect: a fast failure of the probe stays unreadable (None)", collect(slow, clock=lambda: next(ticks))[1] is None)

    global PASSWORD_FILE, CACHE_FILE
    saved = (PASSWORD_FILE, CACHE_FILE)
    PASSWORD_FILE, CACHE_FILE = "/nonexistent/pass", "/nonexistent/cache"
    try:
        lines = run()
    finally:
        PASSWORD_FILE, CACHE_FILE = saved
    check("no credentials and no history: one UNKNOWN service", len(lines) == 1 and lines[0].startswith("3 WAN.Internet "))

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
