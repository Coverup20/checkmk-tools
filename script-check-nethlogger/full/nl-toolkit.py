#!/usr/bin/python3
#
# Copyright (C) 2025 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

"""nl-toolkit - query NethLogger from the command line.

Sibling of ydea-toolkit.py and freshdesk-toolkit.py: one file in /opt, an .env
beside it, subcommands, and output that can be read as a table or piped as
JSON. Everything it knows about the appliance lives in nl_common.py, so the
CheckMK local check and this tool cannot drift apart.

Commands:
  guard                                validate URL, API key, UI login, location
  list [--hours 24] [--min 0]          assets by log volume
  why <asset> [--sample 500]           volumes, top programs, pattern, remedy
  search <text> [--host H] [--program P] [--level L] [--since 24h] [--limit 100]
  sessions --host H [--since 7d]       login, deduced logout, failed attempts
  silent [--hours 24] [--last-seen]    assets that stopped sending logs
  api <endpoint> [--json]              raw noauth_ endpoint call
  version

Usage:
  nl-toolkit.py why nb-angelo
  nl-toolkit.py search "ambiguous column" --since 7d --host nb-angelo
  nl-toolkit.py sessions --host nb-angelo --since 7d
  nl-toolkit.py list --hours 24 --json | jq '.[0:5]'

Environment: see nl_common.py. NETHLOGGER_ENV selects the env file
(default /opt/nethlogger-toolkit/.env).

Version: 1.0.0
"""

import argparse
import json
import sys
from datetime import timedelta

import nl_common as nl

VERSION = "1.0.0"


## Output

