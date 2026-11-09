#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

# Check whether the running OS still receives security updates.
#
# Maps to NIS base measure PR.PS-02.1: only software for which security
# updates are guaranteed may be installed. An OS past its end of security
# support is a direct violation of that requirement.
#
# The lifecycle table is embedded on purpose: a local check runs on every
# host at every cycle, so it must not depend on an external service to
# produce a verdict, and must work on hosts with no egress. The table is
# refreshed when this script is deployed. DATA_AS_OF guards against silent
# rot: stale data can only make a "still supported" verdict wrong, never an
# "already end-of-life" one, so staleness downgrades OK to UNKNOWN and
# leaves the other verdicts untouched.
#
# Source of the dates: endoflife.date, cross-checked against the vendor
# lifecycle pages. Regenerate with script-tools before each release.

import sys
import os
import datetime

SERVICE = "OS.Lifecycle"
CONTROL = "PR.PS-02.1"
VERSION = "1.0.1"

OS_RELEASE = "/etc/os-release"

# Date the embedded table was last refreshed (ISO 8601).
DATA_AS_OF = "2026-10-29"

# Beyond this, a "supported" verdict is no longer trustworthy.
STALE_AFTER_DAYS = 180

# How long before end of support to start warning.
WARN_BEFORE_DAYS = 180

# (os_id, release) -> (end of free security support, end of extended support)
# Extended support is Ubuntu Pro ESM / Debian ELTS: it exists only with an
# active paid subscription, which this check cannot verify from the host.
LIFECYCLE = {
    ("ubuntu", "18.04"): ("2023-05-31", "2028-04-26"),
    ("ubuntu", "20.04"): ("2025-05-31", "2030-04-23"),
    ("ubuntu", "22.04"): ("2027-06-01", "2032-04-21"),
    ("ubuntu", "24.04"): ("2029-05-31", "2034-04-25"),
    ("ubuntu", "26.04"): ("2031-05-29", "2036-04-23"),
    ("ubuntu", "23.10"): ("2024-07-12", None),
    ("ubuntu", "24.10"): ("2025-07-10", None),
    ("ubuntu", "25.04"): ("2026-01-17", None),
    ("ubuntu", "25.10"): ("2026-07-01", None),
    ("ubuntu", "26.10"): ("2027-07-01", None),
    ("debian", "9"): ("2022-07-01", "2027-06-30"),
    ("debian", "10"): ("2024-06-30", "2029-06-30"),
    ("debian", "11"): ("2026-08-31", "2031-06-30"),
    ("debian", "12"): ("2028-06-30", "2033-06-30"),
    ("debian", "13"): ("2030-06-30", "2035-06-30"),
    ("rocky", "8"): ("2029-05-31", None),
    ("rocky", "9"): ("2032-05-31", None),
    ("rocky", "10"): ("2035-05-31", None),
}

# Distributions whose VERSION_ID carries a minor we must drop (9.5 -> 9).
MAJOR_ONLY = ("debian", "rocky", "rhel", "almalinux", "centos")

## Useful

