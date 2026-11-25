#!/usr/bin/env python3
"""webtop_leave_report.py – Webtop 5 / NS8 CalDAV leave & vacation reporter

Connects to Webtop via CalDAV (RFC 4791) using basic-auth credentials,
discovers all accessible calendars (own + shared/delegated), queries VEVENT
entries in a date range and reports those whose SUMMARY or DESCRIPTION
matches configured keywords (default: "ferie", "permesso").

No third-party libraries required; runs anywhere Python 3.8+ is installed.

Usage:
  python3 webtop_leave_report.py \\
      --url https://webtop.example.com \\
      --user jdoe \\
      --password PASSWORD

Env-var fallbacks: WEBTOP_URL, WEBTOP_USER, WEBTOP_PASS

Options:
  --url        Webtop base URL (without trailing slash)
  --user       CalDAV username (plain or user@domain)
  --password   CalDAV password  [env: WEBTOP_PASS]
  --keywords   Comma-separated keywords (default: ferie,permesso)
  --from       Start date YYYY-MM-DD  (default: 1st of current month)
  --to         End date YYYY-MM-DD    (default: today)
  --format     Output format: text | csv | json  (default: text)
  --insecure   Skip TLS cert verification (required for lab self-signed certs)
  --dry-run    Discover and list calendars only, do not fetch events
  --verbose    Print discovery steps and per-calendar counts to stderr
  --self-test  Run the offline self test

Version: 0.1.0
"""

import argparse
import base64
import csv
import io
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from datetime import date
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

VERSION = "0.1.0"

# CalDAV XML namespaces
_DAV = "DAV:"
_CALDAV = "urn:ietf:params:xml:ns:caldav"


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

def _ssl_ctx(insecure: bool) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _basic_header(user: str, password: str) -> str:
    """Build a Basic Authorization header value from plain credentials."""
    encoded = base64.b64encode(f"{user}:{password}".encode()).decode()
    return "Basic " + encoded


def _make_abs(base: str, href: str) -> str:
    """Turn a relative href into an absolute URL using base as origin."""
    if href.startswith("http"):
        return href
    from urllib.parse import urlparse
    p = urlparse(base)
    if href.startswith("/"):
        return f"{p.scheme}://{p.netloc}{href}"
    return base.rstrip("/") + "/" + href.lstrip("/")


class CalDAVClient:
    """Minimal CalDAV client: PROPFIND + REPORT, no third-party deps."""

    def __init__(self, base_url: str, user: str, password: str, insecure: bool = False):
        self.base_url = base_url.rstrip("/")
        self._hdr = _basic_header(user, password)
        self._ctx = _ssl_ctx(insecure)

    def _send(self, method: str, url: str, body: Optional[str],
              extra_headers: Optional[Dict[str, str]] = None,
              follow_redirects: int = 5) -> Tuple[int, bytes]:
        hdrs: Dict[str, str] = {
            "Authorization": self._hdr,
            "Content-Type": "application/xml; charset=utf-8",
        }
        if extra_headers:
            hdrs.update(extra_headers)
        payload = body.encode("utf-8") if body else None
        req = urllib.request.Request(url, data=payload, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, context=self._ctx, timeout=10) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (301, 302, 307, 308) and follow_redirects > 0:
                loc = exc.headers.get("Location", "")
                if loc:
                    return self._send(method, _make_abs(self.base_url, loc),
                                      body, extra_headers, follow_redirects - 1)
            return exc.code, exc.read() or b""
        except (urllib.error.URLError, OSError) as exc:
            raise ConnectionError(f"Cannot reach {url}: {exc}") from exc

    def propfind(self, url: str, depth: str, body: str) -> ET.Element:
        code, data = self._send("PROPFIND", url, body, {"Depth": depth})
        if code not in (200, 207):
            snippet = data[:300].decode("utf-8", errors="replace")
            raise RuntimeError(f"PROPFIND {url} -> HTTP {code}: {snippet}")
        return ET.fromstring(data)

    def report(self, url: str, body: str) -> ET.Element:
        code, data = self._send("REPORT", url, body, {"Depth": "1"})
        if code not in (200, 207):
            snippet = data[:300].decode("utf-8", errors="replace")
            raise RuntimeError(f"REPORT {url} -> HTTP {code}: {snippet}")
        return ET.fromstring(data)


