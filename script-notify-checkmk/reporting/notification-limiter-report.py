#!/usr/bin/env python3
"""
notification-limiter-report.py — Checkmk notification limiter report generator.

Reads JSON Lines diagnostic logs from M@il-20 and Telegram-20 and produces
a human-readable email report showing exactly how the notification limiter
behaved over a selected time window.

Usage:
  # Default: last 24 hours, dry-run to stdout
  python3 notification-limiter-report.py --dry-run

  # With sample/copied logs
  python3 notification-limiter-report.py \\
    --mail-log /path/to/mail-20.log \\
    --telegram-log /path/to/telegram-20.log \\
    --since-hours 24 --dry-run

  # Send email via sendmail
  python3 notification-limiter-report.py --to-email admin@example.com

  # Cron: 13:00 report (previous 19 hours)
  python3 notification-limiter-report.py \\
    --since-hours 19 \\
    --to-email admin@example.com \\
    --subject-prefix "[Checkmk] Notification limiter report 18-13"

  # Cron: 18:00 report (previous 5 hours)
  python3 notification-limiter-report.py \\
    --since-hours 5 \\
    --to-email admin@example.com \\
    --subject-prefix "[Checkmk] Notification limiter report 13-18"
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_VERSION = "1.0.0"
SCRIPT_NAME = "notification-limiter-report"

DEFAULT_LOG_PATHS = {
    "mail": "/omd/sites/monitoring/var/log/notifications/mail-20.log",
    "telegram": "/omd/sites/monitoring/var/log/notifications/telegram-20.log",
}

DEFAULT_DETAIL_LIMIT = 200
DEFAULT_SINCE_HOURS = 24
DEFAULT_FROM_EMAIL = "srv-monitoring-us@nethesis.it"


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------

_LOG_TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})")


def _parse_log_line_ts(line):
    """Extract the ISO-ish timestamp from a log line prefix.

    Returns a datetime.datetime or None.
    """
    m = _LOG_TS_RE.match(line)
    if m:
        try:
            return datetime.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return None


def _parse_record_ts(rec):
    """Try to extract a datetime from a record's timestamp field.

    Supports ISO strings and Unix epoch integers.
    Returns a datetime.datetime or None.
    """
    ts = rec.get("timestamp")
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        try:
            return datetime.datetime.fromtimestamp(ts)
        except (OSError, ValueError):
            return None
    if isinstance(ts, str):
        for fmt in (
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
        ):
            try:
                return datetime.datetime.strptime(ts, fmt)
            except ValueError:
                continue
    return None


# ---------------------------------------------------------------------------
# JSON Lines parsing
# ---------------------------------------------------------------------------


class LogFileStats:
    """Tracks per-file parse statistics."""

    def __init__(self, name):
        self.name = name
        self.total_lines = 0
        self.bad_json = 0
        self.records = []  # list of parsed dicts
        self.unknown_events = Counter()

    @property
    def total_records(self):
        return len(self.records)


def parse_log_file(path, label, logger):
    """Parse a JSON Lines log file.

    Returns a LogFileStats object.  Never raises — bad lines are counted.
    """
    stats = LogFileStats(label)
    pp = Path(path)
    if not pp.exists():
        logger.missing_files.append(str(path))
        return stats

    logger.files_read.append(str(path))

    for line in pp.read_text(errors="replace").splitlines():
        stats.total_lines += 1
        # Find the JSON part after NOTIFY_EVENT marker
        if "NOTIFY_EVENT " not in line:
            continue
        raw = line.split("NOTIFY_EVENT ", 1)[1]
        try:
            rec = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            stats.bad_json += 1
            continue

        # Attach the log-line timestamp as a fallback
        log_ts = _parse_log_line_ts(line)
        if log_ts is not None and "timestamp" not in rec:
            rec["_log_ts"] = log_ts

        rec["_source"] = label
        rec["_raw_line"] = line
        stats.records.append(rec)

    logger.total_raw_lines += stats.total_lines
    return stats


# ---------------------------------------------------------------------------
# Data quality logger
# ---------------------------------------------------------------------------


class DataQuality:
    """Collects data-quality statistics during report generation."""

    def __init__(self):
        self.files_read = []
        self.missing_files = []
        self.total_raw_lines = 0
        self.bad_json_records = 0
        self.outside_period = 0
        self.unknown_events = Counter()
        self.missing_host = 0
        self.missing_category = 0
        self.missing_execution_id = 0

    def add_bad_json(self, count):
        self.bad_json_records += count

    def record_event(self, status):
        if status not in _KNOWN_EVENTS:
            self.unknown_events[status] += 1


_KNOWN_EVENTS = frozenset({
    "INVOKED", "ACCEPTED", "DECISION", "DELIVERING", "DELIVERED",
    "COMPLETE", "FAILED", "ERROR",
    "COOLDOWN_DECISION", "WOULD_SUPPRESS_COOLDOWN", "SUPPRESSED_COOLDOWN",
    "COOLDOWN_BYPASS_RECOVERY", "ADAPTIVE_COOLDOWN_RECOMMENDATION",
    "SUPPRESSED", "WOULD_SUPPRESS", "AUDIT_NOT_SUPPRESSED",
})


# ---------------------------------------------------------------------------
# Time window filtering
# ---------------------------------------------------------------------------


def in_window(rec, window_start, window_end):
    """Check if a record falls within the time window."""
    ts = _parse_record_ts(rec)
    if ts is None:
        ts = rec.get("_log_ts")
    if ts is None:
        return True  # no timestamp — include by default
    # Make naive if needed
    if ts.tzinfo is not None:
        ts = ts.replace(tzinfo=None)
    return window_start <= ts <= window_end


def get_event_ts(rec):
    """Return the best available timestamp for a record."""
    ts = _parse_record_ts(rec)
    if ts is None:
        ts = rec.get("_log_ts")
    if ts is None:
        return "no timestamp"
    if ts.tzinfo is not None:
        ts = ts.replace(tzinfo=None)
    return ts.strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Report engine
# ---------------------------------------------------------------------------


class ReportEngine:
    """Processes parsed records and produces the report."""

    def __init__(self, all_records, args):
        self.records = all_records
        self.args = args
        self.dq = DataQuality()

        # Collection buckets
        self.by_script = defaultdict(list)
        self.by_host = defaultdict(list)
        self.by_category = defaultdict(list)
        self.by_execution = defaultdict(list)

        # Decision tracking
        self.transition_decisions = []
        self.cooldown_decisions = []
        self.blocked_records = []
        self.recovery_records = []
        self.adaptive_records = []
        self.delivered_count = 0
        self.would_suppress_count = 0
        self.suppressed_count = 0
        self.recovery_count = 0
        self.error_count = 0
        self.complete_delivered = 0
        self.complete_suppressed = 0

        self._classify()

    def _classify(self):
        """Classify all records into buckets."""
        for rec in self.records:
            status = rec.get("status", "unknown")
            self.dq.record_event(status)
            source = rec.get("_source", "unknown")
            host = rec.get("host", "") or rec.get("host_name", "") or "unknown"
            category = rec.get("category", "") or "unknown"
            eid = rec.get("execution_id") or rec.get("_execution_id", "")

            if not host or host in ("N/A", "$HOSTNAME$", ""):
                host = "unknown"
                self.dq.missing_host += 1
            if not category or category in ("N/A", "?"):
                category = "unknown"
                self.dq.missing_category += 1
            if not eid:
                # DECISION records may not carry execution_id — use _source to group
                eid = f"dec_{source}_{status}_{host}_{category}_{rec.get('old_state', '?')}_{rec.get('new_state', '?')}"
                rec["_execution_id"] = eid
                self.dq.missing_execution_id += 1
            else:
                rec["_execution_id"] = eid

            rec["_host"] = host
            rec["_category"] = category

            self.by_script[source].append(rec)
            self.by_host[host].append(rec)
            self.by_category[category].append(rec)
            if eid:
                self.by_execution[eid].append(rec)

            # Track decision records
            if status == "DECISION":
                self.transition_decisions.append(rec)
            elif status in ("WOULD_SUPPRESS_COOLDOWN", "SUPPRESSED_COOLDOWN"):
                self.cooldown_decisions.append(rec)
                if status == "WOULD_SUPPRESS_COOLDOWN":
                    self.would_suppress_count += 1
                else:
                    self.suppressed_count += 1
                self.blocked_records.append(rec)
            elif status == "COOLDOWN_BYPASS_RECOVERY":
                self.recovery_count += 1
                self.recovery_records.append(rec)
            elif status == "ADAPTIVE_COOLDOWN_RECOMMENDATION":
                self.adaptive_records.append(rec)
            elif status == "DELIVERED":
                self.delivered_count += 1
            elif status == "FAILED":
                self.error_count += 1
            elif status in ("ERROR",):
                self.error_count += 1

        # Count COMPLETE outcomes
        for eid, recs in self.by_execution.items():
            for r in recs:
                if r.get("status") == "COMPLETE":
                    result = r.get("result", "")
                    if result == "DELIVERED":
                        self.complete_delivered += 1
                    elif result in ("SUPPRESSED",):
                        self.complete_suppressed += 1
                    break

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _make_separator(self, title=""):
        sep = "=" * 72
        if title:
            return f"{sep}\n  {title}\n{sep}"
        return sep

    def _make_sub_separator(self, title=""):
        sep = "-" * 60
        if title:
            return f"{sep}\n  {title}\n{sep}"
        return sep

    # --- Section 1: Executive summary ---

    def section_executive_summary(self):
        lines = []
        lines.append(self._make_separator("1. EXECUTIVE SUMMARY"))
        lines.append("")
        total_decisions = len(self.transition_decisions) + len(self.cooldown_decisions)
        lines.append(f"  Report period:         {self.args.window_start.strftime('%Y-%m-%d %H:%M')}"
                     f" — {self.args.window_end.strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"  Log records parsed:    {len(self.records)}")
        lines.append(f"  Notification executions: {len(self.by_execution)}")
        lines.append(f"  Delivered:             {self.complete_delivered}")
        lines.append(f"  Would suppress (audit):  {self.would_suppress_count}")
        lines.append(f"  Suppressed (enforce):    {self.suppressed_count}")
        lines.append(f"  Recovery bypasses:     {self.recovery_count}")
        lines.append(f"  Cooldown decisions:    {len(self.cooldown_decisions)}")
        lines.append(f"  Transition decisions:  {len(self.transition_decisions)}")
        lines.append(f"  Errors/failures:       {self.error_count}")
        lines.append(f"  Malformed JSON lines:  {self.dq.bad_json_records}")
        lines.append("")
        return "\n".join(lines)

    # --- Section 2: Per-script summary ---

    def section_per_script(self):
        lines = []
        lines.append(self._make_separator("2. PER-SCRIPT SUMMARY"))
        lines.append("")
        lines.append(f"  {'Script':<20} {'Input':>8} {'Deliv.':>8} {'Would-Sup':>10} "
                     f"{'Sup.':>8} {'Recov.':>8} {'Errors':>8} {'BadJSON':>8}")
        lines.append(f"  {'-'*20} {'-'*8} {'-'*8} {'-'*10} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")

        for label in sorted(self.by_script.keys()):
            recs = self.by_script[label]
            input_n = len(set(r.get("_execution_id", r.get("execution_id", "?")) for r in recs))
            would_sup = sum(1 for r in recs if r.get("status") == "WOULD_SUPPRESS_COOLDOWN")
            suppressed = sum(1 for r in recs if r.get("status") == "SUPPRESSED_COOLDOWN")
            recovery = sum(1 for r in recs if r.get("status") == "COOLDOWN_BYPASS_RECOVERY")
            errors = sum(1 for r in recs if r.get("status") in ("FAILED", "ERROR"))
            bad = self.dq.bad_json_records  # counted globally

            lines.append(f"  {label:<20} {input_n:>8} {self.complete_delivered:>8} "
                         f"{would_sup:>10} {suppressed:>8} {recovery:>8} "
                         f"{errors:>8} {bad:>8}")

        lines.append("")
        return "\n".join(lines)

    # --- Section 3: Per-host summary ---

    def section_per_host(self):
        lines = []
        lines.append(self._make_separator("3. PER-HOST SUMMARY"))
        lines.append("")
        lines.append(f"  {'Host':<30} {'Total':>6} {'Deliv.':>8} {'Would-Sup':>10} "
                     f"{'Sup.':>8} {'Recov.':>8} {'Top Cat.':>20} {'Last Event':>20}")
        lines.append(f"  {'-'*30} {'-'*6} {'-'*8} {'-'*10} {'-'*8} {'-'*8} {'-'*20} {'-'*20}")

        for host in sorted(self.by_host.keys()):
            recs = self.by_host[host]
            total = len(set(r.get("_execution_id", r.get("execution_id", "?")) for r in recs))
            would_sup = sum(1 for r in recs if r.get("status") == "WOULD_SUPPRESS_COOLDOWN")
            suppressed = sum(1 for r in recs if r.get("status") == "SUPPRESSED_COOLDOWN")
            recovery = sum(1 for r in recs if r.get("status") == "COOLDOWN_BYPASS_RECOVERY")
            # Most frequent category
            cat_counter = Counter(r.get("_category", "unknown") for r in recs)
            top_cat = cat_counter.most_common(1)[0][0] if cat_counter else "?"
            # Last event timestamp
            last_ts = ""
            for r in reversed(recs):
                ts = get_event_ts(r)
                if ts != "no timestamp":
                    last_ts = ts
                    break

            lines.append(f"  {host:<30} {total:>6} {self.complete_delivered:>8} "
                         f"{would_sup:>10} {suppressed:>8} {recovery:>8} "
                         f"{top_cat[:20]:>20} {last_ts[:20]:>20}")

        lines.append("")
        return "\n".join(lines)

    # --- Section 4: Per-category summary ---

    def section_per_category(self):
        lines = []
        lines.append(self._make_separator("4. PER-CATEGORY SUMMARY"))
        lines.append("")
        lines.append(f"  {'Category':<25} {'Total':>6} {'Deliv.':>8} {'Would-Sup':>10} "
                     f"{'Sup.':>8} {'Recov.':>8}")
        lines.append(f"  {'-'*25} {'-'*6} {'-'*8} {'-'*10} {'-'*8} {'-'*8}")

        for cat in sorted(self.by_category.keys()):
            recs = self.by_category[cat]
            total = len(set(r.get("_execution_id", r.get("execution_id", "?")) for r in recs))
            would_sup = sum(1 for r in recs if r.get("status") == "WOULD_SUPPRESS_COOLDOWN")
            suppressed = sum(1 for r in recs if r.get("status") == "SUPPRESSED_COOLDOWN")
            recovery = sum(1 for r in recs if r.get("status") == "COOLDOWN_BYPASS_RECOVERY")
            lines.append(f"  {cat:<25} {total:>6} {self.complete_delivered:>8} "
                         f"{would_sup:>10} {suppressed:>8} {recovery:>8}")

        lines.append("")
        return "\n".join(lines)

    # --- Section 5: Detailed event table ---

    def section_detailed_events(self):
        limit = self.args.detail_limit

        # Collect all DECISION, WOULD_SUPPRESS_COOLDOWN, SUPPRESSED_COOLDOWN,
        # COOLDOWN_BYPASS_RECOVERY records, sorted by time
        detail_records = []
        for rec in self.records:
            status = rec.get("status", "")
            if status in ("DECISION", "WOULD_SUPPRESS_COOLDOWN",
                          "SUPPRESSED_COOLDOWN", "COOLDOWN_BYPASS_RECOVERY"):
                detail_records.append(rec)

        detail_records.sort(key=lambda r: (get_event_ts(r) or "", r.get("execution_id", "")))

        lines = []
        lines.append(self._make_separator("5. DETAILED EVENT TABLE"))
        lines.append("")
        lines.append(f"  Showing {min(len(detail_records), limit)} of {len(detail_records)} records")

        if len(detail_records) > limit:
            lines.append(f"  (truncated to {limit} — use --detail-limit to increase)")
            detail_records = detail_records[-limit:]

        lines.append("")
        header = (f"  {'Timestamp':<20} {'Script':<10} {'Host':<25} {'Category':<20} "
                  f"{'State':<10} {'Decision':<28} {'EID':<12}")
        lines.append(header)
        lines.append(f"  {'-'*20} {'-'*10} {'-'*25} {'-'*20} {'-'*10} {'-'*28} {'-'*12}")

        for rec in detail_records:
            ts = get_event_ts(rec)
            src = rec.get("_source", "?")[:10]
            host = rec.get("_host", "?")[:25]
            cat = rec.get("_category", "?")[:20]
            old = rec.get("old_state", "")
            new = rec.get("new_state", "")
            state = f"{old}->{new}" if old and new else new or old or "?"
            decision = rec.get("decision", rec.get("status", "?"))[:28]
            eid = (rec.get("_execution_id", rec.get("execution_id", "?")) or "?")[:12]
            lines.append(f"  {ts[:20]:<20} {src:<10} {host:<25} {cat:<20} "
                         f"{state:<10} {decision:<28} {eid:<12}")

        lines.append("")
        return "\n".join(lines)

    # --- Section 6: Blocked/would-blocked details ---

    def section_blocked(self):
        if not self.blocked_records:
            return ""

        limit = self.args.detail_limit
        blocked = sorted(self.blocked_records,
                         key=lambda r: (get_event_ts(r) or "", r.get("execution_id", "")))

        lines = []
        lines.append(self._make_separator("6. BLOCKED / WOULD-BLOCK DETAILS"))
        lines.append("")
        lines.append(f"  Showing {min(len(blocked), limit)} of {len(blocked)} records")

        if len(blocked) > limit:
            lines.append(f"  (truncated to {limit})")
            blocked = blocked[-limit:]

        lines.append("")
        header = (f"  {'Timestamp':<20} {'Script':<10} {'Host':<25} {'Category':<20} "
                  f"{'Decision':<28} {'Cdwn(s)':<8} {'Elapsed':<8} {'EID':<12}")
        lines.append(header)
        lines.append(f"  {'-'*20} {'-'*10} {'-'*25} {'-'*20} {'-'*28} {'-'*8} {'-'*8} {'-'*12}")

        for rec in blocked:
            ts = get_event_ts(rec)
            src = rec.get("_source", "?")[:10]
            host = rec.get("_host", "?")[:25]
            cat = rec.get("_category", "?")[:20]
            decision = rec.get("decision", rec.get("status", "?"))[:28]
            cd_sec = rec.get("cooldown_seconds", rec.get("window", "?"))
            elapsed = rec.get("cooldown_remaining",
                             rec.get("cooldown_blocked", "?"))
            eid = (rec.get("_execution_id", rec.get("execution_id", "?")) or "?")[:12]
            lines.append(f"  {ts[:20]:<20} {src:<10} {host:<25} {cat:<20} "
                         f"{decision:<28} {str(cd_sec):<8} {str(elapsed):<8} {eid:<12}")

        lines.append("")
        return "\n".join(lines)

    # --- Section 7: Recovery bypass details ---

    def section_recovery(self):
        if not self.recovery_records:
            return ""

        limit = self.args.detail_limit
        recov = sorted(self.recovery_records,
                       key=lambda r: (get_event_ts(r) or "", r.get("execution_id", "")))

        lines = []
        lines.append(self._make_separator("7. RECOVERY BYPASS DETAILS"))
        lines.append("")
        lines.append(f"  Showing {min(len(recov), limit)} of {len(recov)} records")

        if len(recov) > limit:
            lines.append(f"  (truncated to {limit})")
            recov = recov[-limit:]

        lines.append("")
        header = (f"  {'Timestamp':<20} {'Script':<10} {'Host':<25} {'Category':<20} "
                  f"{'Old':<8} {'New':<8} {'EID':<12}")
        lines.append(header)
        lines.append(f"  {'-'*20} {'-'*10} {'-'*25} {'-'*20} {'-'*8} {'-'*8} {'-'*12}")

        for rec in recov:
            ts = get_event_ts(rec)
            src = rec.get("_source", "?")[:10]
            host = rec.get("_host", "?")[:25]
            cat = rec.get("_category", "?")[:20]
            old = (rec.get("old_state") or "?")[:8]
            new = (rec.get("new_state") or "?")[:8]
            eid = (rec.get("_execution_id", rec.get("execution_id", "?")) or "?")[:12]
            lines.append(f"  {ts[:20]:<20} {src:<10} {host:<25} {cat:<20} "
                         f"{old:<8} {new:<8} {eid:<12}")

        lines.append("")
        return "\n".join(lines)

    # --- Section 8: Adaptive recommendation summary ---

    def section_adaptive(self):
        lines = []
        lines.append(self._make_separator("8. ADAPTIVE COOLDOWN RECOMMENDATION"))
        lines.append("")

        if not self.adaptive_records:
            lines.append("  No adaptive cooldown recommendation found in the selected period.")
            lines.append("")
            return "\n".join(lines)

        lines.append(f"  {'Script':<12} {'Category':<20} {'Curr.Cdwn':<12} {'Rec.Cdwn':<12} "
                     f"{'Reduc.%':<10} {'Samples':<10} {'Days':<8}")
        lines.append(f"  {'-'*12} {'-'*20} {'-'*12} {'-'*12} {'-'*10} {'-'*10} {'-'*8}")

        for rec in self.adaptive_records:
            src = rec.get("_source", "?")[:12]
            cat = rec.get("category", "?")[:20]
            # Parse the log message for details
            msg = rec.get("message", "")
            # Try to extract structured data from old-style format
            host = rec.get("host", "?")[:20]
            best = rec.get("best_candidate", "?")
            reduction = rec.get("expected_reduction", "?")
            samples = rec.get("samples", "?")
            days = rec.get("learning_days", "?")

            lines.append(f"  {src:<12} {cat:<20} {'3600s':<12} {str(best):<12} "
                         f"{str(reduction):<10} {str(samples):<10} {str(days):<8}")

        lines.append("")
        return "\n".join(lines)

    # --- Section 9: Data quality ---

    def section_data_quality(self):
        lines = []
        lines.append(self._make_separator("9. DATA QUALITY"))
        lines.append("")
        lines.append(f"  Files read:              {len(self.dq.files_read)}")
        for f in self.dq.files_read:
            lines.append(f"    - {f}")
        lines.append(f"  Files missing:           {len(self.dq.missing_files)}")
        for f in self.dq.missing_files:
            lines.append(f"    - {f}")
        lines.append(f"  Malformed JSON lines:    {self.dq.bad_json_records}")
        lines.append(f"  Records outside period:  {self.dq.outside_period}")
        lines.append(f"  Unknown event types:     {len(self.dq.unknown_events)}")
        for ev, cnt in self.dq.unknown_events.most_common():
            lines.append(f"    - {ev}: {cnt}")
        lines.append(f"  Missing host:            {self.dq.missing_host}")
        lines.append(f"  Missing category:        {self.dq.missing_category}")
        lines.append(f"  Missing execution_id:    {self.dq.missing_execution_id}")
        lines.append("")
        return "\n".join(lines)

    # --- Assemble full report ---

    def generate_text(self):
        parts = [
            self.section_executive_summary(),
            self.section_per_script(),
            self.section_per_host(),
            self.section_per_category(),
            self.section_detailed_events(),
            self.section_blocked(),
            self.section_recovery(),
            self.section_adaptive(),
            self.section_data_quality(),
        ]
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Checkmk notification limiter report generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Log paths
    parser.add_argument("--mail-log", default=None,
                        help="Path to mail-20.log (default: production path)")
    parser.add_argument("--telegram-log", default=None,
                        help="Path to telegram-20.log (default: production path)")

    # Time window
    parser.add_argument("--since-hours", type=float, default=DEFAULT_SINCE_HOURS,
                        help="Hours to look back from --to or now (default: %(default)s)")
    parser.add_argument("--from", dest="from_ts", default=None,
                        help="Explicit window start: YYYY-MM-DDTHH:MM:SS")
    parser.add_argument("--to", dest="to_ts", default=None,
                        help="Explicit window end: YYYY-MM-DDTHH:MM:SS (default: now)")

    # Email
    parser.add_argument("--to-email", default=None,
                        help="Recipient email address")
    parser.add_argument("--from-email", default=None,
                        help="Sender email address (default: %(default)s)")
    parser.add_argument("--subject-prefix", default=None,
                        help="Subject line prefix (default: [Checkmk] Notification limiter report)")

    # Output
    parser.add_argument("--detail-limit", type=int, default=DEFAULT_DETAIL_LIMIT,
                        help="Max rows in detail tables (default: %(default)s)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print report to stdout, don't send email")
    parser.add_argument("--output", default=None,
                        help="Write report to file")
    parser.add_argument("--format", choices=("text", "json"), default="text",
                        help="Report format (default: %(default)s)")

    args = parser.parse_args(argv)

    # Resolve log paths
    if args.mail_log is None:
        args.mail_log = DEFAULT_LOG_PATHS["mail"]
    if args.telegram_log is None:
        args.telegram_log = DEFAULT_LOG_PATHS["telegram"]

    # Resolve email
    if args.to_email is None:
        args.to_email = os.environ.get("NOTIFICATION_REPORT_TO")
    if args.from_email is None:
        args.from_email = os.environ.get("NOTIFICATION_REPORT_FROM", DEFAULT_FROM_EMAIL)
    if args.subject_prefix is None:
        args.subject_prefix = os.environ.get("NOTIFICATION_REPORT_SUBJECT_PREFIX",
                                              "[Checkmk] Notification limiter report")

    # Resolve time window
    now = datetime.datetime.now()
    if args.to_ts:
        try:
            args.window_end = datetime.datetime.strptime(args.to_ts, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            parser.error(f"Invalid --to format: {args.to_ts!r} (use YYYY-MM-DDTHH:MM:SS)")
    else:
        args.window_end = now

    if args.from_ts:
        try:
            args.window_start = datetime.datetime.strptime(args.from_ts, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            parser.error(f"Invalid --from format: {args.from_ts!r} (use YYYY-MM-DDTHH:MM:SS)")
    else:
        args.window_start = args.window_end - datetime.timedelta(hours=args.since_hours)

    # Validate
    if not args.dry_run and not args.to_email:
        parser.error("No recipient configured. Use --to-email or set NOTIFICATION_REPORT_TO "
                      "environment variable, or use --dry-run to preview.")

    return args


def send_email(to_addr, from_addr, subject, body):
    """Send email via /usr/sbin/sendmail -t."""
    msg = (
        f"To: {to_addr}\n"
        f"From: {from_addr}\n"
        f"Subject: {subject}\n"
        "Content-Type: text/plain; charset=UTF-8\n"
        "\n"
        f"{body}\n"
    )
    try:
        proc = subprocess.run(
            ["/usr/sbin/sendmail", "-t"],
            input=msg.encode("utf-8"),
            timeout=30,
        )
        return proc.returncode == 0
    except subprocess.TimeoutExpired:
        print("sendmail timeout", file=sys.stderr)
        return False
    except FileNotFoundError:
        print("/usr/sbin/sendmail not found", file=sys.stderr)
        return False
    except Exception as exc:
        print(f"sendmail error: {exc}", file=sys.stderr)
        return False


def main(argv=None):
    args = parse_args(argv)

    # ---- Parse logs ----
    dq = DataQuality()

    mail_stats = parse_log_file(args.mail_log, "M@il-20", dq)
    telegram_stats = parse_log_file(args.telegram_log, "Telegram-20", dq)

    dq.add_bad_json(mail_stats.bad_json + telegram_stats.bad_json)

    all_records = mail_stats.records + telegram_stats.records

    # ---- Filter by time window ----
    filtered = []
    for rec in all_records:
        if in_window(rec, args.window_start, args.window_end):
            filtered.append(rec)
        else:
            dq.outside_period += 1

    # ---- Build report ----
    engine = ReportEngine(filtered, args)
    engine.dq = dq  # share the data quality tracker

    report_body = engine.generate_text()

    # ---- Output ----
    if args.format == "json":
        # Simplified JSON output — structure matches the text sections
        report_body = json.dumps({
            "version": SCRIPT_NAME,
            "generated_at": datetime.datetime.now().isoformat(),
            "period": {
                "start": args.window_start.isoformat(),
                "end": args.window_end.isoformat(),
            },
            "summary": {
                "total_executions": len(engine.by_execution),
                "delivered": engine.complete_delivered,
                "would_suppress": engine.would_suppress_count,
                "suppressed": engine.suppressed_count,
                "recovery": engine.recovery_count,
                "errors": engine.error_count,
            },
        }, indent=2)

    if args.dry_run:
        print(report_body)

    if args.output:
        Path(args.output).write_text(report_body, encoding="utf-8")

    if not args.dry_run:
        subject = f"{args.subject_prefix} - {args.window_start.strftime('%Y-%m-%d %H:%M')}"
        success = send_email(args.to_email, args.from_email, subject, report_body)
        if not success:
            print("Failed to send email", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
