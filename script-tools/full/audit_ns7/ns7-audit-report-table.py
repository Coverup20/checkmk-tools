#!/usr/bin/env python3
"""ns7-audit-report-table.py - NethServer 7 environment audit report

NethServer 7 counterpart of ns8-audit-report-table-v2.py.

Report sections:
  1) Active Directory users (local Samba DC running in the nsdc container)
  2) AD user account status (creation date, enabled/disabled)
  3) AD user password expiration dates (domain password policy aware)
  4) AD groups with members
  5) Shared folder (ibay) permissions with POSIX ACLs
  6) WebTop 5 mail shares (PostgreSQL 9.2+ or MySQL, skipped when absent)

The Samba DC of a NethServer 7 machine runs inside the systemd-nspawn
container "nsdc", so every samba-tool call is executed inside it via
nsenter against the container init PID:

    nsenter -t <leader> -m -u -i -p -- env PYTHONIOENCODING=utf-8 samba-tool ...

No pty is allocated, so hundreds of calls do not exhaust the container
PTYs (systemd-run -t does).

Output: directory /tmp/ns7-audit-YYYYMMDD-HHMMSS/
        (00_report.html and 00_report.pdf, produced by a built-in
        standard-library PDF writer: no external tool or service needed)

Usage:
  ns7-audit-report-table.py [--output-dir DIR] [--pdf|--no-pdf] [--self-test] [--version]

Version: 1.1.8
"""

import getpass
import html
import json
import os
import re
import shlex
import smtplib
import socket
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Dict, List, Optional, Tuple

VERSION = "1.1.8"
PDF_FOOTER = ""

# Domain maximum password age used only when the domain policy cannot be read.
DEFAULT_MAX_PWD_AGE_DAYS = 42

# NethServer 7 always runs its Samba DC in this systemd-nspawn machine.
NSDC_MACHINE = "nsdc"

# UAC flag: password never expires.
UAC_DONT_EXPIRE_PASSWORD = 0x10000
# UAC flag: account is disabled.
UAC_ACCOUNTDISABLE = 0x0002

SMB_CONF = Path("/etc/samba/smb.conf")
IBAY_ROOT = Path("/var/lib/nethserver/ibay")
MYSQL_SECRET = Path("/var/lib/nethserver/secrets/mysql")

# System groups that are not useful in an environment audit.
EXCLUDE_GROUPS = [
    "Denied RODC Password Replication Group",
    "Allowed RODC Password Replication Group",
    "DnsUpdateProxy",
    "Enterprise Read-only Domain Controllers",
    "Enterprise Read-Only Domain Controllers",
    "Network Configuration Operators",
    "Pre-Windows 2000 Compatible Access",
    "Incoming Forest Trust Builders",
    "Terminal Server License Servers",
    "Cryptographic Operators",
    "Remote Desktop Users",
    "RAS and IAS Servers",
    "Event Log Readers",
    "Guests",
    "Certificate Service DCOM Access",
    "Read-only Domain Controllers",
    "Windows Authorization Access Group",
    "Performance Monitor Users",
]

# ANSI colors, enabled only when stdout is a terminal.
try:
    _USE_COLORS = sys.stdout.isatty()
except (AttributeError, ValueError):
    _USE_COLORS = False

RED = "\033[0;31m" if _USE_COLORS else ""
GREEN = "\033[0;32m" if _USE_COLORS else ""
YELLOW = "\033[1;33m" if _USE_COLORS else ""
BLUE = "\033[0;34m" if _USE_COLORS else ""
NC = "\033[0m" if _USE_COLORS else ""

# Global counters.
GLOBAL_USER_COUNT = 0
GLOBAL_DISABLED_COUNT = 0
GLOBAL_GROUP_COUNT = 0
GLOBAL_COMPUTER_COUNT = 0
GLOBAL_SHARE_COUNT = 0
GLOBAL_WEBTOP_COUNT = 0

# Well-known SIDs that samba-tool may return as group members.
WELL_KNOWN_SIDS = {
    "S-1-1-0": "Everyone",
    "S-1-5-2": "Network",
    "S-1-5-4": "INTERACTIVE",
    "S-1-5-11": "Authenticated Users",
    "S-1-5-17": "IUSR",
    "S-1-5-18": "SYSTEM",
    "S-1-5-32-544": "Administrators",
    "S-1-5-32-545": "Users",
    "S-1-5-32-546": "Guests",
}

# Cache for getent lookups.
NAME_CACHE: Dict[str, str] = {}

# Collected report blocks, rendered to HTML/PDF at the end.
# Each block: {"title": str, "headers": [str], "rows": [[str]]}
REPORT_BLOCKS: List[Dict[str, object]] = []


# ---------------------------------------------------------------------------
# Logging and command helpers
# ---------------------------------------------------------------------------

def log_info(msg: str) -> None:
    """Print an info message."""
    print("%s[INFO]%s %s" % (BLUE, NC, msg))


def log_success(msg: str) -> None:
    """Print a success message."""
    print("%s[OK]%s %s" % (GREEN, NC, msg))


def log_warn(msg: str) -> None:
    """Print a warning message."""
    print("%s[WARN]%s %s" % (YELLOW, NC, msg))


def log_error(msg: str) -> None:
    """Print an error message."""
    print("%s[ERROR]%s %s" % (RED, NC, msg))


