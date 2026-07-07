#!/usr/bin/env python3
"""check_martian_packets.py - CheckMK martian packets check (pyuci beta).

Reads /var/log/messages for martian packet detection.
Removes dmesg subprocess call — uses only log file.
"""

import re
import sys
from pathlib import Path

BETA = True
VERSION = "1.1.3b1"
SERVICE = "Martian.Packets"
WARN = 10
CRIT = 50
LOG_FILE = Path("/var/log/messages")

try:
    from euci import EUci
except ImportError:
    EUci = None


def main():
    count = 0
    sources = []
    destinations = []

    lines = []
    if LOG_FILE.exists():
        lines = LOG_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()[-200:]

    for line in lines:
        lower = line.lower()
        if "martian" not in lower:
            continue
        if "martian source" in lower:
            count += 1
            m = re.search(r"from ((\d{1,3}\.){3}\d{1,3})", line)
            if m:
                sources.append(m.group(1))
        if "martian destination" in lower:
            count += 1
            m = re.search(r"to ((\d{1,3}\.){3}\d{1,3})", line)
            if m:
                destinations.append(m.group(1))

    unique = len(set(sources + destinations))

    if count >= CRIT:
        st, txt = 2, f"CRITICAL - {count} martian packets"
    elif count >= WARN:
        st, txt = 1, f"WARNING - {count} martian packets"
    elif count > 0:
        st, txt = 0, f"OK - {count} martian packets (below threshold)"
    else:
        st, txt = 0, "OK - No martian packets"

    print(
        f"{st} {SERVICE} count={count};{WARN};{CRIT};0 unique_ips={unique} "
        f"- {txt} [beta]"
        f" | martian_count={count} unique_ips={unique}"
    )
    if sources:
        print(f"0 Martian.Sources - IPs: {' '.join(sorted(set(sources))[:5])} [beta]")
    if destinations:
        print(f"0 Martian.Destinations - IPs: {' '.join(sorted(set(destinations))[:5])} [beta]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