def emit(payload, as_json, headers, rows):
    """Print JSON, or a table with the given headers and rows."""
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=False))
        return
    if not rows:
        print("(no rows)")
        return
    widths = [len(header) for header in headers]
    cells = []
    for row in rows:
        current = [str(cell) for cell in row]
        cells.append(current)
        for index, value in enumerate(current):
            widths[index] = max(widths[index], len(value))
    print("  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    for current in cells:
        print("  ".join(value.ljust(widths[index]) for index, value in enumerate(current)))


def counters_text(counters):
    parts = ["%s=%d" % (level, int(counters.get(level) or 0)) for level in nl.LEVELS
             if int(counters.get(level) or 0) > 0]
    return " ".join(parts) if parts else "none"


## Commands

def cmd_guard(client, args):
    report = {"url": client.base_url, "apikey": False, "ui_login": False,
              "location": bool(client.location), "assets": 0, "errors": []}
    if not client.base_url:
        report["errors"].append("NETHLOGGER_URL is not set")
    else:
        try:
            start, end = nl.parse_window("%dh" % args.hours)
            report["assets"] = len(client.assets(start, end))
            report["apikey"] = True
        except Exception as error:  # noqa: BLE001 - report, do not crash
            report["errors"].append("api: %s" % error)
        if client.has_ui():
            try:
                start, end = nl.parse_window("%dh" % args.hours)
                client.search(program="*", length=1, start=start, end=end)
                report["ui_login"] = True
            except Exception as error:  # noqa: BLE001
                report["errors"].append("ui: %s" % error)
        else:
            report["errors"].append("UI credentials or LOCATION missing")
    rows = [
        ("url", report["url"]),
        ("apikey", "ok" if report["apikey"] else "FAIL"),
        ("ui login", "ok" if report["ui_login"] else "FAIL"),
        ("location", "ok" if report["location"] else "FAIL"),
        ("assets in %dh" % args.hours, str(report["assets"])),
    ]
    if report["errors"]:
        rows.append(("errors", "; ".join(report["errors"])))
    emit(report, args.json, ("check", "value"), rows)
    return 0 if report["apikey"] and report["ui_login"] else 1


def cmd_list(client, args):
    start, end = nl.parse_window("%dh" % args.hours)
    hosts = [host for host in client.assets(start, end) if host["total"] >= args.min]
    if args.limit:
        hosts = hosts[:args.limit]
    rows = [(host["name"], host["total"], counters_text(host["counters"])) for host in hosts]
    emit(hosts, args.json, ("asset", "logs", "counters"), rows)
    return 0


def cmd_why(client, args):
    windows = [item.strip() for item in args.windows.split(",") if item.strip()]
    start, end = nl.parse_window(windows[0])
    known = {host["name"]: host for host in client.assets(start, end)}
    report = {"asset": args.asset, "alias": "", "volumes": [], "programs": [],
              "pattern": None, "remediation": "", "samples": 0, "error": ""}
    if args.asset in known:
        report["alias"] = known[args.asset]["alias"]
    else:
        report["error"] = "asset not in the last %s: check the spelling with `list`" % windows[0]
    report["volumes"] = client.volumes(args.asset, windows=windows)
    if args.sample:
        try:
            rows = client.search(host=args.asset, program="*", level=args.level,
                                 start=start, end=end, length=args.sample)
        except Exception as error:  # noqa: BLE001
            rows = []
            report["error"] = "search: %s" % error
        report["samples"] = len(rows)
        report["programs"] = nl.programs_by_volume(rows)
        patterns = nl.top_patterns(rows)
        if patterns:
            report["pattern"] = patterns[0]
            report["remediation"] = nl.remediation(patterns[0]["program"], patterns[0]["pattern"])
    if args.json:
        emit(report, True, (), ())
        return 0
    print("%s%s" % (report["asset"], "  (%s)" % report["alias"] if report["alias"] else ""))
    print()
    for volume in report["volumes"]:
        print("  %-4s %12d  %s" % (volume["window"], volume["total"], counters_text(volume["counters"])))
    if report["error"]:
        print("\n  note: %s" % report["error"])
    if report["programs"]:
        print("\n  programs in the last %s (%d rows sampled):" % (windows[0], report["samples"]))
        for entry in report["programs"]:
            print("    %-32s %6d  %5.1f%%" % (entry["program"], entry["count"], entry["share"]))
    if report["pattern"]:
        pattern = report["pattern"]
        print("\n  dominant: %s %.0f%%" % (pattern["program"], pattern["program_share"]))
        print("  pattern:  %s" % pattern["pattern"])
        print("  remedy:   %s" % report["remediation"])
    return 0


def cmd_search(client, args):
    start, end = nl.parse_window(args.since)
    rows = client.search(host=args.host, program=args.program, level=args.level,
                         msg=args.text, start=start, end=end, length=args.limit)
    if args.json:
        emit(rows, True, (), ())
        return 0
    table = [(row.get("date") or "", row.get("time") or "", row.get("host") or "",
              row.get("priority") or "", (row.get("program") or "")[:20],
              (row.get("msg") or "").replace("\n", " ")[:100]) for row in rows]
    emit(rows, False, ("date", "time", "host", "prio", "program", "message"), table)
    return 0


def cmd_sessions(client, args):
    start, end = nl.parse_window(args.since)
    events = nl.sessions(client, args.host, start, end, length=args.limit)
    summary = nl.session_summary(events)
    if args.json:
        emit({"host": args.host, "since": args.since, "summary": summary, "events": events},
             True, (), ())
        return 0
    print("%s, last %s: %d events" % (args.host, args.since, len(events)))
    if summary:
        print()
        print("  %-20s %6s %7s %5s %5s" % ("user", "logins", "logouts", "ends", "fails"))
        for entry in summary:
            print("  %-20s %6d %7d %5d %5d" % (entry["user"], entry["logins"],
                                                entry["logouts"], entry["ends"], entry["fails"]))
    if events:
        print()
        for event in events:
            print("  %s %s  %-10s %-18s %s" % (event["date"], event["time"], event["kind"],
                                                event["program"], event["user"]))
    return 0


def cmd_silent(client, args):
    start, end = nl.parse_window("%dh" % args.hours)
    quiet = [host for host in client.assets(start, end) if host["total"] == 0]
    quiet.sort(key=lambda item: item["name"])
    report = []
    for host in quiet[:args.max]:
        entry = {"asset": host["name"], "alias": host["alias"], "last_seen": ""}
        if args.last_seen:
            try:
                rows = client.search(host=host["name"], program="*",
                                     start=start - timedelta(days=args.last_seen_days),
                                     end=end, length=1)
                if rows:
                    entry["last_seen"] = "%s %s" % (rows[0].get("date") or "", rows[0].get("time") or "")
            except Exception as error:  # noqa: BLE001
                entry["last_seen"] = "error: %s" % error
        report.append(entry)
    if args.json:
        emit(report, True, (), ())
        return 0
    print("assets with no logs in the last %dh: %d (showing %d)"
          % (args.hours, len(quiet), len(report)))
    rows = [(entry["asset"], entry["alias"], entry["last_seen"] or "-") for entry in report]
    emit(report, False, ("asset", "alias", "last seen"), rows)
    return 0


def cmd_api(client, args):
    start = end = None
    if args.since:
        start, end = nl.parse_window(args.since)
    payload = client.api(args.endpoint, start, end)
    if args.json:
        emit(payload, True, (), ())
        return 0
    print(json.dumps(payload, indent=2)[:args.head])
    return 0


## Entry point

def build_parser():
    parser = argparse.ArgumentParser(
        prog="nl-toolkit.py",
        description="Query NethLogger from the command line.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--env", default=None, help="env file (default NETHLOGGER_ENV or /opt/nethlogger-toolkit/.env)")
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    parser.add_argument("--debug", action="store_true", help="show tracebacks")
    subs = parser.add_subparsers(dest="command", required=True)

    guard = subs.add_parser("guard", help="validate configuration and both transports")
    guard.add_argument("--hours", type=int, default=24)
    guard.set_defaults(func=cmd_guard)

    listing = subs.add_parser("list", help="assets by log volume")
    listing.add_argument("--hours", type=int, default=24)
    listing.add_argument("--min", type=int, default=0)
    listing.add_argument("--limit", type=int, default=0)
    listing.set_defaults(func=cmd_list)

    why = subs.add_parser("why", help="volumes, programs, pattern and remedy for one asset")
    why.add_argument("asset")
    why.add_argument("--windows", default="24h,7d,30d", help="comma separated, newest first")
    why.add_argument("--sample", type=int, default=500, help="rows to sample, 0 to skip")
    why.add_argument("--level", default="err", help="level sampled: err, warning, info or empty for all")
    why.set_defaults(func=cmd_why)

    search = subs.add_parser("search", help="free text search in the logs")
    search.add_argument("text")
    search.add_argument("--host")
    search.add_argument("--program", default="*", help="program name, * for all")
    search.add_argument("--level", default="", help="err, warning, info, debug or empty for all")
    search.add_argument("--since", default="24h")
    search.add_argument("--limit", type=int, default=100)
    search.set_defaults(func=cmd_search)

    sessions = subs.add_parser("sessions", help="login, logout and failed attempts of one asset")
    sessions.add_argument("--host", required=True)
    sessions.add_argument("--since", default="7d")
    sessions.add_argument("--limit", type=int, default=500)
    sessions.set_defaults(func=cmd_sessions)

    silent = subs.add_parser("silent", help="assets that stopped sending logs")
    silent.add_argument("--hours", type=int, default=24)
    silent.add_argument("--last-seen", action="store_true", help="look up the last row per asset (slow)")
    silent.add_argument("--last-seen-days", type=int, default=30)
    silent.add_argument("--max", type=int, default=25)
    silent.set_defaults(func=cmd_silent)

    api = subs.add_parser("api", help="raw API call")
    api.add_argument("endpoint", choices=nl.API_ENDPOINTS)
    api.add_argument("--since", default="", help="window for getstats/getcyber")
    api.add_argument("--head", type=int, default=4000, help="bytes printed when not --json")
    api.set_defaults(func=cmd_api)

    version = subs.add_parser("version", help="show versions")
    version.set_defaults(func=None)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "version":
        print("nl-toolkit.py %s (nl_common %s)" % (VERSION, nl.VERSION))
        return 0
    client = nl.NethLogger(args.env)
    try:
        return args.func(client, args)
    except KeyboardInterrupt:
        return 130
    except Exception as error:  # noqa: BLE001 - the CLI reports, it does not trace
        if args.debug:
            raise
        print("error: %s" % error, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