def run_command(cmd: List[str], timeout: int = 60) -> Tuple[int, str, str]:
    """Execute a command and return (exit_code, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=False,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )
        return (
            result.returncode,
            result.stdout.decode("utf-8", "replace"),
            result.stderr.decode("utf-8", "replace"),
        )
    except subprocess.TimeoutExpired:
        return 124, "", "Timeout"
    except FileNotFoundError:
        return 127, "", "Command not found: %s" % cmd[0]
    except Exception as exc:  # noqa: BLE001 - report any failure to the caller
        return 1, "", str(exc)


TOOL_NOISE_RE = re.compile(
    r"^(Traceback \(most recent call last\):|  File \"|File \"|"
    r"return self\.run\(|self\.out\.write\(|"
    r"[A-Za-z_]+Error: [^ ])"
)


def filter_tool_noise(text: str) -> str:
    """Drop samba-tool Python traceback lines from command output."""
    kept = [line for line in text.splitlines() if not TOOL_NOISE_RE.match(line)]
    return "\n".join(kept)


_NSDC_LEADER = None


def nsdc_leader() -> str:
    """Return the PID of the container init, for nsenter."""
    global _NSDC_LEADER
    if _NSDC_LEADER:
        return _NSDC_LEADER
    rc, out, _ = run_command(["machinectl", "show", NSDC_MACHINE, "-p", "Leader"], timeout=10)
    if rc == 0:
        for line in out.splitlines():
            if line.startswith("Leader="):
                pid = line.split("=", 1)[1].strip()
                if pid and pid != "0":
                    _NSDC_LEADER = pid
    return _NSDC_LEADER or ""


def run_nsdc(args: List[str], timeout: int = 60) -> Tuple[int, str, str]:
    """Run a command inside the nsdc container.

    Uses nsenter against the container init: systemd-run -t allocates a pty
    for every call and leaks them, so a full audit (hundreds of samba-tool
    calls) ends with "Failed to get machine PTY". nsenter needs no pty.
    PYTHONIOENCODING=utf-8 keeps samba-tool from dying with UnicodeEncodeError
    on names with non-ASCII characters.
    """
    leader = nsdc_leader()
    if leader:
        cmd = [
            "nsenter", "-t", leader, "-m", "-u", "-i", "-p", "--",
            "/usr/bin/env", "PYTHONIOENCODING=utf-8",
        ] + args
    else:
        cmd = [
            "systemd-run", "-M", NSDC_MACHINE, "-t",
            "/usr/bin/env", "PYTHONIOENCODING=utf-8",
        ] + args
    rc, out, err = run_command(cmd, timeout=timeout)

    noise = ("Running as unit", "Press ^]", "disconnect TTY")
    clean_lines = [l for l in err.splitlines() if not any(n in l for n in noise)]
    return rc, filter_tool_noise(out), "\n".join(clean_lines).strip()


def getent_name(kind: str, identifier: str) -> Optional[str]:
    """Resolve a numeric uid/gid to a name with getent, with caching."""
    key = "%s:%s" % (kind, identifier)
    if key in NAME_CACHE:
        return NAME_CACHE[key] or None
    rc, out, _ = run_command(["getent", kind, identifier], timeout=10)
    name = None
    if rc == 0 and out.strip():
        name = out.strip().split(":")[0]
    NAME_CACHE[key] = name or ""
    return name


# ---------------------------------------------------------------------------
# Pure parsers (testable with --self-test)
# ---------------------------------------------------------------------------

def parse_ldap_timestamp(value: str) -> Optional[datetime]:
    """Parse an AD generalized time value such as 20261118165219.0Z."""
    value = value.strip()
    for fmt in ("%Y%m%d%H%M%S.%fZ", "%Y%m%d%H%M%SZ"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def parse_filetime(value: str) -> Optional[datetime]:
    """Convert an AD FILETIME (100 ns since 1601-01-01 UTC) to datetime."""
    try:
        raw = int(value)
    except (TypeError, ValueError):
        return None
    if raw <= 0:
        return None
    try:
        return datetime(1601, 1, 1) + timedelta(microseconds=raw // 10)
    except (OverflowError, ValueError):
        return None


def parse_password_settings(text: str) -> Dict[str, object]:
    """Parse `samba-tool domain passwordsettings show` output."""
    policy: Dict[str, object] = {
        "max_age_days": DEFAULT_MAX_PWD_AGE_DAYS,
        "never_expires": False,
        "found": False,
    }
    for line in text.splitlines():
        match = re.match(r"\s*Maximum password age \(days\):\s*(\d+)", line)
        if match:
            days = int(match.group(1))
            policy["max_age_days"] = days
            policy["never_expires"] = days == 0
            policy["found"] = True
            break
    return policy


def parse_smb_conf(text: str) -> List[Tuple[str, str]]:
    """Return [(share_name, path)] for file shares declared in smb.conf."""
    shares: List[Tuple[str, str]] = []
    current: Optional[str] = None
    current_path: Optional[str] = None

    def flush() -> None:
        if current and current_path:
            shares.append((current, current_path))

    for raw in text.splitlines():
        line = raw.strip()
        section = re.match(r"^\[([^\]]+)\]", line)
        if section:
            flush()
            name = section.group(1).strip()
            if name.lower() in ("global", "homes", "printers", "print$"):
                current, current_path = None, None
            else:
                current, current_path = name, None
            continue
        if current and "=" in line and not line.startswith(("#", ";")):
            key, value = line.split("=", 1)
            if key.strip().lower() == "path":
                current_path = value.strip()
    flush()
    return shares


def unescape_acl_name(name: str) -> str:
    """Decode octal escapes used by getfacl (e.g. \\040 for a space)."""
    return re.sub(r"\\([0-3][0-7]{2})", lambda m: chr(int(m.group(1), 8)), name)


def parse_getfacl(text: str) -> List[Tuple[str, str]]:
    """Return [(entity, permission)] from getfacl output.

    Permission is RW when the write bit is set, RO otherwise.
    Default (inherited) entries, mask and other metadata are skipped.
    """
    rows: List[Tuple[str, str]] = []
    owner: Optional[str] = None
    group: Optional[str] = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            if line.startswith("# owner:"):
                owner = unescape_acl_name(line.split(":", 1)[1].strip())
            elif line.startswith("# group:"):
                group = unescape_acl_name(line.split(":", 1)[1].strip())
            continue
        if line.startswith("default:"):
            continue
        if ":" not in line:
            continue

        parts = line.split(":")
        kind = parts[0]
        if kind == "user" and len(parts) >= 3:
            perms = parts[2]
            if parts[1]:
                entity = parts[1]
                if entity.isdigit():
                    entity = getent_name("passwd", entity) or entity
            else:
                entity = "owner:%s" % (owner or "unknown")
            rows.append((entity, "RW" if "w" in perms else "RO"))
        elif kind == "group" and len(parts) >= 3:
            perms = parts[2]
            if parts[1]:
                entity = parts[1]
                if entity.isdigit():
                    entity = getent_name("group", entity) or entity
                entity = "@%s" % entity
            else:
                entity = "@%s" % (group or "unknown")
            rows.append((entity, "RW" if "w" in perms else "RO"))
        elif kind == "other":
            rows.append(("Everyone", "RW" if "w" in parts[-1] else "RO"))
        # mask:: and any unexpected entry are ignored on purpose.
    return rows


def parse_list_users_json(text: str) -> Dict[str, Dict[str, object]]:
    """Parse /usr/libexec/nethserver/list-users JSON, tolerating errors."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------

def check_prerequisites() -> Dict[str, object]:
    """Detect NethServer release, accounts provider, nsdc and WebTop."""
    info: Dict[str, object] = {
        "release": "",
        "provider": "",
        "dc_ok": False,
        "webtop": "",
    }

    log_info("Checking prerequisites...")

    rc, out, _ = run_command(["cat", "/etc/nethserver-release"], timeout=10)
    if rc == 0:
        info["release"] = out.strip().splitlines()[0] if out.strip() else ""
    if "release 7" not in str(info["release"]).lower():
        log_warn("This host does not look like a NethServer 7 machine")

    rc, out, _ = run_command(
        ["db", "configuration", "getprop", "sssd", "Provider"], timeout=15
    )
    if rc == 0:
        info["provider"] = out.strip()
    log_info("Accounts provider: %s" % (info["provider"] or "unknown"))

    rc, _, _ = run_command(["systemctl", "is-active", "--quiet", "nsdc"], timeout=10)
    info["dc_ok"] = rc == 0
    if info["dc_ok"]:
        log_success("nsdc container is running (local Samba DC)")
    else:
        log_error("nsdc container is not running: the local AD cannot be queried")

    info["webtop"] = detect_webtop()

    return info


def run_preflight() -> int:
    """Verify that this host can run the audit; return 0 when ready."""
    failures = 0

    if sys.version_info < (3, 6):
        log_error("Python 3.6+ is required (found %s)" % sys.version.split()[0])
        failures += 1

    info = check_prerequisites()

    if not info["dc_ok"]:
        log_error("nsdc container is not running: only a local Samba AD is supported")
        failures += 1
    else:
        rc, out, err = run_nsdc(["/usr/bin/samba-tool", "user", "list"], timeout=30)
        if rc != 0:
            log_error("samba-tool inside nsdc failed: %s" % (err or "unknown error"))
            failures += 1
        else:
            count = len([line for line in out.splitlines() if line.strip()])
            log_success("samba-tool works inside nsdc (%d users)" % count)

    if str(info.get("provider", "")) != "ad":
        log_warn("accounts provider is '%s' (expected 'ad')" % (info.get("provider") or "unknown"))

    for tool in ("getfacl", "runuser"):
        rc, _, _ = run_command(["which", tool], timeout=10)
        if rc != 0:
            log_error("required tool missing: %s" % tool)
            failures += 1

    if SMB_CONF.exists():
        log_success("smb.conf found: %s" % SMB_CONF)
    else:
        log_warn("smb.conf not found: share section will be empty")

    engine = str(info.get("webtop") or "")
    if engine:
        log_success("WebTop 5 usable (%s)" % engine)
    else:
        log_warn("WebTop 5 not detected: mail share section will be skipped")

    if failures:
        log_error("Preflight failed: %d blocking issue(s)" % failures)
        return 1

    log_success("Preflight OK: this host can run the audit")
    return 0


def mysql_query(sql: str, database: Optional[str] = None, timeout: int = 20) -> Tuple[int, str, str]:
    """Run a MySQL query as root, reading the root password from the secrets file."""
    cmd = ["mysql", "-N", "-B", "-u", "root"]
    if database:
        cmd += ["-D", database]
    cmd += ["-e", sql]

    env = os.environ.copy()
    try:
        if MYSQL_SECRET.exists():
            env["MYSQL_PWD"] = MYSQL_SECRET.read_text().strip()
    except OSError:
        pass

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=False,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            env=env,
        )
        return (
            result.returncode,
            result.stdout.decode("utf-8", "replace"),
            result.stderr.decode("utf-8", "replace"),
        )
    except subprocess.TimeoutExpired:
        return 124, "", "Timeout"
    except FileNotFoundError:
        return 127, "", "mysql client not found"
    except Exception as exc:  # noqa: BLE001
        return 1, "", str(exc)


