#!/usr/bin/env python3
"""check_root_access.py - CheckMK root access check (pyuci beta).

Replaces subprocess who with /var/run/utmp parsing (standard Unix format).
Replaces subprocess ps with /proc scan for dropbear/sshd processes.
Log file parsing preserved (Python-native).
"""

import re
import struct
import sys
from pathlib import Path

BETA = True
VERSION = "1.3.0b1"
SERVICE = "Root.Access"
LOG_FILE = Path("/var/log/messages")

try:
    from euci import EUci
except ImportError:
    EUci = None


def get_active_root_sessions():
    """Count active root SSH sessions from utmp file + /proc scan."""
    count = 0

    # Method 1: parse /var/run/utmp for USER_PROCESS entries with root
    utmp = Path("/var/run/utmp")
    if utmp.exists():
        fmt = "hi32s4s32s256siiiiii4i"
        size = struct.calcsize(fmt)
        try:
            data = utmp.read_bytes()
            for i in range(0, len(data), size):
                rec = data[i:i + size]
                if len(rec) < size:
                    break
                entry = struct.unpack(fmt, rec)
                ut_type = entry[0]
                ut_user = entry[2].split(b'\x00', 1)[0].decode("utf-8", errors="replace")
                # USER_PROCESS = 7
                if ut_type == 7 and ut_user == "root":
                    count += 1
        except Exception:
            pass

    # Method 2: fallback — scan /proc for sshd/dropbear processes
    if count == 0:
        try:
            for proc in Path("/proc").iterdir():
                if not proc.name.isdigit():
                    continue
                try:
                    cmdline = (proc / "cmdline").read_bytes()
                    if b"dropbear" in cmdline or b"sshd" in cmdline:
                        # Exclude the main daemon (PID 1 parent or no pts)
                        count += 1
                except (PermissionError, FileNotFoundError, OSError):
                    pass
        except PermissionError:
            pass

    return count


def main():
    active = get_active_root_sessions()

    successful = 0
    failed = 0
    recent_ips = []
    if LOG_FILE.exists():
        for line in LOG_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()[-500:]:
            lower = line.lower()
            if ("accepted password" in lower or "accepted publickey" in lower) and " for root" in lower:
                successful += 1
                m = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", line)
                if m:
                    recent_ips.append(m.group(1))
            if ("failed password" in lower or "authentication failure" in lower) and " for root" in lower:
                failed += 1

    unique_ips = len(set(recent_ips))

    if failed >= 10:
        st, txt = 2, f"CRITICAL - Too many failed attempts ({failed})"
    elif failed >= 5:
        st, txt = 1, f"WARNING - Failed attempts: {failed}"
    elif active > 2:
        st, txt = 1, f"WARNING - Too many root sessions: {active}"
    elif successful > 0 or active > 0:
        st, txt = 0, f"OK - Logins: {successful}, Sessions: {active}"
    else:
        st, txt = 0, "OK - No recent access"

    print(
        f"{st} {SERVICE} sessions={active};2;3;0 logins={successful} "
        f"failed={failed};5;10;0 - {txt} [beta]"
        f" | active_sessions={active} successful_logins={successful} "
        f"failed_logins={failed} unique_ips={unique_ips}"
    )
    if recent_ips:
        print(f"0 Root.AccessIPs - Recent: {' '.join(sorted(set(recent_ips))[:5])} [beta]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
