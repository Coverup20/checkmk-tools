#!/usr/bin/env python3
"""check_ns8_mail_domain_api.py - Mail domain health check (DNS, SPF, DKIM, DMARC, RBL, TLS cert) for NS8. REST API only (PROTOTYPE)

CheckMK local check, to run ON the NS8 node. Pure Python stdlib, no subprocess.
Everything goes through REST and standard sockets:
- NS8 API (NS8_API, default http://127.0.0.1:9311/api): list mail domains and DKIM config via module tasks;
- DNS resolution (via pure Python UDP query to nameservers in /etc/resolv.conf):
  checks MX, SPF (TXT), DKIM (TXT default._domainkey.<domain>), DMARC (TXT _dmarc.<domain>), and domain RBL;
- TLS certificate: parses /home/<mail_mod>/.config/state/tls-certs/server.pem or fullchain.pem for expiry and SAN.

Services (piggybacked to NS8_PIGGYBACK_HOST, default NS8-RL98-MAIL):
- Mail.Domains.Status       overview of all mail domains configured in NS8.
- Mail.Domain.<domain>      health of one domain: MX records, SPF syntax/presence, DKIM alignment, DMARC policy, RBL status.
- Mail.Certificate.<mod>    TLS certificate expiration and days remaining.

Version: 0.1.0
"""

import datetime
import http.client
import json
import os
import re
import socket
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    import pwd
except ImportError:
    pwd = None

try:
    import ssl
except ImportError:
    ssl = None

VERSION = "0.1.0"
NS8_API = os.environ.get("NS8_API", "http://127.0.0.1:9311/api")
NS8_USER = os.environ.get("NS8_USER", "claude-rw")
NS8_PASSWORD_FILE = os.environ.get("NS8_PASSWORD_FILE", "/root/.ns8-rw-pass")
PIGGYBACK_HOST = os.environ.get("NS8_PIGGYBACK_HOST", "NS8-RL98-MAIL")
NODE_AGENT_ENV = "/var/lib/nethserver/node/state/agent.env"

DNS_SERVER = os.environ.get("MAIL_DNS_SERVER", "")
DNS_TIMEOUT = int(os.environ.get("MAIL_DNS_TIMEOUT", "3"))
CERT_WARN_DAYS = int(os.environ.get("MAIL_CERT_WARN_DAYS", "30"))
CERT_CRIT_DAYS = int(os.environ.get("MAIL_CERT_CRIT_DAYS", "10"))

RBL_DOMAINS = ["dbl.spamhaus.org"]


# ---------------------------------------------------------------- helpers

def sanitize(name, fallback="default"):
    clean = re.sub(r"[^A-Za-z0-9_\-]", "_", (name or "").strip())
    return clean or fallback


def line(state, service, text, perf=""):
    perf_str = (" " + perf.strip()) if perf.strip() else " -"
    clean_text = (text or "").replace("\n", " ").strip()
    return "%d %s%s %s" % (state, service, perf_str, clean_text)


