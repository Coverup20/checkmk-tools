#!/usr/bin/python3
#
# Copyright (C) 2025 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

# CheckMK local check: OpenVPN net-to-net tunnel status
# Pings the gateway of each remote subnet to verify the tunnel is up.
# One CheckMK service per tunnel.

import subprocess
import sys

VERSION = "1.2.0"

# Remote subnet gateways — one entry per VPN tunnel.
# Format: (service_name, gateway_ip)
# Local subnet 192.168.10.0/24 is excluded (it is the monitoring server LAN).
TUNNELS = [
    ("VPN-net-1",  "192.168.1.254"),
    ("VPN-net-20", "192.168.20.1"),
    ("VPN-net-30", "192.168.30.1"),
    ("VPN-net-40", "192.168.40.1"),
    ("VPN-net-50", "192.168.50.1"),
    ("VPN-net-60", "192.168.60.1"),
    ("VPN-net-61", "192.168.61.1"),
]

PING_COUNT = 3
PING_TIMEOUT = 2  # seconds per ping attempt


## Utils

def ping(ip):
    """Ping an IP address. Returns (reachable, rtt_avg_ms_str or None)."""
    try:
        r = subprocess.run(
            ["ping", "-c", str(PING_COUNT), "-W", str(PING_TIMEOUT), "-q", ip],
            capture_output=True,
            text=True,
            timeout=PING_COUNT * PING_TIMEOUT + 3,
        )
        if r.returncode != 0:
            return False, None
        # Parse avg rtt from: rtt min/avg/max/mdev = 1.2/2.3/3.4/0.1 ms
        for line in r.stdout.splitlines():
            if "rtt min/avg/max" in line or "round-trip" in line:
                try:
                    avg = line.split("=")[1].strip().split("/")[1]
                    return True, avg + "ms"
                except:
                    pass
        return True, "ok"
    except:
        return False, None


## Check

def check():
    for name, gateway in TUNNELS:
        ok, rtt = ping(gateway)
        if ok:
            print("0 {} - OK: net to net UP (rtt={})".format(name, rtt))
        else:
            print("2 {} - CRITICAL: net to net DOWN - gateway {} unreachable".format(name, gateway))


check()