# ---------------------------------------------------------------------------
# CalDAV discovery
# ---------------------------------------------------------------------------

_PF_CURRENT_PRINCIPAL = """\
<?xml version="1.0" encoding="utf-8"?>
<D:propfind xmlns:D="DAV:">
  <D:prop>
    <D:current-user-principal/>
  </D:prop>
</D:propfind>"""

_PF_CALENDAR_HOME = """\
<?xml version="1.0" encoding="utf-8"?>
<D:propfind xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <D:prop>
    <C:calendar-home-set/>
    <D:displayname/>
  </D:prop>
</D:propfind>"""

_PF_CALENDARS = """\
<?xml version="1.0" encoding="utf-8"?>
<D:propfind xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <D:prop>
    <D:displayname/>
    <D:resourcetype/>
    <C:supported-calendar-component-set/>
  </D:prop>
</D:propfind>"""


def discover_principal(client: CalDAVClient, user: str) -> str:
    """Return the CalDAV principal URL for user, trying multiple paths in order."""
    # Paths tried: .well-known/caldav, direct user path, principals path, DAV root
    for path in [
        "/.well-known/caldav",
        f"/webtop/dav/{user}/",
        f"/webtop/dav/principals/users/{user}/",
        "/webtop/dav/",
    ]:
        url = _make_abs(client.base_url, path)
        try:
            root = client.propfind(url, "0", _PF_CURRENT_PRINCIPAL)
        except (RuntimeError, ConnectionError):
            continue

        # Preferred: current-user-principal href
        cup = root.find(f".//{{{_DAV}}}current-user-principal/{{{_DAV}}}href")
        if cup is not None and (cup.text or "").strip():
            return _make_abs(client.base_url, cup.text.strip())

        # Fallback: use the first responding href in the multistatus
        href_el = root.find(f"{{{_DAV}}}response/{{{_DAV}}}href")
        if href_el is not None and (href_el.text or "").strip() not in ("", "/"):
            return _make_abs(client.base_url, href_el.text.strip())

    raise RuntimeError(
        "Cannot discover CalDAV principal. "
        "Check the base URL, credentials, and that Webtop is running."
    )


def discover_calendar_home(client: CalDAVClient, principal_url: str) -> str:
    """Return the calendar-home-set URL from the principal resource."""
    try:
        root = client.propfind(principal_url, "0", _PF_CALENDAR_HOME)
    except RuntimeError as exc:
        raise RuntimeError(f"Cannot read calendar-home-set: {exc}") from exc

    chs = root.find(f".//{{{_CALDAV}}}calendar-home-set/{{{_DAV}}}href")
    if chs is not None and (chs.text or "").strip():
        return _make_abs(client.base_url, chs.text.strip())

    # Webtop may put the calendar home directly on the user DAV path —
    # treat the principal URL as the home in that case.
    return principal_url


def list_calendars(client: CalDAVClient, home_url: str) -> List[Dict[str, str]]:
    """PROPFIND Depth:1 on the calendar home; returns [{url, name}] per VEVENT calendar."""
    try:
        root = client.propfind(home_url, "1", _PF_CALENDARS)
    except RuntimeError as exc:
        raise RuntimeError(f"Cannot list calendars: {exc}") from exc

    calendars = []
    for resp in root.findall(f"{{{_DAV}}}response"):
        href_el = resp.find(f"{{{_DAV}}}href")
        if href_el is None or not (href_el.text or "").strip():
            continue
        abs_url = _make_abs(client.base_url, href_el.text.strip())

        # Must declare resourcetype = calendar
        rt = resp.find(f".//{{{_DAV}}}resourcetype")
        if rt is None or rt.find(f"{{{_CALDAV}}}calendar") is None:
            continue

        # Must support VEVENT (or omit supported-calendar-component-set entirely)
        sccs = resp.find(f".//{{{_CALDAV}}}supported-calendar-component-set")
        if sccs is not None:
            comps = {c.get("name", "").upper()
                     for c in sccs.findall(f"{{{_CALDAV}}}comp")}
            if comps and "VEVENT" not in comps:
                continue

        name_el = resp.find(f".//{{{_DAV}}}displayname")
        name = (name_el.text or "").strip() if name_el is not None else ""
        if not name:
            name = href_el.text.strip().rstrip("/").rsplit("/", 1)[-1] or abs_url
        calendars.append({"url": abs_url, "name": name})

    return calendars