def parse_os_release(path=OS_RELEASE):
    """Return the /etc/os-release key/value pairs as a dict."""
    data = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                data[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        return {}
    return data


def identify(data):
    """Map os-release fields to a (os_id, release) lookup key."""
    os_id = (data.get("ID") or "").strip().lower()
    version_id = (data.get("VERSION_ID") or "").strip()
    if not os_id or not version_id:
        return None, None
    if os_id in MAJOR_ONLY:
        version_id = version_id.split(".")[0]
    return os_id, version_id


def parse_date(value):
    """Parse an ISO date, or return None."""
    try:
        return datetime.date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def days_between(start, end):
    """Whole days from start to end, negative when end is in the past."""
    return (end - start).days


# Other checks on the same host may close a piggyback block with <<<<>>>>,
# which leaves no section open. Emitting our own header keeps these lines
# inside the local section regardless of what ran before us.
LOCAL_SECTION = "<<<local:sep(0)>>>"


def local_line(state, service, perfdata, message):
    """Build one CheckMK local-check line: state, service, metrics (or -), detail."""
    return f"{state} {service} {perfdata or '-'} {message}"


def evaluate(os_id, release, today, table=None, data_as_of=DATA_AS_OF):
    """Decide the verdict. Pure function so the self-test can drive it.

    Returns (state, perfdata, message)."""
    table = LIFECYCLE if table is None else table

    if not os_id or not release:
        return 3, "-", "UNKNOWN: cannot determine OS from " + OS_RELEASE

    label = f"{os_id} {release}"
    entry = table.get((os_id, release))
    if entry is None:
        return 3, "-", f"UNKNOWN: no lifecycle data for {label}"

    eol = parse_date(entry[0])
    eoes = parse_date(entry[1]) if entry[1] else None
    if eol is None:
        return 3, "-", f"UNKNOWN: malformed lifecycle data for {label}"

    left = days_between(today, eol)
    perf = f"days_to_eol={left}"

    # Already past free security support.
    if left < 0:
        gone = -left
        if eoes and today < eoes:
            ext_left = days_between(today, eoes)
            return 1, perf, (
                f"WARNING [{CONTROL}]: {label} left standard security support "
                f"on {eol} ({gone} days ago); covered by extended support until "
                f"{eoes} ({ext_left} days), which needs an active subscription "
                f"this check cannot verify - confirm it is in place"
            )
        return 2, perf, (
            f"CRITICAL [{CONTROL}]: {label} lost security support on {eol} "
            f"({gone} days ago) and has no extended support - "
            f"security updates are no longer guaranteed"
        )

    # Still supported: a stale table could be hiding a newer end date.
    refreshed = parse_date(data_as_of)
    if refreshed is None:
        return 3, perf, f"UNKNOWN: malformed DATA_AS_OF value {data_as_of!r}"
    age = days_between(refreshed, today)
    if age > STALE_AFTER_DAYS:
        return 3, perf, (
            f"UNKNOWN: lifecycle data is {age} days old (refreshed {data_as_of}); "
            f"cannot confirm {label} is still supported - redeploy this check"
        )

    if left <= WARN_BEFORE_DAYS:
        return 1, perf, (
            f"WARNING [{CONTROL}]: {label} reaches end of security support "
            f"on {eol} ({left} days left) - plan the upgrade"
        )

    return 0, perf, f"OK: {label} supported until {eol} ({left} days left)"


## Self-test

def self_test():
    """Exercise evaluate() against known data and report PASS/FAIL per case."""
    today = datetime.date(2026, 10, 29)
    table = {
        ("ubuntu", "24.04"): ("2029-05-31", "2034-04-25"),
        ("ubuntu", "23.10"): ("2024-07-12", None),
        ("ubuntu", "20.04"): ("2025-05-31", "2030-04-23"),
        ("debian", "11"): ("2026-08-31", "2031-06-30"),
        # EOL still ahead but inside WARN_BEFORE_DAYS of the test date.
        ("nearly", "1"): ("2026-12-15", None),
        ("broken", "1"): ("not-a-date", None),
    }

    cases = [
        ("supported release is OK", ("ubuntu", "24.04"), 0, "supported until"),
        ("EOL with no extended support is CRITICAL", ("ubuntu", "23.10"), 2, "no extended support"),
        ("EOL but under ESM is WARNING", ("ubuntu", "20.04"), 1, "extended support until"),
        ("EOL ahead but inside the warning window", ("nearly", "1"), 1, "end of security support"),
        ("EOL past, ELTS still running", ("debian", "11"), 1, "extended support until"),
        ("unknown release is UNKNOWN", ("ubuntu", "99.04"), 3, "no lifecycle data"),
        ("missing os-release is UNKNOWN", (None, None), 3, "cannot determine OS"),
        ("malformed date is UNKNOWN", ("broken", "1"), 3, "malformed lifecycle data"),
    ]

    failures = 0
    for name, (os_id, release), want_state, want_text in cases:
        state, _, message = evaluate(os_id, release, today, table=table)
        ok = state == want_state and want_text in message
        if not ok:
            failures += 1
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            print(f"      expected state {want_state} containing {want_text!r}")
            print(f"      got      state {state}: {message}")

    # Stale embedded data must not be reported as a healthy OK.
    state, _, message = evaluate(
        "ubuntu", "24.04", today, table=table, data_as_of="2025-01-01"
    )
    ok = state == 3 and "lifecycle data is" in message
    if not ok:
        failures += 1
    print(f"{'PASS' if ok else 'FAIL'}  stale data downgrades OK to UNKNOWN")

    # Staleness must not soften an already-CRITICAL verdict.
    state, _, _ = evaluate(
        "ubuntu", "23.10", today, table=table, data_as_of="2025-01-01"
    )
    ok = state == 2
    if not ok:
        failures += 1
    print(f"{'PASS' if ok else 'FAIL'}  stale data leaves CRITICAL untouched")

    # Every shipped entry must be parseable.
    bad = [k for k, v in LIFECYCLE.items()
           if parse_date(v[0]) is None or (v[1] and parse_date(v[1]) is None)]
    ok = not bad
    if not ok:
        failures += 1
    print(f"{'PASS' if ok else 'FAIL'}  embedded table parses ({len(LIFECYCLE)} entries)")
    if bad:
        print(f"      malformed: {bad}")

    total = len(cases) + 3
    print(f"\n{total - failures}/{total} passed")
    sys.exit(1 if failures else 0)


## Check

def check():
    print(LOCAL_SECTION)
    if not os.path.exists(OS_RELEASE):
        print(local_line(3, SERVICE, "-", f"UNKNOWN: {OS_RELEASE} not found"))
        return
    os_id, release = identify(parse_os_release())
    state, perf, message = evaluate(os_id, release, datetime.date.today())
    print(local_line(state, SERVICE, perf, message))


if "--self-test" in sys.argv:
    self_test()
else:
    check()
