#!/usr/bin/env python3
"""agent_ns8_probe.py - CheckMK special agent (datasource program): endpoint probes for the NS8 modules (PROTOTYPE)

Runs on the CheckMK server and checks, from the outside, what each NS8 module
exposes on the node. No credentials, nothing installed on the node. Prints
CheckMK local-check lines (NS8.Probe.<name>).

Probes:
- web (HTTPS with SNI + Host header): WebTop, NethVoice, NethCTI, cluster-admin, Grafana, Prometheus
  OK on 2xx/3xx; for the two that sit behind NS8 basic auth a 401 means "reachable, protected"
  (OK); 5xx or no answer is CRITICAL. TLS certificate days left are reported (WARN < 21, CRIT < 7).
- mail: SMTP 25, submission 587 and IMAP 143 / POP3 110 (greeting banner is read and checked),
  SMTPS 465, IMAPS 993, POP3S 995 (TLS handshake + certificate)
- Samba AD: LDAP 389 and Global Catalog 3268 (an anonymous LDAP bind must get an LDAP answer), LDAPS 636 (TLS),
  SMB 445 (an SMB2 negotiation must be answered), DNS 53 (a real UDP query for the DC name must be answered),
  Kerberos 88 (TCP connect only: a bare "port open" proves little when something in the network path accepts
  connections for any address, as the Twingate client does, so it is the weakest probe here)

Response time: WARN >= 2 s, CRIT >= 5 s.

Certificate pinning (--pin-sha256): every TLS-speaking probe here already
disables CA validation (the lab certificate is self-signed), which by itself
means ANY certificate is accepted - a machine-in-the-middle on the same
network could present its own certificate and go unnoticed. --pin-sha256
closes that: give the SHA-256 fingerprint (hex) of the real certificate (this
node uses the SAME one for Traefik, Postfix, Dovecot and Samba) and every web
or TLS probe then fails CRIT with a clear warning the moment it sees a
different one, instead of silently trusting it. Not a secret, so a plain CLI
argument.

Usage (datasource program):
  agent_ns8_probe.py --ip 10.155.100.149 --dc-name dc1.ad.nethlab.it --pin-sha256 <fingerprint>

Version: 0.2.0"""

import argparse
import concurrent.futures
import hashlib
import os
import re
import socket
import ssl
import struct
import sys
import tempfile
import time
from typing import Callable, List, Optional

VERSION = "0.2.0"
TIMEOUT = 5.0
RESP = (2.0, 5.0)
CERT_DAYS = (21, 7)  # WARN below / CRIT below

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

_PIN = ""  # set from --pin-sha256 in main(); empty means pinning is off


def pin_mismatch(der: Optional[bytes]) -> Optional[str]:
    """None if OK (no pin configured, or it matches); otherwise a ready-to-emit warning."""
    if not _PIN or not der:
        return None
    actual = hashlib.sha256(der).hexdigest()
    if actual != _PIN:
        return "PIN MISMATCH (possible machine-in-the-middle): expected %s, got %s" % (_PIN, actual)
    return None


def line(state: int, name: str, text: str, metrics: Optional[List[str]] = None) -> str:
    return "%d NS8.Probe.%s %s %s" % (state, name, "|".join(metrics) if metrics else "-", text.replace("\n", " "))


def rt_state(secs: float) -> int:
    return 2 if secs >= RESP[1] else 1 if secs >= RESP[0] else 0


def rt_metric(secs: float) -> str:
    return "response_seconds=%.3f;%g;%g;0;" % (secs, RESP[0], RESP[1])


