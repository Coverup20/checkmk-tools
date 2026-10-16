#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

"""check_dns_resolution_api.py - NethSecurity DNS monitoring for CheckMK (PROTOTYPE)

CheckMK local check, to run ON the firewall. 100% REST-only via NethSecurity ubus REST API:
No subprocess, no raw UDP socket probes, no UCI.
Queries NSEC REST API on localhost (NSEC_API, default https://127.0.0.1:9090/api):
1. 'ns.dashboard service-status' and 'service list' for dnsmasq daemon status;
2. 'ns.dns get-config' for configured upstream forwarders, domain, and rebind protection.

Services:
- DNS.Resolution            Resolver daemon (dnsmasq) health and forwarder overview.
                            CRIT if dnsmasq daemon is stopped or dead.
                            WARN if dnsmasq is running but 0 forwarders are configured.
                            Perfdata: running=1|forwarders=N
- DNS.Primary, DNS.Secondary Configured forwarders read from ns.dns get-config in order.
                            Entry text shows configured IP and port.

Security notes:
- The API does NOT enforce per-object permissions for /api/ubus/call: claude-ro has
  read-only ACL group (ns-check-reader) but must be treated as full administrator.
- TLS verification is disabled for loopback connection only.

Version: 0.2.0
"""

import base64
import ipaddress
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Tuple

VERSION = "0.2.0"
API = os.environ.get("NSEC_API", "https://127.0.0.1:9090/api")
USER = os.environ.get("NSEC_USER", "claude-ro")
PASSWORD_FILE = os.environ.get("NSEC_PASSWORD_FILE", "/root/.nsec-ro-pass")
CACHE_FILE = os.environ.get("NSEC_DNS_CACHE", "/tmp/check_dns_resolution_api.cache")
SERVICE = "DNS.Resolution"
ROLE_NAMES = ("Primary", "Secondary", "Tertiary")


def role_name(position: int) -> str:
    """Service name of the forwarder in this position (0 = first configured)."""
    return "DNS.%s" % (ROLE_NAMES[position] if position < len(ROLE_NAMES) else "Server%d" % (position + 1))


def line(state: int, name: str, perf: str, text: str) -> str:
    return "%d %s %s %s" % (state, name, perf or "-", text)


# ---------------------------------------------------------------- REST API Client

class Api:
    def __init__(self, base: str = API):
        self.base = base
        self.token = ""
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE

    def _post(self, path: str, body: dict, token: str = "", timeout: float = 15.0) -> Tuple[int, dict]:
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

    def login(self, user: str, password: str) -> str:
        """Returns empty string on success, otherwise an error description."""
        st, js = self._post("/login", {"username": user, "password": password})
        tok = js.get("token") if isinstance(js, dict) else None
        if st == 200 and tok:
            self.token = tok
            return ""
        return "login failed (HTTP %s)" % st if st else "NSEC API unreachable at %s" % self.base

    def call(self, path: str, method: str, payload: Optional[dict] = None, timeout: float = 15.0) -> Tuple[str, Optional[dict]]:
        """Returns (state, data); state is ok, denied, error or unreachable."""
        st, js = self._post("/ubus/call", {"path": path, "method": method, "payload": payload or {}}, self.token, timeout)
        if st == 0:
            return "unreachable", None
        if st in (401, 403):
            return "denied", None
        if st != 200 or not isinstance(js, dict) or js.get("code") != 200:
            return "error", None
        return "ok", js.get("data")


def jwt_exp(token: str) -> int:
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        return int(json.loads(base64.urlsafe_b64decode(part.encode())).get("exp", 0))
    except (IndexError, ValueError, TypeError):
        return 0


