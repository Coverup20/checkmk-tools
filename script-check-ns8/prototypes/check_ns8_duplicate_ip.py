#!/usr/bin/env python3
"""check_ns8_duplicate_ip.py - CheckMK Local Check: duplicate-IP detection on the node's own address

Detects the case where someone gives another device the same static IP as the
NS8 node (which is also the AD domain controller here): the resulting address
conflict takes the real server off the network (ARP replies start coming from
two different MAC addresses for the same IP, confusing every client).

Runs DIRECTLY ON THE NODE (not through podman exec into any module - this is a
layer-2/ARP concern for the node's own primary interface, not something any
container-scoped tool can see), unlike every other check in this set: `arping
-D` (duplicate address detection mode) sends ARP probes for the node's own IP
and reports if ANY other MAC answers for it. Exit code 1 (per arping(8): "DAD
failed, that address is already in use") + a non-zero "Received N response(s)"
means a real conflict RIGHT NOW. This affects every module on this single-node
cluster, not just the AD, but was asked about specifically in the context of
AD going offline, so it is piggybacked there for visibility; it is really a
whole-node concern.

Interface/IP are auto-detected (default route's interface and its IPv4), not
hardcoded, so this keeps working if the node's NIC name or address changes.

Checks:
- AD.DuplicateIpCheck: CRIT if any other host answers ARP probes for this
  node's own IP (verified against a clean/no-conflict baseline on NS8-RL98;
  a real conflict was not reproduced here on purpose - see PROTOTYPE CAVEAT).

PROTOTYPE CAVEAT: tested only against the healthy, no-conflict case (0
responses, as expected). Deliberately did not simulate a real duplicate here
(would have required assigning the node's own IP to another live host on the
lab network, a disruptive thing to do just to test a check) - the parsing of
a real conflict's output/exit code is based on arping(8)'s documented
behaviour, not observed firsthand.

Piggybacked to NS8-RL98-SAMBA (see memory ns8_rl98 local check reorganisation,
2026-10-12) even though it is really a node-wide concern, because that is the
context this was asked about.

Version: 1.0.0"""

import re
import subprocess
import sys

ARPING_TIMEOUT = 5
PROBE_COUNT = 3


def default_iface_and_ip():
    """(iface, ip) of the interface carrying the default route, or (None, None)."""
    try:
        route = subprocess.run(["ip", "-4", "route", "show", "default"], capture_output=True, text=True, timeout=5)
        m = re.search(r"dev (\S+)", route.stdout)
        if not m:
            return None, None
        iface = m.group(1)
        addr = subprocess.run(["ip", "-4", "-br", "addr", "show", "dev", iface], capture_output=True, text=True, timeout=5)
        m2 = re.search(r"(\d+\.\d+\.\d+\.\d+)/\d+", addr.stdout)
        return iface, (m2.group(1) if m2 else None)
    except (subprocess.SubprocessError, OSError):
        return None, None


def main() -> int:
    iface, ip = default_iface_and_ip()
    if not iface or not ip:
        print("3 AD.DuplicateIpCheck - UNKNOWN: could not determine the node's own default-route interface/IP")
        return 0

    try:
        result = subprocess.run(
            ["arping", "-D", "-c", str(PROBE_COUNT), "-w", str(ARPING_TIMEOUT), "-I", iface, ip],
            capture_output=True, text=True, timeout=ARPING_TIMEOUT + 5,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        print(f"3 AD.DuplicateIpCheck - UNKNOWN: could not run arping: {exc}")
        return 0

    m = re.search(r"Received (\d+) response", result.stdout)
    responses = int(m.group(1)) if m else None

    if result.returncode == 1 or (responses or 0) > 0:
        print(f"2 AD.DuplicateIpCheck - CRITICAL: {ip} ({iface}) answered by another host - "
              f"address conflict, this node's identity on the network is NOT reliable right now "
              f"| arping_output={result.stdout.strip().replace(chr(10), ' ')[:150]}")
    elif result.returncode == 0 and responses == 0:
        print(f"0 AD.DuplicateIpCheck - {ip} ({iface}) is not claimed by any other host")
    else:
        print(f"3 AD.DuplicateIpCheck - UNKNOWN: unexpected arping result (exit {result.returncode}): "
              f"{result.stdout.strip()[:150]} {result.stderr.strip()[:150]}")
    return 0


if __name__ == "__main__":
    print("<<<<NS8-RL98-SAMBA>>>>")
    print("<<<local:sep(0)>>>")
    _rc = main()
    print("<<<<>>>>")
    sys.exit(_rc)
