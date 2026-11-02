#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

# Twingate client health: is the client online, and is every remote resource
# actually authenticated?
#
# Maps to NIS base measure DE.CM-01: the network is monitored to detect
# potential cybersecurity events. The specific failure this check exists for
# is silent: after a reboot of vm-z1-00, `twingate status` keeps reporting
# "online" while individual resources drop to "AUTH STATUS: Pending". In that
# state the client looks healthy but flows toward those networks are
# suspended by the Twingate service (authorize_flow: SUSPEND in the journal),
# with no error and no alarm. It has happened three times in thirty days; the
# last occurrence left 10.155.100.0/24 unreachable for three days before it
# was noticed. This check makes that state visible instead of silent.
#
# Why the boot time is in the client message: the trigger is the reboot, so a
# "Pending" resource next to a recent boot is the immediate diagnosis, while
# the same "Pending" on a host up for weeks points elsewhere. /proc is local
# and needs no privilege.
#
# Both CLI commands are read-only queries against the local Twingate daemon
# (no network calls); this check never runs `twingate auth` or anything else
# that changes state. It is a passive local check: stdout only.
#
# Emitted services:
#   Twingate.Client            [DE.CM-01] client state + boot time, with
#                                        perfdata resources_total /
#                                        resources_authenticated /
#                                        resources_pending
#   Twingate.Resource.<name>   [DE.CM-01] one per listed resource:
#                                        Pending -> WARNING (flows suspended),
#                                        "expires" -> OK,
#                                        anything else -> UNKNOWN
#
# Compatible with Python 3.9+, the oldest interpreter in the fleet.

import datetime
import re
import subprocess
import sys
import time

VERSION = "1.0.0"

SERVICE = "Twingate.Client"
RESOURCE_SERVICE = "Twingate.Resource"
CONTROL = "DE.CM-01"

# Other checks on the same host may close a piggyback block with <<<<>>>>,
# which leaves no section open. Emitting our own header keeps these lines
# inside the local section regardless of what ran before us.
LOCAL_SECTION = "<<<local:sep(0)>>>"


def local_line(state, service, perfdata, message):
    """Build one CheckMK local-check line: state, service, metrics (or -), detail."""
    return "%s %s %s %s" % (state, service, perfdata or "-", message)


def service_token(value):
    """Resource names can contain spaces; CheckMK service names cannot, so
    anything that is not a service-name character becomes '_'."""
    token = re.sub(r"[^A-Za-z0-9._-]+", "_", value or "").strip("_")
    return token or "unknown"


def run(cmd, timeout=15):
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
    except PermissionError:
        return 126, "", "command not executable"
    except Exception as exc:  # noqa: BLE001 - a check must never raise
        return 1, "", str(exc)


## Parsing

def parse_resources(text):
    """Parse `twingate resources` output into a list of dicts.

    Columns are TAB-separated with space padding:
        RESOURCE NAME\tADDRESS        \tALIAS\tAUTH STATUS
    The header row is skipped, blank lines are ignored, and a resource name
    may itself contain spaces (only TABs are column separators). Returns
    [{"name", "address", "auth_status"}, ...]."""
    resources = []
    for raw in (text or "").splitlines():
        if not raw.strip():
            continue
        cells = [cell.strip() for cell in raw.split("\t")]
        if not cells or not cells[0]:
            continue
        if cells[0].upper() == "RESOURCE NAME":
            continue
        if len(cells) >= 4:
            name, address, auth = cells[0], cells[1], cells[3]
        elif len(cells) == 3:
            name, address, auth = cells[0], cells[1], cells[2]
        else:
            continue
        if not name or not auth:
            continue
        resources.append({"name": name, "address": address, "auth_status": auth})
    return resources


def count_resources(resources):
    """Return (total, authenticated, pending) for a parsed resource list.

    "authenticated" means the AUTH STATUS contains "expires" (the only healthy
    wording); "pending" is the exact reboot-induced failure state."""
    total = len(resources)
    pending = 0
    authenticated = 0
    for resource in resources:
        status = (resource.get("auth_status") or "").strip().lower()
        if status == "pending":
            pending += 1
        elif "expires" in status:
            authenticated += 1
    return total, authenticated, pending


def client_perfdata(resources):
    total, authenticated, pending = count_resources(resources)
    return "resources_total=%d|resources_authenticated=%d|resources_pending=%d" % (
        total, authenticated, pending,
    )


## Verdicts

def resource_verdict(name, address, auth_status):
    """One resource's verdict. Pure so the self-test can drive it.

    Returns (state, message)."""
    status = (auth_status or "").strip()
    low = status.lower()
    if low == "pending":
        return 1, (
            "WARNING [%s]: flows to %s are suspended - resource %s is "
            "'Pending' after a reboot; run `twingate auth %s` to re-authenticate"
            % (CONTROL, address, name, name)
        )
    if "expires" in low:
        return 0, "OK [%s]: %s is authenticated (%s)" % (CONTROL, address, status)
    return 3, (
        "UNKNOWN [%s]: unrecognized AUTH STATUS %r for %s (%s)"
        % (CONTROL, status, name, address)
    )