def psql_query(sql: str, database: str = "webtop5", timeout: int = 20) -> Tuple[int, str, str]:
    """Run a PostgreSQL query as the postgres user (peer authentication)."""
    cmd = ["runuser", "-u", "postgres", "--", "psql", "-t", "-A", "-F", "|", "-d", database, "-c", sql]
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=False,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )
        return (
            result.returncode,
            result.stdout.decode("utf-8", "replace"),
            result.stderr.decode("utf-8", "replace"),
        )
    except FileNotFoundError:
        # Fallback for older util-linux without runuser.
        shell_cmd = "psql -t -A -F '|' -d %s -c %s" % (shlex.quote(database), shlex.quote(sql))
        rc, out, err = run_command(["su", "-", "postgres", "-c", shell_cmd], timeout=timeout)
        return rc, out, err
    except subprocess.TimeoutExpired:
        return 124, "", "Timeout"
    except Exception as exc:  # noqa: BLE001
        return 1, "", str(exc)


def detect_webtop() -> str:
    """Return the WebTop database engine ("postgres", "mysql") or an empty string."""
    rc, _, _ = run_command(["which", "psql"], timeout=10)
    if rc == 0:
        rc, out, _ = psql_query("SELECT 1", timeout=15)
        if rc == 0 and out.strip():
            log_success("WebTop 5 detected (PostgreSQL)")
            return "postgres"

    rc, _, _ = run_command(["which", "mysql"], timeout=10)
    if rc == 0:
        rc, out, _ = mysql_query("SHOW DATABASES LIKE 'webtop5'", timeout=15)
        if rc == 0 and "webtop5" in out:
            log_success("WebTop 5 detected (MySQL)")
            return "mysql"

    return ""


# ---------------------------------------------------------------------------
# Section 1: users
# ---------------------------------------------------------------------------

def collect_ad_users(output_dir: Path) -> int:
    """Collect AD usernames into 01_users/users.txt."""
    log_info("Collecting AD users...")

    users_dir = output_dir / "01_users"
    users_dir.mkdir(parents=True, exist_ok=True)

    rc, out, err = run_nsdc(["/usr/bin/samba-tool", "user", "list"])
    if rc != 0:
        log_error("Failed to collect users: %s" % (err or "unknown error"))
        return 0

    users = [line.strip() for line in out.splitlines() if line.strip()]
    (users_dir / "users.txt").write_text("\n".join(users) + "\n", encoding="utf-8")
    log_success("AD users collected: %d" % len(users))
    return len(users)