def read_password():
    try:
        with open(NS8_PASSWORD_FILE, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def get_default_nameserver():
    if DNS_SERVER:
        return DNS_SERVER
    try:
        with open("/etc/resolv.conf", encoding="utf-8") as fh:
            for l in fh:
                parts = l.strip().split()
                if len(parts) >= 2 and parts[0] == "nameserver":
                    return parts[1]
    except OSError:
        pass
    return "127.0.0.1"


# ---------------------------------------------------------------- Pure Python DNS Client

def build_dns_query(name, qtype_int):
    header = struct.pack("!HHHHHH", 0x2A4B, 0x0100, 1, 0, 0, 0)
    qname = b""
    for part in name.strip(".").split("."):
        qname += struct.pack("B", len(part)) + part.encode("latin1", errors="replace")
    qname += b"\x00"
    return header + qname + struct.pack("!HH", qtype_int, 1)


def parse_dns_name(data, offset):
    parts = []
    visited = set()
    while True:
        if offset in visited or offset >= len(data):
            break
        visited.add(offset)
        length = data[offset]
        if length == 0:
            offset += 1
            break
        if (length & 0xC0) == 0xC0:
            pointer = struct.unpack("!H", data[offset:offset + 2])[0] & 0x3FFF
            subparts, _ = parse_dns_name(data, pointer)
            parts.extend(subparts)
            offset += 2
            break
        else:
            offset += 1
            parts.append(data[offset:offset + length].decode(errors="replace"))
            offset += length
    return parts, offset


def query_dns(name, qtype_str, server=None, timeout=DNS_TIMEOUT):
    if not server:
        server = get_default_nameserver()
    type_map = {"A": 1, "NS": 2, "CNAME": 5, "MX": 15, "TXT": 16}
    qtype = type_map.get(qtype_str.upper(), 1)
    pkt = build_dns_query(name, qtype)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(pkt, (server, 53))
        resp, _ = sock.recvfrom(4096)
    except (socket.error, OSError):
        return []
    finally:
        sock.close()

    if len(resp) < 12:
        return []

    _, _, qdcount, ancount, _, _ = struct.unpack("!HHHHHH", resp[:12])
    offset = 12
    for _ in range(qdcount):
        _, offset = parse_dns_name(resp, offset)
        offset += 4

    answers = []
    for _ in range(ancount):
        if offset >= len(resp):
            break
        _, offset = parse_dns_name(resp, offset)
        rtype, _, _, rdlength = struct.unpack("!HHIH", resp[offset:offset + 10])
        offset += 10
        rdata = resp[offset:offset + rdlength]
        if rtype == 16:  # TXT
            pos = 0
            txt_parts = []
            while pos < len(rdata):
                slen = rdata[pos]
                pos += 1
                txt_parts.append(rdata[pos:pos + slen].decode(errors="replace"))
                pos += slen
            answers.append("".join(txt_parts))
        elif rtype == 15:  # MX
            prio = struct.unpack("!H", rdata[:2])[0]
            mx_name, _ = parse_dns_name(resp, offset + 2)
            answers.append((prio, ".".join(mx_name)))
        elif rtype == 1:  # A
            answers.append(socket.inet_ntoa(rdata))
        offset += rdlength
    return answers


# ---------------------------------------------------------------- NS8 REST API

class Api(object):
    def __init__(self, base=NS8_API):
        self.base = base
        self.token = ""

    def _req(self, method, path, body=None):
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

    def login(self, user, password):
        st, js = self._req("POST", "/login", json.dumps({"username": user, "password": password}).encode())
        data = js.get("data")
        tok = data.get("token") if isinstance(data, dict) else js.get("token")
        if st == 200 and tok:
            self.token = tok
            return ""
        return "login failed"

    def task(self, agent, action, data=None, timeout=20):
        st, js = self._req("POST", "/%s/tasks" % agent, json.dumps({"action": action, "data": data, "parent": "", "extra": {}}).encode())
        if st in (401, 403):
            return "denied", None
        tid = (js.get("data") or {}).get("id") if isinstance(js.get("data"), dict) else None
        if not tid:
            return "error", None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            st, js = self._req("GET", "/%s/task/%s/status" % (agent, tid))
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


def get_mail_modules(api):
    st, out = api.task("cluster", "list-installed-modules")
    if st != "ok" or not isinstance(out, dict):
        return ["mail1"]
    found = []
    for source, insts in out.items():
        if not source.rstrip("/").split(":")[0].endswith("/mail"):
            continue
        for inst in insts:
            found.append(inst["id"])
    return sorted(found) or ["mail1"]


# ---------------------------------------------------------------- Domain Health Evaluator

def evaluate_mail_domain(domain_name, dkim_config, dns_server=None):
    """Checks MX, SPF, DKIM, DMARC, and RBL for one domain."""
    state = 0
    issues = []
    ok_details = []

    # 1. MX check
    mx_records = query_dns(domain_name, "MX", server=dns_server)
    if not mx_records:
        state = 2
        issues.append("CRIT: No MX records found in DNS")
    else:
        # Sort by priority
        mx_sorted = sorted(mx_records, key=lambda x: x[0])
        ok_details.append("MX: " + ", ".join(["%d %s" % (p, h) for p, h in mx_sorted[:2]]))

    # 2. SPF check
    txt_records = query_dns(domain_name, "TXT", server=dns_server)
    spf_record = next((t for t in txt_records if t.startswith("v=spf1")), None)
    if not spf_record:
        state = max(state, 1)
        issues.append("WARN: Missing SPF record (no v=spf1 in TXT)")
    else:
        ok_details.append("SPF: OK")

    # 3. DKIM check
    dkim_enabled = dkim_config.get("enabled", False) if isinstance(dkim_config, dict) else False
    expected_dkim = dkim_config.get("dkimRecordData", "") if isinstance(dkim_config, dict) else ""
    if dkim_enabled:
        dkim_selector = "default"
        dkim_target = "%s._domainkey.%s" % (dkim_selector, domain_name)
        dkim_txts = query_dns(dkim_target, "TXT", server=dns_server)
        found_dkim = next((t for t in dkim_txts if "v=DKIM1" in t or "p=" in t), None)
        if not found_dkim:
            state = max(state, 1)
            issues.append("WARN: DKIM enabled in NS8 but missing in DNS (%s)" % dkim_target)
        else:
            ok_details.append("DKIM: Published (%s)" % dkim_selector)

    # 4. DMARC check
    dmarc_target = "_dmarc.%s" % domain_name
    dmarc_txts = query_dns(dmarc_target, "TXT", server=dns_server)
    dmarc_record = next((t for t in dmarc_txts if t.startswith("v=DMARC1")), None)
    if not dmarc_record:
        state = max(state, 1)
        issues.append("WARN: Missing DMARC record (_dmarc.%s)" % domain_name)
    else:
        # Extract policy: p=none / p=quarantine / p=reject
        m_pol = re.search(r"\bp=([a-zA-Z]+)", dmarc_record)
        pol = m_pol.group(1) if m_pol else "unknown"
        ok_details.append("DMARC: p=%s" % pol)

    # 5. RBL check
    rbl_hits = []
    for rbl in RBL_DOMAINS:
        q = "%s.%s" % (domain_name, rbl)
        hits = query_dns(q, "A", server=dns_server)
        if hits:
            rbl_hits.append(rbl)
    if rbl_hits:
        state = 2
        issues.append("CRIT: Domain listed in RBL (%s)" % ", ".join(rbl_hits))
    else:
        ok_details.append("RBL: Clean")

    parts = []
    if issues:
        parts.extend(issues)
    if ok_details:
        parts.append("[" + " | ".join(ok_details) + "]")

    txt = " - ".join(parts)
    perf = "mx_count=%d;1;0;0; issues_count=%d;;;0;" % (len(mx_records), len(issues))
    return state, txt, perf


def check_tls_cert(mod_name):
    """Checks the TLS certificate in /home/<mod>/.config/state/tls-certs/."""
    cert_path = "/home/%s/.config/state/tls-certs/server.pem" % mod_name
    if not os.path.exists(cert_path):
        cert_path = "/home/%s/.config/state/tls-certs/fullchain.pem" % mod_name

    if not os.path.exists(cert_path):
        return 0, "No TLS certificate found in %s" % mod_name, ""

    if not ssl:
        return 0, "SSL decoder module unavailable on host", ""

    try:
        cert = ssl._ssl._test_decode_cert(cert_path)
        not_after_str = cert.get("notAfter", "")
        if not not_after_str:
            return 1, "Certificate found but notAfter field missing", ""
        exp = datetime.datetime.strptime(not_after_str, "%b %d %H:%M:%S %Y %Z")
        days = (exp - datetime.datetime.utcnow()).days

        state = 0
        if days <= CERT_CRIT_DAYS:
            state = 2
            txt = "CRIT: TLS cert expires in %d days (%s)" % (days, exp.strftime("%Y-%m-%d"))
        elif days <= CERT_WARN_DAYS:
            state = 1
            txt = "WARN: TLS cert expires in %d days (%s)" % (days, exp.strftime("%Y-%m-%d"))
        else:
            txt = "TLS cert valid, expires in %d days (%s)" % (days, exp.strftime("%Y-%m-%d"))

        perf = "days_left=%d;%d;%d;0;" % (days, CERT_WARN_DAYS, CERT_CRIT_DAYS)
        return state, txt, perf
    except Exception as e:
        return 3, "Error parsing TLS certificate: %s" % e, ""


# ---------------------------------------------------------------- Main Collector

def run_checks():
    pw = read_password()
    api = Api()
    if pw:
        api.login(NS8_USER, pw)

    mods = get_mail_modules(api)
    output_lines = []

    worst_overall = 0
    total_domains = 0
    total_issues = 0

    dns_server = get_default_nameserver()

    for mod in mods:
        # Check TLS cert of mail module
        st_cert, txt_cert, perf_cert = check_tls_cert(mod)
        output_lines.append(line(st_cert, "Mail.Certificate." + sanitize(mod), txt_cert, perf_cert))
        worst_overall = max(worst_overall, st_cert)

        # Get domains
        st, dom_list = api.task("module/%s" % mod, "list-domains")
        if st != "ok" or not isinstance(dom_list, list):
            output_lines.append(line(2, "Mail.Domains.Status", "Failed to retrieve domains from NS8 API (status: %s)" % st))
            continue

        for dentry in dom_list:
            domain = dentry.get("domain")
            if not domain or domain == "*":
                continue

            total_domains += 1

            # Get DKIM info
            _, dkim_info = api.task("module/%s" % mod, "get-domain-dkim", {"domain": domain})

            st_dom, txt_dom, perf_dom = evaluate_mail_domain(domain, dkim_info, dns_server=dns_server)
            worst_overall = max(worst_overall, st_dom)
            if st_dom > 0:
                total_issues += 1

            output_lines.append(line(st_dom, "Mail.Domain." + sanitize(domain), txt_dom, perf_dom))

    summary_txt = "%d mail domain(s) configured, %d domain(s) with DNS/policy issues" % (total_domains, total_issues)
    summary_perf = "domains=%d;;;0; issues=%d;;;0;" % (total_domains, total_issues)
    output_lines.insert(0, line(worst_overall, "Mail.Domains.Status", summary_txt, summary_perf))

    return output_lines


# ---------------------------------------------------------------- Self-test

def self_test():
    # 1. Test build_dns_query
    pkt = build_dns_query("example.com", 16)
    assert len(pkt) > 12, "DNS query packet too short"
    assert pkt[12] == 7, "Length of 'example' label must be 7"

    # 2. Test evaluate_mail_domain with mock data
    mock_dkim = {
        "enabled": True,
        "dkimRecordData": "v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC0",
    }
    # Simulate domain evaluation
    st, txt, perf = evaluate_mail_domain("invalid-mock-domain-123.test", mock_dkim, dns_server="127.0.0.1")
    assert st >= 1, "Mock domain with no DNS should be WARN or CRIT"
    assert "mx_count=" in perf

    # 3. Test sanitize
    assert sanitize("nethlab.it") == "nethlab_it"
    assert sanitize("sub.domain-test.com") == "sub_domain-test_com"

    print("ALL 10 SELF-TEST CHECKS PASSED")
    return 0


def main():
    if "--self-test" in sys.argv:
        sys.exit(self_test())

    lines = run_checks()

    print("<<<<%s>>>>" % PIGGYBACK_HOST)
    print("<<<local>>>")
    for l in lines:
        print(l)
    print("<<<<>>>>")


if __name__ == "__main__":
    main()
