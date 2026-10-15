#!/usr/bin/python3
"""check_dns_resolution_api.py - NethSecurity DNS monitoring for CheckMK (PROTOTYPE)

CheckMK local check, to run ON the firewall. A DNS check has to ask a DNS question and see whether the answer comes
back: that cannot be a REST read, so the queries are raw UDP DNS packets sent by this script (no subprocess, no UCI,
no nethsec library). The REST API is used for the one thing it knows: the DNS servers the firewall forwards to
(ns.dns get-config), through the firewall's own API on localhost (NSEC_API, default https://127.0.0.1:9090/api), logged
in with a dedicated account (NSEC_USER, default claude-ro; password in NSEC_PASSWORD_FILE, default /root/.nsec-ro-pass,
mode 600).

Services:
- DNS.Resolution            same name, test names, perfdata and thresholds as check_dns_resolution.py: the three
                            names (DNS_TEST_DOMAINS) are asked to the local resolver, 127.0.0.1:53. CRIT when none
                            answers or the average is over 1000 ms, WARN when some fail or the average is over 500 ms.
                            Perfdata: response_time (ms, levels 500/1000), successful, failed, total.
- DNS.Primary, DNS.Secondary   NEW, one per forwarder read from the API, in the order they are configured (a third one
                            is DNS.Tertiary, further ones DNS.Server4, DNS.Server5, ...): the same three names asked
                            directly to that server; its address is in the text. It tells "the local dnsmasq is broken"
                            from "one of the servers it forwards to is broken": with two forwarders, the legacy check
                            stays OK while one of them is down. CRIT when the server answers nothing, WARN when some
                            tests fail or it is slow (same thresholds). The names follow the position: if the
                            administrator swaps the two servers, DNS.Primary becomes the other address (the text says
                            which). Entries that only apply to some domains (dnsmasq "/domain/server") are not tested
                            and do not take a position: they would refuse the test names.

Corrections to the legacy check, on purpose:
- timeouts: the legacy check waited 5 s per name one after the other (15 s with the resolver down, stalling the agent).
  Here every query has a 2 s timeout (DNS_TIMEOUT) and all of them run in parallel: the whole check ends in about 2 s
  at the very worst;
- the text names the tests that failed and why (no response, SERVFAIL, REFUSED, NXDOMAIN, malformed answer) instead of
  only "Some tests failed";
- the local resolver is tested even when the API cannot be read (the API is only needed for the forwarders).

When the API cannot be read, the forwarders seen on the previous successful run (kept in the cache file) are reported as
UNKNOWN, so their services do not vanish from CheckMK.

Security notes:
- The API does NOT enforce per-object permissions for /api/ubus/call (verified 2026-10-14 on NethSecurity 8.8.0): an
  account limited by an rpcd ACL group can still call any ubus object. claude-ro has a read-only ACL group
  (ns-check-reader) but must be treated as a full administrator account.
- TLS verification is off for the loopback connection only (the firewall's certificate is self-signed).

Cache: the API token and the last known forwarders are kept in NSEC_DNS_CACHE (default /tmp/check_dns_resolution_api.cache,
mode 600).

Version: 0.1.0"""

import base64
import ipaddress
import json
import os
import socket
import ssl
import struct
import sys
import threading
import time
import urllib.error
import urllib.request

VERSION = "0.1.0"
API = os.environ.get("NSEC_API", "https://127.0.0.1:9090/api")
USER = os.environ.get("NSEC_USER", "claude-ro")
PASSWORD_FILE = os.environ.get("NSEC_PASSWORD_FILE", "/root/.nsec-ro-pass")
CACHE_FILE = os.environ.get("NSEC_DNS_CACHE", "/tmp/check_dns_resolution_api.cache")
SERVICE = "DNS.Resolution"
ROLE_NAMES = ("Primary", "Secondary", "Tertiary")


def role_name(position):
    """Service name of the forwarder in this position (0 = first configured)."""
    return "DNS.%s" % (ROLE_NAMES[position] if position < len(ROLE_NAMES) else "Server%d" % (position + 1))
TEST_DOMAINS = [d.strip() for d in os.environ.get("DNS_TEST_DOMAINS", "google.com,cloudflare.com,dns.google").split(",") if d.strip()]
LOCAL_RESOLVER = ("127.0.0.1", 53)
WARN_MS = 500
CRIT_MS = 1000
try:
    DNS_TIMEOUT = float(os.environ.get("DNS_TIMEOUT", "2"))
except ValueError:
    DNS_TIMEOUT = 2.0
RCODES = {1: "FORMERR", 2: "SERVFAIL", 3: "NXDOMAIN", 4: "NOTIMP", 5: "REFUSED"}


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