def cert_days(der: Optional[bytes]) -> Optional[int]:
    """Days until the certificate expires, None if it cannot be read."""
    if not der:
        return None
    try:
        pem = ssl.DER_cert_to_PEM_cert(der)
        with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as fh:
            fh.write(pem)
            path = fh.name
        try:
            info = ssl._ssl._test_decode_cert(path)  # stdlib, no extra package needed
        finally:
            os.unlink(path)
        return int((ssl.cert_time_to_seconds(info["notAfter"]) - time.time()) // 86400)
    except Exception:  # noqa: BLE001 - expiry is a bonus, never break the probe for it
        return None


def cert_state(days: Optional[int]) -> int:
    if days is None:
        return 0
    return 2 if days < CERT_DAYS[1] else 1 if days < CERT_DAYS[0] else 0


def probe_web(ip: str, name: str, host: str, path: str, auth_ok: bool = False) -> str:
    t0 = time.monotonic()
    try:
        sock = socket.create_connection((ip, 443), TIMEOUT)
        tls = _CTX.wrap_socket(sock, server_hostname=host)
        tls.settimeout(TIMEOUT)
        der = tls.getpeercert(binary_form=True)
        mismatch = pin_mismatch(der)
        if mismatch:
            tls.close()
            return line(2, name, mismatch)
        tls.sendall(("GET %s HTTP/1.1\r\nHost: %s\r\nUser-Agent: checkmk-probe\r\nConnection: close\r\n\r\n" % (path, host)).encode())
        data = b""
        while b"\r\n" not in data and len(data) < 2000:
            chunk = tls.recv(1000)
            if not chunk:
                break
            data += chunk
        tls.close()
    except (OSError, ssl.SSLError) as exc:
        return line(2, name, "https://%s%s not reachable: %s" % (host, path, exc.__class__.__name__))
    secs = time.monotonic() - t0
    m = re.match(rb"HTTP/\d\.\d (\d{3})", data)
    code = int(m.group(1)) if m else 0
    days = cert_days(der)
    state = 0 if (200 <= code < 400 or (auth_ok and code in (401, 403))) else 2
    state = max(state, rt_state(secs), cert_state(days))
    text = "https://%s%s -> HTTP %d%s in %.2f s" % (host, path, code, " (protected, reachable)" if code in (401, 403) else "", secs)
    metrics = [rt_metric(secs)]
    if days is not None:
        text += ", certificate valid %d more day(s)" % days
        metrics.append("cert_days=%d;%d;%d;0;" % (days, CERT_DAYS[0], CERT_DAYS[1]))
    return line(state, name, text, metrics)


def probe_banner(ip: str, name: str, port: int, expect: str) -> str:
    t0 = time.monotonic()
    try:
        s = socket.create_connection((ip, port), TIMEOUT)
        s.settimeout(TIMEOUT)
        banner = s.recv(120).decode(errors="replace").strip()
        s.close()
    except OSError as exc:
        return line(2, name, "port %d not reachable: %s" % (port, exc.__class__.__name__))
    secs = time.monotonic() - t0
    ok = banner.startswith(expect)
    return line(max(0 if ok else 2, rt_state(secs)), name, "port %d greeting %s in %.2f s: %s" % (port, "OK" if ok else "UNEXPECTED", secs, banner[:60]), [rt_metric(secs)])


def probe_tls(ip: str, name: str, port: int) -> str:
    t0 = time.monotonic()
    try:
        s = socket.create_connection((ip, port), TIMEOUT)
        tls = _CTX.wrap_socket(s, server_hostname=ip)
        der = tls.getpeercert(binary_form=True)
        tls.close()
    except (OSError, ssl.SSLError) as exc:
        return line(2, name, "TLS on port %d failed: %s" % (port, exc.__class__.__name__))
    mismatch = pin_mismatch(der)
    if mismatch:
        return line(2, name, mismatch)
    secs = time.monotonic() - t0
    days = cert_days(der)
    metrics = [rt_metric(secs)]
    text = "port %d TLS handshake OK in %.2f s" % (port, secs)
    if days is not None:
        text += ", certificate valid %d more day(s)" % days
        metrics.append("cert_days=%d;%d;%d;0;" % (days, CERT_DAYS[0], CERT_DAYS[1]))
    return line(max(rt_state(secs), cert_state(days)), name, text, metrics)


def probe_tcp(ip: str, name: str, port: int, label: str) -> str:
    t0 = time.monotonic()
    try:
        socket.create_connection((ip, port), TIMEOUT).close()
    except OSError as exc:
        return line(2, name, "%s port %d not reachable: %s" % (label, port, exc.__class__.__name__))
    secs = time.monotonic() - t0
    return line(rt_state(secs), name, "%s port %d accepts connections (%.2f s)" % (label, port, secs), [rt_metric(secs)])


# anonymous LDAP simple bind (version 3): any BER LDAPMessage (0x30 ...) with a bindResponse (0x61) proves an LDAP server answers,
# whatever the result code is (AD may refuse anonymous binds, that is fine)
_LDAP_BIND = bytes.fromhex("300c020101600702010304008000")
# minimal SMB2 NEGOTIATE (dialect 2.1) inside a NetBIOS session header
_SMB2_NEGOTIATE = (b"\x00\x00\x00\x66" + b"\xfeSMB" + struct.pack("<HHIHHIIQIIQ", 64, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0) + b"\x00" * 16
                   + struct.pack("<HHHHI", 36, 1, 1, 0, 0) + b"\x00" * 16 + b"\x00" * 8 + struct.pack("<H", 0x0210))


def _exchange(ip: str, port: int, payload: bytes, size: int = 200) -> Optional[bytes]:
    try:
        s = socket.create_connection((ip, port), TIMEOUT)
        s.settimeout(TIMEOUT)
        s.sendall(payload)
        data = s.recv(size)
        s.close()
        return data
    except OSError:
        return None


def probe_ldap(ip: str, name: str, port: int, label: str) -> str:
    t0 = time.monotonic()
    data = _exchange(ip, port, _LDAP_BIND)
    secs = time.monotonic() - t0
    if data is None:
        return line(2, name, "%s port %d not reachable" % (label, port))
    ok = len(data) > 5 and data[0] == 0x30 and b"\x61" in data[:12]
    return line(max(0 if ok else 2, rt_state(secs)), name, "%s port %d %s in %.2f s" % (label, port, "answers LDAP" if ok else "does not speak LDAP (got %d byte(s))" % len(data), secs), [rt_metric(secs)])


def probe_smb(ip: str, name: str, port: int) -> str:
    t0 = time.monotonic()
    data = _exchange(ip, port, _SMB2_NEGOTIATE)
    secs = time.monotonic() - t0
    if data is None:
        return line(2, name, "SMB port %d not reachable" % port)
    ok = len(data) >= 8 and data[4:8] in (b"\xfeSMB", b"\xffSMB")
    return line(max(0 if ok else 2, rt_state(secs)), name, "SMB port %d %s in %.2f s" % (port, "answers the SMB negotiation" if ok else "does not speak SMB (got %d byte(s))" % len(data), secs), [rt_metric(secs)])


def probe_dns(ip: str, name: str, qname: str) -> str:
    qid = os.getpid() & 0xFFFF
    packet = struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, 0) + b"".join(bytes([len(p)]) + p.encode() for p in qname.split(".")) + b"\x00" + struct.pack(">HH", 1, 1)
    t0 = time.monotonic()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(TIMEOUT)
        s.sendto(packet, (ip, 53))
        data, _ = s.recvfrom(512)
        s.close()
    except OSError as exc:
        return line(2, name, "DNS query for %s got no answer: %s" % (qname, exc.__class__.__name__))
    secs = time.monotonic() - t0
    if len(data) < 12 or struct.unpack(">H", data[:2])[0] != qid:
        return line(2, name, "DNS answer not understood")
    rcode, answers = data[3] & 0x0F, struct.unpack(">H", data[6:8])[0]
    ok = rcode == 0 and answers >= 1
    return line(max(0 if ok else 2, rt_state(secs)), name, "UDP 53 answered for %s: rcode %d, %d record(s) in %.2f s" % (qname, rcode, answers, secs), [rt_metric(secs)])


