#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

# Check how long security updates have been left uninstalled.
#
# Maps to NIS base measure PR.PS-02.2: the latest vendor security updates are
# installed without undue delay. Counting pending updates is the easy half;
# the requirement is about elapsed time, so this check dates them.
#
# Two design points worth knowing before reading the code:
#
# 1. How long an update has been pending is not recorded anywhere on the
#    host, so this check keeps its own state file and measures age from the
#    moment it first saw a package listed. That is "first observed here",
#    not "released by the vendor" - the message says so rather than implying
#    a precision it does not have.
#
# 2. An empty update list is only trustworthy if the package metadata is
#    fresh. A host that has not refreshed its lists reports zero pending
#    updates and looks healthy while being months behind. When metadata is
#    stale this check reports UNKNOWN, never OK: not knowing is not the same
#    as being up to date.
#
# Supports apt (Debian/Ubuntu) and dnf (Rocky/RHEL family).
# Must stay compatible with Python 3.9, the oldest interpreter in the fleet.

import sys
import os
import json
import time
import subprocess
import datetime

SERVICE = "Patch.Posture"
CONTROL = "PR.PS-02.2"
VERSION = "1.0.1"

# Remediation deadlines, in days, measured from first observation.
#
# PROVISIONAL. "Without undue delay" is a governance decision, not a
# technical constant: the owning organisation has to state the number and
# accept it. These defaults are placeholders so the check is usable now, and
# both can be overridden per host via the environment.
GRACE_DAYS = int(os.environ.get("CHECK_PATCH_GRACE_DAYS", "7"))
SLA_DAYS = int(os.environ.get("CHECK_PATCH_SLA_DAYS", "14"))

# Package metadata older than this makes an empty result untrustworthy.
METADATA_STALE_DAYS = int(os.environ.get("CHECK_PATCH_METADATA_DAYS", "3"))

STATE_CANDIDATES = (
    "/var/lib/check_mk_agent/patch_posture_state.json",
    "/var/tmp/patch_posture_state.json",
)

APT_CHECK = "/usr/lib/update-notifier/apt-check"
APT_LISTS = "/var/lib/apt/lists"
APT_STAMP = "/var/lib/apt/periodic/update-success-stamp"
DNF_CACHE = "/var/cache/dnf"
REBOOT_FLAG = "/var/run/reboot-required"

## Useful