# ---------------------------------------------------------------------------
# Event query
# ---------------------------------------------------------------------------

_REPORT_TMPL = """\
<?xml version="1.0" encoding="utf-8"?>
<C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <D:prop>
    <D:getetag/>
    <C:calendar-data/>
  </D:prop>
  <C:filter>
    <C:comp-filter name="VCALENDAR">
      <C:comp-filter name="VEVENT">
        <C:time-range start="{start}" end="{end}"/>
      </C:comp-filter>
    </C:comp-filter>
  </C:filter>
</C:calendar-query>"""


def _caldav_dt(d: date, end_of_day: bool = False) -> str:
    """Format a date as a CalDAV UTC timestamp (YYYYMMDDTHHMMSSZ)."""
    if end_of_day:
        return d.strftime("%Y%m%dT235959Z")
    return d.strftime("%Y%m%dT000000Z")


def fetch_events_raw(client: CalDAVClient, calendar_url: str,
                     d_from: date, d_to: date) -> List[str]:
    """Return list of raw iCalendar strings from a REPORT calendar-query."""
    body = _REPORT_TMPL.format(
        start=_caldav_dt(d_from),
        end=_caldav_dt(d_to, end_of_day=True),
    )
    try:
        root = client.report(calendar_url, body)
    except (RuntimeError, ConnectionError) as exc:
        print(f"  [SKIP] {calendar_url.split('/')[-2]}: {exc}", file=sys.stderr)
        return []

    result = []
    for resp in root.findall(f"{{{_DAV}}}response"):
        cal_data = resp.find(f".//{{{_CALDAV}}}calendar-data")
        if cal_data is not None and cal_data.text:
            result.append(cal_data.text)
    return result


# ---------------------------------------------------------------------------
# iCalendar parser  (no vobject / icalendar dependency)
# ---------------------------------------------------------------------------

def _unfold(text: str) -> str:
    """RFC 5545 §3.1 line unfolding: CRLF followed by SPACE or TAB = continuation."""
    return re.sub(r"\r?\n[ \t]", "", text)


def _prop_value(line: str) -> Tuple[str, str]:
    """Split 'PROPNAME[;params]:value' into (NAME_UPPER, value_string)."""
    m = re.match(r"^([A-Z][A-Z0-9\-]*)(?:;[^:]*)?:(.*)", line, re.IGNORECASE)
    if m:
        return m.group(1).upper(), m.group(2).strip()
    return "", ""


def _parse_date(raw: str) -> str:
    """Convert a DTSTART/DTEND value to YYYY-MM-DD (best-effort).

    Handles: 20261101, 20261101T090000, 20261101T090000Z
    """
    m = re.match(r"(\d{4})(\d{2})(\d{2})", raw.strip())
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return raw.strip()


def parse_vevents(ical_text: str) -> List[Dict[str, str]]:
    """Parse a VCALENDAR string and return a list of event attribute dicts."""
    unfolded = _unfold(ical_text)
    events: List[Dict[str, str]] = []

    for block in re.split(r"BEGIN:VEVENT\r?\n?", unfolded, flags=re.IGNORECASE)[1:]:
        end_parts = re.split(r"END:VEVENT", block, flags=re.IGNORECASE, maxsplit=1)
        lines = [ln for ln in end_parts[0].splitlines() if ln.strip()]

        props: Dict[str, str] = {}
        for ln in lines:
            name, value = _prop_value(ln)
            if name and name not in props:  # first occurrence wins (RFC 5545)
                props[name] = value

        organizer = props.get("ORGANIZER", "")
        # Strip CN=... params and mailto: prefix
        organizer = re.sub(r"(?i)^.*mailto:", "", organizer).strip()

        events.append({
            "uid": props.get("UID", ""),
            "summary": props.get("SUMMARY", ""),
            "description": props.get("DESCRIPTION", "").replace("\\n", " ").strip(),
            "dtstart": _parse_date(props.get("DTSTART", "")),
            "dtend": _parse_date(props.get("DTEND", props.get("DUE", ""))),
            "organizer": organizer,
            "location": props.get("LOCATION", ""),
        })
    return events


