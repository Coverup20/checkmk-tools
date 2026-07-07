#!/usr/bin/env python3
"""check_firewall_connections.py - CheckMK conntrack check (pyuci beta).

Already Python-native: reads /proc/sys/net/netfilter/ directly.
Beta adds pyuci import check and identifies itself as beta.
"""

import sys
from pathlib import Path

BETA = True
VERSION = "1.0.0b1"
SERVICE = "Firewall.Connections"

try:
    from euci import EUci
except ImportError:
    EUci = None


def main():
    cnt = Path("/proc/sys/net/netfilter/nf_conntrack_count")
    mx = Path("/proc/sys/net/netfilter/nf_conntrack_max")
    if not cnt.exists() or not mx.exists():
        print(f"1 {SERVICE} - Conntrack not available")
        return 0

    current = int(cnt.read_text().strip())
    maxval = int(mx.read_text().strip())
    pct = int(current * 100 / maxval) if maxval > 0 else 0

    if pct >= 90:
        st, txt = 2, "CRITICAL"
    elif pct >= 80:
        st, txt = 1, "WARNING"
    else:
        st, txt = 0, "OK"

    warn = int(maxval * 80 / 100)
    crit = int(maxval * 90 / 100)
    print(
        f"{st} {SERVICE} connections={current};{warn};{crit};0;{maxval} "
        f"Active connections: {current}/{maxval} ({pct}%) - {txt} [beta]"
        f" | current={current} max={maxval} percent={pct}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
