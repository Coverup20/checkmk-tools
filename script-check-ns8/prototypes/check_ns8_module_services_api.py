#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

# The systemd services of every installed NS8 module: one CheckMK service per
# module, plus a node roll-up.
#
# WHY THIS DOES NOT USE THE NS8 API, even though an API action exists.
# module/<id>/get-status returns exactly the right data, and the first version
# of this check used it. It had to be withdrawn from the reference node the
# same day, because every call to the NS8 task system:
#   - leaked hundreds of Redis connections inside api-server (measured: +706
#     for one API check, +2532 for a full agent run, growing ~1300/min until
#     api-server reached maxclients and stopped authenticating anybody), and
#   - raised a banner notification in the cluster-admin interface, one per
#     call. With one task per module, this check alone produced eleven
#     notifications every run and made the interface unusable for the operator.
# A monitoring check must not damage the system it watches, so this version
# reads systemd directly through runagent. That is a local subprocess rather
# than the REST call the other prototypes prefer, and it is the deliberate
# trade: no tasks, no leaked connections, no notifications.
#
# The Podman socket was evaluated as a REST alternative and rejected: it lists
# containers, not systemd units, so it cannot see a failed oneshot or timer
# unit. On the reference node that is precisely what was broken - nethvoice1's
# reports-scheduler.service - so a container-only view would have reported the
# node healthy.
#
# The false positive this check avoids:
# modules legitimately contain units that are loaded but not running -
# get-certificate, grub-boot-success, systemd-tmpfiles-clean, socket-activated
# podman. They are oneshot or timer units sitting idle between runs. Treating
# "not active" as a fault would make every module warn forever on a healthy
# node, and an alarm that never stops is an alarm nobody reads.
#   failed          -> CRITICAL, named. Unambiguous.
#   inactive        -> idle, reported but not a fault, unless the unit is
#                      listed in CHECK_NS8_SERVICES_REQUIRE_ACTIVE
#   no units at all -> UNKNOWN. A module that reports nothing is blind, not
#                      healthy.
#
# Emitted services:
#   NS8.Services            [DE.CM-01] roll-up across every installed module
#   NS8.Services.<module>   [DE.CM-01] one per module instance
#
# Compatible with Python 3.9+ (Rocky Linux 9).

import os
import re
import subprocess
import sys

VERSION = "2.0.0"

SVC_ROLLUP = "NS8.Services"
CTRL = "DE.CM-01"

HOME_ROOT = os.environ.get("CHECK_NS8_SERVICES_HOME_ROOT", "/home")
RUNAGENT = os.environ.get("CHECK_NS8_SERVICES_RUNAGENT", "runagent")
UNIT_TIMEOUT = float(os.environ.get("CHECK_NS8_SERVICES_UNIT_TIMEOUT", "20"))

# Units that must be running; anything here that is loaded but inactive is
# escalated instead of being reported as idle. Empty by default on purpose:
# which units matter is a per-deployment decision, not something to guess.
REQUIRE_ACTIVE = set(
    name.strip()
    for name in os.environ.get("CHECK_NS8_SERVICES_REQUIRE_ACTIVE", "").split(",")
    if name.strip()
)

LOCAL_SECTION = "<<<local:sep(0)>>>"

RE_MODULE_ID = re.compile(r"^MODULE_ID=(?P<id>[A-Za-z0-9_.-]+)\s*$")


def local_line(state, service, perfdata, message):
    """Build one CheckMK local-check line: state, service, metrics (or -), detail."""
    return "%d %s %s %s" % (state, service, perfdata or "-", message)


def service_token(value):
    token = re.sub(r"[^A-Za-z0-9._-]+", "_", value or "").strip("_")
    return token or "unknown"


def discover_modules(home_root=None):
    """Find installed module instances locally: each owns a system user whose
    home holds .config/state/environment with a MODULE_ID line."""
    root = home_root or HOME_ROOT
    found = []
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return []
    for entry in entries:
        env_path = os.path.join(root, entry, ".config", "state", "environment")
        try:
            with open(env_path, encoding="utf-8") as handle:
                for line in handle:
                    match = RE_MODULE_ID.match(line.strip())
                    if match:
                        found.append(match.group("id"))
                        break
        except OSError:
            continue
    return sorted(set(found))