def read_user_list(output_dir: Path) -> List[str]:
    """Read the user list produced by collect_ad_users."""
    users_file = output_dir / "01_users" / "users.txt"
    if not users_file.exists():
        return []
    return [line.strip() for line in users_file.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Section 2: account status
# ---------------------------------------------------------------------------

def collect_user_status_table(output_dir: Path) -> int:
    """Collect creation date and enabled/disabled status for every user."""
    log_info("Collecting AD account status...")

    users = read_user_list(output_dir)
    if not users:
        log_error("User list not found, run section 1 first")
        return 0

    rows: List[Tuple[str, str, str, str]] = []
    disabled_count = 0

    for index, username in enumerate(users, 1):
        if index % 10 == 0:
            log_info("  Progress: %d/%d users" % (index, len(users)))

        rc, out, _ = run_nsdc(["/usr/bin/samba-tool", "user", "show", username], timeout=20)
        if rc != 0:
            rows.append((username, "N/A", "Query error", ""))
            continue

        created = "N/A"
        match = re.search(r"^whenCreated:\s+(.+)$", out, re.MULTILINE)
        if match:
            parsed = parse_ldap_timestamp(match.group(1))
            if parsed:
                created = parsed.strftime("%Y-%m-%d")

        disabled = False
        match = re.search(r"^userAccountControl:\s+(\d+)", out, re.MULTILINE)
        if match:
            disabled = bool(int(match.group(1)) & UAC_ACCOUNTDISABLE)

        changed = ""
        match = re.search(r"^whenChanged:\s+(.+)$", out, re.MULTILINE)
        if match:
            parsed = parse_ldap_timestamp(match.group(1))
            if parsed:
                changed = parsed.strftime("%Y-%m-%d")

        if disabled:
            disabled_count += 1
            rows.append((username, created, changed or "N/A", "Disabled"))
        else:
            rows.append((username, created, "", "Active"))

    print()
    print("=" * 120)
    print("  AD USER ACCOUNT STATUS")
    print("=" * 120)
    print()
    print("%-25s %-15s %-18s %-15s" % ("USER", "CREATED", "DISABLED ON", "STATUS"))
    print("%-25s %-15s %-18s %-15s" % ("-" * 25, "-" * 15, "-" * 18, "-" * 15))
    for username, created, disabled_on, status in rows:
        if status == "Disabled":
            shown = RED + status + NC
        elif status == "Active":
            shown = GREEN + status + NC
        else:
            shown = status
        print("%-25s %-15s %-18s %-15s" % (username, created, disabled_on, shown))
    print()
    print("=" * 120)
    log_success("Account status done (%d users, %d disabled)" % (len(rows), disabled_count))

    REPORT_BLOCKS.append({
        "title": "AD User Account Status",
        "headers": ["User", "Created", "Disabled On", "Status"],
        "rows": [[row[0], row[1], row[2], row[3]] for row in rows],
    })

    md_file = output_dir / "06_user_status.md"
    with open(md_file, "w", encoding="utf-8") as handle:
        handle.write("# AD User Account Status\n\n")
        handle.write("Report generated: %s\n\n" % datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
        handle.write("## Summary\n\n")
        handle.write("- **Total users:** %d\n" % len(rows))
        handle.write("- **Active:** %d\n" % (len(rows) - disabled_count))
        handle.write("- **Disabled:** %d\n\n" % disabled_count)
        handle.write("---\n\n")
        handle.write("## Account Status Table\n\n")
        handle.write("| User | Created | Disabled On | Status |\n")
        handle.write("|------|---------|-------------|--------|\n")
        for username, created, disabled_on, status in rows:
            handle.write("| %s | %s | %s | %s |\n" % (username, created, disabled_on, status))
        handle.write("\n")

    global GLOBAL_DISABLED_COUNT
    GLOBAL_DISABLED_COUNT = disabled_count
    return disabled_count


# ---------------------------------------------------------------------------
# Section 3: password expiration
# ---------------------------------------------------------------------------

def get_password_policy() -> Dict[str, object]:
    """Read the domain password policy, falling back to the default."""
    rc, out, _ = run_nsdc(["/usr/bin/samba-tool", "domain", "passwordsettings", "show"], timeout=30)
    if rc != 0:
        log_warn("Cannot read domain password policy, using default %d days" % DEFAULT_MAX_PWD_AGE_DAYS)
        return parse_password_settings("")
    return parse_password_settings(out)


def password_status(last_change: datetime, max_age: int, now: datetime) -> Tuple[str, str, str, int]:
    """Return (last change, expiry, status, days left) for a password."""
    expires = last_change + timedelta(days=max_age)
    days_left = (expires.date() - now.date()).days
    if days_left < 0:
        status = "Expired"
    elif days_left <= 7:
        status = "Expiring soon"
    else:
        status = "Valid"
    return (
        last_change.strftime("%Y-%m-%d"),
        expires.strftime("%Y-%m-%d"),
        status,
        days_left,
    )


def collect_password_expiry_table(output_dir: Path, policy: Dict[str, object]) -> None:
    """Collect password expiry for every user according to the domain policy."""
    log_info("Collecting password expiration dates...")

    users = read_user_list(output_dir)
    if not users:
        log_error("User list not found, run section 1 first")
        return

    max_age_raw = policy.get("max_age_days")
    max_age = max_age_raw if isinstance(max_age_raw, int) else DEFAULT_MAX_PWD_AGE_DAYS
    never_expires_domain = bool(policy.get("never_expires", False))

    password_dir = output_dir / "02_password"
    password_dir.mkdir(parents=True, exist_ok=True)

    rows: List[Tuple[str, str, str, str]] = []
    expired = 0
    expiring = 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    for index, username in enumerate(users, 1):
        if index % 10 == 0:
            log_info("  Progress: %d/%d users" % (index, len(users)))

        rc, out, _ = run_nsdc(["/usr/bin/samba-tool", "user", "show", username], timeout=20)
        if rc != 0:
            rows.append((username, "N/A", "N/A", "N/A"))
            continue

        uac = 0
        match = re.search(r"^userAccountControl:\s+(\d+)", out, re.MULTILINE)
        if match:
            uac = int(match.group(1))

        if never_expires_domain or (uac & UAC_DONT_EXPIRE_PASSWORD):
            rows.append((username, "N/A", "Never", "Never expires"))
            continue

        match = re.search(r"^pwdLastSet:\s+(-?\d+)", out, re.MULTILINE)
        if not match or int(match.group(1)) <= 0:
            rows.append((username, "Never changed", "N/A", "Must change at logon"))
            continue

        last_change = parse_filetime(match.group(1))
        if not last_change:
            rows.append((username, "N/A", "N/A", "Parse error"))
            continue

        last_date, expires_str, status, days_left = password_status(last_change, max_age, now)
        if status == "Expired":
            expired += 1
        elif status == "Expiring soon":
            expiring += 1

        rows.append((
            username,
            last_date,
            expires_str,
            "%s (%d days)" % (status, days_left),
        ))

    print()
    print("=" * 120)
    print("  AD USER PASSWORD EXPIRATION")
    print("=" * 120)
    print()
    if never_expires_domain:
        print("Domain policy: passwords never expire")
        print()
    print("%-25s %-15s %-15s %-25s" % ("USER", "LAST CHANGE", "EXPIRES", "STATUS"))
    print("%-25s %-15s %-15s %-25s" % ("-" * 25, "-" * 15, "-" * 15, "-" * 25))
    for username, last_change, expires, status in rows:
        shown = status
        if status.startswith("Expired"):
            shown = RED + status + NC
        elif status.startswith("Expiring"):
            shown = YELLOW + status + NC
        elif status == "Valid":
            shown = GREEN + status + NC
        print("%-25s %-15s %-15s %-25s" % (username, last_change, expires, shown))
    print()
    print("=" * 120)
    log_success("Password expiration done (%d users, %d expired, %d expiring)" % (len(rows), expired, expiring))

    REPORT_BLOCKS.append({
        "title": "AD User Password Expiration",
        "headers": ["User", "Last Change", "Expires", "Status"],
        "rows": [[row[0], row[1], row[2], row[3]] for row in rows],
    })

    md_file = output_dir / "01_password_expiry.md"
    with open(md_file, "w", encoding="utf-8") as handle:
        handle.write("# Password Expiration Report\n\n")
        handle.write("Report generated: %s\n\n" % datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
        handle.write("## Summary\n\n")
        handle.write("- **Total users:** %d\n" % len(rows))
        handle.write("- **Expired passwords:** %d\n" % expired)
        handle.write("- **Expiring within 7 days:** %d\n" % expiring)
        if never_expires_domain:
            handle.write("- **Domain policy:** passwords never expire\n")
        handle.write("\n")
        handle.write("---\n\n")
        handle.write("## Password Expiration Table\n\n")
        handle.write("| User | Last Change | Expires | Status |\n")
        handle.write("|------|-------------|---------|--------|\n")
        for username, last_change, expires, status in rows:
            handle.write("| %s | %s | %s | %s |\n" % (username, last_change, expires, status))
        handle.write("\n")


# ---------------------------------------------------------------------------
# Section 4: groups and computers
# ---------------------------------------------------------------------------

def collect_ad_groups_table(output_dir: Path) -> int:
    """Collect AD groups with their members."""
    log_info("Collecting AD groups...")

    rc, out, err = run_nsdc(["/usr/bin/samba-tool", "group", "list"])
    if rc != 0:
        log_error("Failed to collect groups: %s" % (err or "unknown error"))
        return 0

    all_groups = [line.strip() for line in out.splitlines() if line.strip()]
    groups = [g for g in all_groups if g not in EXCLUDE_GROUPS]

    group_rows: List[Tuple[str, List[str], List[str]]] = []
    for index, group in enumerate(groups, 1):
        if index % 10 == 0:
            log_info("  Progress: %d/%d groups" % (index, len(groups)))

        rc, members_out, _ = run_nsdc(
            ["/usr/bin/samba-tool", "group", "listmembers", group], timeout=20
        )
        members: List[str] = []
        computers: List[str] = []
        if any(line.startswith("ERROR") for line in members_out.splitlines()):
            log_warn("Cannot list members of %s" % group)
            members.append("(unavailable)")
        elif rc == 0 and members_out.strip():
            for member in members_out.splitlines():
                member = member.strip()
                if not member or "codec" in member:
                    continue
                if member.endswith("$"):
                    computers.append(member)
                else:
                    members.append(WELL_KNOWN_SIDS.get(member, member))
        group_rows.append((group, members, computers))

    print()
    print("=" * 90)
    print("  ACTIVE DIRECTORY GROUPS")
    print("=" * 90)
    print()
    print("%-40s %-40s" % ("GROUP", "MEMBER"))
    print("%-40s %-40s" % ("-" * 40, "-" * 40))
    for group, members, computers in group_rows:
        if members:
            for member in members:
                print("%-40s %-40s" % (group[:39], member[:39]))
        elif not computers:
            print("%-40s %-40s" % (group[:39], "(no members)"))
    print()
    print("=" * 90)

    # Machine accounts appear as members ending with "$".
    computer_pairs = [(group, computer) for group, _, computers in group_rows for computer in computers]
    if computer_pairs:
        print()
        print("=" * 90)
        print("  DOMAIN COMPUTERS (FROM GROUP MEMBERSHIP)")
        print("=" * 90)
        print()
        print("Total computer accounts: %d" % len(computer_pairs))
        print()
        print("%-40s %-40s" % ("GROUP", "COMPUTER"))
        print("%-40s %-40s" % ("-" * 40, "-" * 40))
        for group, computer in sorted(computer_pairs):
            print("%-40s %-40s" % (group[:39], computer[:39]))
        print()
        print("=" * 90)

    log_success("Groups collected: %d" % len(groups))

    group_table_rows: List[List[str]] = []
    for group, members, computers in group_rows:
        if members:
            for member in members:
                group_table_rows.append([group, member])
        elif computers:
            for computer in computers:
                group_table_rows.append([group, computer])
        else:
            group_table_rows.append([group, "(no members)"])
    REPORT_BLOCKS.append({
        "title": "Active Directory Groups",
        "headers": ["Group", "Member"],
        "rows": group_table_rows,
    })

    md_file = output_dir / "02_ad_groups.md"
    with open(md_file, "w", encoding="utf-8") as handle:
        handle.write("# Active Directory Groups\n\n")
        handle.write("Report generated: %s\n\n" % datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
        handle.write("**Total groups:** %d (system groups excluded: %d)\n\n" % (len(groups), len(all_groups) - len(groups)))
        handle.write("---\n\n")
        handle.write("## Group Members Table\n\n")
        handle.write("| Group | Member |\n")
        handle.write("|-------|--------|\n")
        for group, members, computers in group_rows:
            if members:
                for member in members:
                    handle.write("| %s | %s |\n" % (group, member))
            elif computers:
                for computer in computers:
                    handle.write("| %s | %s |\n" % (group, computer))
            else:
                handle.write("| %s | (no members) |\n" % group)
        handle.write("\n")

    global GLOBAL_GROUP_COUNT
    GLOBAL_GROUP_COUNT = len(groups)
    return len(groups)


def collect_domain_computers(output_dir: Path, info: Dict[str, object]) -> int:
    """Collect computer accounts with samba-tool computer list."""
    log_info("Collecting domain computers...")

    rc, out, _ = run_nsdc(["/usr/bin/samba-tool", "computer", "list"], timeout=30)
    if rc != 0:
        log_warn("Cannot list computer accounts")
        return 0

    computers = sorted(
        line.strip()
        for line in out.splitlines()
        if line.strip() and not line.startswith("ERROR") and "codec" not in line
    )

    print()
    print("=" * 90)
    print("  DOMAIN COMPUTERS")
    print("=" * 90)
    print()
    print("Total computer accounts: %d" % len(computers))
    print()
    for computer in computers:
        print("  %s" % computer)
    print()
    print("=" * 90)
    log_success("Domain computers collected: %d" % len(computers))

    REPORT_BLOCKS.append({
        "title": "Domain Computers",
        "headers": ["Computer"],
        "rows": [[computer] for computer in computers],
    })

    md_file = output_dir / "05_domain_computers.md"
    with open(md_file, "w", encoding="utf-8") as handle:
        handle.write("# Domain Computers\n\n")
        handle.write("Report generated: %s\n\n" % datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
        handle.write("**Total computer accounts:** %d\n\n" % len(computers))
        if info.get("release"):
            handle.write("Host: %s\n\n" % info["release"])
        handle.write("---\n\n")
        handle.write("## Computer Accounts Table\n\n")
        handle.write("| Computer |\n")
        handle.write("|----------|\n")
        for computer in computers:
            handle.write("| %s |\n" % computer)
        handle.write("\n")

    global GLOBAL_COMPUTER_COUNT
    GLOBAL_COMPUTER_COUNT = len(computers)
    return len(computers)


# ---------------------------------------------------------------------------
# Section 5: shared folders (ibay) and ACLs
# ---------------------------------------------------------------------------

def collect_shares_table(output_dir: Path) -> int:
    """Collect file shares and their POSIX ACLs from smb.conf and getfacl."""
    log_info("Collecting shared folders and ACLs...")

    shares_dir = output_dir / "03_shares"
    shares_dir.mkdir(parents=True, exist_ok=True)

    if not SMB_CONF.exists():
        log_warn("smb.conf not found, no shares to inspect")
        shares: List[Tuple[str, str]] = []
    else:
        shares = parse_smb_conf(SMB_CONF.read_text(encoding="utf-8", errors="replace"))

    if not shares:
        log_warn("No file shares configured")

    share_data: List[Tuple[str, str, List[Tuple[str, str]]]] = []
    acl_ok = 0
    acl_failed = 0

    for share_name, share_path in shares:
        path_obj = Path(share_path)
        if not path_obj.exists():
            log_warn("Share %s points to a missing path: %s" % (share_name, share_path))
            share_data.append((share_name, share_path, []))
            acl_failed += 1
            continue

        rc, acl_out, _ = run_command(["getfacl", "-p", share_path], timeout=30)
        if rc != 0 or "user::" not in acl_out:
            log_warn("Cannot read ACL for %s (%s)" % (share_name, share_path))
            share_data.append((share_name, share_path, []))
            acl_failed += 1
            continue

        acl_ok += 1
        share_data.append((share_name, share_path, parse_getfacl(acl_out)))

    print()
    print("=" * 130)
    print("  SHARED FOLDERS")
    print("=" * 130)
    print()
    print("%-30s %-45s %-25s %-10s" % ("SHARE", "PATH", "USER/GROUP", "PERM"))
    print("%-30s %-45s %-25s %-10s" % ("-" * 30, "-" * 45, "-" * 25, "-" * 10))
    for share_name, share_path, acl_rows in share_data:
        if acl_rows:
            for entity, perm in acl_rows:
                print("%-30s %-45s %-25s %-10s" % (share_name[:29], share_path[:44], entity[:24], perm))
        else:
            print("%-30s %-45s %-25s %-10s" % (share_name[:29], share_path[:44], "(no ACL data)", "-"))
    print()
    print("=" * 130)
    log_success("Shares collected: %d (ACL: %d OK, %d failed)" % (len(shares), acl_ok, acl_failed))

    share_table_rows: List[List[str]] = []
    for share_name, share_path, acl_rows in share_data:
        if acl_rows:
            for entity, perm in acl_rows:
                share_table_rows.append([share_name, share_path, entity, perm])
        else:
            share_table_rows.append([share_name, share_path, "(no ACL data)", "-"])
    REPORT_BLOCKS.append({
        "title": "Shared Folders",
        "headers": ["Share", "Path", "User/Group", "Permission"],
        "rows": share_table_rows,
    })

    md_file = output_dir / "04_share_permissions.md"
    with open(md_file, "w", encoding="utf-8") as handle:
        handle.write("# Shared Folders - Permissions\n\n")
        handle.write("Report generated: %s\n\n" % datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
        handle.write("**Total shares:** %d\n\n" % len(shares))
        handle.write("---\n\n")
        handle.write("## Share Permissions Table\n\n")
        handle.write("| Share | Path | User/Group | Permission |\n")
        handle.write("|-------|------|------------|------------|\n")
        for share_name, share_path, acl_rows in share_data:
            if acl_rows:
                for entity, perm in acl_rows:
                    handle.write("| %s | %s | %s | %s |\n" % (share_name, share_path, entity, perm))
            else:
                handle.write("| %s | %s | (no ACL data) | - |\n" % (share_name, share_path))
        handle.write("\n")

    global GLOBAL_SHARE_COUNT
    GLOBAL_SHARE_COUNT = len(shares)
    return len(shares)


# ---------------------------------------------------------------------------
# Section 6: WebTop 5 mail shares
# ---------------------------------------------------------------------------

def load_ad_guid_names() -> Dict[str, str]:
    """Map AD objectGUID to account name for WebTop user UUIDs.

    WebTop stores principals as LDAP objectGUID strings, but core.users only
    contains accounts that logged in at least once. The missing ones are
    resolved against the AD database itself.
    """
    mapping: Dict[str, str] = {}
    sam_db = "/var/lib/samba/private/sam.ldb"
    for filter_expr, name_attr in (
        ("(objectClass=user)", "sAMAccountName"),
        ("(objectClass=group)", "cn"),
    ):
        rc, out, _ = run_nsdc(
            ["/usr/bin/ldbsearch", "-H", sam_db, filter_expr, "objectGUID", name_attr],
            timeout=60,
        )
        if rc != 0:
            continue
        guid = None
        for line in out.splitlines():
            if line.startswith("objectGUID:"):
                guid = line.split(":", 1)[1].strip().lower()
            elif line.startswith(name_attr + ":") and guid:
                mapping[guid] = line.split(":", 1)[1].strip()
                guid = None
    return mapping


def collect_webtop_sharing(output_dir: Path, engine: str) -> int:
    """Collect WebTop 5 mail sharing information when WebTop is installed."""
    md_file = output_dir / "03_webtop_shares.md"

    if not engine:
        log_warn("WebTop 5 not installed, skipping mail share collection")
        with open(md_file, "w", encoding="utf-8") as handle:
            handle.write("# WebTop Mail Shares\n\n")
            handle.write("WebTop 5 is not installed on this host.\n")
        return 0

    log_info("Collecting WebTop mail shares (%s)..." % engine)

    if engine == "postgres":
        rc, out, err = psql_query("SELECT user_uid, user_id FROM core.users")
    else:
        rc, out, err = mysql_query("SELECT user_uid, user_id FROM core_users", database="webtop5")

    if rc != 0:
        log_warn("Cannot read WebTop users: %s" % (err or "unknown error"))
        with open(md_file, "w", encoding="utf-8") as handle:
            handle.write("# WebTop Mail Shares\n\n")
            handle.write("[!] **Error:** cannot query WebTop database\n")
        return 0

    separator = "|" if engine == "postgres" else "\t"
    uuid_map: Dict[str, str] = {}
    for line in out.splitlines():
        parts = line.split(separator)
        if len(parts) >= 2 and parts[0].strip():
            uuid_map[parts[0].strip().lower()] = parts[1].strip()

    ad_map = load_ad_guid_names()
    uuid_map.update({key: value for key, value in ad_map.items() if key not in uuid_map})

    def resolve_uuid(value: str) -> str:
        if not value:
            return ""
        return uuid_map.get(value) or "(removed: %s)" % value

    sql = (
        "SELECT s.share_id, s.user_uid, s.key, sd.user_uid, sd.value "
        "FROM core.shares s LEFT JOIN core.shares_data sd ON s.share_id = sd.share_id "
        "WHERE s.service_id LIKE '%mail%' "
        "ORDER BY s.user_uid, s.share_id, sd.user_uid"
    )
    if engine == "postgres":
        rc, out, err = psql_query(sql, timeout=30)
    else:
        rc, out, err = mysql_query(sql.replace("core.", "core_"), database="webtop5", timeout=30)

    removed = 0
    if rc != 0:
        log_warn("Cannot read WebTop shares: %s" % (err or "unknown error"))
        shares_data: List[Tuple[str, str, str]] = []
    else:
        shares_data = []
        for line in out.splitlines():
            parts = line.split(separator)
            if len(parts) < 4:
                continue
            owner_uuid = parts[1].strip().lower()
            shared_uuid = parts[3].strip().lower()
            if not shared_uuid:
                # LEFT JOIN row without a principal: not a real share.
                continue
            value = parts[4].strip() if len(parts) > 4 else ""
            owner = resolve_uuid(owner_uuid)
            shared = resolve_uuid(shared_uuid)
            perm = "RW" if "shareIdentity" in value and "true" in value else "RO"
            if shared.startswith("(removed:"):
                removed += 1
            shares_data.append((owner, shared, perm))

    if removed:
        log_warn(
            "%d WebTop share rows reference principals no longer in AD "
            "(WebTop keeps them after account deletion)" % removed
        )

    REPORT_BLOCKS.append({
        "title": "WebTop Mail Shares",
        "headers": ["From", "To", "Type"],
        "rows": [[owner, shared, perm] for owner, shared, perm in shares_data],
    })

    log_success("WebTop shares collected: %d" % len(shares_data))

    with open(md_file, "w", encoding="utf-8") as handle:
        handle.write("# WebTop Mail Shares\n\n")
        handle.write("Report generated: %s\n\n" % datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
        handle.write("**Total shares:** %d\n\n" % len(shares_data))
        handle.write("---\n\n")
        if shares_data:
            handle.write("## Share Table\n\n")
            handle.write("| From | To | Type |\n")
            handle.write("|------|----|------|\n")
            for owner, shared, perm in shares_data:
                handle.write("| %s | %s | %s |\n" % (owner, shared, perm))
            if removed:
                handle.write(
                    "\n**Removed principals:** %d rows reference accounts no longer "
                    "in AD; WebTop keeps them after account deletion.\n" % removed
                )
        else:
            handle.write("*No mail shares configured*\n")
        handle.write("\n")

    global GLOBAL_WEBTOP_COUNT
    GLOBAL_WEBTOP_COUNT = len(shares_data)
    return len(shares_data)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def generate_summary_table(output_dir: Path, policy: Dict[str, object]) -> None:
    """Write the summary table to console and SUMMARY_TABLE.txt."""
    print()
    print("=" * 80)
    print("  REPORT SUMMARY")
    print("=" * 80)
    print()
    print("%-30s %-20s" % ("CATEGORY", "TOTAL"))
    print("%-30s %-20s" % ("-" * 30, "-" * 20))
    print("%-30s %-20s" % ("AD Users", GLOBAL_USER_COUNT))
    print("%-30s %-20s" % ("Disabled Users", GLOBAL_DISABLED_COUNT))
    print("%-30s %-20s" % ("AD Groups", GLOBAL_GROUP_COUNT))
    print("%-30s %-20s" % ("Domain Computers", GLOBAL_COMPUTER_COUNT))
    print("%-30s %-20s" % ("Shared Folders", GLOBAL_SHARE_COUNT))
    print("%-30s %-20s" % ("WebTop Shares", GLOBAL_WEBTOP_COUNT))
    print()
    print("=" * 80)

    summary_rows = [
        ["AD Users", str(GLOBAL_USER_COUNT)],
        ["Disabled Users", str(GLOBAL_DISABLED_COUNT)],
        ["AD Groups", str(GLOBAL_GROUP_COUNT)],
        ["Domain Computers", str(GLOBAL_COMPUTER_COUNT)],
        ["Shared Folders", str(GLOBAL_SHARE_COUNT)],
        ["WebTop Shares", str(GLOBAL_WEBTOP_COUNT)],
        ["Password Policy Max Age (days)", str(policy.get("max_age_days", "N/A"))],
        ["Passwords Never Expire", str(policy.get("never_expires", "N/A"))],
    ]
    REPORT_BLOCKS.append({
        "title": "Report Summary",
        "headers": ["Category", "Total"],
        "rows": summary_rows,
    })

    summary_file = output_dir / "SUMMARY_TABLE.txt"
    with open(summary_file, "w", encoding="utf-8") as handle:
        handle.write("NS7 AUDIT REPORT TABLE VERSION\n")
        handle.write("Version: %s\n" % VERSION)
        handle.write("Generated: %s\n\n" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        handle.write("AD Users: %d\n" % GLOBAL_USER_COUNT)
        handle.write("Disabled Users: %d\n" % GLOBAL_DISABLED_COUNT)
        handle.write("AD Groups: %d\n" % GLOBAL_GROUP_COUNT)
        handle.write("Domain Computers: %d\n" % GLOBAL_COMPUTER_COUNT)
        handle.write("Shared Folders: %d\n" % GLOBAL_SHARE_COUNT)
        handle.write("WebTop Shares: %d\n" % GLOBAL_WEBTOP_COUNT)
        handle.write("Password Policy Max Age (days): %s\n" % policy.get("max_age_days", "N/A"))
        handle.write("Passwords Never Expire: %s\n" % policy.get("never_expires", "N/A"))

    log_success("Summary table generated")


# ---------------------------------------------------------------------------
# Email delivery
# ---------------------------------------------------------------------------

def render_html_report(output_dir: Path) -> Path:
    """Render every collected block into one self-contained HTML file."""
    generated = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    hostname = socket.gethostname()

    parts: List[str] = []
    parts.append("<!doctype html>")
    parts.append('<html lang="en"><head><meta charset="utf-8">')
    parts.append("<title>NS7 Audit Report - %s</title>" % html.escape(hostname))
    parts.append(
        "<style>"
        "body{font-family:'DejaVu Sans',Arial,Helvetica,sans-serif;font-size:11px;color:#222;margin:24px;}"
        "h1{font-size:20px;margin:0 0 4px 0;}"
        "h2{font-size:14px;margin:22px 0 6px 0;border-bottom:1px solid #bbb;padding-bottom:2px;}"
        "table{border-collapse:collapse;width:100%;margin-bottom:10px;}"
        "th,td{border:1px solid #ccc;padding:3px 5px;text-align:left;vertical-align:top;}"
        "th{background:#eee;font-weight:bold;}"
        "tr:nth-child(even) td{background:#fafafa;}"
        ".meta{color:#555;margin-bottom:12px;}"
        "</style>"
    )
    parts.append("</head><body>")
    parts.append("<h1>NS7 Audit Report</h1>")
    parts.append(
        '<div class="meta">Host: %s &middot; Generated: %s &middot; Version: %s</div>'
        % (html.escape(hostname), html.escape(generated), VERSION)
    )

    for block in REPORT_BLOCKS:
        title = str(block.get("title", ""))
        headers_raw = block.get("headers")
        rows_raw = block.get("rows")
        headers = headers_raw if isinstance(headers_raw, list) else []
        rows = rows_raw if isinstance(rows_raw, list) else []

        parts.append("<h2>%s</h2>" % html.escape(title))
        parts.append("<table><thead><tr>")
        for header in headers:
            parts.append("<th>%s</th>" % html.escape(str(header)))
        parts.append("</tr></thead><tbody>")
        if rows:
            for row in rows:
                parts.append("<tr>")
                for cell in row:
                    parts.append("<td>%s</td>" % html.escape(str(cell)))
                parts.append("</tr>")
        else:
            parts.append('<tr><td colspan="%d">(no data)</td></tr>' % max(1, len(headers)))
        parts.append("</tbody></table>")

    parts.append("</body></html>")

    html_file = output_dir / "00_report.html"
    html_file.write_text("\n".join(parts), encoding="utf-8")
    return html_file


class SimplePdfWriter:
    """Minimal A4 PDF writer with Helvetica fonts, tables and pagination.

    Uses only the Python standard library: no external converter is required
    on the audited host.
    """

    PAGE_W = 595
    PAGE_H = 842
    MARGIN = 40
    ROW_H = 12
    HEADER_H = 14
    FOOTER: str = ""

    def __init__(self) -> None:
        self.pages: List[str] = []
        self.ops: List[str] = []
        self.y = float(self.PAGE_H - self.MARGIN)

    @staticmethod
    def _escape(text: str) -> str:
        data = text.encode("cp1252", "replace").decode("latin-1")
        return data.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    def _text(self, x: float, y: float, size: int, text: str, bold: bool = False) -> None:
        font = "F2" if bold else "F1"
        self.ops.append(
            "BT /%s %d Tf 1 0 0 1 %.1f %.1f Tm (%s) Tj ET"
            % (font, size, x, y, self._escape(text))
        )

    def _stroke_rect(self, x: float, y: float, width: float, height: float) -> None:
        self.ops.append("%.1f %.1f %.1f %.1f re S" % (x, y, width, height))

    def _fill_rect(self, x: float, y: float, width: float, height: float, gray: float) -> None:
        self.ops.append("%.2f g %.1f %.1f %.1f %.1f re f 0 g" % (gray, x, y, width, height))

    def _footer(self) -> None:
        """Draw the optional footer text at the bottom of the current page."""
        if not self.FOOTER:
            return
        text = " ".join(str(self.FOOTER).split())
        width = len(text) * 3.6
        x = max(float(self.MARGIN), (self.PAGE_W - width) / 2.0)
        self._text(x, 18, 7, text)

    def _new_page(self) -> None:
        self._footer()
        self.pages.append("\n".join(self.ops))
        self.ops = []
        self.y = float(self.PAGE_H - self.MARGIN)

    @staticmethod
    def _fit(value: object, width: float) -> str:
        text = " ".join(str(value).split())
        max_chars = max(4, int((width - 6) / 4.4))
        if len(text) > max_chars:
            return text[: max_chars - 3] + "..."
        return text

    def add_title(self, title: str, meta: str) -> None:
        self._text(self.MARGIN, self.y - 14, 15, title, True)
        self.y -= 22
        self._text(self.MARGIN, self.y, 8, meta)
        self.y -= 16

    def _column_widths(self, headers: List[str], rows: List[List[str]]) -> List[float]:
        columns = max(1, len(headers))
        content_w = float(self.PAGE_W - 2 * self.MARGIN)
        weights: List[int] = []
        for index in range(columns):
            longest = len(str(headers[index])) if index < len(headers) else 1
            for row in rows:
                if index < len(row):
                    longest = max(longest, min(len(str(row[index])), 40))
            weights.append(max(4, longest))
        total = float(sum(weights)) or 1.0
        return [content_w * weight / total for weight in weights]

    def _row(self, widths: List[float], cells: List[str], height: float, bold: bool) -> None:
        x = float(self.MARGIN)
        for index, width in enumerate(widths):
            cell = cells[index] if index < len(cells) else ""
            if bold:
                self._fill_rect(x, self.y - height, width, height, 0.90)
            self._stroke_rect(x, self.y - height, width, height)
            self._text(x + 3, self.y - height + 4, 8, self._fit(cell, width), bold)
            x += width
        self.y -= height

    def add_block(self, title: str, headers: List[str], rows: List[List[str]]) -> None:
        widths = self._column_widths(headers, rows)

        if self.y < self.MARGIN + 60:
            self._new_page()

        self._text(self.MARGIN, self.y - 11, 11, title, True)
        self.y -= 18
        self._row(widths, headers, float(self.HEADER_H), True)

        if not rows:
            self._row(widths, ["(no data)"], float(self.ROW_H), False)
        for row in rows:
            if self.y - self.ROW_H < self.MARGIN:
                self._new_page()
                self._text(self.MARGIN, self.y - 11, 10, title + " (continued)", True)
                self.y -= 16
                self._row(widths, headers, float(self.HEADER_H), True)
            self._row(widths, row, float(self.ROW_H), False)

        self.y -= 8

    def save(self, path: Path) -> None:
        self._footer()
        self.pages.append("\n".join(self.ops))
        self.ops = []
        page_count = len(self.pages)

        objects: List[str] = [
            "<< /Type /Catalog /Pages 2 0 R >>",
            "<< /Type /Pages /Kids [%s] /Count %d >>"
            % (" ".join("%d 0 R" % (5 + i) for i in range(page_count)), page_count),
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
        ]
        for index in range(page_count):
            objects.append(
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] "
                "/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents %d 0 R >>"
                % (self.PAGE_W, self.PAGE_H, 5 + page_count + index)
            )
        for content in self.pages:
            raw = content.encode("latin-1", "replace")
            objects.append("<< /Length %d >>\nstream\n%s\nendstream" % (len(raw), content))

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets: List[int] = []
        for index, obj in enumerate(objects, 1):
            offsets.append(len(out))
            out.extend(("%d 0 obj\n%s\nendobj\n" % (index, obj)).encode("latin-1", "replace"))

        xref_pos = len(out)
        out.extend(("xref\n0 %d\n" % (len(objects) + 1)).encode("latin-1"))
        out.extend(b"0000000000 65535 f \n")
        for offset in offsets:
            out.extend(("%010d 00000 n \n" % offset).encode("latin-1"))
        out.extend(
            (
                "trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
                % (len(objects) + 1, xref_pos)
            ).encode("latin-1")
        )
        path.write_bytes(bytes(out))


def generate_pdf(output_dir: Path) -> Path:
    """Render the collected blocks to a PDF using only the standard library."""
    writer = SimplePdfWriter()
    writer.FOOTER = PDF_FOOTER
    meta = "Host: %s  |  Generated: %s  |  Version: %s" % (
        socket.gethostname(),
        datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        VERSION,
    )
    writer.add_title("NS7 Audit Report", meta)

    for block in REPORT_BLOCKS:
        headers_raw = block.get("headers")
        rows_raw = block.get("rows")
        headers = [str(h) for h in headers_raw] if isinstance(headers_raw, list) else []
        rows = [[str(cell) for cell in row] for row in rows_raw] if isinstance(rows_raw, list) else []
        writer.add_block(str(block.get("title", "")), headers, rows)

    pdf_file = output_dir / "00_report.pdf"
    writer.save(pdf_file)
    return pdf_file


def send_email_interactive(output_dir: Path) -> bool:
    """Offer to send the report by email (interactive, skipped when not a TTY)."""
    print()
    print("=" * 80)

    if not sys.stdin.isatty():
        log_info("Standard input is not a terminal, email delivery skipped")
        return False

    try:
        send_prompt = input("Send the report by email? (y/n): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        log_info("Email delivery skipped")
        return False

    if send_prompt not in ("y", "yes"):
        log_info("Email delivery skipped")
        return False

    print()
    log_info("Email configuration...")

    try:
        print()
        recipient = input("Recipient email: ").strip()
        if not recipient:
            log_error("Recipient email is required")
            return False

        print()
        hostname = socket.gethostname()
        default_from = "root@%s" % hostname
        from_email = input("Sender (From) [%s]: " % default_from).strip() or default_from

        print()
        smtp_server = input("SMTP server [smtp.example.com]: ").strip()
        if not smtp_server:
            log_error("SMTP server is required")
            return False

        print()
        smtp_port_raw = input("SMTP port [587]: ").strip()
        smtp_port = int(smtp_port_raw) if smtp_port_raw else 587

        print()
        smtp_user = input("SMTP username: ").strip()
        if not smtp_user:
            log_error("SMTP username is required")
            return False

        print()
        smtp_pass = getpass.getpass("SMTP password: ")
        if not smtp_pass:
            log_error("SMTP password is required")
            return False

    except (EOFError, KeyboardInterrupt):
        print()
        log_error("Input interrupted")
        return False

    print()
    log_info("Preparing email...")

    subject = "NS7 Audit Report - %s - %s" % (hostname, datetime.now().strftime("%d/%m/%Y %H:%M"))

    msg = MIMEMultipart()
    msg["From"] = from_email
    msg["To"] = recipient
    msg["Subject"] = subject

    body = """NS7 Audit Report - %s
Date: %s

========================================================================================
REPORT SUMMARY
========================================================================================

AD Users: %d
Disabled Users: %d
AD Groups: %d
Domain Computers: %d
Shared Folders: %d
WebTop Shares: %d

========================================================================================

Full details are available in the attached files in Markdown format.

Attached files:
- SUMMARY_TABLE.txt (summary)
- 01_password_expiry.md (password expiring)
- 02_ad_groups.md (groups and members)
- 03_webtop_shares.md (WebTop shares)
- 04_share_permissions.md (share permissions)
- 05_domain_computers.md (domain computers)
- 06_user_status.md (user account status)""" % (
        hostname,
        datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        GLOBAL_USER_COUNT,
        GLOBAL_DISABLED_COUNT,
        GLOBAL_GROUP_COUNT,
        GLOBAL_COMPUTER_COUNT,
        GLOBAL_SHARE_COUNT,
        GLOBAL_WEBTOP_COUNT,
    )
    msg.attach(MIMEText(body, "plain", "utf-8"))

    attachments = [
        "SUMMARY_TABLE.txt",
        "00_report.html",
        "01_password_expiry.md",
        "02_ad_groups.md",
        "03_webtop_shares.md",
        "04_share_permissions.md",
        "05_domain_computers.md",
        "06_user_status.md",
    ]
    for pdf_file in sorted(output_dir.glob("*.pdf")):
        attachments.append(pdf_file.name)

    attached = 0
    for filename in attachments:
        path = output_dir / filename
        if not path.exists():
            continue
        with open(path, "rb") as handle:
            part = MIMEBase("text", "plain")
            part.set_payload(handle.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", 'attachment; filename="%s"' % filename)
            msg.attach(part)
            attached += 1

    log_info("Attachments: %d" % attached)
    log_info("Sending email to %s via %s:%d..." % (recipient, smtp_server, smtp_port))

    try:
        server = smtplib.SMTP(smtp_server, smtp_port, timeout=30)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        server.quit()
        log_success("Email sent to %s" % recipient)
        return True
    except smtplib.SMTPAuthenticationError:
        log_error("SMTP authentication failed")
        return False
    except smtplib.SMTPException as exc:
        log_error("SMTP error: %s" % exc)
        return False
    except socket.timeout:
        log_error("Connection to %s:%d timed out" % (smtp_server, smtp_port))
        return False
    except Exception as exc:  # noqa: BLE001
        log_error("Email delivery failed: %s" % exc)
        return False


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def run_self_test() -> int:
    """Exercise the pure parsers; return 0 when all checks pass."""
    failures = 0

    parsed = parse_ldap_timestamp("20261118165219.0Z")
    if not parsed or parsed.strftime("%Y-%m-%d") != "2026-11-18":
        print("FAIL: parse_ldap_timestamp")
        failures += 1

    parsed = parse_filetime("134394943418277680")
    if not parsed or parsed.strftime("%Y-%m-%d") != "2026-11-18":
        print("FAIL: parse_filetime")
        failures += 1

    policy = parse_password_settings("Maximum password age (days): 0\n")
    if not policy["never_expires"] or policy["max_age_days"] != 0:
        print("FAIL: parse_password_settings never")
        failures += 1

    policy = parse_password_settings("Maximum password age (days): 43\n")
    if policy["never_expires"] or policy["max_age_days"] != 43:
        print("FAIL: parse_password_settings 43")
        failures += 1

    policy = parse_password_settings("no policy here")
    if policy["max_age_days"] != DEFAULT_MAX_PWD_AGE_DAYS:
        print("FAIL: parse_password_settings fallback")
        failures += 1

    conf = """[global]
workgroup = EXAMPLE
[share1]
path = /var/lib/nethserver/ibay/share1
browseable = yes
[homes]
path = /home
"""
    shares = parse_smb_conf(conf)
    if shares != [("share1", "/var/lib/nethserver/ibay/share1")]:
        print("FAIL: parse_smb_conf")
        failures += 1

    acl = """# file: /srv
# owner: root
# group: domain admins
user::rwx
user:marzio:rwx
group::r-x
group:staff:r-x
mask::rwx
other::---
default:user::rwx
"""
    rows = parse_getfacl(acl)
    expected = [
        ("owner:root", "RW"),
        ("marzio", "RW"),
        ("@domain admins", "RO"),
        ("@staff", "RO"),
        ("Everyone", "RO"),
    ]
    if rows != expected:
        print("FAIL: parse_getfacl -> %r" % (rows,))
        failures += 1

    base_now = datetime(2026, 11, 19, 12, 0, 0)
    status_cases = [
        (datetime(2026, 11, 19), 30, "Valid", 30),
        (datetime(2026, 10, 25), 30, "Expiring soon", 5),
        (datetime(2026, 10, 10), 30, "Expired", -10),
    ]
    for last_change, max_age, want_status, want_days in status_cases:
        _, _, status, days = password_status(last_change, max_age, base_now)
        if status != want_status or days != want_days:
            print(
                "FAIL: password_status(%s, %d) -> %s/%d, expected %s/%d"
                % (last_change.date(), max_age, status, days, want_status, want_days)
            )
            failures += 1

    noisy = (
        "PC-ONE$\n"
        "Traceback (most recent call last):\n"
        "  File \"/usr/lib64/python3.6/site-packages/samba/netcmd/__init__.py\", line 186, in _run\n"
        "return self.run(*args, **kwargs)\n"
        "self.out.write(\"%s\\n\" % msg.get(\"samaccountname\", idx=0))\n"
        "UnicodeEncodeError: 'ascii' codec can't encode character\n"
        "PC-TWO$\n"
    )
    if filter_tool_noise(noisy) != "PC-ONE$\nPC-TWO$":
        print("FAIL: filter_tool_noise -> %r" % filter_tool_noise(noisy))
        failures += 1

    writer = SimplePdfWriter()
    writer.FOOTER = "footer@example.test"
    writer.add_block("T", ["A"], [["v%d" % i] for i in range(120)])
    fd, pdf_name = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    pdf_path = Path(pdf_name)
    writer.save(pdf_path)
    pdf_bytes = pdf_path.read_bytes()
    pdf_path.unlink()
    if pdf_bytes.count(b"footer@example.test") < 2:
        print("FAIL: PDF footer missing on every page")
        failures += 1

    if failures == 0:
        print("PASS: ns7-audit-report-table.py self-test")
        return 0
    print("FAILED: %d self-test(s)" % failures)
    return 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    """Main entry point."""
    global GLOBAL_USER_COUNT

    print("=" * 80)
    print("NS7 Audit Report - Table Version v%s" % VERSION)
    print("=" * 80)
    print()

    output_base = Path("/tmp")
    do_self_test = False
    do_check = False
    pdf_mode = "auto"

    global PDF_FOOTER
    index = 1
    while index < len(sys.argv):
        arg = sys.argv[index]
        if arg == "--help":
            print("Usage: ns7-audit-report-table.py [--output-dir DIR] [--pdf|--no-pdf] [--check] [--self-test] [--version] [--footer TEXT]")
            return 0
        if arg == "--version":
            print(VERSION)
            return 0
        if arg == "--self-test":
            do_self_test = True
            index += 1
            continue
        if arg == "--check":
            do_check = True
            index += 1
            continue
        if arg == "--pdf":
            pdf_mode = "yes"
            index += 1
            continue
        if arg == "--no-pdf":
            pdf_mode = "no"
            index += 1
            continue
        if arg == "--output-dir" and index + 1 < len(sys.argv):
            output_base = Path(sys.argv[index + 1])
            index += 2
            continue
        if arg == "--footer" and index + 1 < len(sys.argv):
            PDF_FOOTER = sys.argv[index + 1]
            index += 2
            continue
        index += 1

    if do_self_test:
        return run_self_test()

    if do_check:
        return run_preflight()

    report_date = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = output_base / ("ns7-audit-%s" % report_date)
    output_dir.mkdir(parents=True, exist_ok=True)
    log_success("Output: %s" % output_dir)

    info = check_prerequisites()
    print()

    if not info["dc_ok"]:
        log_error("The local Samba DC (nsdc) is not running: cannot audit AD users, groups or shares")
        return 1

    GLOBAL_USER_COUNT = collect_ad_users(output_dir)
    collect_user_status_table(output_dir)

    policy = get_password_policy()
    log_info(
        "Domain password policy: max age %s days%s"
        % (
            policy["max_age_days"],
            " (never expires)" if policy["never_expires"] else "",
        )
    )
    collect_password_expiry_table(output_dir, policy)

    collect_ad_groups_table(output_dir)
    collect_domain_computers(output_dir, info)
    collect_shares_table(output_dir)
    collect_webtop_sharing(output_dir, str(info["webtop"] or ""))

    print()
    generate_summary_table(output_dir, policy)

    html_file = render_html_report(output_dir)
    log_success("HTML report: %s" % html_file)

    if pdf_mode != "no":
        try:
            pdf_file = generate_pdf(output_dir)
            log_success("PDF report: %s" % pdf_file)
        except Exception as exc:  # noqa: BLE001
            log_error("PDF generation failed: %s" % exc)

    print()
    log_success("Report completed")
    log_info("Output: %s" % output_dir)

    send_email_interactive(output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