def load_cache() -> dict:
    try:
        with open(CACHE_FILE, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cache(d: dict) -> None:
    try:
        tmp = "%s.%d.tmp" % (CACHE_FILE, os.getpid())
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(d, fh)
        os.replace(tmp, CACHE_FILE)
    except OSError:
        pass


def open_session(api: Api, cache: dict) -> str:
    """Reuses cached token if still valid, otherwise performs REST login."""
    tok = cache.get("token", "")
    if tok and jwt_exp(tok) - time.time() > 60:
        api.token = tok
        return ""
    try:
        with open(PASSWORD_FILE, encoding="utf-8") as fh:
            password = fh.read().strip()
    except OSError:
        return "cannot read password file %s" % PASSWORD_FILE
    err = api.login(USER, password)
    if not err:
        cache["token"] = api.token
        save_cache(cache)
    return err


# ---------------------------------------------------------------- Data Parsing

def parse_server(entry: str) -> Optional[Tuple[str, int]]:
    """Parses dnsmasq server entry: 'ip' or 'ip#port'. Domain entries (/domain/ip) ignored."""
    s = str(entry).strip()
    if not s or s.startswith("/"):
        return None
    host, _, port = s.partition("#")
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None
    return str(ip), int(port) if port.isdigit() else 53


def parse_service_running(service_data: Optional[dict], service_name: str = "dnsmasq") -> Tuple[bool, Optional[int]]:
    """Checks if service is running in ubus service list output. Returns (is_running, pid)."""
    if not isinstance(service_data, dict):
        return False, None
    svc_entry = service_data.get(service_name)
    if not isinstance(svc_entry, dict):
        return False, None
    instances = svc_entry.get("instances", {})
    if isinstance(instances, dict):
        for _, inst_info in instances.items():
            if isinstance(inst_info, dict) and inst_info.get("running"):
                return True, inst_info.get("pid")
    return False, None


# ---------------------------------------------------------------- Evaluation Logic

def evaluate_dns_status(
    daemon_running: bool,
    daemon_pid: Optional[int],
    forwarders: List[Tuple[str, int]],
    domain: str = "",
    error_msg: str = ""
) -> List[Tuple[int, str, str, str]]:
    """Evaluates DNS status purely from REST API telemetry.

    Returns list of (state, service_name, perfdata, text).
    """
    results = []

    if error_msg:
        results.append((3, SERVICE, "running=0;1;0;0;1", f"UNKNOWN - {error_msg}"))
        return results

    num_forwarders = len(forwarders)
    running_int = 1 if daemon_running else 0
    perf_main = f"running={running_int};1;0;0;1|forwarders={num_forwarders};1;0;0;"

    if not daemon_running:
        msg = "CRITICAL - dnsmasq resolver service is not running"
        results.append((2, SERVICE, perf_main, msg))
        return results

    pid_str = f" (pid {daemon_pid})" if daemon_pid else ""
    if num_forwarders == 0:
        msg = f"WARNING - dnsmasq resolver running{pid_str} but 0 forwarders configured in ns.dns"
        results.append((1, SERVICE, perf_main, msg))
    else:
        fw_list = ", ".join(f"{ip}:{p}" if p != 53 else ip for ip, p in forwarders)
        dom_str = f", domain: {domain}" if domain else ""
        msg = f"OK - dnsmasq resolver running{pid_str}, {num_forwarders} forwarder(s) configured ({fw_list}){dom_str}"
        results.append((0, SERVICE, perf_main, msg))

    # Detailed per-forwarder services
    for idx, (ip, port) in enumerate(forwarders):
        srv_name = role_name(idx)
        addr_str = f"{ip}:{port}" if port != 53 else ip
        results.append((0, srv_name, "-", f"OK - configured upstream forwarder {addr_str}"))

    return results


# ---------------------------------------------------------------- Main Collector

def run() -> List[str]:
    cache = load_cache()
    api = Api()
    err = open_session(api, cache)
    if err:
        return [line(3, SERVICE, "-", f"UNKNOWN - {err}")]

    # 1. Query service status via service list
    st_svc, data_svc = api.call("service", "list", {"name": "dnsmasq"})
    running = False
    pid = None
    if st_svc == "ok":
        running, pid = parse_service_running(data_svc, "dnsmasq")
    else:
        # Fallback to ns.dashboard service-status
        st_dash, data_dash = api.call("ns.dashboard", "service-status", {"service": "dnsmasq"})
        if st_dash == "ok" and isinstance(data_dash, dict):
            res = data_dash.get("result", {}) if "result" in data_dash else data_dash
            running = res.get("status") == "ok" or res.get("enabled", False)

    # 2. Query DNS configuration via ns.dns get-config
    st_dns, data_dns = api.call("ns.dns", "get-config")
    forwarders = []
    domain = ""
    if st_dns == "ok" and isinstance(data_dns, dict):
        domain = str(data_dns.get("domain", ""))
        for entry in data_dns.get("server") or []:
            p = parse_server(entry)
            if p and p not in forwarders:
                forwarders.append(p)

    err_msg = ""
    if st_svc != "ok" and st_dns != "ok":
        err_msg = f"cannot query ubus API for dnsmasq status ({st_svc})"

    eval_items = evaluate_dns_status(running, pid, forwarders, domain, err_msg)
    return [line(s, name, perf, txt) for s, name, perf, txt in eval_items]


def self_test():
    failed, done = [], []

    def check(name: str, cond: bool):
        done.append(name)
        status = "ok  " if cond else "FAIL"
        print(f"{status} {name}")
        if not cond:
            failed.append(name)

    # Test 1: JWT expiry parser
    payload = base64.urlsafe_b64encode(json.dumps({"exp": 100}).encode()).decode().rstrip("=")
    check("jwt exp valid", jwt_exp(f"x.{payload}.y") == 100)
    check("jwt exp invalid", jwt_exp("invalid") == 0)

    # Test 2: Server string parser
    check("parse_server plain IP", parse_server("8.8.8.8") == ("8.8.8.8", 53))
    check("parse_server IP with port", parse_server("1.1.1.1#5353") == ("1.1.1.1", 5353))
    check("parse_server IPv6", parse_server("2001:4860:4860::8888") == ("2001:4860:4860::8888", 53))
    check("parse_server ignores domain-specific", parse_server("/example.test/8.8.4.4") is None)
    check("parse_server invalid input", parse_server("not-valid") is None)

    # Test 3: parse_service_running from ubus output
    mock_service_data = {
        "dnsmasq": {
            "instances": {
                "instance1": {
                    "running": True,
                    "pid": 5432
                }
            }
        }
    }
    r, p = parse_service_running(mock_service_data, "dnsmasq")
    check("parse_service_running detected true with pid", r is True and p == 5432)

    mock_stopped = {"dnsmasq": {"instances": {"instance1": {"running": False}}}}
    r_stop, _ = parse_service_running(mock_stopped, "dnsmasq")
    check("parse_service_running detected stopped", r_stop is False)

    # Test 4: evaluate_dns_status cases
    # Case A: Running with forwarders -> OK (0)
    res_ok = evaluate_dns_status(True, 1234, [("8.8.8.8", 53), ("1.1.1.1", 53)], "nethsec.local")
    check("evaluate_dns_status normal returns OK", res_ok[0][0] == 0 and "running=1" in res_ok[0][2])
    check("evaluate_dns_status creates forwarder services", len(res_ok) == 3 and res_ok[1][1] == "DNS.Primary")

    # Case B: Stopped service -> CRITICAL (2)
    res_crit = evaluate_dns_status(False, None, [("8.8.8.8", 53)])
    check("evaluate_dns_status stopped returns CRITICAL", res_crit[0][0] == 2 and "CRITICAL" in res_crit[0][3])

    # Case C: Running with 0 forwarders -> WARNING (1)
    res_warn = evaluate_dns_status(True, 1234, [])
    check("evaluate_dns_status 0 forwarders returns WARNING", res_warn[0][0] == 1 and "WARNING" in res_warn[0][3])

    # Case D: API Error -> UNKNOWN (3)
    res_err = evaluate_dns_status(False, None, [], error_msg="connection refused")
    check("evaluate_dns_status error returns UNKNOWN", res_err[0][0] == 3 and "UNKNOWN" in res_err[0][3])

    print(f"\nSelf-test results: {len(done) - len(failed)}/{len(done)} passed")
    if failed:
        sys.exit(1)


def check():
    for out in run():
        print(out)


if "--self-test" in sys.argv:
    self_test()
else:
    check()
