#!/usr/bin/python3
"""check_firewall_rules_api.py - NethSecurity firewall rule inventory for CheckMK, REST API only (PROTOTYPE)

CheckMK local check, to run ON the firewall. No subprocess, no nft, no UCI, no nethsec library: everything goes
through the firewall's own REST API on localhost (NSEC_API, default https://127.0.0.1:9090/api), logged in with a
dedicated account (NSEC_USER, default claude-ro; password in NSEC_PASSWORD_FILE, default /root/.nsec-ro-pass, mode
600). The calls are ubus read methods through POST /api/ubus/call:
- ns.firewall list_zones_no_aliases                          the zones the administrator configured;
- ns.firewall list_forwardings                                zone-to-zone traffic allowed;
- ns.firewall list-input-rules / list-output-rules / list-forward-rules   the administrator's own rule objects;
- ns.redirects list-redirects                                  port forwards (DNAT) configured.

Service: Firewall.Rules.

Difference from check_firewall_rules.py, on purpose: the legacy check counted two different things depending on what
was installed - `nft -j list ruleset` (the FULL compiled nftables ruleset, every table/chain/rule including the ones
NethSecurity's own fw4 templates generate; 116 rules on a nearly empty test firewall) when nft was present, or the UCI
objects an administrator actually configured (6 on the same firewall) as a fallback. The same host could show wildly
different numbers across runs depending on which path ran, with nothing in the text to explain why. The REST API only
exposes the administrator's own objects, so this check always counts the same thing: zones, forwardings, rule objects
and redirects as configured, never the compiled ruleset.

The legacy check was purely an inventory (state 0 unless the data could not be read, state 3 UNKNOWN then) - it never
reached WARNING or CRITICAL, so it could never raise an alert or open a ticket on its own. This one adds real
thresholds, modeled on the ways a firewall's rule set actually breaks (a wipe, an accidental mass-delete, every rule
disabled at once), not a size the admin merely trimmed on purpose on their own:
- CRITICAL when no zone is configured at all (ZONES_ZERO_IS_CRIT): NethSecurity always ships at least a lan zone, so
  zero means the firewall configuration was wiped or corrupted;
- CRITICAL when there were active rules on the previous run and none are active now (every rule was deleted or
  disabled in one step);
- WARNING / CRITICAL when the number of active rules drops by RULES_DROP_WARN_PCT (default 20) / RULES_DROP_CRIT_PCT
  (default 50) percent or more since the previous run;
- WARNING when the number of zones decreases since the previous run.
Every run updates the baseline to the current counts, so a change the administrator keeps in place becomes the new
normal from the next run on and does not keep alerting - only the step itself is flagged, the same way
check_wan_throughput_api.py's counter baseline only flags a reset, not every subsequent reading.
Zones, forwardings, rules (active and disabled) and redirects are always in the perfdata and the text, whether or not
they changed enough to move the state.

Security notes:
- The API does NOT enforce per-object permissions for /api/ubus/call (verified 2026-10-14 on NethSecurity 8.8.0): an
  account limited by an rpcd ACL group can still call any ubus object. claude-ro has a read-only ACL group
  (ns-check-reader) but must be treated as a full administrator account.
- TLS verification is off for the loopback connection only (the firewall's certificate is self-signed).

Cache: the API token and the previous reading are kept in NSEC_FW_CACHE (default
/tmp/check_firewall_rules_api.cache, mode 600).

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
CACHE_FILE = os.environ.get("NSEC_FW_CACHE", "/tmp/check_firewall_rules_api.cache")
SERVICE = "Firewall.Rules"


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


RULES_DROP_WARN_PCT = env_int("RULES_DROP_WARN_PCT", 20)
RULES_DROP_CRIT_PCT = env_int("RULES_DROP_CRIT_PCT", 50)
ZONES_ZERO_IS_CRIT = True


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
def rule_counts(rules):
    rules = rules if isinstance(rules, list) else []
    active = sum(1 for r in rules if isinstance(r, dict) and r.get("enabled"))
    return len(rules), active


def collect(api):
    """Returns (counts, error). counts: {zones, forwardings, rules, rules_active, rules_disabled, redirects}."""
    st, z = api.call("ns.firewall", "list_zones_no_aliases")
    if st != "ok" or not isinstance(z, dict):
        return None, "cannot read the zones (%s)" % st
    st, f = api.call("ns.firewall", "list_forwardings")
    if st != "ok" or not isinstance(f, dict):
        return None, "cannot read the forwardings (%s)" % st
    total = active = 0
    for method in ("list-input-rules", "list-output-rules", "list-forward-rules"):
        st, d = api.call("ns.firewall", method)
        if st != "ok" or not isinstance(d, dict):
            return None, "cannot read the %s (%s)" % (method, st)
        t, a = rule_counts(d.get("rules"))
        total += t
        active += a
    st, r = api.call("ns.redirects", "list-redirects")
    if st != "ok" or not isinstance(r, dict):
        return None, "cannot read the redirects (%s)" % st
    return {
        "zones": len(z), "forwardings": len(f),
        "rules": total, "rules_active": active, "rules_disabled": total - active,
        "redirects": len(r.get("redirects") or {}),
    }, ""


# ---------------------------------------------------------------- evaluation
def line(state, perf, text):
    return "%d %s %s %s" % (state, SERVICE, perf or "-", text)


def perfdata(c):
    return "zones=%d|forwardings=%d|rules=%d|rules_active=%d|rules_disabled=%d|redirects=%d" % (
        c["zones"], c["forwardings"], c["rules"], c["rules_active"], c["rules_disabled"], c["redirects"])


def summary(c):
    return "%d zone(s), %d forwarding(s), %d rule(s) (%d active, %d disabled), %d redirect(s)" % (
        c["zones"], c["forwardings"], c["rules"], c["rules_active"], c["rules_disabled"], c["redirects"])


def evaluate(current, previous):
    """previous is None on the first run or after an unreadable run."""
    perf = perfdata(current)
    if ZONES_ZERO_IS_CRIT and current["zones"] == 0:
        return line(2, perf, "CRITICAL - no firewall zone configured: %s" % summary(current))
    if previous is None:
        return line(0, perf, "OK - Initializing: %s" % summary(current))
    base_active = previous.get("rules_active", 0)
    cur_active = current["rules_active"]
    if base_active > 0 and cur_active == 0:
        return line(2, perf, "CRITICAL - all %d previously active rule(s) are now gone or disabled: %s" % (base_active, summary(current)))
    if base_active > 0:
        drop_pct = (base_active - cur_active) / base_active * 100
        if drop_pct >= RULES_DROP_CRIT_PCT:
            return line(2, perf, "CRITICAL - active rules dropped %.0f%% (from %d to %d): %s" % (drop_pct, base_active, cur_active, summary(current)))
        if drop_pct >= RULES_DROP_WARN_PCT:
            return line(1, perf, "WARNING - active rules dropped %.0f%% (from %d to %d): %s" % (drop_pct, base_active, cur_active, summary(current)))
    base_zones = previous.get("zones", 0)
    if current["zones"] < base_zones:
        return line(1, perf, "WARNING - zones decreased from %d to %d: %s" % (base_zones, current["zones"], summary(current)))
    return line(0, perf, "OK - %s" % summary(current))


# ---------------------------------------------------------------- main
def run():
    cache = load_cache()
    api = Api()
    err = open_session(api, cache)
    if err:
        return [line(3, "-", "UNKNOWN: %s" % err)]
    current, err = collect(api)
    if err:
        return [line(3, "-", "UNKNOWN: %s" % err)]
    out = evaluate(current, cache.get("previous"))
    cache["previous"] = current
    save_cache(cache)
    return [out]


def self_test():
    failed, done = [], []

    def check(name, cond):
        done.append(name)
        print("%s %s" % ("ok  " if cond else "FAIL", name))
        if not cond:
            failed.append(name)

    c = lambda zones=1, fwd=2, total=6, active=6, redirects=0: {
        "zones": zones, "forwardings": fwd, "rules": total, "rules_active": active,
        "rules_disabled": total - active, "redirects": redirects}

    payload = base64.urlsafe_b64encode(json.dumps({"exp": 3}).encode()).decode().rstrip("=")
    check("jwt exp", jwt_exp("x.%s.y" % payload) == 3 and jwt_exp("bad") == 0)
    check("rule_counts: total and enabled", rule_counts([{"enabled": True}, {"enabled": False}, {"enabled": True}]) == (3, 2))
    check("rule_counts: not a list -> 0, 0", rule_counts(None) == (0, 0) and rule_counts("x") == (0, 0))

    out = evaluate(c(zones=0), None)
    check("zero zones -> CRITICAL even on the first run", out.startswith("2 Firewall.Rules ") and "no firewall zone configured" in out)
    out = evaluate(c(), None)
    check("first run with zones -> OK Initializing", out.startswith("0 Firewall.Rules ") and "Initializing" in out and "6 rule(s) (6 active, 0 disabled)" in out)
    out = evaluate(c(active=6), c(active=6))
    check("unchanged -> OK, no 'Initializing'", out.startswith("0 ") and "Initializing" not in out)
    out = evaluate(c(active=5), c(active=6))
    check("one rule disabled out of 6 (17% drop): under the 20% WARN level -> OK", out.startswith("0 "))
    out = evaluate(c(active=4, total=4), c(active=6, total=6))
    check("active rules 6 -> 4 (33% drop) -> WARNING with before/after counts", out.startswith("1 ") and "dropped 33%" in out and "from 6 to 4" in out)
    out = evaluate(c(active=3, total=3), c(active=6, total=6))
    check("active rules 6 -> 3 (50% drop) -> CRITICAL, not WARNING", out.startswith("2 ") and "dropped 50%" in out)
    out = evaluate(c(active=0, total=4), c(active=6, total=6))
    check("every previously active rule gone -> CRITICAL names the count", out.startswith("2 ") and "all 6 previously active rule(s)" in out)
    out = evaluate(c(active=0, total=0), c(active=0, total=0))
    check("still zero active rules as before (no baseline to drop from) -> OK, not CRITICAL", out.startswith("0 "))
    out = evaluate(c(zones=1), c(zones=3))
    check("zones decreased 3 -> 1 -> WARNING", out.startswith("1 ") and "zones decreased from 3 to 1" in out)
    out = evaluate(c(zones=4), c(zones=3))
    check("zones increased -> not a WARNING by itself", out.startswith("0 "))
    out = evaluate(c(zones=0, active=0, total=0), c(zones=3, active=6, total=6))
    check("zones wiped to zero takes priority over the rule-drop message", out.startswith("2 ") and "no firewall zone configured" in out and "all 6 previously active" not in out)
    out = evaluate(c(fwd=9, redirects=3), c(fwd=2, redirects=0))
    check("forwardings and redirects never move the state, only the text/perfdata", out.startswith("0 ") and "9 forwarding(s)" in out and "3 redirect(s)" in out)
    check("perfdata carries every count", perfdata(c(zones=2, fwd=3, total=7, active=5, redirects=1)) == "zones=2|forwardings=3|rules=7|rules_active=5|rules_disabled=2|redirects=1")

    class Fake(object):
        def __init__(self, data):
            self.data = data

        def call(self, path, method, payload=None, timeout=15):
            v = self.data.get((path, method))
            return ("ok", v) if v is not None else ("error", None)

    fake = Fake({
        ("ns.firewall", "list_zones_no_aliases"): {"ns_lan": {}, "ns_wan": {}},
        ("ns.firewall", "list_forwardings"): {"ns_a": {}},
        ("ns.firewall", "list-input-rules"): {"rules": [{"enabled": True}, {"enabled": True}]},
        ("ns.firewall", "list-output-rules"): {"rules": []},
        ("ns.firewall", "list-forward-rules"): {"rules": [{"enabled": False}]},
        ("ns.redirects", "list-redirects"): {"redirects": {"ns_r1": {}}},
    })
    result, err = collect(fake)
    check("collect: sums rules across the three kinds, counts enabled", err == "" and result == {"zones": 2, "forwardings": 1, "rules": 3, "rules_active": 2, "rules_disabled": 1, "redirects": 1})
    result, err = collect(Fake({}))
    check("collect: unreadable zones -> error, no partial result", result is None and err.startswith("cannot read the zones"))
    half = Fake({("ns.firewall", "list_zones_no_aliases"): {"ns_lan": {}}, ("ns.firewall", "list_forwardings"): {}})
    result, err = collect(half)
    check("collect: unreadable rules -> error even though zones/forwardings were read", result is None and err.startswith("cannot read the list-input-rules"))

    global PASSWORD_FILE, CACHE_FILE
    saved = (PASSWORD_FILE, CACHE_FILE)
    PASSWORD_FILE, CACHE_FILE = "/nonexistent/pass", "/nonexistent/cache"
    try:
        lines = run()
    finally:
        PASSWORD_FILE, CACHE_FILE = saved
    check("no credentials -> one UNKNOWN line", len(lines) == 1 and lines[0].startswith("3 Firewall.Rules "))

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