def main() -> int:
    ap = argparse.ArgumentParser(description="Endpoint probes for the NS8 modules (no credentials)")
    ap.add_argument("--ip", required=True, help="IP of the NS8 node")
    ap.add_argument("--dc-name", default="", help="name the Samba AD DNS must answer (e.g. dc1.ad.nethlab.it)")
    ap.add_argument("--node-host", default="NS8-RL98.nethlab.it", help="FQDN of the node (cluster-admin, Grafana, Prometheus)")
    ap.add_argument("--webtop-host", default="webtop.nethlab.it")
    ap.add_argument("--voice-host", default="voice.nethlab.it")
    ap.add_argument("--cti-host", default="cti.nethlab.it")
    ap.add_argument("--pin-sha256", default="", help="SHA-256 fingerprint (hex) of the expected certificate; not a secret")
    a = ap.parse_args()

    global _PIN
    _PIN = a.pin_sha256.strip().lower().replace(":", "")

    jobs: List[Callable[[], str]] = [
        lambda: probe_web(a.ip, "WebTop", a.webtop_host, "/webtop/"),
        lambda: probe_web(a.ip, "NethVoice", a.voice_host, "/"),
        lambda: probe_web(a.ip, "NethCTI", a.cti_host, "/"),
        lambda: probe_web(a.ip, "ClusterAdmin", a.node_host, "/cluster-admin/"),
        lambda: probe_web(a.ip, "Grafana", a.node_host, "/grafana/api/health", auth_ok=True),
        lambda: probe_web(a.ip, "Prometheus", a.node_host, "/prometheus/-/ready", auth_ok=True),
        lambda: probe_banner(a.ip, "Smtp25", 25, "220"),
        lambda: probe_banner(a.ip, "Submission587", 587, "220"),
        lambda: probe_banner(a.ip, "Imap143", 143, "* OK"),
        lambda: probe_banner(a.ip, "Pop3110", 110, "+OK"),
        lambda: probe_tls(a.ip, "Smtps465", 465),
        lambda: probe_tls(a.ip, "Imaps993", 993),
        lambda: probe_tls(a.ip, "Pop3s995", 995),
        lambda: probe_tls(a.ip, "Ldaps636", 636),
        lambda: probe_ldap(a.ip, "Ldap389", 389, "LDAP"),
        lambda: probe_smb(a.ip, "Smb445", 445),
        lambda: probe_tcp(a.ip, "Kerberos88", 88, "Kerberos (connect only)"),
        lambda: probe_ldap(a.ip, "GlobalCatalog3268", 3268, "Global Catalog"),
    ]
    if a.dc_name:
        jobs.append(lambda: probe_dns(a.ip, "Dns53", a.dc_name))

    print("<<<check_mk>>>")
    print("Version: ns8-probe-special-agent-%s" % VERSION)
    print("AgentOS: ns8-probe")
    print("<<<local:sep(0)>>>")
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = [f.result() for f in [pool.submit(j) for j in jobs]]
    print("\n".join(sorted(results, key=lambda r: r.split(" ", 2)[1])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
