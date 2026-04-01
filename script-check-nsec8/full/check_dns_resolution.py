#!/usr/bin/env python3
"""check_dns_resolution.py - CheckMK local check DNS resolution (Python puro)."""

import subprocess
import sys
import time

SERVICE = "DNS.Resolution"
TEST_DOMAINS = ["google.com", "cloudflare.com", "dns.google"]


def main() -> int:
    successful = 0
    failed = 0
    response_times = []

    for domain in TEST_DOMAINS:
        start = time.perf_counter()
        result = subprocess.run(
            ["nslookup", domain, "127.0.0.1"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
            check=False,
        )
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        if result.returncode == 0 and "Address" in (result.stdout or ""):
            successful += 1
            response_times.append(elapsed_ms)
        else:
            failed += 1

    total = len(TEST_DOMAINS)
    avg_time = int(sum(response_times) / len(response_times)) if response_times else 0

    if failed == total:
        status, status_text = 2, "CRITICAL - DNS non risponde"
    elif failed > 0:
        status, status_text = 1, "WARNING - Alcuni test falliti"
    elif avg_time > 1000:
        status, status_text = 1, "WARNING - DNS lento"
    else:
        status, status_text = 0, "OK"

    print(
        f"{status} {SERVICE} response_time={avg_time}ms;500;1000 "
        f"Test: {successful}/{total} OK, tempo medio: {avg_time}ms - {status_text} "
        f"| successful={successful} failed={failed} total={total} avg_time_ms={avg_time}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
