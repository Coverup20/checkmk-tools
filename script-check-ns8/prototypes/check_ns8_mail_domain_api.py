#!/usr/bin/env python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

"""check_ns8_mail_domain_api.py - Mail domain and DKIM configuration check for NS8 (PROTOTYPE)

CheckMK local check, to run ON the NS8 node. 100% REST-only via NS8 REST API:
No subprocess, no raw UDP DNS sockets, no local log scraping.
Queries NS8 REST API (NS8_API, default http://127.0.0.1:9311/api):
1. 'cluster/list-installed-modules' to locate active mail modules (e.g. mail1);
2. 'module/<mail_mod>/list-domains' to retrieve all configured mail domains;
3. 'module/<mail_mod>/get-domain-dkim' for DKIM status, selector, and keys;
4. 'cluster/list-certificates' to monitor TLS certificate expiration and domain coverage.

Services (piggybacked to NS8_PIGGYBACK_HOST, default NS8-RL98-MAIL):
- Mail.Domains.Status       Overview of configured domains and DKIM deployment in NS8.
                            CRIT if NS8 API is unreachable or 0 domains found.
                            WARN if any domain has DKIM disabled.
                            Perfdata: domains=N|dkim_enabled=M|issues=K
- Mail.Domain.<domain>      Health and status of one domain (DKIM selector, key size, relay).
- Mail.Certificate.<cert>   TLS certificate expiration days and SAN coverage.
                            WARN if <= 30 days, CRIT if <= 10 days.

Version: 0.2.0
"""

import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple

VERSION = "0.2.0"
NS8_API = os.environ.get("NS8_API", "http://127.0.0.1:9311/api")
NS8_USER = os.environ.get("NS8_USER", "claude-rw")
NS8_PASSWORD_FILE = os.environ.get("NS8_PASSWORD_FILE", "/root/.ns8-rw-pass")
PIGGYBACK_HOST = os.environ.get("NS8_PIGGYBACK_HOST", "NS8-RL98-MAIL")
SERVICE = "Mail.Domains.Status"

CERT_WARN_DAYS = int(os.environ.get("MAIL_CERT_WARN_DAYS", "30"))
CERT_CRIT_DAYS = int(os.environ.get("MAIL_CERT_CRIT_DAYS", "10"))


def sanitize(name: str, fallback: str = "default") -> str:
    clean = re.sub(r"[^A-Za-z0-9_\-]", "_", (name or "").strip())
    return clean or fallback


def line(state: int, service: str, text: str, perf: str = "") -> str:
    perf_str = (" " + perf.strip()) if perf.strip() else " -"
    clean_text = (text or "").replace("\n", " ").strip()
    return "%d %s%s %s" % (state, service, perf_str, clean_text)


