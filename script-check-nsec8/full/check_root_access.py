#!/usr/bin/env python3
"""check_root_access.py - CheckMK root access check.

Detects active root SSH sessions via:
  - /var/run/utmp (USER_PROCESS entries)
  - /proc scan for dropbear/sshd children (excluding main daemons)
Parses /var/log/messages for successful/failed login attempts.
"""

import re
import struct
import sys
from pathlib import Path

VERSION = "1.4.0"
SERVICE = "Root.Access"
LOG_FILE = Path("/var/log/messages")

# Warning thresholds
SESSIONS_WARN = 5
SESSIONS_CRIT = 10
FAILED_WARN = 5
FAILED_CRIT = 10


def get_active_root_sessions():
    """Count active root SSH sessions from utmp + /proc scan."""
    sessions = set()

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
                ut_host = entry[4].split(b'\x00', 1)[0].decode("utf-8", errors="replace")
                ut_line = entry[3].split(b'\x00', 1)[0].decode("utf-8", errors="replace")
                # USER_PROCESS = 7
                if ut_type == 7 and ut_user == "root":
                    # Identify by host or line for uniqueness
                    session_id = ut_host or ut_line or str(i)
                    sessions.add(session_id)
        except Exception:
            pass

    # Method 2: /proc scan for dropbear/sshd children
    # Count only session processes (pts/ssh), skip main daemons
    try:
        for proc in Path("/proc").iterdir():
            if not proc.name.isdigit():
                continue
            try:
                cmdline = (proc / "cmdline").read_bytes()
                is_ssh = b"dropbear" in cmdline or b"sshd" in cmdline
                if not is_ssh:
                    continue
                # Check for child process (has a parent that is also dropbear/sshd)
                # or has an associated pts
                try:
                    status = (proc / "status").read_text()
                    for line in status.splitlines():
                        if line.startswith("Name:"):
                            name = line.split(":", 1)[1].strip()
                            break
                    # Only count if it's a session child (not the main daemon)
                    # Main daemon typically has no pts and PPID=1
                    is_main = False
                    for line in status.splitlines():
                        if line.startswith("PPID:"):
                            ppid = line.split(":", 1)[1].strip()
                            if ppid == "1":
                                try:
                                    parent_cmd = (Path("/proc") / ppid / "cmdline").read_bytes()
                                    if b"dropbear" in parent_cmd or b"sshd" in parent_cmd:
                                        is_main = True
                                except Exception:
                                    pass
                            break
                    if not is_main:
                        sessions.add(f"proc:{proc.name}")
                except Exception:
                    sessions.add(f"proc:{proc.name}")
            except (PermissionError, FileNotFoundError, OSError):
                pass
    except PermissionError:
        pass

    return len(sessions), sessions


def parse_auth_log():
    """Parse auth log via logread (OpenWrt/NethSecurity) or /var/log/messages (Linux).

    Returns:
        Tuple (successful, failed, recent_ips) or (None, None, []) if unavailable
    """
    lines = []

    # Try logread first (OpenWrt/NethSecurity default)
    try:
        import subprocess
        result = subprocess.run(
            ["logread"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            lines = result.stdout.splitlines()
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass

    # Fallback to /var/log/messages (standard Linux)
    if not lines and LOG_FILE.exists():
        try:
            lines = LOG_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            pass

    if not lines:
        return None, None, []
        
    for line in lines[-500:]:
        lower = line.lower()
        if ("accepted password" in lower or "accepted publickey" in lower) and " for root " in lower:
            successful += 1
            m = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", line)
            if m:
                recent_ips.append(m.group(1))
        if ("failed password" in lower or "authentication failure" in lower) and " for root " in lower:
            failed += 1
            
    return successful, failed, recent_ips


def main():
    active_count, sessions = get_active_root_sessions()
    successful, failed, recent_ips = parse_auth_log()

    # Build status
    login_state = "none"
    if failed is not None and failed > 0:
        login_state = "failed"
    elif successful is not None and successful > 0:
        login_state = "passed"

    if failed is not None and failed >= FAILED_CRIT:
        st, txt = 2, f"CRITICAL - login_state={login_state}, Failed attempts: {failed}"
    elif failed is not None and failed >= FAILED_WARN:
        st, txt = 1, f"WARNING - login_state={login_state}, Failed attempts: {failed}"
    elif active_count >= SESSIONS_CRIT:
        st, txt = 2, f"CRITICAL - login_state={login_state}, Too many root sessions: {active_count}"
    elif active_count >= SESSIONS_WARN:
        st, txt = 1, f"WARNING - login_state={login_state}, Active root sessions: {active_count}"
    elif successful is not None and successful > 0:
        st, txt = 0, f"OK - login_state={login_state}, Logins: {successful}, Sessions: {active_count}"
    elif active_count > 0:
        st, txt = 0, f"OK - login_state={login_state}, Sessions: {active_count}"
    else:
        st, txt = 0, f"OK - login_state={login_state}, No recent access"

    # Log availability
    log_note = ""
    if successful is None:
        log_note = " (auth log unavailable)"

    failed_display = failed if failed is not None else 0
    successful_display = successful if successful is not None else 0
    unique_ips = len(set(recent_ips)) if recent_ips else 0

    print(
        f"{st} {SERVICE} sessions={active_count};{SESSIONS_WARN};{SESSIONS_CRIT};0 "
        f"logins={successful_display} "
        f"failed={failed_display};{FAILED_WARN};{FAILED_CRIT};0 "
        f"login_state={login_state} "
        f"- {txt}{log_note}"
        f" | active_sessions={active_count} successful_logins={successful_display} "
        f"failed_logins={failed_display} unique_ips={unique_ips}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