# ---------------------------------------------------------------------------
# Keyword matching
# ---------------------------------------------------------------------------

def matches_keywords(event: Dict[str, str], keywords: List[str]) -> bool:
    """True if any keyword appears (case-insensitive) in SUMMARY or DESCRIPTION."""
    haystack = (
        event.get("summary", "") + " " + event.get("description", "")
    ).lower()
    return any(kw.lower() in haystack for kw in keywords)


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def _fmt_text(hits: List[Dict[str, str]], period: str) -> str:
    if not hits:
        return f"No leave/vacation events found in period {period}."
    sep = "─" * 70
    lines = [
        "Leave / vacation events report",
        f"Period   : {period}",
        f"Matches  : {len(hits)} event(s)",
        sep,
    ]
    for h in hits:
        lines.append(f"  Calendar : {h.get('_calendar', '')}")
        lines.append(f"  Summary  : {h.get('summary') or '(no title)'}")
        lines.append(f"  Dates    : {h.get('dtstart', '?')} -> {h.get('dtend', '?')}")
        organizer = h.get("organizer", "")
        if organizer:
            lines.append(f"  Organizer: {organizer}")
        location = h.get("location", "")
        if location:
            lines.append(f"  Location : {location}")
        description = h.get("description", "")
        if description:
            snippet = description[:160] + ("..." if len(description) > 160 else "")
            lines.append(f"  Note     : {snippet}")
        lines.append("")
    return "\n".join(lines)


def _fmt_csv(hits: List[Dict[str, str]]) -> str:
    out = io.StringIO()
    fields = ["calendar", "summary", "dtstart", "dtend", "organizer", "location", "description"]
    w = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for h in hits:
        w.writerow({
            "calendar": h.get("_calendar", ""),
            "summary": h.get("summary", ""),
            "dtstart": h.get("dtstart", ""),
            "dtend": h.get("dtend", ""),
            "organizer": h.get("organizer", ""),
            "location": h.get("location", ""),
            "description": h.get("description", ""),
        })
    return out.getvalue()