# ---------------------------------------------------------------- DNS queries
def build_query(domain, txid):
    header = struct.pack(">HHHHHH", txid, 0x0100, 1, 0, 0, 0)
    qname = b"".join(struct.pack("B", len(label)) + label.encode("ascii") for label in domain.split(".")) + b"\x00"
    return header + qname + struct.pack(">HH", 1, 1)  # QTYPE=A, QCLASS=IN


def parse_answer(data, txid):
    """Returns "" when the answer is a NOERROR for this query, otherwise the reason."""
    if len(data) < 12:
        return "malformed answer"
    resp_id, flags = struct.unpack(">HH", data[:4])
    if resp_id != txid:
        return "answer for another query"
    rcode = flags & 0x000F
    if rcode == 0:
        return ""
    return RCODES.get(rcode, "rcode %d" % rcode)


def query(server, port, domain, timeout):
    """One raw UDP DNS query. Returns (ok, milliseconds, reason)."""
    start = time.perf_counter()
    txid = (int(time.time() * 1000) ^ (threading.get_ident() & 0xFFFF)) & 0xFFFF
    family = socket.AF_INET6 if ":" in server else socket.AF_INET
    try:
        sock = socket.socket(family, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        try:
            sock.sendto(build_query(domain, txid), (server, port))
            data, _ = sock.recvfrom(512)
        finally:
            sock.close()
    except socket.timeout:
        return False, int((time.perf_counter() - start) * 1000), "no response"
    except (OSError, UnicodeError) as e:
        return False, int((time.perf_counter() - start) * 1000), "cannot query (%s)" % (getattr(e, "strerror", None) or type(e).__name__)
    ms = int((time.perf_counter() - start) * 1000)
    reason = parse_answer(data, txid)
    return reason == "", ms, reason


def run_queries(targets, domains, timeout):
    """targets: {label: (server, port)}. All the queries run in parallel; returns {label: [(domain, ok, ms, reason)]}."""
    results = {label: [None] * len(domains) for label in targets}
    threads = []

    def work(label, idx, server, port, domain):
        ok, ms, reason = query(server, port, domain, timeout)
        results[label][idx] = (domain, ok, ms, reason)

    for label, (server, port) in targets.items():
        for idx, domain in enumerate(domains):
            t = threading.Thread(target=work, args=(label, idx, server, port, domain))
            t.daemon = True
            t.start()
            threads.append(t)
    for t in threads:
        t.join(timeout + 3)
    for label in results:  # a thread that did not finish is a failure, never a missing result
        for idx, domain in enumerate(domains):
            if results[label][idx] is None:
                results[label][idx] = (domain, False, int(timeout * 1000), "no response")
    return results


def parse_server(entry):
    """dnsmasq "server" entries: "ip", "ip#port". Domain-specific entries ("/domain/ip") are not tested.
    Returns (ip, port) or None."""
    s = str(entry).strip()
    if not s or s.startswith("/"):
        return None
    host, _, port = s.partition("#")
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None
    return str(ip), int(port) if port.isdigit() else 53


def server_label(ip, port):
    return ip if port == 53 else "%s:%d" % (ip, port)


def server_text(entry):
    """The address as shown in the text of a forwarder service."""
    return " (server %s)" % server_label(entry[0], entry[1])


# ---------------------------------------------------------------- evaluation
def line(state, name, perf, text):
    return "%d %s %s %s" % (state, name, perf or "-", text)


def evaluate_target(name, rows, who, where=""):
    """rows: [(domain, ok, ms, reason)]. who: 'DNS' for the local resolver, 'upstream' for a forwarder.
    where: the address of the forwarder, appended to the text."""
    total = len(rows)
    good = [r for r in rows if r[1]]
    bad = [r for r in rows if not r[1]]
    avg = int(sum(r[2] for r in good) / len(good)) if good else 0
    failed_txt = "; ".join("%s (%s)" % (r[0], r[3]) for r in bad)
    if len(bad) == total:
        state, txt = 2, "CRITICAL - %s not responding: %s" % (who, failed_txt)
    elif bad:
        state, txt = 1, "WARNING - Some tests failed: %s" % failed_txt
    elif avg > CRIT_MS:
        state, txt = 2, "CRITICAL - %s slow response" % who
    elif avg > WARN_MS:
        state, txt = 1, "WARNING - %s slow response" % who
    else:
        state, txt = 0, "OK"
    perf = "response_time=%dms;%d;%d|successful=%d|failed=%d|total=%d" % (avg, WARN_MS, CRIT_MS, len(good), len(bad), total)
    return line(state, name, perf, "Test: %d/%d OK, avg time: %dms - %s%s" % (len(good), total, avg, txt, where))


def evaluate(local_rows, upstream_rows, servers=None):
    """upstream_rows: {service name: rows}, in the order of configuration. servers: {service name: (ip, port)}.
    Returns the lines, local resolver first."""
    servers = servers or {}
    out = [evaluate_target(SERVICE, local_rows, "DNS")]
    for name in upstream_rows:
        out.append(evaluate_target(name, upstream_rows[name], "upstream", server_text(servers[name]) if name in servers else ""))
    return out


def upstream_unknown(names, err):
    return [line(3, n, "-", "UNKNOWN - %s" % err) for n in names]


# ---------------------------------------------------------------- main
def read_forwarders(cache):
    """Returns (servers, error): servers {service name: (ip, port)} from the API, in the order of configuration (the
    first testable one is DNS.Primary, the second DNS.Secondary, ...), "" or a short error text."""
    api = Api()
    err = open_session(api, cache)
    if err:
        return {}, err
    st, d = api.call("ns.dns", "get-config")
    if st != "ok" or not isinstance(d, dict):
        return {}, "cannot read the DNS configuration (%s)" % st
    servers = {}
    for entry in d.get("server") or []:
        p = parse_server(entry)
        if p and p not in servers.values():
            servers[role_name(len(servers))] = p
    return servers, ""


def run():
    cache = load_cache()
    servers, err = read_forwarders(cache)
    targets = {"": LOCAL_RESOLVER}
    targets.update(servers)
    results = run_queries(targets, TEST_DOMAINS, DNS_TIMEOUT)
    local_rows = results.pop("")
    out = evaluate(local_rows, results, servers)
    if err:
        out.extend(upstream_unknown([k for k in cache.get("servers", {})], err))
    else:
        cache["servers"] = {k: list(v) for k, v in servers.items()}
        save_cache(cache)
    return out


def self_test():
    failed, done = [], []

    def check(name, cond):
        done.append(name)
        print("%s %s" % ("ok  " if cond else "FAIL", name))
        if not cond:
            failed.append(name)

    payload = base64.urlsafe_b64encode(json.dumps({"exp": 5}).encode()).decode().rstrip("=")
    check("jwt exp", jwt_exp("x.%s.y" % payload) == 5 and jwt_exp("bad") == 0)
    q = build_query("dns.google", 0x1234)
    check("query packet: id, one question, labels", q[:2] == b"\x12\x34" and q[4:6] == b"\x00\x01" and b"\x03dns\x06google\x00" in q)
    check("parse_answer NOERROR/SERVFAIL/REFUSED/other/mismatch/short",
          parse_answer(struct.pack(">HH", 7, 0x8180) + b"\0" * 8, 7) == "" and
          parse_answer(struct.pack(">HH", 7, 0x8182) + b"\0" * 8, 7) == "SERVFAIL" and
          parse_answer(struct.pack(">HH", 7, 0x8185) + b"\0" * 8, 7) == "REFUSED" and
          parse_answer(struct.pack(">HH", 7, 0x818E) + b"\0" * 8, 7) == "rcode 14" and
          parse_answer(struct.pack(">HH", 8, 0x8180) + b"\0" * 8, 7) == "answer for another query" and
          parse_answer(b"\0\0", 7) == "malformed answer")
    check("parse_server: ip, ip#port, ipv6, domain-specific and junk",
          parse_server("8.8.8.8") == ("8.8.8.8", 53) and parse_server("10.0.0.1#5353") == ("10.0.0.1", 5353) and
          parse_server("2001:4860:4860::8888") == ("2001:4860:4860::8888", 53) and parse_server("/corp.lan/10.1.1.1") is None and
          parse_server("") is None and parse_server("not-an-ip") is None)
    check("server_label hides port 53", server_label("8.8.8.8", 53) == "8.8.8.8" and server_label("10.0.0.1", 5353) == "10.0.0.1:5353")

    # real UDP query path against tiny local DNS servers (an answering one, a SERVFAIL one, a silent one)
    def serve(mode):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("127.0.0.1", 0))
        s.settimeout(6)

        def loop():
            try:
                while True:
                    data, addr = s.recvfrom(512)
                    if mode == "silent":
                        continue
                    rcode = 0 if mode == "ok" else 2
                    s.sendto(data[:2] + struct.pack(">H", 0x8180 | rcode) + data[4:], addr)
            except (OSError, socket.timeout):
                pass
        t = threading.Thread(target=loop)
        t.daemon = True
        t.start()
        return s, s.getsockname()[1]

    s_ok, p_ok = serve("ok")
    s_bad, p_bad = serve("servfail")
    s_mute, p_mute = serve("silent")
    ok, ms, why = query("127.0.0.1", p_ok, "google.com", 1.0)
    check("real query: answered -> ok", ok and why == "" and ms < 1000)
    ok, ms, why = query("127.0.0.1", p_bad, "google.com", 1.0)
    check("real query: SERVFAIL -> failed with the reason", not ok and why == "SERVFAIL")
    t0 = time.time()
    ok, ms, why = query("127.0.0.1", p_mute, "google.com", 0.5)
    check("real query: silence -> 'no response' after the timeout", not ok and why == "no response" and 0.4 <= time.time() - t0 < 2)
    t0 = time.time()
    res = run_queries({"a": ("127.0.0.1", p_ok), "m1": ("127.0.0.1", p_mute), "m2": ("127.0.0.1", p_mute)}, ["x.test", "y.test", "z.test"], 0.5)
    check("parallel run: 9 queries, the silent ones fail, the whole run takes about one timeout (not 6)",
          all(r[1] for r in res["a"]) and not any(r[1] for r in res["m1"]) and time.time() - t0 < 2)
    for s in (s_ok, s_bad, s_mute):
        s.close()

    rows = lambda *ms_: [("d%d" % i, True, m, "") for i, m in enumerate(ms_)]
    out = evaluate_target("DNS.Resolution", rows(10, 20, 30), "DNS")
    check("all fast -> OK with the legacy perfdata", out == "0 DNS.Resolution response_time=20ms;500;1000|successful=3|failed=0|total=3 Test: 3/3 OK, avg time: 20ms - OK")
    out = evaluate_target("DNS.Resolution", rows(600, 600, 600), "DNS")
    check("average over 500 ms -> WARN slow", out.startswith("1 ") and "WARNING - DNS slow response" in out)
    out = evaluate_target("DNS.Resolution", rows(1200, 1100, 1300), "DNS")
    check("average over 1000 ms -> CRIT slow", out.startswith("2 ") and "CRITICAL - DNS slow response" in out)
    mixed = [("a.test", True, 10, ""), ("b.test", False, 2000, "no response"), ("c.test", True, 30, "")]
    out = evaluate_target("DNS.Resolution", mixed, "DNS")
    check("some failed -> WARN naming the failed test and why", out.startswith("1 ") and "b.test (no response)" in out and "successful=2|failed=1" in out)
    dead = [("a.test", False, 2000, "no response"), ("b.test", False, 5, "REFUSED"), ("c.test", False, 7, "SERVFAIL")]
    out = evaluate_target("DNS.Resolution", dead, "DNS")
    check("none answered -> CRIT with every reason, response_time 0", out.startswith("2 ") and "DNS not responding" in out and "b.test (REFUSED)" in out and "response_time=0ms" in out)
    out = evaluate_target("DNS.Primary", dead, "upstream", server_text(("8.8.8.8", 53)))
    check("upstream dead -> CRIT that says upstream, with the address in the text", out.startswith("2 DNS.Primary ") and "upstream not responding" in out and out.endswith("(server 8.8.8.8)"))
    check("role names by position: Primary, Secondary, Tertiary, then DNS.Server4", [role_name(i) for i in range(5)] == ["DNS.Primary", "DNS.Secondary", "DNS.Tertiary", "DNS.Server4", "DNS.Server5"])
    servers = {"DNS.Primary": ("10.0.0.1", 53), "DNS.Secondary": ("8.8.8.8", 53)}
    out = evaluate(rows(5, 5, 5), {"DNS.Primary": dead, "DNS.Secondary": rows(5, 5, 5)}, servers)
    check("primary down, secondary fine, local fine: only DNS.Primary CRIT, with its address",
          out[0].startswith("0 DNS.Resolution ") and out[1].startswith("2 DNS.Primary ") and "(server 10.0.0.1)" in out[1] and out[2].startswith("0 DNS.Secondary ") and "(server 8.8.8.8)" in out[2])
    out = upstream_unknown(["DNS.Primary", "DNS.Secondary"], "login failed (HTTP 401)")
    check("API down: the known forwarders are UNKNOWN, not gone", len(out) == 2 and out[0].startswith("3 DNS.Primary ") and out[1].startswith("3 DNS.Secondary "))

    class FakeApi(object):
        def __init__(self, data):
            self.data = data

        def call(self, path, method, payload=None, timeout=15):
            v = self.data.get((path, method))
            return ("ok", v) if v is not None else ("error", None)

    global PASSWORD_FILE, CACHE_FILE
    saved = (PASSWORD_FILE, CACHE_FILE)
    PASSWORD_FILE, CACHE_FILE = "/nonexistent/pass", "/nonexistent/cache"
    try:
        servers, err = read_forwarders({})
    finally:
        PASSWORD_FILE, CACHE_FILE = saved
    check("no credentials: forwarders unreadable with a clear error, never an empty OK", servers == {} and err.startswith("cannot read the password file"))

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