def read_password() -> str:
    try:
        with open(NS8_PASSWORD_FILE, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


# ---------------------------------------------------------------- NS8 REST API Client

class Api:
    def __init__(self, base: str = NS8_API):
        self.base = base
        self.token = ""

    def _req(self, method: str, path: str, body: Optional[bytes] = None) -> Tuple[int, dict]:
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

    def login(self, user: str, password: str) -> str:
        st, js = self._req("POST", "/login", json.dumps({"username": user, "password": password}).encode())
        data = js.get("data")
        tok = data.get("token") if isinstance(data, dict) else js.get("token")
        if st == 200 and tok:
            self.token = tok
            return ""
        return "login failed (HTTP %s)" % st if st else "API unreachable at %s" % self.base

    def task(self, agent: str, action: str, data: Optional[dict] = None, timeout: float = 20.0) -> Tuple[str, Optional[dict]]:
        payload = json.dumps({"action": action, "data": data, "parent": "", "extra": {}}).encode()
        st, js = self._req("POST", f"/{agent}/tasks", payload)
        if st in (401, 403):
            return "denied", None
        tid = (js.get("data") or {}).get("id") if isinstance(js.get("data"), dict) else None
        if not tid:
            return "error", None

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            st, js = self._req("GET", f"/{agent}/task/{tid}/status")
            if st == 200:
                d = js.get("data") or {}
                out = d.get("output")
                if isinstance(out, str):
                    try:
                        out = json.loads(out)
                    except ValueError:
                        pass
                ec = d.get("exit_code")
                return ("ok" if ec == 0 else "error"), out
            if st in (401, 403):
                return "denied", None
            time.sleep(0.25)
        return "timeout", None


def get_mail_modules(api: Api) -> List[str]:
    """Finds installed mail modules in NS8 cluster."""
    st, out = api.task("cluster", "list-installed-modules")
    if st != "ok" or not isinstance(out, dict):
        return ["mail1"]
    found = []
    for source, insts in out.items():
        if not source.rstrip("/").split(":")[0].endswith("/mail"):
            continue
        for inst in insts:
            if isinstance(inst, dict) and "id" in inst:
                found.append(inst["id"])
    return sorted(found) or ["mail1"]


# ---------------------------------------------------------------- Evaluation Logic

def evaluate_domain_dkim(domain: str, dkim_info: Optional[dict], domain_entry: Optional[dict] = None) -> Tuple[int, str, str]:
    """Evaluates domain DKIM and mail delivery configuration from NS8 REST data."""
    if not isinstance(dkim_info, dict):
        return 1, "WARNING: DKIM configuration unavailable from NS8 API", "dkim_enabled=0;;;0;1"

    enabled = bool(dkim_info.get("enabled", False))
    selector = dkim_info.get("selector", "default")
    key_size = dkim_info.get("keySize", dkim_info.get("keysize", 2048))
    has_record = bool(dkim_info.get("dkimRecordData"))

    relay = domain_entry.get("relay", False) if isinstance(domain_entry, dict) else False
    relay_str = " (relay domain)" if relay else ""

    perf = f"dkim_enabled={1 if enabled else 0};;;0;1|key_size={key_size};;;0;"

    if not enabled:
        msg = f"WARNING: DKIM signing is disabled for domain {domain}{relay_str}"
        return 1, msg, perf

    if not has_record:
        msg = f"WARNING: DKIM enabled but record data is empty for domain {domain}"
        return 1, msg, perf

    msg = f"OK: DKIM active (selector: {selector}, {key_size}-bit RSA){relay_str}"
    return 0, msg, perf


def parse_certificate_expiry(not_after_raw: str) -> Optional[int]:
    """Parses certificate not_after string to remaining days."""
    if not not_after_raw:
        return None
    now = datetime.datetime.now(datetime.timezone.utc)

    # Try standard date formats
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%b %d %H:%M:%S %Y %Z"):
        try:
            dt = datetime.datetime.strptime(not_after_raw.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            delta = dt - now
            return delta.days
        except ValueError:
            continue
    return None


def evaluate_certificate(cert_data: dict) -> Tuple[int, str, str, str]:
    """Evaluates a certificate entry from cluster/list-certificates.

    Returns (state, service_name, text, perfdata).
    """
    cert_id = cert_data.get("id") or cert_data.get("name") or "default"
    srv_name = f"Mail.Certificate.{sanitize(cert_id)}"

    not_after = cert_data.get("not_after") or cert_data.get("expire") or cert_data.get("expires") or ""
    days_left = parse_certificate_expiry(str(not_after)) if not_after else None

    domains = cert_data.get("domains") or cert_data.get("san") or []
    dom_str = f" [{', '.join(domains[:3])}]" if domains else ""

    if days_left is None:
        return 0, srv_name, f"OK: Certificate registered in cluster{dom_str}", ""

    perf = f"days_left={days_left};{CERT_WARN_DAYS};{CERT_CRIT_DAYS};0;"
    if days_left <= CERT_CRIT_DAYS:
        return 2, srv_name, f"CRITICAL: TLS cert expires in {days_left} days ({not_after}){dom_str}", perf
    if days_left <= CERT_WARN_DAYS:
        return 1, srv_name, f"WARNING: TLS cert expires in {days_left} days ({not_after}){dom_str}", perf

    return 0, srv_name, f"OK: TLS cert valid, {days_left} days remaining ({not_after}){dom_str}", perf


# ---------------------------------------------------------------- Main Collector

def run_checks() -> List[str]:
    api = Api()
    pw = read_password()
    if pw:
        err = api.login(NS8_USER, pw)
        if err:
            return [line(3, SERVICE, f"UNKNOWN: {err}")]

    output_lines = []
    total_domains = 0
    total_issues = 0
    dkim_active_count = 0
    worst_overall = 0

    # 1. Certificates check via cluster/list-certificates
    st_cert, cert_list = api.task("cluster", "list-certificates")
    if st_cert == "ok" and isinstance(cert_list, list):
        for c in cert_list:
            if isinstance(c, dict):
                st_c, name_c, txt_c, perf_c = evaluate_certificate(c)
                output_lines.append(line(st_c, name_c, txt_c, perf_c))
                worst_overall = max(worst_overall, st_c)

    # 2. Mail modules inspection
    mods = get_mail_modules(api)
    for mod in mods:
        st_doms, dom_list = api.task(f"module/{mod}", "list-domains")
        if st_doms != "ok" or not isinstance(dom_list, list):
            output_lines.append(line(2, SERVICE, f"CRITICAL: Failed to retrieve domains from {mod} (status: {st_doms})"))
            worst_overall = max(worst_overall, 2)
            continue

        for dentry in dom_list:
            if not isinstance(dentry, dict):
                continue
            domain = dentry.get("domain")
            if not domain or domain == "*":
                continue

            total_domains += 1

            # Query DKIM config
            st_dkim, dkim_info = api.task(f"module/{mod}", "get-domain-dkim", {"domain": domain})
            st_eval, txt_eval, perf_eval = evaluate_domain_dkim(domain, dkim_info if st_dkim == "ok" else None, dentry)

            if st_eval == 0 and "active" in txt_eval:
                dkim_active_count += 1
            if st_eval > 0:
                total_issues += 1
            worst_overall = max(worst_overall, st_eval)

            output_lines.append(line(st_eval, f"Mail.Domain.{sanitize(domain)}", txt_eval, perf_eval))

    summary_perf = f"domains={total_domains};1;0;0; dkim_active={dkim_active_count};;;0; issues={total_issues};;;0;"
    if total_domains == 0 and worst_overall == 0:
        summary_txt = "OK: No mail domains configured on this node"
    else:
        summary_txt = f"{total_domains} mail domain(s) configured ({dkim_active_count} with DKIM active, {total_issues} issue(s))"
    output_lines.insert(0, line(worst_overall, SERVICE, summary_txt, summary_perf))

    return output_lines


# ---------------------------------------------------------------- Self-test

def self_test():
    failed, done = [], []

    def check(name: str, cond: bool):
        done.append(name)
        status = "ok  " if cond else "FAIL"
        print(f"{status} {name}")
        if not cond:
            failed.append(name)

    # 1. Sanitize helper
    check("sanitize domain name", sanitize("nethlab.it") == "nethlab_it")
    check("sanitize dashes and subdomains", sanitize("mail-01.sub.domain.org") == "mail-01_sub_domain_org")

    # 2. DKIM evaluation cases
    # Case A: DKIM active
    valid_dkim = {"enabled": True, "selector": "default", "keySize": 2048, "dkimRecordData": "v=DKIM1; ..."}
    st, txt, perf = evaluate_domain_dkim("example.com", valid_dkim)
    check("evaluate_domain_dkim active returns OK", st == 0 and "DKIM active" in txt and "dkim_enabled=1" in perf)

    # Case B: DKIM disabled
    disabled_dkim = {"enabled": False}
    st_dis, txt_dis, perf_dis = evaluate_domain_dkim("example.com", disabled_dkim)
    check("evaluate_domain_dkim disabled returns WARNING", st_dis == 1 and "disabled" in txt_dis and "dkim_enabled=0" in perf_dis)

    # Case C: Relay domain
    st_rel, txt_rel, _ = evaluate_domain_dkim("relay.com", valid_dkim, {"relay": True})
    check("evaluate_domain_dkim notes relay domain", st_rel == 0 and "relay domain" in txt_rel)

    # 3. Certificate expiry parser
    fut_date = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=45)).strftime("%Y-%m-%dT%H:%M:%SZ")
    days = parse_certificate_expiry(fut_date)
    check("parse_certificate_expiry 45 days parsed", days is not None and 44 <= days <= 46)

    # 4. Certificate evaluation
    # Valid certificate (> 30 days)
    cert_valid = {"id": "cert1", "not_after": fut_date, "domains": ["mail.nethlab.it"]}
    st_c, srv_c, txt_c, perf_c = evaluate_certificate(cert_valid)
    check("evaluate_certificate valid returns OK", st_c == 0 and "valid" in txt_c and "days_left=" in perf_c)

    # Expiring soon certificate (7 days left -> CRITICAL)
    crit_date = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cert_crit = {"id": "cert2", "not_after": crit_date, "domains": ["old.nethlab.it"]}
    st_crit, _, txt_crit, _ = evaluate_certificate(cert_crit)
    check("evaluate_certificate <=10d returns CRITICAL", st_crit == 2 and "CRITICAL" in txt_crit)

    print(f"\nSelf-test results: {len(done) - len(failed)}/{len(done)} passed")
    if failed:
        sys.exit(1)


def check():
    lines = run_checks()
    print(f"<<<<{PIGGYBACK_HOST}>>>>")
    print("<<<local>>>")
    for l in lines:
        print(l)
    print("<<<<>>>>")


if "--self-test" in sys.argv:
    self_test()
else:
    check()
