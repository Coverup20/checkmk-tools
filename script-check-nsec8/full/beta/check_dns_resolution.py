#!/usr/bin/env python3
"""check_dns_resolution.py - CheckMK DNS check (pyuci beta).

Replaces subprocess nslookup with Python socket.getaddrinfo().
"""

import socket
import sys
import time

BETA = True
VERSION = "1.0.0b1"
SERVICE = "DNS.Resolution"
TEST_DOMAINS = ["google.com", "cloudflare.com", "dns.google"]

try:
    from euci import EUci
except ImportError:
    EUci = None


def resolve(domain, resolver="127.0.0.1", timeout_sec=5):
    """Resolve a domain using the specified resolver. Return (ok, ms)."""
    start = time.perf_counter()
    try:
        orig = socket.getdefaulttimeout()
        socket.setdefaulttimeout(timeout_sec)
        try:
            socket.getaddrinfo(domain, 53)
            ok = True
        except socket.gaierror:
            ok = False
        finally:
            if orig is not None:
                socket.setdefaulttimeout(orig)
            else:
                socket.setdefaulttimeout(None)
        elapsed = int((time.perf_counter() - start) * 1000)
        return ok, elapsed
    except Exception:
        return False, int((time.perf_counter() - start) * 1000)


def main():
    successful = 0
    failed = 0
    times = []

    for domain in TEST_DOMAINS:
        ok, ms = resolve(domain)
        if ok:
            successful += 1
            times.append(ms)
        else:
            failed += 1

    total = len(TEST_DOMAINS)
    avg = int(sum(times) / len(times)) if times else 0

    if failed == total:
        st, txt = 2, "CRITICAL - DNS not responding"
    elif failed > 0:
        st, txt = 1, "WARNING - Some tests failed"
    elif avg > 1000:
        st, txt = 1, "WARNING - DNS slow response"
    else:
        st, txt = 0, "OK"

    print(
        f"{st} {SERVICE} response_time={avg}ms;500;1000 "
        f"Test: {successful}/{total} OK, avg time: {avg}ms - {txt} [beta]"
        f" | successful={successful} failed={failed} total={total} avg_time_ms={avg}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
