#!/usr/bin/python3
"""check_firewall_traffic_api.py - NethSecurity WAN/LAN interface traffic for CheckMK, REST API only (PROTOTYPE)

CheckMK local check, to run ON the firewall. No subprocess, no UCI, no nethsec library, no /proc or /sys: everything
goes through the firewall's own REST API on localhost (NSEC_API, default https://127.0.0.1:9090/api), logged in with a
dedicated account (NSEC_USER, default claude-ro; password in NSEC_PASSWORD_FILE, default /root/.nsec-ro-pass, mode
600). One ubus read method through POST /api/ubus/call:
- ns.devices list-devices   all devices with link state ("up"), byte/packet/error/drop counters ("stats"), and
                            "devices_by_zone", the firewall zone membership (lan, wan, vpn, ...).

Service: Traffic.<device>, one per device assigned to the wan or lan zone (same scope as check_firewall_traffic.py).
Rates (bytes, packets, errors, drops per second) come from the counters between two runs.

Thresholds, modelled on real failure modes (the legacy check had a single WARN on cumulative errors and no CRIT):
- link down ("up" is false)                                   CRIT
- (rx+tx errors) / (rx+tx packets) in the interval            WARN >= 0.1%, CRIT >= 1%   (bad cable, duplex/MTU)
- tx_dropped / tx_packets in the interval                     WARN >= 1%,   CRIT >= 5%   (egress queue overflow)
  Both ratios are evaluated only with at least MIN_PACKETS packets in the interval (a handful of packets on an idle
  link would make any ratio meaningless).
- rx_dropped is perfdata only: on a shared segment it counts unknown-protocol and broadcast frames the host never
  wanted (3.7% on the test VM's wan2 with zero errors), so a threshold would only be noise.
- link saturation is not evaluated here: WAN.Throughput already does it against the link speed.

Corrections to the legacy check, on purpose:
- cumulative error counters since boot (WARN forever after 100 old errors) become an error ratio over the interval;
- a CRIT state exists (link down, heavy errors, heavy tx drops): without one there is no alert and no ticket;
- the first measurement, a baseline older than MAX_INTERVAL (default 900 s) and counters that went backwards (reboot,
  driver reset) are OK, and the measurement restarts: not a problem of the line;
- an unreadable API is UNKNOWN, never OK; the devices seen on the last successful run (cache) are kept as UNKNOWN
  services so they do not vanish from CheckMK; a zone device the API does not list is UNKNOWN too, not silently skipped.

Perfdata: if_in_octets, if_out_octets (B/s), in_pps, out_pps, if_in_errors, if_out_errors, if_in_discards,
if_out_discards (per second), err_pct and txdrop_pct (with levels).

Security notes:
- The API does NOT enforce per-object permissions for /api/ubus/call (verified 2026-10-14 on NethSecurity 8.8.0): an
  account limited by an rpcd ACL group can still call any ubus object. claude-ro has a read-only ACL group
  (ns-check-reader) but must be treated as a full administrator account.
- TLS verification is off for the loopback connection only (the firewall's certificate is self-signed).

Cache: the API token, the last known device list and the counter baselines are kept in NSEC_TR_CACHE (default
/tmp/check_firewall_traffic_api.cache, mode 600).

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
CACHE_FILE = os.environ.get("NSEC_TR_CACHE", "/tmp/check_firewall_traffic_api.cache")
SERVICE = "Traffic"
ZONES = ("wan", "lan")
ERR_WARN_PCT = 0.1
ERR_CRIT_PCT = 1.0
TXDROP_WARN_PCT = 1.0
TXDROP_CRIT_PCT = 5.0
MIN_PACKETS = 1000
MAX_INTERVAL = 900  # seconds: an older baseline is discarded
COUNTERS = ("rx", "tx", "rx_pkt", "tx_pkt", "rx_err", "tx_err", "rx_drop", "tx_drop")


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
def num(v, default=0):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else default


def collect(api):
    """Returns (devices, error). devices: list of {name, up, stats}; stats is None when the device is not listed or
    its counters are incomplete, otherwise {rx, tx, rx_pkt, tx_pkt, rx_err, tx_err, rx_drop, tx_drop}."""
    st, d = api.call("ns.devices", "list-devices")
    if st != "ok" or not isinstance(d, dict):
        return [], "cannot read the device list (%s)" % st
    zones = d.get("devices_by_zone")
    if not isinstance(zones, list):
        return [], "the device list has no zone information"
    by_name = {}
    for x in d.get("all_devices") or []:
        if isinstance(x, dict) and x.get("name"):
            by_name[x["name"]] = x
    names = []
    for z in zones:
        if isinstance(z, dict) and z.get("name") in ZONES:
            for n in z.get("devices") or []:
                if isinstance(n, str) and n not in names:
                    names.append(n)
    out = []
    for n in sorted(names):
        x = by_name.get(n)
        stats, up = None, True
        if x is not None:
            up = x.get("up") is not False
            s = x.get("stats")
            if isinstance(s, dict):
                vals = {"rx": s.get("rx_bytes"), "tx": s.get("tx_bytes"), "rx_pkt": s.get("rx_packets"),
                        "tx_pkt": s.get("tx_packets"), "rx_err": s.get("rx_errors"), "tx_err": s.get("tx_errors"),
                        "rx_drop": s.get("rx_dropped"), "tx_drop": s.get("tx_dropped")}
                if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals.values()):
                    stats = vals
        out.append({"name": n, "up": up, "listed": x is not None, "stats": stats})
    return out, ""


# ---------------------------------------------------------------- evaluation
def line(state, name, perf, text):
    return "%d %s %s %s" % (state, name, perf or "-", text)


def fmt_bps(bps):
    if bps < 1024:
        return "%.1f B/s" % bps
    if bps < 1024 ** 2:
        return "%.1f KiB/s" % (bps / 1024)
    if bps < 1024 ** 3:
        return "%.2f MiB/s" % (bps / 1024 ** 2)
    return "%.2f GiB/s" % (bps / 1024 ** 3)


def level(value, warn, crit):
    return 2 if value >= crit else (1 if value >= warn else 0)


def evaluate_one(dev, base, now):
    """Returns (line, new_baseline). base is the previous {counters..., ts} or None."""
    name = "%s.%s" % (SERVICE, dev["name"])
    tag = "[%s]" % dev["name"]
    s = dev["stats"]
    zero = "if_in_octets=0|if_out_octets=0"
    if not dev["listed"]:
        return line(3, name, "-", "%s UNKNOWN - the device is in a WAN/LAN zone but the API does not list it" % tag), base
    if s is None:
        return line(3, name, "-", "%s UNKNOWN - cannot read the counters" % tag), base
    new = dict(s, ts=now)
    down = [] if dev["up"] else ["link is down"]
    if base is None:
        st = 2 if down else 0
        txt = "Initializing: rates are available at the next run"
        return line(st, name, zero, "%s %s" % (tag, ", ".join(down + [txt]))), new
    delta = now - base["ts"]
    if delta < 1:
        return line(2 if down else 0, name, zero, "%s %sInterval too short (%.1fs)" % (tag, "link is down, " if down else "", delta)), base
    if delta > MAX_INTERVAL:
        return line(2 if down else 0, name, zero, "%s %sBaseline older than %d s, restarting the measurement" % (
            tag, "link is down, " if down else "", MAX_INTERVAL)), new
    if any(s[k] < base.get(k, 0) for k in COUNTERS):
        return line(2 if down else 0, name, zero, "%s %sCounters reset, re-baselining" % (tag, "link is down, " if down else "")), new
    d = {k: s[k] - base[k] for k in COUNTERS if k in base}
    if len(d) != len(COUNTERS):  # baseline from an older cache layout
        return line(2 if down else 0, name, zero, "%s %sInitializing: rates are available at the next run" % (
            tag, "link is down, " if down else "")), new
    pkts = d["rx_pkt"] + d["tx_pkt"]
    err_pct = (d["rx_err"] + d["tx_err"]) * 100.0 / pkts if pkts >= MIN_PACKETS else 0.0
    txdrop_pct = d["tx_drop"] * 100.0 / d["tx_pkt"] if d["tx_pkt"] >= MIN_PACKETS else 0.0
    state = 2 if down else 0
    problems = list(down)
    es = level(err_pct, ERR_WARN_PCT, ERR_CRIT_PCT)
    if es:
        problems.append("errors %.2f%% of packets (%d rx, %d tx)" % (err_pct, d["rx_err"], d["tx_err"]))
    ts = level(txdrop_pct, TXDROP_WARN_PCT, TXDROP_CRIT_PCT)
    if ts:
        problems.append("tx drops %.2f%% of transmitted packets (%d)" % (txdrop_pct, d["tx_drop"]))
    state = max(state, es, ts)
    perf = ("if_in_octets=%.2f|if_out_octets=%.2f|in_pps=%.2f|out_pps=%.2f|if_in_errors=%.3f|if_out_errors=%.3f"
            "|if_in_discards=%.3f|if_out_discards=%.3f|err_pct=%.3f;%s;%s|txdrop_pct=%.3f;%s;%s") % (
        d["rx"] / delta, d["tx"] / delta, d["rx_pkt"] / delta, d["tx_pkt"] / delta, d["rx_err"] / delta,
        d["tx_err"] / delta, d["rx_drop"] / delta, d["tx_drop"] / delta, err_pct, ERR_WARN_PCT, ERR_CRIT_PCT,
        txdrop_pct, TXDROP_WARN_PCT, TXDROP_CRIT_PCT)
    text = "In: %s, Out: %s" % (fmt_bps(d["rx"] / delta), fmt_bps(d["tx"] / delta))
    if d["rx_drop"]:
        text += ", rx drops %.2f/s (not evaluated)" % (d["rx_drop"] / delta)
    if problems:
        text = "; ".join(problems) + " - " + text
    return line(state, name, perf, "%s %s" % (tag, text)), new


def evaluate(devices, baselines, now):
    """Returns (lines, new_baselines)."""
    if not devices:
        return [line(0, SERVICE, "-", "No WAN/LAN device found")], {}
    out, new_base = [], {}
    for dev in devices:
        ln, nb = evaluate_one(dev, baselines.get(dev["name"]), now)
        out.append(ln)
        if nb is not None:
            new_base[dev["name"]] = nb
    return out, new_base


def unknown_lines(names, err):
    """The API is unreadable: keep the per-device services alive as UNKNOWN."""
    if not names:
        return [line(3, SERVICE, "-", "UNKNOWN: %s" % err)]
    return [line(3, "%s.%s" % (SERVICE, n), "-", "UNKNOWN - %s" % err) for n in names]


# ---------------------------------------------------------------- main
def run():
    cache = load_cache()
    api = Api()
    err = open_session(api, cache)
    if err:
        return unknown_lines(cache.get("names", []), err)
    devices, err = collect(api)
    if err:
        return unknown_lines(cache.get("names", []), err)
    out, new_base = evaluate(devices, cache.get("baselines", {}), time.time())
    cache["names"] = [x["name"] for x in devices]
    cache["baselines"] = new_base
    save_cache(cache)
    return out


def self_test():
    failed, done = [], []

    def check(name, cond):
        done.append(name)
        print("%s %s" % ("ok  " if cond else "FAIL", name))
        if not cond:
            failed.append(name)

    def dev(name="eth1", up=True, listed=True, stats="default", **kw):
        if stats == "default":
            stats = {"rx": 1000, "tx": 500, "rx_pkt": 100, "tx_pkt": 50, "rx_err": 0, "tx_err": 0, "rx_drop": 0, "tx_drop": 0}
            stats.update(kw)
        return {"name": name, "up": up, "listed": listed, "stats": stats}

    t0 = 1000.0
    base = lambda ts=t0, **kw: dict({"rx": 1000, "tx": 500, "rx_pkt": 100, "tx_pkt": 50, "rx_err": 0, "tx_err": 0,
                                     "rx_drop": 0, "tx_drop": 0, "ts": ts}, **kw)
    busy = dict(rx=61000, tx=30500, rx_pkt=5100, tx_pkt=5050)  # 5000 packets each way in 60 s

    payload = base64.urlsafe_b64encode(json.dumps({"exp": 7}).encode()).decode().rstrip("=")
    check("jwt exp", jwt_exp("x.%s.y" % payload) == 7 and jwt_exp("bad") == 0)
    check("format rates", fmt_bps(10) == "10.0 B/s" and fmt_bps(2048) == "2.0 KiB/s" and fmt_bps(3 * 1024 ** 2) == "3.00 MiB/s")

    out, nb = evaluate([], {}, t0)
    check("no WAN/LAN device -> OK", out == ["0 Traffic - No WAN/LAN device found"] and nb == {})
    ln, nb = evaluate_one(dev(), None, t0)
    check("first run -> OK Initializing, baseline stored", ln.startswith("0 Traffic.eth1 ") and "Initializing" in ln and nb["rx"] == 1000)
    ln, _ = evaluate_one(dev(up=False), None, t0)
    check("link down on the first run -> CRIT already", ln.startswith("2 ") and "link is down" in ln)
    ln, _ = evaluate_one(dev(stats=None), base(), t0 + 60)
    check("counters unreadable -> UNKNOWN", ln.startswith("3 Traffic.eth1 "))
    ln, _ = evaluate_one(dev(listed=False, stats=None), base(), t0 + 60)
    check("zone device not listed by the API -> UNKNOWN (was silently skipped)", ln.startswith("3 ") and "does not list" in ln)
    ln, nb = evaluate_one(dev(**busy), base(), t0 + 60)
    check("clean traffic -> OK with rates and perfdata", ln.startswith("0 Traffic.eth1 if_in_octets=1000.00|if_out_octets=500.00|in_pps=83.33|out_pps=83.33|") and "err_pct=0.000;0.1;1.0|txdrop_pct=0.000;1.0;5.0" in ln and nb["ts"] == t0 + 60)
    ln, _ = evaluate_one(dev(up=False, **busy), base(), t0 + 60)
    check("link down -> CRIT", ln.startswith("2 ") and "link is down" in ln)
    ln, _ = evaluate_one(dev(**dict(busy, rx_err=12)), base(), t0 + 60)
    check("errors 0.12% -> WARN", ln.startswith("1 ") and "errors 0.12%" in ln)
    ln, _ = evaluate_one(dev(**dict(busy, tx_err=150)), base(), t0 + 60)
    check("errors 1.5% -> CRIT", ln.startswith("2 ") and "errors 1.50%" in ln)
    ln, _ = evaluate_one(dev(**dict(busy, rx_err=5)), base(), t0 + 60)
    check("errors 0.05% -> OK", ln.startswith("0 "))
    ln, _ = evaluate_one(dev(**dict(busy, tx_drop=60)), base(), t0 + 60)
    check("tx drops 1.2% -> WARN", ln.startswith("1 ") and "tx drops 1.20%" in ln)
    ln, _ = evaluate_one(dev(**dict(busy, tx_drop=300)), base(), t0 + 60)
    check("tx drops 5.9% -> CRIT", ln.startswith("2 ") and "tx drops" in ln)
    ln, _ = evaluate_one(dev(**dict(busy, rx_drop=2000)), base(), t0 + 60)
    check("rx drops: perfdata and text only, no state change", ln.startswith("0 ") and "if_in_discards=33.333" in ln and "rx drops 33.33/s (not evaluated)" in ln)
    ln, _ = evaluate_one(dev(rx=1100, tx=600, rx_pkt=110, tx_pkt=60, rx_err=9, tx_err=9), base(), t0 + 60)
    check("few packets: ratios not evaluated (idle link) -> OK", ln.startswith("0 "))
    ln, _ = evaluate_one(dev(rx=5, tx=5, rx_pkt=1, tx_pkt=1), base(), t0 + 60)
    check("counters went backwards -> OK re-baselining", ln.startswith("0 ") and "Counters reset" in ln)
    ln, nb = evaluate_one(dev(**busy), base(), t0 + 100000)
    check("baseline older than 900 s -> OK, restarts", ln.startswith("0 ") and "Baseline older" in ln and nb["ts"] == t0 + 100000)
    ln, _ = evaluate_one(dev(), base(), t0 + 0.4)
    check("interval too short -> OK", ln.startswith("0 ") and "Interval too short" in ln)
    old = {"rx": 1, "tx": 1, "ts": t0}
    ln, _ = evaluate_one(dev(**busy), old, t0 + 60)
    check("baseline from an older cache layout -> OK Initializing", ln.startswith("0 ") and "Initializing" in ln)
    out, nb = evaluate([dev(**busy), dev("eth0", rx=9, tx=9, rx_pkt=9, tx_pkt=9)], {"eth1": base()}, t0 + 60)
    check("two devices: independent baselines", out[0].startswith("0 Traffic.eth1 if_in") and "Initializing" in out[1] and set(nb) == {"eth0", "eth1"})
    out = unknown_lines(["eth0", "eth1"], "login failed (HTTP 401)")
    check("API down with history: one UNKNOWN per device", len(out) == 2 and all(o.startswith("3 Traffic.eth") for o in out))
    check("API down without history: one UNKNOWN service", unknown_lines([], "x") == ["3 Traffic - UNKNOWN: x"])

    class Fake(object):
        def __init__(self, data):
            self.data = data

        def call(self, path, method, payload=None, timeout=15):
            v = self.data.get((path, method))
            return ("ok", v) if v is not None else ("error", None)

    stats = {"rx_bytes": 5000, "tx_bytes": 400, "rx_packets": 50, "tx_packets": 40, "rx_errors": 1, "tx_errors": 0,
             "rx_dropped": 2, "tx_dropped": 0}
    listing = {"all_devices": [
        {"name": "eth0", "up": True, "stats": stats},
        {"name": "eth1", "up": False, "stats": stats},
        {"name": "eth3", "up": True, "stats": {"rx_bytes": 1}},
        {"name": "tuntest", "up": True, "stats": stats}],
        "devices_by_zone": [{"name": "lan", "devices": ["eth0", "eth3"]}, {"name": "wan", "devices": ["eth1", "eth9", "eth0"]},
                            {"name": "vpn", "devices": ["tuntest"]}, {"name": "unknown", "devices": []}]}
    devices, err = collect(Fake({("ns.devices", "list-devices"): listing}))
    names = [x["name"] for x in devices]
    check("collect: wan+lan only, no vpn, no duplicates, sorted", err == "" and names == ["eth0", "eth1", "eth3", "eth9"])
    by = {x["name"]: x for x in devices}
    check("collect: link state, stats, incomplete stats, unlisted device",
          by["eth0"]["stats"]["rx"] == 5000 and by["eth0"]["up"] is True and by["eth1"]["up"] is False
          and by["eth3"]["stats"] is None and by["eth9"]["listed"] is False)
    devices, err = collect(Fake({}))
    check("collect: unreadable device list gives an error", devices == [] and err.startswith("cannot read the device list"))
    devices, err = collect(Fake({("ns.devices", "list-devices"): {"all_devices": []}}))
    check("collect: no zone information gives an error", devices == [] and "no zone information" in err)

    global PASSWORD_FILE, CACHE_FILE
    saved = (PASSWORD_FILE, CACHE_FILE)
    PASSWORD_FILE, CACHE_FILE = "/nonexistent/pass", "/nonexistent/cache"
    try:
        lines = run()
    finally:
        PASSWORD_FILE, CACHE_FILE = saved
    check("no credentials and no history: one UNKNOWN service", len(lines) == 1 and lines[0].startswith("3 Traffic "))

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