def evaluate_client(kind, status_text, err, resources, resources_err, boot):
    """Decide the Twingate.Client verdict. Pure so the self-test can drive it.

    kind is 'missing' (binary absent or not executable), 'error' (the status
    command ran but failed) or 'status' (a status string was read). Returns
    (state, perfdata, message)."""
    boot = boot or "uptime unknown"
    perf = client_perfdata(resources) if resources_err is None else "-"
    total, authenticated, pending = count_resources(resources)

    if kind == "missing":
        return 3, "-", (
            "UNKNOWN [%s]: twingate command is not installed or not executable "
            "(%s) - %s" % (CONTROL, err or "command not found", boot)
        )
    if kind == "error":
        return 2, perf, (
            "CRITICAL [%s]: twingate status could not be read (%s) - %s"
            % (CONTROL, err or "status command failed", boot)
        )

    value = (status_text or "").strip()
    if value.lower() != "online":
        return 2, perf, (
            "CRITICAL [%s]: twingate client reports %r instead of 'online' - %s"
            % (CONTROL, value, boot)
        )

    # The client is online; the resource list is a separate query that can
    # still fail, in which case per-resource auth states are simply unchecked.
    if resources_err is not None:
        return 0, perf, (
            "OK [%s]: twingate client is online, but the resource list could "
            "not be read (%s), so per-resource auth states are not checked - %s"
            % (CONTROL, resources_err, boot)
        )
    if pending:
        return 0, perf, (
            "OK [%s]: twingate client is online - %d of %d resources "
            "authenticated, %d pending (see %s services) - %s"
            % (CONTROL, authenticated, total, pending, RESOURCE_SERVICE, boot)
        )
    return 0, perf, (
        "OK [%s]: twingate client is online, all %d resources authenticated - %s"
        % (CONTROL, total, boot)
    )


## Boot time

def format_uptime(seconds):
    """Compact human-readable duration, e.g. '3d 4h 12m'."""
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    parts = []
    if days:
        parts.append("%dd" % days)
    if hours:
        parts.append("%dh" % hours)
    if minutes:
        parts.append("%dm" % minutes)
    if not parts:
        return "%ds" % seconds
    return " ".join(parts)