def parse_units(text):
    """Parse `systemctl --user list-units --no-legend --plain` output.

    Columns: UNIT LOAD ACTIVE SUB DESCRIPTION. A unit whose ACTIVE or SUB
    column reads "failed" is failed; "active" is running; anything else
    (inactive, deactivating) is idle."""
    units = []
    for raw in (text or "").splitlines():
        parts = raw.split()
        if len(parts) < 4:
            continue
        name, _load, active, sub = parts[0], parts[1], parts[2], parts[3]
        if not name.endswith(".service"):
            continue
        if active == "failed" or sub == "failed":
            state = "failed"
        elif active == "active":
            state = "running"
        else:
            state = "idle"
        units.append({"name": name[: -len(".service")], "state": state})
    return units


def collect_units(module):
    """Read one module's systemd user units. Returns (units, error)."""
    try:
        result = subprocess.run(
            [
                RUNAGENT, "-m", module,
                "systemctl", "--user", "list-units",
                "--type=service", "--all", "--no-legend", "--plain",
            ],
            capture_output=True,
            text=True,
            timeout=UNIT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return [], "runagent-failed"
    if result.returncode != 0:
        return [], "systemctl-exit-%d" % result.returncode
    return parse_units(result.stdout), ""


def classify_units(units):
    """Split units into running / idle / failed / required-but-idle."""
    running, idle, failed, must_run = [], [], [], []
    for unit in units:
        name = unit.get("name") or "(unnamed)"
        state = unit.get("state")
        if state == "failed":
            failed.append(name)
        elif state == "running":
            running.append(name)
        elif name in REQUIRE_ACTIVE:
            must_run.append(name)
        else:
            idle.append(name)
    return running, idle, failed, must_run


def evaluate_module(module, units, err):
    """One module's service health."""
    running, idle, failed, must_run = classify_units(units or [])
    total = len(running) + len(idle) + len(failed) + len(must_run)
    # "services_idle" rather than bare "idle": CheckMK's built-in metric "idle"
    # is CPU idle percentage, so using that name graphs idle systemd units as "%"
    # and collides with cmk.plugins.collection.graphing.cpu_util.
    perf = "services=%d|running=%d|services_idle=%d|failed=%d" % (
        total, len(running), len(idle), len(failed) + len(must_run)
    )
    if err:
        return (
            3, perf,
            "UNKNOWN [%s]: the services of module %s could not be read (%s) - "
            "this is not evidence that they are healthy" % (CTRL, module, err),
        )
    if total == 0:
        return (
            3, perf,
            "UNKNOWN [%s]: module %s reported no services at all - a module "
            "that reports nothing is blind, not healthy" % (CTRL, module),
        )
    if failed:
        return (
            2, perf,
            "CRITICAL [%s]: module %s has %d failed service(s): %s; %d running, %d idle"
            % (CTRL, module, len(failed), ", ".join(sorted(failed)),
               len(running), len(idle)),
        )
    if must_run:
        return (
            1, perf,
            "WARNING [%s]: module %s has %d service(s) required to be running "
            "but idle: %s; %d running"
            % (CTRL, module, len(must_run), ", ".join(sorted(must_run)), len(running)),
        )
    message = "OK [%s]: module %s - %d of %d services running" % (
        CTRL, module, len(running), total
    )
    if idle:
        message += ", %d idle (oneshot/timer/socket-activated: %s)" % (
            len(idle), ", ".join(sorted(idle)[:4])
        )
    return (0, perf, message)


def evaluate_rollup(results, discovered):
    """Node-wide summary across every module."""
    failed_modules = [n for n, (st, _p, _m) in results.items() if st == 2]
    warn_modules = [n for n, (st, _p, _m) in results.items() if st == 1]
    unknown_modules = [n for n, (st, _p, _m) in results.items() if st == 3]
    perf = "modules=%d|modules_failed=%d|modules_warning=%d|modules_unknown=%d" % (
        len(results), len(failed_modules), len(warn_modules), len(unknown_modules)
    )
    if not discovered:
        return (
            3, perf,
            "UNKNOWN [%s]: no NS8 module was found on this node - either none "
            "is installed or module discovery failed" % CTRL,
        )
    parts = []
    state = 0
    if failed_modules:
        state = 2
        parts.append("%d module(s) with failed services: %s"
                     % (len(failed_modules), ", ".join(sorted(failed_modules))))
    if warn_modules:
        state = max(state, 1)
        parts.append("%d module(s) with services expected to run but idle: %s"
                     % (len(warn_modules), ", ".join(sorted(warn_modules))))
    if unknown_modules:
        state = 3 if state == 0 else state
        parts.append("%d module(s) could not be read: %s"
                     % (len(unknown_modules), ", ".join(sorted(unknown_modules))))
    if not parts:
        return (0, perf,
                "OK [%s]: all %d installed modules report their services healthy"
                % (CTRL, len(results)))
    label = {0: "OK", 1: "WARNING", 2: "CRITICAL", 3: "UNKNOWN"}[state]
    return (state, perf, "%s [%s]: %s" % (label, CTRL, "; ".join(parts)))


def self_test():
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

    # Real output shape from `runagent -m samba1 systemctl --user list-units`.
    sample = (
        "agent.service loaded active running Rootless module/samba1 agent\n"
        "get-certificate.service loaded inactive dead Get TLS certificate\n"
        "samba-dc.service loaded active running Samba DC and File Server\n"
        "timescaledb.service loaded active running TimescaleDB for Samba Audit logs\n"
        "some.timer loaded active waiting A timer, not a service\n"
    )
    units = parse_units(sample)
    expect("only .service units are considered",
           len(units) == 4 and all(u["name"] != "some" for u in units), str(units))
    expect("the .service suffix is stripped for readability",
           any(u["name"] == "samba-dc" for u in units), str(units))

    running, idle, failed, _mr = classify_units(units)
    expect("running units are detected",
           sorted(running) == ["agent", "samba-dc", "timescaledb"], str(running))
    expect("an inactive oneshot unit is idle, not failed",
           idle == ["get-certificate"] and failed == [], str((idle, failed)))

    st, perf, msg = evaluate_module("samba1", units, "")
    expect("a healthy module is OK despite an idle oneshot unit",
           st == 0 and "3 of 4 services running" in msg, msg)
    expect("idle units are explained rather than hidden",
           "oneshot/timer/socket-activated" in msg, msg)
    expect("perfdata counts services", "services=4|running=3" in perf, perf)

    # The real fault found on the reference node.
    broken = parse_units(
        "reports-scheduler.service loaded failed failed Generate reports\n"
        "freepbx.service loaded active running FreePBX\n"
    )
    st, _perf, msg = evaluate_module("nethvoice1", broken, "")
    expect("a failed unit is CRITICAL and named",
           st == 2 and "reports-scheduler" in msg, msg)

    st, _perf, msg = evaluate_module("x1", [], "")
    expect("a module reporting no services is UNKNOWN, not healthy",
           st == 3 and "blind, not healthy" in msg, msg)

    st, _perf, msg = evaluate_module("x1", [], "runagent-failed")
    expect("an unreadable module is UNKNOWN, never OK",
           st == 3 and "not evidence that they are healthy" in msg, msg)

    global REQUIRE_ACTIVE
    saved = REQUIRE_ACTIVE
    REQUIRE_ACTIVE = {"get-certificate"}
    st, _perf, msg = evaluate_module("samba1", units, "")
    expect("a unit listed as required-to-run escalates when idle",
           st == 1 and "get-certificate" in msg, msg)
    REQUIRE_ACTIVE = saved

    results = {"samba1": (0, "", "ok"), "mail1": (0, "", "ok")}
    st, perf, msg = evaluate_rollup(results, ["samba1", "mail1"])
    expect("all healthy modules roll up to OK",
           st == 0 and "all 2 installed modules" in msg, msg)
    expect("roll-up perfdata counts modules", "modules=2" in perf, perf)

    results["nethvoice1"] = (2, "", "crit")
    st, _perf, msg = evaluate_rollup(results, ["samba1", "mail1", "nethvoice1"])
    expect("a failed module makes the roll-up CRITICAL",
           st == 2 and "nethvoice1" in msg, msg)

    st, _perf, msg = evaluate_rollup({"samba1": (3, "", "u")}, ["samba1"])
    expect("an unreadable module makes the roll-up UNKNOWN",
           st == 3 and "could not be read" in msg, msg)

    st, _perf, msg = evaluate_rollup({}, [])
    expect("no modules discovered is UNKNOWN, not OK",
           st == 3 and "no NS8 module was found" in msg, msg)

    expect("module names are safe for service names",
           service_token("nethvoice-proxy2") == "nethvoice-proxy2", "")

    print("")
    print("%d/%d checks passed" % (ran - failures, ran))
    sys.exit(1 if failures else 0)


def check():
    modules = discover_modules()
    print(LOCAL_SECTION)
    if not modules:
        st, perf, msg = evaluate_rollup({}, [])
        print(local_line(st, SVC_ROLLUP, perf, msg))
        return

    results = {}
    for module in modules:
        units, err = collect_units(module)
        results[module] = evaluate_module(module, units, err)

    st, perf, msg = evaluate_rollup(results, modules)
    print(local_line(st, SVC_ROLLUP, perf, msg))

    for module in modules:
        state, perfdata, message = results[module]
        print(local_line(state, "%s.%s" % (SVC_ROLLUP, service_token(module)),
                         perfdata, message))


if "--self-test" in sys.argv:
    self_test()
else:
    check()
