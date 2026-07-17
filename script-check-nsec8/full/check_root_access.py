#!/usr/bin/env python3
"""check_root_access.py - CheckMK root access check.

Detects active root SSH sessions via a /proc scan for dropbear/sshd
processes (excluding main daemons).
Parses auth logs (logread or /var/log/messages) for successful/failed
login attempts.

Note: an earlier revision also tried to parse /var/run/utmp directly with a
hardcoded glibc struct layout. That file does not exist at all on
NethSecurity 8.8 (verified live: no getty/utmp accounting on this minimal
BusyBox userland) and the struct layout was never verified against musl -
removed rather than carry an unverified binary parser for a file that isn't
even present on the target platform.
"""

import re
import sys
from pathlib import Path

VERSION = "1.5.0"
SERVICE = "Root.Access"
LOG_FILE = Path("/var/log/messages")

# Warning thresholds
SESSIONS_WARN = 5
SESSIONS_CRIT = 10
FAILED_WARN = 5
FAILED_CRIT = 10


def get_active_root_sessions():
    """Count active root SSH sessions via a /proc scan."""
    sessions = set()

    # /proc scan for dropbear/sshd children.
    # Count only session processes (pts/ssh), skip main daemons.
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
                    # Only count if it's a session child (not the main daemon).
                    # The main daemon is spawned directly by the init/process
                    # supervisor (PPid=1 - procd on OpenWrt/NethSecurity,
                    # systemd/init elsewhere) - PID 1 itself is ALWAYS the
                    # supervisor, never dropbear/sshd, so no extra check
                    # against PID 1's own cmdline makes sense there.
                    #
                    # NOTE (two compounding bugs fixed here):
                    # 1. /proc/<pid>/status uses "PPid:" (mixed case), not
                    #    "PPID:" - the previous all-caps check never matched
                    #    any line, so is_main was always False.
                    # 2. Even with the case fixed, the old code additionally
                    #    required PID 1's own cmdline to contain
                    #    dropbear/sshd before treating PPid==1 as "main
                    #    daemon" - impossible on any real system, since PID 1
                    #    is always the init/supervisor, not the daemon.
                    is_main = False
                    for line in status.splitlines():
                        if line.startswith("PPid:"):
                            ppid = line.split(":", 1)[1].strip()
                            is_main = ppid == "1"
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

    successful = 0
    failed = 0
    recent_ips = []

    root_markers = (" for root ", "for 'root'", 'for "root"', "user=root")
    success_markers = (
        "accepted password",
        "accepted publickey",
        "password auth succeeded",
        "pubkey auth succeeded",
    )
    failed_markers = (
        "failed password",
        "bad password attempt",
        "authentication failure",
    )

    for line in lines[-500:]:
        lower = line.lower()
        is_root = any(marker in lower for marker in root_markers)
        if any(marker in lower for marker in success_markers) and is_root:
            successful += 1
            m = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", line)
            if m:
                recent_ips.append(m.group(1))
        if any(marker in lower for marker in failed_markers) and is_root:
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
