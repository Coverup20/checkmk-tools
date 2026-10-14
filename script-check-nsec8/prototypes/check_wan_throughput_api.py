#!/usr/bin/python3
"""check_wan_throughput_api.py - NethSecurity WAN throughput for CheckMK, REST API only (PROTOTYPE)

CheckMK local check, to run ON the firewall. No subprocess, no UCI, no nethsec library, no /proc or /sys: everything
goes through the firewall's own REST API on localhost (NSEC_API, default https://127.0.0.1:9090/api), logged in with a
dedicated account (NSEC_USER, default claude-ro; password in NSEC_PASSWORD_FILE, default /root/.nsec-ro-pass, mode
600). The calls are ubus read methods through POST /api/ubus/call:
- ns.dashboard list-wans    the WAN interfaces (name and device);
- ns.devices list-devices   for every device: byte counters, error and drop counters, link speed ("stats", "speed").

Service, same name, perfdata and thresholds as check_wan_throughput.py: WAN.Throughput.<label>, one per WAN: rate in
and out (bytes per second, from the counters between two runs), WARN at 80% and CRIT at 95% of the link speed when the
speed is known (virtual NICs report -1: then the rate is shown without thresholds).

Corrections to the legacy check, on purpose:
- the first measurement ("Initializing") is OK, not WARN: the rate is only available from the second run, and a WARN
  at every reboot or /tmp cleanup is not a problem of the line;
- no WAN configured is OK ("No WAN device found"), like WAN.Status, not CRIT;
- counters that cannot be read are UNKNOWN, not CRIT: a failure of the check is not a failure of the line;
- a baseline older than MAX_INTERVAL (default 900 s) is discarded: the legacy check averaged over any interval, so a
  check that had been off for a day reported a meaningless rate;
- the perfdata carry the levels and the maximum (when the speed is known), so CheckMK graphs show them;
- packet errors and drops per second are added to the perfdata and, when not zero, to the text (no thresholds).

When the API cannot be read, the WANs seen on the previous successful run (kept in the cache file) are reported as
UNKNOWN, so the per-WAN services do not vanish from CheckMK; with no history, one WAN.Throughput service is UNKNOWN.

Security notes:
- The API does NOT enforce per-object permissions for /api/ubus/call (verified 2026-10-14 on NethSecurity 8.8.0): an
  account limited by an rpcd ACL group can still call any ubus object. claude-ro has a read-only ACL group
  (ns-check-reader) but must be treated as a full administrator account.
- TLS verification is off for the loopback connection only (the firewall's certificate is self-signed).

Cache: the API token, the last known WAN labels and the counter baselines are kept in NSEC_TP_CACHE (default
/tmp/check_wan_throughput_api.cache, mode 600).

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
CACHE_FILE = os.environ.get("NSEC_TP_CACHE", "/tmp/check_wan_throughput_api.cache")
SERVICE = "WAN.Throughput"
WARN_PCT = 80.0
CRIT_PCT = 95.0
MAX_INTERVAL = 900  # seconds: an older baseline is discarded


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
def num(v, default=0):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else default


def collect(api):
    """Returns (wans, error). wans: list of {label, device, stats}; stats is None when the device is not listed,
    otherwise {rx, tx, rx_err, tx_err, rx_drop, tx_drop, speed}. error is "" or a short text (no WAN list)."""
    st, d = api.call("ns.dashboard", "list-wans")
    if st != "ok":
        return [], "cannot read the WAN list (%s)" % st
    rows = unwrap(d)
    sd, dev = api.call("ns.devices", "list-devices")
    by_dev = {}
    if sd == "ok" and isinstance(dev, dict):
        for x in dev.get("all_devices") or []:
            if isinstance(x, dict) and x.get("name"):
                by_dev[x["name"]] = x
    wans = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        label = r.get("iface") or r.get("device") or "?"
        device = r.get("device") or ""
        x = by_dev.get(device)
        stats = None
        if x is not None and isinstance(x.get("stats"), dict):
            s = x["stats"]
            stats = {"rx": num(s.get("rx_bytes"), None), "tx": num(s.get("tx_bytes"), None),
                     "rx_err": num(s.get("rx_errors")), "tx_err": num(s.get("tx_errors")),
                     "rx_drop": num(s.get("rx_dropped")), "tx_drop": num(s.get("tx_dropped")),
                     "speed": num(x.get("speed"), -1)}
            if stats["rx"] is None or stats["tx"] is None:
                stats = None
        wans.append({"label": label, "device": device, "stats": stats})
    return wans, ""


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


def fmt_speed(mbps):
    return "%d GBit/s" % (mbps // 1000) if mbps >= 1000 else "%d MBit/s" % mbps


def evaluate_one(w, base, now):
    """Returns (line, new_baseline). base is the previous {rx, tx, ts} or None."""
    name = "%s.%s" % (SERVICE, w["label"])
    dev = w["device"]
    s = w["stats"]
    zero = "if_in_octets=0|if_out_octets=0"
    if s is None:
        return line(3, name, zero, "[%s] cannot read the counters" % dev), base
    new = {"rx": s["rx"], "tx": s["tx"], "ts": now}
    if base is None:
        return line(0, name, zero, "[%s] Initializing: the rate is available at the next run" % dev), new
    delta = now - base["ts"]
    if delta < 1:
        return line(0, name, zero, "[%s] Interval too short (%.1fs)" % (dev, delta)), new
    if delta > MAX_INTERVAL:
        return line(0, name, zero, "[%s] Baseline older than %d s, restarting the measurement" % (dev, MAX_INTERVAL)), new
    if s["rx"] < base["rx"] or s["tx"] < base["tx"]:
        return line(0, name, zero, "[%s] Counters reset, re-baselining" % dev), new
    rx_bps = (s["rx"] - base["rx"]) / delta
    tx_bps = (s["tx"] - base["tx"]) / delta
    errs = {k: (s[k] - base.get(k, s[k])) / delta for k in ("rx_err", "tx_err", "rx_drop", "tx_drop")}
    new.update({k: s[k] for k in ("rx_err", "tx_err", "rx_drop", "tx_drop")})
    extra = "|if_in_errors=%.3f|if_out_errors=%.3f|if_in_discards=%.3f|if_out_discards=%.3f" % (
        max(errs["rx_err"], 0), max(errs["tx_err"], 0), max(errs["rx_drop"], 0), max(errs["tx_drop"], 0))
    note = ""
    bad = [("rx errors", errs["rx_err"]), ("tx errors", errs["tx_err"]), ("rx drops", errs["rx_drop"]), ("tx drops", errs["tx_drop"])]
    bad = ["%s %.2f/s" % (n, v) for n, v in bad if v > 0]
    if bad:
        note = ", " + ", ".join(bad)
    speed = s["speed"]
    if speed <= 0:
        return line(0, name, "if_in_octets=%.2f|if_out_octets=%.2f%s" % (rx_bps, tx_bps, extra),
                    "[%s] Speed: unknown, In: %s, Out: %s%s" % (dev, fmt_bps(rx_bps), fmt_bps(tx_bps), note)), new
    speed_bps = speed * 125000
    warn_bps, crit_bps = speed_bps * WARN_PCT / 100, speed_bps * CRIT_PCT / 100
    state = 2 if (rx_bps >= crit_bps or tx_bps >= crit_bps) else (1 if (rx_bps >= warn_bps or tx_bps >= warn_bps) else 0)
    perf = "if_in_octets=%.2f;%.0f;%.0f;0;%d|if_out_octets=%.2f;%.0f;%.0f;0;%d%s" % (
        rx_bps, warn_bps, crit_bps, speed_bps, tx_bps, warn_bps, crit_bps, speed_bps, extra)
    return line(state, name, perf, "[%s] Speed: %s, In: %s (%.2f%%), Out: %s (%.2f%%)%s" % (
        dev, fmt_speed(speed), fmt_bps(rx_bps), rx_bps / speed_bps * 100, fmt_bps(tx_bps), tx_bps / speed_bps * 100, note)), new


def evaluate(wans, baselines, now):
    """Returns (lines, new_baselines)."""
    if not wans:
        return [line(0, SERVICE, "if_in_octets=0|if_out_octets=0", "No WAN device found")], {}
    out, new_base = [], {}
    for w in wans:
        ln, nb = evaluate_one(w, baselines.get(w["device"]), now)
        out.append(ln)
        if nb is not None:
            new_base[w["device"]] = nb
    return out, new_base


def unknown_lines(labels, err):
    """The API is unreadable: keep the per-WAN services alive as UNKNOWN."""
    if not labels:
        return [line(3, SERVICE, "-", "UNKNOWN: %s" % err)]
    return [line(3, "%s.%s" % (SERVICE, label), "-", "UNKNOWN - %s" % err) for label in labels]


# ---------------------------------------------------------------- main
def run():
    cache = load_cache()
    api = Api()
    err = open_session(api, cache)
    if err:
        return unknown_lines(cache.get("labels", []), err)
    wans, err = collect(api)
    if err:
        return unknown_lines(cache.get("labels", []), err)
    out, new_base = evaluate(wans, cache.get("baselines", {}), time.time())
    cache["labels"] = [w["label"] for w in wans]
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

    def w(label="wan", dev="eth1", rx=1000, tx=500, speed=-1, **kw):
        s = {"rx": rx, "tx": tx, "rx_err": 0, "tx_err": 0, "rx_drop": 0, "tx_drop": 0, "speed": speed}
        s.update(kw)
        return {"label": label, "device": dev, "stats": s}

    t0 = 1000.0
    base = lambda rx=1000, tx=500, ts=t0, **kw: dict({"rx": rx, "tx": tx, "ts": ts, "rx_err": 0, "tx_err": 0, "rx_drop": 0, "tx_drop": 0}, **kw)

    check("unwrap result/values", unwrap({"result": [1]}) == [1] and unwrap({"a": 1, "b": 2}) == {"a": 1, "b": 2})
    payload = base64.urlsafe_b64encode(json.dumps({"exp": 7}).encode()).decode().rstrip("=")
    check("jwt exp", jwt_exp("x.%s.y" % payload) == 7 and jwt_exp("bad") == 0)
    check("format rates", fmt_bps(10) == "10.0 B/s" and fmt_bps(2048) == "2.0 KiB/s" and fmt_bps(3 * 1024 ** 2) == "3.00 MiB/s")
    check("format speed", fmt_speed(100) == "100 MBit/s" and fmt_speed(2500) == "2 GBit/s")

    out, nb = evaluate([], {}, t0)
    check("no WAN -> OK (corrected, was CRIT)", out == ["0 WAN.Throughput if_in_octets=0|if_out_octets=0 No WAN device found"] and nb == {})
    ln, nb = evaluate_one(w(), None, t0)
    check("first run -> OK Initializing (corrected, was WARN) and a baseline is stored", ln.startswith("0 WAN.Throughput.wan ") and "Initializing" in ln and nb["rx"] == 1000)
    ln, _ = evaluate_one({"label": "wan", "device": "eth1", "stats": None}, base(), t0 + 60)
    check("counters unreadable -> UNKNOWN (corrected, was CRIT)", ln.startswith("3 WAN.Throughput.wan "))
    ln, nb = evaluate_one(w(rx=61000, tx=30500), base(), t0 + 60)
    check("rate computed, speed unknown: OK without thresholds", ln.startswith("0 WAN.Throughput.wan if_in_octets=1000.00|if_out_octets=500.00") and "Speed: unknown" in ln and nb["ts"] == t0 + 60)
    ln, _ = evaluate_one(w(rx=61000, tx=31000, speed=100), base(), t0 + 60)
    check("speed known: perfdata carry levels and maximum", "if_in_octets=1000.00;10000000;11875000;0;12500000" in ln and "Speed: 100 MBit/s" in ln)
    ln, _ = evaluate_one(w(rx=1000 + 10_000_000 * 60, speed=100), base(), t0 + 60)
    check("80% of the link -> WARN", ln.startswith("1 "))
    ln, _ = evaluate_one(w(rx=1000, tx=500 + 12_000_000 * 60, speed=100), base(), t0 + 60)
    check("95% of the link (out) -> CRIT", ln.startswith("2 "))
    ln, nb = evaluate_one(w(rx=5), base(), t0 + 60)
    check("counters went backwards -> OK re-baselining, no spike", ln.startswith("0 ") and "Counters reset" in ln and nb["rx"] == 5)
    ln, nb = evaluate_one(w(rx=10 ** 12), base(), t0 + 100000)
    check("baseline older than 900 s -> OK, restarts (corrected, was a meaningless average)", ln.startswith("0 ") and "Baseline older" in ln and nb["ts"] == t0 + 100000)
    ln, _ = evaluate_one(w(), base(), t0 + 0.4)
    check("interval too short -> OK", ln.startswith("0 ") and "Interval too short" in ln)
    ln, _ = evaluate_one(w(rx_err=60, rx_drop=120), base(), t0 + 60)
    check("errors and drops: perfdata and text, no state change", "if_in_errors=1.000" in ln and "if_in_discards=2.000" in ln and "rx errors 1.00/s" in ln and "rx drops 2.00/s" in ln and ln.startswith("0 "))
    ln, _ = evaluate_one(w(), base(), t0 + 60)
    check("no errors: nothing added to the text", "errors" not in ln.split("]")[1] and "drops" not in ln)
    out, nb = evaluate([w(), w("wan2", "eth2", rx=77, tx=55)], {"eth1": base()}, t0 + 60)
    check("two WANs: independent baselines", out[0].startswith("0 WAN.Throughput.wan ") and "Initializing" in out[1] and set(nb) == {"eth1", "eth2"})
    out = unknown_lines(["wan", "wan2"], "login failed (HTTP 401)")
    check("API down with history: one UNKNOWN per WAN", len(out) == 2 and all(o.startswith("3 WAN.Throughput.wan") for o in out))
    check("API down without history: one UNKNOWN service", unknown_lines([], "x") == ["3 WAN.Throughput - UNKNOWN: x"])

    class Fake(object):
        def __init__(self, data):
            self.data = data

        def call(self, path, method, payload=None, timeout=15):
            v = self.data.get((path, method))
            return ("ok", v) if v is not None else ("error", None)

    fake = Fake({
        ("ns.dashboard", "list-wans"): {"result": [{"iface": "wan", "device": "eth1"}, {"iface": "wan2", "device": "eth2"}]},
        ("ns.devices", "list-devices"): {"all_devices": [
            {"name": "eth0", "stats": {"rx_bytes": 1, "tx_bytes": 1}, "speed": -1},
            {"name": "eth1", "stats": {"rx_bytes": 5000, "tx_bytes": 400, "rx_errors": 1, "tx_errors": 0, "rx_dropped": 2, "tx_dropped": 0}, "speed": 1000}]},
    })
    wans, err = collect(fake)
    check("collect: two WANs, stats and speed of the first, none for the unlisted device", err == "" and len(wans) == 2 and wans[0]["stats"]["rx"] == 5000 and wans[0]["stats"]["speed"] == 1000 and wans[1]["stats"] is None)
    wans, err = collect(Fake({}))
    check("collect: unreadable WAN list gives an error", wans == [] and err.startswith("cannot read the WAN list"))
    bad = Fake({("ns.dashboard", "list-wans"): {"result": [{"iface": "wan", "device": "eth1"}]},
                ("ns.devices", "list-devices"): {"all_devices": [{"name": "eth1", "stats": {"tx_bytes": 1}}]}})
    check("collect: counters missing -> stats None (UNKNOWN later)", collect(bad)[0][0]["stats"] is None)

    global PASSWORD_FILE, CACHE_FILE
    saved = (PASSWORD_FILE, CACHE_FILE)
    PASSWORD_FILE, CACHE_FILE = "/nonexistent/pass", "/nonexistent/cache"
    try:
        lines = run()
    finally:
        PASSWORD_FILE, CACHE_FILE = saved
    check("no credentials and no history: one UNKNOWN service", len(lines) == 1 and lines[0].startswith("3 WAN.Throughput "))

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