def boot_info():
    """Last-boot time and uptime, or a graceful fallback."""
    try:
        with open("/proc/stat", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.startswith("btime "):
                    btime = int(line.split()[1])
                    boot_at = datetime.datetime.fromtimestamp(btime)
                    uptime = int(time.time()) - btime
                    return "last boot %s (%s ago)" % (
                        boot_at.strftime("%Y-%m-%d %H:%M:%S"),
                        format_uptime(uptime),
                    )
    except (OSError, ValueError, IndexError):
        pass
    try:
        with open("/proc/uptime", encoding="utf-8", errors="replace") as handle:
            uptime = float(handle.read().split()[0])
        return "uptime %s" % format_uptime(uptime)
    except (OSError, ValueError, IndexError):
        return "uptime unknown"


## Self-test

def self_test():
    """Exercise the pure functions against known data; print PASS/FAIL per case."""
    failures = 0
    ran = 0

    def expect(name, cond, detail=""):
        nonlocal failures, ran
        ran += 1
        if not cond:
            failures += 1
        print("%s  %s" % ("PASS" if cond else "FAIL", name))
        if not cond and detail:
            print("      %s" % detail)

    # Real output shape from `twingate resources` (TAB-separated, padded).
    healthy = (
        "RESOURCE NAME\tADDRESS        \tALIAS\tAUTH STATUS\n"
        "NS          \t192.168.5.0/24 \t-    \tAuth expires in over a week\n"
        "Office      \t10.155.100.0/24\t-    \tAuth expires in over a week\n"
    )
    resources = parse_resources(healthy)
    expect("healthy output parses two resources",
           len(resources) == 2 and resources[0]["name"] == "NS", str(resources))
    expect("padded TAB cells are stripped",
           resources[1]["address"] == "10.155.100.0/24", str(resources[1]))

    st, perf, msg = evaluate_client("status", "online", "", resources, None,
                                    "last boot 2026-11-02 09:00:00 (2h ago)")
    expect("healthy client is OK", st == 0 and "all 2 resources" in msg, msg)
    expect("client perfdata counts resources",
           "resources_total=2|resources_authenticated=2|resources_pending=0" in perf,
           perf)
    expect("boot time is in the client message", "last boot" in msg, msg)

    st, msg = resource_verdict("Office", "10.155.100.0/24", "Auth expires in over a week")
    expect("an 'expires' resource is OK", st == 0, msg)

    # One resource Pending after a reboot.
    one_pending = (
        "RESOURCE NAME\tADDRESS        \tALIAS\tAUTH STATUS\n"
        "NS          \t192.168.5.0/24 \t-    \tAuth expires in over a week\n"
        "Office      \t10.155.100.0/24\t-    \tPending\n"
    )
    resources = parse_resources(one_pending)
    st, msg = resource_verdict("Office", "10.155.100.0/24", "Pending")
    expect("a Pending resource is WARNING",
           st == 1 and "suspended" in msg and "twingate auth Office" in msg, msg)
    st, perf, msg = evaluate_client("status", "online", "", resources, None,
                                    "last boot 2026-11-02 09:00:00 (5m ago)")
    expect("client stays OK while resources are checked per-service",
           st == 0 and "1 pending" in msg, msg)
    expect("pending count reaches the perfdata",
           "resources_pending=1" in perf, perf)

    # Both resources Pending.
    both_pending = (
        "RESOURCE NAME\tADDRESS        \tALIAS\tAUTH STATUS\n"
        "NS          \t192.168.5.0/24 \t-    \tPending\n"
        "Office      \t10.155.100.0/24\t-    \tPending\n"
    )
    resources = parse_resources(both_pending)
    st, perf, msg = evaluate_client("status", "online", "", resources, None,
                                    "last boot 2026-11-02 09:00:00 (5m ago)")
    expect("two Pending resources are counted",
           "resources_total=2" in perf and "resources_pending=2" in perf, perf)

    # Empty output and header-only output both mean "no resources listed".
    expect("empty resource output parses to zero resources",
           parse_resources("") == [], "")
    expect("header-only output parses to zero resources",
           parse_resources("RESOURCE NAME\tADDRESS\tALIAS\tAUTH STATUS\n") == [], "")

    # Missing binary: a single UNKNOWN service, never a crash.
    st, perf, msg = evaluate_client("missing", "", "command not found", [], None,
                                    "uptime unknown")
    expect("missing twingate binary is UNKNOWN",
           st == 3 and "not installed" in msg and perf == "-", msg)

    # Binary present but status command failed.
    st, perf, msg = evaluate_client("error", "", "exit 1", [], None,
                                    "uptime 3d")
    expect("a failed status command is CRITICAL",
           st == 2 and "could not be read" in msg, msg)

    # Status output that is not 'online'.
    st, _, msg = evaluate_client("status", "offline", "", [], None, "uptime 3d")
    expect("a non-online status is CRITICAL and quoted",
           st == 2 and "'offline'" in msg, msg)

    # Unrecognized AUTH STATUS is UNKNOWN with the literal value.
    st, msg = resource_verdict("Office", "10.155.100.0/24", "Weird state")
    expect("an unrecognized AUTH STATUS is UNKNOWN and quoted",
           st == 3 and "'Weird state'" in msg, msg)

    # Resource names with spaces survive parsing but are sanitised in the
    # service name (CheckMK service names cannot contain spaces).
    spaced = parse_resources(
        "RESOURCE NAME\tADDRESS\tALIAS\tAUTH STATUS\n"
        "Office VPC\t10.9.0.0/24\t-\tPending\n"
    )
    expect("a resource name with spaces is kept intact",
           spaced[0]["name"] == "Office VPC", str(spaced))
    expect("service names are sanitised for CheckMK",
           service_token("Office VPC") == "Office_VPC", "")

    print("")
    print("%d/%d passed" % (ran - failures, ran))
    sys.exit(1 if failures else 0)


## Check

def check():
    print(LOCAL_SECTION)
    boot = boot_info()

    code, out, err = run(["twingate", "status"])
    rcode, rout, rerr = run(["twingate", "resources"])

    resources = []
    resources_err = None
    if rcode == 0:
        resources = parse_resources(rout)
    else:
        resources_err = rerr.strip() or ("exit %d" % rcode)

    if code in (126, 127):
        # Not installed / not executable: one UNKNOWN service and nothing else.
        st, perf, msg = evaluate_client("missing", "", err, [], None, boot)
        print(local_line(st, SERVICE, perf, msg))
        return
    if code != 0:
        st, perf, msg = evaluate_client(
            "error", "", err or ("exit %d" % code), resources, resources_err, boot)
    else:
        st, perf, msg = evaluate_client(
            "status", out.strip(), "", resources, resources_err, boot)
    print(local_line(st, SERVICE, perf, msg))

    for resource in resources:
        rstate, rmsg = resource_verdict(
            resource["name"], resource["address"], resource["auth_status"])
        print(local_line(
            rstate,
            "%s.%s" % (RESOURCE_SERVICE, service_token(resource["name"])),
            "-",
            rmsg,
        ))


if "--self-test" in sys.argv:
    self_test()
else:
    check()