def _fmt_json(hits: List[Dict[str, str]], period: str) -> str:
    payload = {
        "period": period,
        "total": len(hits),
        "events": [
            {
                "calendar": h.get("_calendar", ""),
                "summary": h.get("summary", ""),
                "dtstart": h.get("dtstart", ""),
                "dtend": h.get("dtend", ""),
                "organizer": h.get("organizer", ""),
                "location": h.get("location", ""),
                "description": h.get("description", ""),
            }
            for h in hits
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Self test
# ---------------------------------------------------------------------------

def self_test() -> int:
    """Offline test of the pure helpers; no network access."""
    failures = []

    def expect(condition: bool, label: str) -> None:
        if condition:
            print(f"  [PASS] {label}")
        else:
            print(f"  [FAIL] {label}")
            failures.append(label)

    expect(_basic_header("user", "pass") == "Basic dXNlcjpwYXNz",
           "_basic_header encodes user:pass")

    base = "https://webtop.example.com"
    expect(_make_abs(base, "/dav/user/") == "https://webtop.example.com/dav/user/",
           "_make_abs resolves an absolute path")
    expect(_make_abs(base, "https://other.example.com/x") == "https://other.example.com/x",
           "_make_abs keeps an already absolute URL")
    expect(_make_abs("https://webtop.example.com/base", "cal/")
           == "https://webtop.example.com/base/cal/",
           "_make_abs appends a relative path")

    expect(_caldav_dt(date(2026, 1, 2)) == "20260102T000000Z",
           "_caldav_dt formats the start of the day")
    expect(_caldav_dt(date(2026, 1, 2), end_of_day=True) == "20260102T235959Z",
           "_caldav_dt formats the end of the day")

    expect(_unfold("A: b\r\n c") == "A: bc", "_unfold joins a folded line")
    expect(_prop_value("SUMMARY;LANGUAGE=en:Hello") == ("SUMMARY", "Hello"),
           "_prop_value splits name, params and value")
    expect(_prop_value("not a property") == ("", ""),
           "_prop_value rejects a malformed line")

    expect(_parse_date("20261101") == "2026-11-01", "_parse_date handles a date")
    expect(_parse_date("20261101T090000Z") == "2026-11-01",
           "_parse_date handles a UTC date-time")
    expect(_parse_date("unknown") == "unknown",
           "_parse_date falls back to the raw value")

    ics = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:evt-1@example.com\r\n"
        "SUMMARY:Annual lea\r\n"
        " ve\r\n"
        "DTSTART;VALUE=DATE:20261102\r\n"
        "DTEND;VALUE=DATE:20261103\r\n"
        "DESCRIPTION:Vacation day\\nsecond line\r\n"
        "END:VEVENT\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:evt-2@example.com\r\n"
        "SUMMARY:Team meeting\r\n"
        "DTSTART:20261105T090000Z\r\n"
        "DTEND:20261105T100000Z\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    events = parse_vevents(ics)
    expect(len(events) == 2, "parse_vevents finds both events")
    expect(events[0]["summary"] == "Annual leave",
           "parse_vevents unfolds a folded SUMMARY")
    expect(events[0]["dtstart"] == "2026-11-02" and events[0]["dtend"] == "2026-11-03",
           "parse_vevents handles an all-day event")
    expect(events[0]["description"] == "Vacation day second line",
           "parse_vevents normalizes escaped newlines in DESCRIPTION")

    expect(matches_keywords(events[0], ["LEAVE"]),
           "matches_keywords is case-insensitive on SUMMARY")
    expect(matches_keywords(events[0], ["vacation"]),
           "matches_keywords matches in DESCRIPTION")
    expect(matches_keywords(events[1], ["meeting"]),
           "matches_keywords matches another SUMMARY")
    expect(not matches_keywords(events[1], ["leave"]),
           "matches_keywords ignores unrelated keywords")

    hits = [
        {"_calendar": "Personal", "summary": "Annual leave",
         "dtstart": "2026-11-02", "dtend": "2026-11-03",
         "organizer": "jdoe", "location": "Home",
         "description": "Vacation day second line"},
        {"_calendar": "Team", "summary": "Team meeting",
         "dtstart": "2026-11-05", "dtend": "2026-11-05",
         "organizer": "", "location": "", "description": ""},
    ]
    period = "2026-11-01 -> 2026-11-30"
    text = _fmt_text(hits, period)
    expect("Matches  : 2 event(s)" in text and "Annual leave" in text,
           "_fmt_text renders both hits")
    csv_out = _fmt_csv(hits)
    expect(csv_out.startswith(
               "calendar,summary,dtstart,dtend,organizer,location,description")
           and csv_out.count("\n") == 3,
           "_fmt_csv renders header and two rows")
    payload = json.loads(_fmt_json(hits, period))
    expect(payload["total"] == 2 and len(payload["events"]) == 2
           and payload["events"][0]["summary"] == "Annual leave",
           "_fmt_json renders the two hits")

    if failures:
        print(f"[FAIL] self test: {len(failures)} failure(s)")
        return 1
    print("SELFTEST PASS")
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    today = date.today()
    first_of_month = date(today.year, today.month, 1)

    ap = argparse.ArgumentParser(
        description="Webtop 5 CalDAV leave/vacation event reporter",
    )
    ap.add_argument("--url", default=os.environ.get("WEBTOP_URL", ""),
                    help="Webtop base URL  [env: WEBTOP_URL]")
    ap.add_argument("--user", default=os.environ.get("WEBTOP_USER", ""),
                    help="CalDAV username  [env: WEBTOP_USER]")
    ap.add_argument("--password", default=os.environ.get("WEBTOP_PASS", ""),
                    help="CalDAV password  [env: WEBTOP_PASS]")
    ap.add_argument("--keywords", default="ferie,permesso",
                    help="Comma-separated keywords (default: ferie,permesso)")
    ap.add_argument("--from", dest="date_from", default=first_of_month.isoformat(),
                    metavar="YYYY-MM-DD",
                    help=f"Start date (default: {first_of_month})")
    ap.add_argument("--to", dest="date_to", default=today.isoformat(),
                    metavar="YYYY-MM-DD",
                    help=f"End date (default: {today})")
    ap.add_argument("--format", dest="fmt", choices=["text", "csv", "json"], default="text",
                    help="Output format (default: text)")
    ap.add_argument("--insecure", action="store_true",
                    help="Skip TLS certificate verification")
    ap.add_argument("--dry-run", action="store_true",
                    help="Discover and list calendars only; do not fetch events")
    ap.add_argument("--verbose", action="store_true",
                    help="Print discovery steps and per-calendar counts to stderr")
    ap.add_argument("--self-test", action="store_true",
                    help="Run the offline self test")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    missing = [f"--{n}" for n, v in [("url", args.url), ("user", args.user),
                                      ("password", args.password)] if not v]
    if missing:
        ap.error(f"Required: {', '.join(missing)}")

    try:
        d_from = date.fromisoformat(args.date_from)
        d_to = date.fromisoformat(args.date_to)
    except ValueError as exc:
        ap.error(f"Invalid date: {exc}")

    if d_from > d_to:
        ap.error("--from must be <= --to")

    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    period = f"{d_from} -> {d_to}"

    def vprint(*msg: str) -> None:
        if args.verbose:
            print("[*]", *msg, file=sys.stderr)

    client = CalDAVClient(args.url, args.user, args.password, insecure=args.insecure)

    # 1. Discover principal
    vprint(f"Discovering CalDAV principal for '{args.user}' at {args.url}")
    try:
        principal_url = discover_principal(client, args.user)
    except (RuntimeError, ConnectionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    vprint(f"Principal URL: {principal_url}")

    # 2. Calendar home set
    try:
        home_url = discover_calendar_home(client, principal_url)
    except (RuntimeError, ConnectionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    vprint(f"Calendar home: {home_url}")

    # 3. List calendars
    try:
        calendars = list_calendars(client, home_url)
    except (RuntimeError, ConnectionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if not calendars:
        print("No accessible VEVENT calendars found.", file=sys.stderr)
        return 0

    vprint(f"Found {len(calendars)} calendar(s):")
    for c in calendars:
        vprint(f"  · {c['name']!r}  {c['url']}")

    if args.dry_run:
        print(f"Calendars accessible to '{args.user}':")
        for c in calendars:
            print(f"  {c['name']:<40}  {c['url']}")
        return 0

    # 4. Fetch and filter events across all calendars
    all_hits: List[Dict[str, str]] = []
    for cal in calendars:
        raw_list = fetch_events_raw(client, cal["url"], d_from, d_to)
        total_in_cal = 0
        matched_in_cal = 0
        for ical in raw_list:
            events = parse_vevents(ical)
            total_in_cal += len(events)
            for ev in events:
                if matches_keywords(ev, keywords):
                    ev["_calendar"] = cal["name"]
                    all_hits.append(ev)
                    matched_in_cal += 1
        vprint(f"  Calendar {cal['name']!r}: {total_in_cal} event(s) fetched, "
               f"{matched_in_cal} matched {keywords}")

    # Sort by dtstart, then calendar name
    all_hits.sort(key=lambda e: (e.get("dtstart") or "", e.get("_calendar") or ""))

    # 5. Output report
    if args.fmt == "csv":
        print(_fmt_csv(all_hits), end="")
    elif args.fmt == "json":
        print(_fmt_json(all_hits, period))
    else:
        print(_fmt_text(all_hits, period))

    return 0


if __name__ == "__main__":
    sys.exit(main())