def run(cmd, timeout=60):
    """Run a command and return (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return 1, "", "command timed out"
    except FileNotFoundError:
        return 127, "", "command not found"
    except Exception as exc:  # noqa: BLE001 - a check must never raise
        return 1, "", str(exc)


def have(binary):
    """True when the binary is on PATH."""
    code, _, _ = run(["which", binary], timeout=10)
    return code == 0


# Other checks on the same host may close a piggyback block with <<<<>>>>,
# which leaves no section open. Emitting our own header keeps these lines
# inside the local section regardless of what ran before us.
LOCAL_SECTION = "<<<local:sep(0)>>>"


def local_line(state, service, perfdata, message):
    """Build one CheckMK local-check line: state, service, metrics (or -), detail."""
    return "%s %s %s %s" % (state, service, perfdata or "-", message)


def newest_mtime(path):
    """Most recent mtime at or under path, or None when nothing is found."""
    newest = None
    if os.path.isfile(path):
        return os.path.getmtime(path)
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                stamp = os.path.getmtime(os.path.join(root, name))
            except OSError:
                continue
            if newest is None or stamp > newest:
                newest = stamp
    return newest


def metadata_age_days(manager):
    """Age in days of the newest package metadata, or None when unknown."""
    stamps = []
    if manager == "apt":
        for path in (APT_STAMP, APT_LISTS):
            stamp = newest_mtime(path)
            if stamp:
                stamps.append(stamp)
    elif manager == "dnf":
        stamp = newest_mtime(DNF_CACHE)
        if stamp:
            stamps.append(stamp)
    if not stamps:
        return None
    return (time.time() - max(stamps)) / 86400.0


## Package managers

def apt_pending():
    """Return (security_packages, total_count) for apt, or (None, None)."""
    # apt-check is the canonical Ubuntu source and prints "total;security".
    if os.path.exists(APT_CHECK):
        code, _, err = run([APT_CHECK], timeout=60)
        if code == 0 and ";" in err:
            try:
                total, security = (int(x) for x in err.strip().split(";")[:2])
            except ValueError:
                total, security = None, None
            if total is not None:
                # apt-check gives counts, not names: synthesise stable keys so
                # ageing still works, at the cost of per-package granularity.
                return ["apt-security-%d" % i for i in range(security)], total

    # Fallback: simulate the upgrade and read the planned installs.
    code, out, _ = run(
        ["apt-get", "-s", "-q", "-o", "Debug::NoLocking=true", "dist-upgrade"],
        timeout=120,
    )
    if code != 0:
        return None, None
    security, total = [], 0
    for line in out.splitlines():
        if not line.startswith("Inst "):
            continue
        total += 1
        parts = line.split()
        name = parts[1] if len(parts) > 1 else "unknown"
        low = line.lower()
        if "-security" in low or "security-updates" in low:
            security.append(name)
    return security, total


def dnf_pending():
    """Return (security_packages, total_count) for dnf, or (None, None)."""
    code, out, _ = run(["dnf", "-q", "--security", "check-update"], timeout=180)
    # 100 = updates available, 0 = none, anything else = failure.
    if code not in (0, 100):
        return None, None
    security = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith(("Last metadata", "Obsoleting", "Security:")):
            continue
        parts = line.split()
        if len(parts) >= 3 and "." in parts[0]:
            security.append(parts[0])

    code, out, _ = run(["dnf", "-q", "check-update"], timeout=180)
    if code not in (0, 100):
        return security, len(security)
    total = 0
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith(("Last metadata", "Obsoleting")):
            continue
        parts = line.split()
        if len(parts) >= 3 and "." in parts[0]:
            total += 1
    return security, max(total, len(security))


def reboot_required(manager):
    """True/False, or None when it cannot be determined."""
    if os.path.exists(REBOOT_FLAG):
        return True
    if manager == "apt":
        return False
    # On RHEL 8+ needs-restarting is a dnf plugin, not a standalone binary:
    # only older yum-utils ships it on PATH. Missing this is how a host that
    # has the security kernel installed but is still running the old one gets
    # reported as healthy, so try both forms before giving up.
    for cmd in (["needs-restarting", "-r"], ["dnf", "needs-restarting", "-r"]):
        code, _, err = run(cmd, timeout=60)
        if code == 127:
            continue
        low = err.lower()
        if "no such command" in low or "not a valid command" in low:
            continue
        if code in (0, 1):
            return code == 1
    return None


## State

def state_path():
    """First writable state file location."""
    for path in STATE_CANDIDATES:
        parent = os.path.dirname(path)
        if os.path.isdir(parent) and os.access(parent, os.W_OK):
            return path
    return STATE_CANDIDATES[-1]


def load_state(path):
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return data.get("first_seen", {}) if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(path, first_seen):
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"first_seen": first_seen}, handle)
    except OSError:
        pass  # a read-only host still gets a verdict, just without ageing


def age_of_oldest(packages, first_seen, today):
    """Update the first-seen record and return (age_days, pruned_state).

    Packages no longer pending are dropped so a reinstalled package is not
    credited with the age of a previous occurrence."""
    stamp = today.isoformat()
    updated = {}
    oldest = None
    for name in packages:
        seen = first_seen.get(name, stamp)
        updated[name] = seen
        seen_date = None
        try:
            seen_date = datetime.date.fromisoformat(seen)
        except (ValueError, TypeError):
            seen_date = today
        age = (today - seen_date).days
        if oldest is None or age > oldest:
            oldest = age
    return oldest, updated


## Verdict

def evaluate(manager, security, total, oldest_age, reboot, meta_age,
             first_run=False, grace=None, sla=None, stale_after=None):
    """Decide the verdict. Pure function so the self-test can drive it.

    Returns (state, perfdata, message)."""
    grace = GRACE_DAYS if grace is None else grace
    sla = SLA_DAYS if sla is None else sla
    stale_after = METADATA_STALE_DAYS if stale_after is None else stale_after

    if manager is None:
        return 3, "-", "UNKNOWN: no supported package manager found (apt, dnf)"
    if security is None:
        return 3, "-", "UNKNOWN: %s failed to report pending updates" % manager

    count = len(security)
    perf = "security_updates=%d|total_updates=%d|oldest_days=%d" % (
        count, total or 0, oldest_age or 0,
    )

    # An empty list only means something if the metadata is fresh.
    if meta_age is None:
        return 3, perf, (
            "UNKNOWN: cannot determine %s metadata age, so a result of "
            "%d pending security updates cannot be trusted" % (manager, count)
        )
    if meta_age > stale_after:
        return 3, perf, (
            "UNKNOWN: %s metadata is %.1f days old (limit %d), so "
            "'%d pending' may be hiding updates - refresh the package lists"
            % (manager, meta_age, stale_after, count)
        )

    if count == 0:
        if reboot:
            return 1, perf, (
                "WARNING [%s]: no pending security updates, but a reboot is "
                "required to activate the ones already installed" % CONTROL
            )
        return 0, perf, (
            "OK: no pending security updates (%d other updates, metadata "
            "%.1f days old)" % (total or 0, meta_age)
        )

    # On the very first run there is no history, so every update looks new.
    # Reporting OK here would hand a clean bill of health to a host that may
    # have been neglected for a year. Say what is actually known instead.
    if first_run:
        extra = ", and a reboot is required" if reboot else ""
        return 1, perf, (
            "WARNING [%s]: %d security update%s pending%s - first run on this "
            "host, so how long they have been pending is not yet known; "
            "ageing starts now" % (
                CONTROL, count, "" if count == 1 else "s", extra)
        )

    age = oldest_age or 0
    detail = "%d security update%s pending, oldest first seen %d day%s ago" % (
        count, "" if count == 1 else "s", age, "" if age == 1 else "s",
    )
    if reboot:
        detail += ", reboot also required"

    if age >= sla:
        return 2, perf, (
            "CRITICAL [%s]: %s - past the %d-day remediation deadline"
            % (CONTROL, detail, sla)
        )
    if age >= grace:
        return 1, perf, (
            "WARNING [%s]: %s - deadline is %d days" % (CONTROL, detail, sla)
        )
    if reboot:
        return 1, perf, "WARNING [%s]: %s" % (CONTROL, detail)
    return 0, perf, "OK: %s - within the %d-day grace period" % (detail, grace)


## Self-test

def self_test():
    """Exercise evaluate() and age_of_oldest(); print PASS/FAIL per case."""
    cases = [
        ("no manager is UNKNOWN",
         (None, None, None, None, False, 1.0), 3, "no supported package manager"),
        ("manager failure is UNKNOWN",
         ("apt", None, None, None, False, 1.0), 3, "failed to report"),
        ("stale metadata is UNKNOWN, not OK",
         ("apt", [], 0, 0, False, 30.0), 3, "metadata is 30.0 days old"),
        ("unknown metadata age is UNKNOWN",
         ("apt", [], 0, 0, False, None), 3, "cannot determine"),
        ("clean host is OK",
         ("apt", [], 0, 0, False, 1.0), 0, "no pending security updates"),
        ("clean but reboot pending is WARNING",
         ("apt", [], 0, 0, True, 1.0), 1, "reboot is required"),
        ("fresh security update inside grace is OK",
         ("apt", ["a"], 3, 2, False, 1.0), 0, "within the 7-day grace period"),
        ("past grace is WARNING",
         ("apt", ["a", "b"], 5, 9, False, 1.0), 1, "deadline is 14 days"),
        ("past deadline is CRITICAL",
         ("dnf", ["a"], 1, 21, False, 0.5), 2, "past the 14-day remediation"),
        ("reboot inside grace still WARNS",
         ("apt", ["a"], 1, 1, True, 1.0), 1, "reboot also required"),
    ]

    failures = 0
    for name, args, want_state, want_text in cases:
        manager, security, total, oldest, reboot, meta = args
        state, _, message = evaluate(manager, security, total, oldest, reboot, meta)
        ok = state == want_state and want_text in message
        if not ok:
            failures += 1
        print("%s  %s" % ("PASS" if ok else "FAIL", name))
        if not ok:
            print("      expected state %d containing %r" % (want_state, want_text))
            print("      got      state %d: %s" % (state, message))

    # First run must not hand out an OK it cannot justify.
    state, _, message = evaluate("apt", ["a"], 3, 0, False, 1.0, first_run=True)
    ok = state == 1 and "not yet known" in message
    if not ok:
        failures += 1
    print("%s  first run with pending updates warns instead of OK"
          % ("PASS" if ok else "FAIL"))

    # ...but a genuinely clean host is still OK on its first run.
    state, _, _ = evaluate("apt", [], 0, 0, False, 1.0, first_run=True)
    ok = state == 0
    if not ok:
        failures += 1
    print("%s  first run on a clean host is still OK"
          % ("PASS" if ok else "FAIL"))

    # Ageing: a package seen before keeps its original date.
    today = datetime.date(2026, 10, 29)
    prior = {"pkg-old": "2026-10-01", "pkg-gone": "2026-01-01"}
    age, updated = age_of_oldest(["pkg-old", "pkg-new"], prior, today)
    ok = age == 28 and updated["pkg-old"] == "2026-10-01"
    if not ok:
        failures += 1
    print("%s  oldest pending update is aged from first sighting"
          % ("PASS" if ok else "FAIL"))

    # Packages no longer pending must not linger in the state file.
    ok = "pkg-gone" not in updated
    if not ok:
        failures += 1
    print("%s  resolved packages are pruned from state"
          % ("PASS" if ok else "FAIL"))

    # A newly seen package is zero days old, not negative or absent.
    age, _ = age_of_oldest(["brand-new"], {}, today)
    ok = age == 0
    if not ok:
        failures += 1
    print("%s  newly seen package starts at zero days"
          % ("PASS" if ok else "FAIL"))

    # A corrupted date must not crash the check.
    age, _ = age_of_oldest(["weird"], {"weird": "not-a-date"}, today)
    ok = age == 0
    if not ok:
        failures += 1
    print("%s  malformed stored date degrades safely"
          % ("PASS" if ok else "FAIL"))

    total = len(cases) + 6
    print("\n%d/%d passed" % (total - failures, total))
    sys.exit(1 if failures else 0)


## Check

def check():
    print(LOCAL_SECTION)
    if have("apt-get"):
        manager = "apt"
        security, total = apt_pending()
    elif have("dnf"):
        manager = "dnf"
        security, total = dnf_pending()
    else:
        print(local_line(3, SERVICE, "-",
                         "UNKNOWN: no supported package manager found (apt, dnf)"))
        return

    today = datetime.date.today()
    oldest = None
    first_run = False
    if security:
        path = state_path()
        prior = load_state(path)
        first_run = not prior
        oldest, updated = age_of_oldest(security, prior, today)
        save_state(path, updated)

    state, perf, message = evaluate(
        manager, security, total, oldest,
        reboot_required(manager), metadata_age_days(manager),
        first_run=first_run,
    )
    print(local_line(state, SERVICE, perf, message))


if "--self-test" in sys.argv:
    self_test()
else:
    check()
