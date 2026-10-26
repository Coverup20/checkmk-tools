#!/usr/bin/python3
"""
freshdesk - Freshdesk Ticketing Integration
Bulk: no

CheckMK notification script - integrates with the Freshdesk ticketing system.
Features: smart detection, flapping protection, host aggregation, cache
management, and a post-creation group fix that survives helpdesk automation.

Modelled on the Ydea notification script, with the toolkit subprocess calls
replaced by direct Freshdesk REST calls.

Version: 1.0.1
"""
#
# Copyright (C) 2025 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

import base64
import fcntl
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

VERSION = "1.0.1"

# Credentials live in a root-owned file on the monitoring host, not in the
# CheckMK notification rule: a rule parameter is readable by anyone who can
# open the rule in the UI, and ends up in the site configuration backups.
# Values already exported by CheckMK win over the file, so a rule can still
# override any of them without the file being edited.
ENV_FILE = os.environ.get("FRESHDESK_ENV", "/opt/freshdesk-toolkit/.env")


def load_env(path):
    """Load KEY=VALUE lines from an env file into the process environment.

    Accepts the 'export KEY=value' form and quoted values. Never raises: a
    missing or unreadable file only means the values have to come from the
    environment instead, which the caller reports on its own.
    """
    if not os.path.exists(path):
        return
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                line = line.replace("export ", "", 1).strip()
                key, value = line.split("=", 1)
                key = key.strip()
                if key not in os.environ:
                    os.environ[key] = value.strip().strip('"').strip("'")
    except Exception as e:
        print(f"WARNING: could not read {path}: {e}", file=sys.stderr)


load_env(ENV_FILE)

# === CONFIG ===
# Everything environment-specific comes from the OMD environment or from the
# env file loaded above - never from this file.
FRESHDESK_DOMAIN = os.environ.get("FRESHDESK_DOMAIN", "")
FRESHDESK_API_KEY = os.environ.get("FRESHDESK_API_KEY", "")
FRESHDESK_GROUP_ID = os.environ.get("FRESHDESK_GROUP_ID", "")
FRESHDESK_REQUESTER_EMAIL = os.environ.get("FRESHDESK_REQUESTER_EMAIL", "")

# Mandatory custom field: the API rejects ticket creation without it.
FRESHDESK_TIPO_INTERVENTO = os.environ.get("FRESHDESK_TIPO_INTERVENTO", "Problema")

CACHE_DIR = os.environ.get("FRESHDESK_CACHE_DIR", "/omd/sites/monitoring/var/freshdesk")
TICKET_CACHE = f"{CACHE_DIR}/freshdesk_checkmk_tickets.json"
FLAPPING_CACHE = f"{CACHE_DIR}/freshdesk_checkmk_flapping.json"
CACHE_LOCK = f"{CACHE_DIR}/freshdesk_cache.lock"

RESOLVED_TICKET_TTL = 5 * 24 * 3600  # keep resolved entries for 5 days
CACHE_MAX_AGE = 30 * 24 * 3600       # keep active entries for 30 days
FLAPPING_THRESHOLD = 5               # state changes within the window
FLAPPING_WINDOW = 600                # 10 minutes

AGGREGATE_BY_HOST = int(os.environ.get("AGGREGATE_BY_HOST", "1"))
RESOLVE_ON_SERVICE_OK = int(os.environ.get("RESOLVE_ON_SERVICE_OK", "0"))

HTTP_TIMEOUT = int(os.environ.get("FRESHDESK_TIMEOUT", "25"))
MAX_RETRIES = int(os.environ.get("FRESHDESK_MAX_RETRIES", "3"))
RETRY_DELAY = int(os.environ.get("FRESHDESK_RETRY_DELAY", "10"))

# A helpdesk automation rule rewrites group_id about a second after creation,
# routing the ticket to the group tied to the requester contact. The ticket is
# therefore moved back with a PUT once that rule has fired - sending the group
# in the POST alone is not enough. 'type' is deliberately never sent: the same
# rule sets it, and that value is the wanted one.
GROUP_FIX_DELAY = int(os.environ.get("FRESHDESK_GROUP_FIX_DELAY", "5"))
GROUP_FIX_ATTEMPTS = int(os.environ.get("FRESHDESK_GROUP_FIX_ATTEMPTS", "3"))

# Freshdesk status codes
STATUS_OPEN = 2
STATUS_RESOLVED = 4
STATUS_CLOSED = 5
RESOLVED_STATUSES = {STATUS_RESOLVED, STATUS_CLOSED}

# Freshdesk priority codes
PRIORITY_LOW = 1
PRIORITY_HIGH = 3

DEBUG = os.environ.get("DEBUG_FRESHDESK", "0") == "1"
# ==============

## Useful


def log(msg):
    """Log message to stderr."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}", file=sys.stderr)


def debug(msg):
    """Log message only when debugging is enabled."""
    if DEBUG:
        log(f"DEBUG: {msg}")


def log_ticket_event(event_type, ticket_id, details=""):
    """Log a ticket lifecycle event in a greppable format."""
    log(f"[TICKET-EVENT] [{event_type}] #{ticket_id} {details}")


def is_transient_network_error(text):
    """Return True if the error is a transient network/DNS failure worth retrying."""
    t = (text or "").lower()
    return any(k in t for k in (
        "nameresolut",
        "failed to resolve",
        "errno -3",
        "temporary failure in name resolution",
        "max retries exceeded",
        "connection refused",
        "connection timed out",
        "connection reset",
        "remotedisconnected",
        "broken pipe",
        "network is unreachable",
        "timed out",
    ))


def api_request(method, path, payload=None, timeout=None):
    """Call the Freshdesk REST API.

    Returns (status_code, parsed_body). status_code is 0 when the request
    never reached the server, so callers can tell a transport failure from an
    HTTP error. Retries transient network failures and HTTP 429/5xx.
    """
    if timeout is None:
        timeout = HTTP_TIMEOUT

    if not FRESHDESK_DOMAIN or not FRESHDESK_API_KEY:
        log("ERROR: FRESHDESK_DOMAIN or FRESHDESK_API_KEY not set")
        return 0, None

    url = f"https://{FRESHDESK_DOMAIN}/api/v2{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None

    # The API key is used as the basic-auth username, with any password.
    token = base64.b64encode(f"{FRESHDESK_API_KEY}:X".encode("utf-8")).decode("ascii")

    last_status, last_body = 0, None
    for attempt in range(1, MAX_RETRIES + 1):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Basic {token}")
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", "CheckMK-Freshdesk-Notifier")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return resp.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            try:
                body = json.loads(raw) if raw else None
            except ValueError:
                body = {"raw": raw}
            last_status, last_body = e.code, body
            # 429 is rate limiting, 5xx is a server-side hiccup: both retryable.
            if e.code == 429 or e.code >= 500:
                log(f"WARN: {method} {path} returned {e.code} (attempt {attempt}/{MAX_RETRIES})")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
                    continue
            return e.code, body
        except Exception as e:
            last_status, last_body = 0, {"error": str(e)}
            if is_transient_network_error(str(e)) and attempt < MAX_RETRIES:
                log(f"WARN: {method} {path} network error (attempt {attempt}/{MAX_RETRIES}): {e}")
                time.sleep(RETRY_DELAY)
                continue
            log(f"ERROR: {method} {path} failed: {e}")
            return 0, last_body

    return last_status, last_body


## Cache


def atomic_cache_write(cache_file, content):
    """Write a cache file atomically, serialised by an exclusive flock."""
    cache_path = Path(cache_file)
    cache_dir = cache_path.parent

    if not os.access(cache_dir, os.W_OK):
        log(f"ERROR: No write permission on {cache_dir}")
        return False

    temp_file = f"{cache_file}.tmp.{os.getpid()}"
    lock_file = Path(CACHE_LOCK)

    try:
        lock_file.touch(mode=0o666, exist_ok=True)
        with open(lock_file, "r") as lock_fd:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
            with open(temp_file, "w") as f:
                f.write(content)
            os.chmod(temp_file, 0o666)
            os.replace(temp_file, cache_file)
            os.chmod(cache_file, 0o666)
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        debug(f"atomic_cache_write OK: {cache_file}")
        return True
    except Exception as e:
        log(f"ERROR: atomic_cache_write failed: {e}")
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except OSError:
                pass
        return False


def read_cache(cache_file):
    """Read a JSON cache file, returning {} on any failure."""
    try:
        with open(cache_file, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def reset_corrupt_cache(cache_file):
    """Move a corrupted cache aside and start from an empty one."""
    log(f"WARN: cache {cache_file} corrupted, reset")
    backup = f"{cache_file}.corrupt.{int(time.time())}"
    try:
        os.rename(cache_file, backup)
    except OSError:
        pass
    atomic_cache_write(cache_file, "{}")


def init_cache():
    """Create the cache directory and files, dropping invalid entries."""
    Path(CACHE_DIR).mkdir(parents=True, exist_ok=True, mode=0o777)

    lock_path = Path(CACHE_LOCK)
    if not lock_path.exists():
        lock_path.touch(mode=0o666, exist_ok=True)

    ticket_path = Path(TICKET_CACHE)
    if not ticket_path.exists():
        atomic_cache_write(TICKET_CACHE, "{}")
    else:
        try:
            with open(TICKET_CACHE, "r") as f:
                data = json.load(f)
            cleaned = {}
            for key, value in data.items():
                try:
                    int(value.get("ticket_id"))
                    cleaned[key] = value
                except (TypeError, ValueError):
                    pass
            if cleaned != data:
                atomic_cache_write(TICKET_CACHE, json.dumps(cleaned))
        except json.JSONDecodeError:
            reset_corrupt_cache(TICKET_CACHE)

    flapping_path = Path(FLAPPING_CACHE)
    if not flapping_path.exists():
        atomic_cache_write(FLAPPING_CACHE, "{}")
    else:
        try:
            with open(FLAPPING_CACHE, "r") as f:
                json.load(f)
        except json.JSONDecodeError:
            reset_corrupt_cache(FLAPPING_CACHE)

    clean_old_cache_entries()


def clean_old_cache_entries():
    """Drop resolved entries past their TTL and stale active ones."""
    now = int(time.time())
    resolved_cutoff = now - RESOLVED_TICKET_TTL
    active_cutoff = now - CACHE_MAX_AGE

    data = read_cache(TICKET_CACHE)
    if not data:
        return

    cleaned = {}
    for key, value in data.items():
        resolved_at = value.get("resolved_at")
        last_update = value.get("last_update")
        if resolved_at:
            if resolved_at > resolved_cutoff:
                cleaned[key] = value
        elif last_update and last_update > active_cutoff:
            cleaned[key] = value

    if cleaned != data:
        atomic_cache_write(TICKET_CACHE, json.dumps(cleaned))
        debug("Cache cleaned: removed old entries")


def get_ticket_key(host, service="HOST"):
    """Build the cache key: one ticket per host, or one per service."""
    if AGGREGATE_BY_HOST == 1:
        return host
    return f"{host}:{service}"


def get_ticket_id(key):
    """Return the cached ticket id for a key, or None."""
    ticket_id = read_cache(TICKET_CACHE).get(key, {}).get("ticket_id")
    try:
        return int(ticket_id) if ticket_id else None
    except (TypeError, ValueError):
        return None


def save_ticket_cache(key, ticket_id, state):
    """Store a newly created ticket in the cache."""
    data = read_cache(TICKET_CACHE)
    now = int(time.time())
    data[key] = {
        "ticket_id": ticket_id,
        "state": state,
        "created_at": now,
        "last_update": now,
        "resolved_at": None,
    }
    atomic_cache_write(TICKET_CACHE, json.dumps(data))
    debug(f"Ticket cached: {key} -> {ticket_id}")


def update_ticket_state(key, state):
    """Record the latest state for a cached ticket."""
    data = read_cache(TICKET_CACHE)
    if key not in data:
        return
    data[key]["state"] = state
    data[key]["last_update"] = int(time.time())
    # A new CRITICAL reopens an entry previously marked resolved.
    if state in ("CRITICAL", "CRIT", "DOWN"):
        data[key]["resolved_at"] = None
    atomic_cache_write(TICKET_CACHE, json.dumps(data))


def mark_ticket_resolved(key):
    """Mark a cached ticket as resolved."""
    data = read_cache(TICKET_CACHE)
    if key not in data:
        debug(f"Ticket {key} not in cache, skip mark_resolved")
        return
    now = int(time.time())
    data[key]["resolved_at"] = now
    data[key]["last_update"] = now
    atomic_cache_write(TICKET_CACHE, json.dumps(data))
    debug(f"Ticket {key} marked as resolved")


def remove_ticket_from_cache(key):
    """Forget a ticket so the next alert opens a fresh one."""
    data = read_cache(TICKET_CACHE)
    if key in data:
        del data[key]
        atomic_cache_write(TICKET_CACHE, json.dumps(data))
        debug(f"Ticket {key} removed from cache")


def record_state_change(key, state):
    """Append a state change used by the flapping detector."""
    data = read_cache(FLAPPING_CACHE)
    data.setdefault(key, []).append({"state": state, "timestamp": int(time.time())})
    atomic_cache_write(FLAPPING_CACHE, json.dumps(data))


def is_flapping(key):
    """Return (flapping, message) for the recent state changes of a key."""
    changes = read_cache(FLAPPING_CACHE).get(key, [])
    window_start = int(time.time()) - FLAPPING_WINDOW
    recent = [c for c in changes if c.get("timestamp", 0) >= window_start]
    if len(recent) >= FLAPPING_THRESHOLD:
        return True, f"{len(recent)} state changes in {FLAPPING_WINDOW // 60} minutes"
    return False, ""


## Alert formatting


def detect_alert_type(output):
    """Classify the alert from the check output."""
    o = (output or "").lower()
    if "socket.timeout" in o or "read timed out" in o:
        return "COMMUNICATION_TIMEOUT"
    if "connection refused" in o or "errno 111" in o:
        return "HOST_OFFLINE_REFUSED"
    if "network unreachable" in o or "errno 113" in o:
        return "HOST_OFFLINE_NETWORK"
    if "timeout" in o or "timed out" in o or "no route" in o:
        return "HOST_OFFLINE_TIMEOUT"
    if "no data" in o or "piggyback" in o or "stale cache" in o:
        return "HOST_NODATA"
    return "UNKNOWN"


def get_alert_label(alert_type):
    """Human-readable label for an alert type."""
    return {
        "HOST_OFFLINE_REFUSED": "Connection Refused",
        "HOST_OFFLINE_NETWORK": "Network Unreachable",
        "HOST_OFFLINE_TIMEOUT": "Timeout",
        "HOST_NODATA": "No Data",
        "COMMUNICATION_TIMEOUT": "Communication Timeout",
    }.get(alert_type, "Alert")


def get_state_icon(state):
    """Status circle for the ticket body."""
    if state in ("OK", "UP"):
        return "\U0001F7E2"
    if state in ("WARNING", "WARN"):
        return "\U0001F7E1"
    return "\U0001F534"


def build_cmk_marker(hostname, ip):
    """Marker used to find the ticket back from the host it belongs to."""
    return f"[CMK HOST={hostname} IP={ip}]"


def build_description(hostname, ip, service, state, output, marker):
    """Build the HTML body used when opening a ticket."""
    icon = get_state_icon(state)
    return (
        f"<b>{icon} {html.escape(state)} - monitoring alert</b><br><br>"
        f"Host: {html.escape(hostname)} ({html.escape(ip)})<br>"
        f"Service: {html.escape(service)}<br>"
        f"State: {html.escape(state)}<br>"
        f"Output:<br><pre>{html.escape(output)}</pre><br>"
        f"{html.escape(marker)}"
    )


def build_note(hostname, ip, service, state, last_state, output, flap_msg):
    """Build the HTML body of a private note on an existing ticket."""
    icon = get_state_icon(state)
    stamp = datetime.now().strftime("%d/%m/%y %H:%M")
    if state in ("OK", "UP"):
        header = f"{icon} [{stamp}] ALERT CLEARED"
    elif flap_msg:
        header = f"{icon} [{stamp}] FLAPPING DETECTED"
    else:
        header = f"{icon} [{stamp}] ALERT UPDATE"

    body = (
        f"<b>{header}</b><br><br>"
        f"Host: {html.escape(hostname)} ({html.escape(ip)})<br>"
        f"Service: {html.escape(service)}<br>"
        f"State: {html.escape(last_state)} -&gt; {html.escape(state)}<br>"
        f"Output:<br><pre>{html.escape(output)}</pre>"
    )
    if flap_msg:
        body += f"<br>Flapping: {html.escape(flap_msg)}"
    return body


## Freshdesk operations


def fetch_ticket(ticket_id):
    """Return the ticket payload, or None when it is gone or unreadable."""
    status, body = api_request("GET", f"/tickets/{ticket_id}")
    if status == 404:
        return None
    if status != 200 or not isinstance(body, dict):
        debug(f"fetch_ticket #{ticket_id} failed (status {status})")
        return None
    return body


def is_ticket_usable(ticket):
    """Return False when a ticket can no longer be annotated.

    A deleted ticket is not a 404: the API still answers HTTP 200 and reports
    its original status, but rejects every write with 405 Method Not Allowed
    (allow: GET). Spam behaves the same way. Both have to be dropped from the
    cache, otherwise every later alert for that host keeps trying to annotate
    a ticket nobody will ever read.
    """
    if not ticket:
        return False
    return not (ticket.get("deleted") or ticket.get("spam"))


def fix_ticket_group(ticket_id):
    """Move a freshly created ticket back to the configured group.

    The helpdesk automation reassigns the group about a second after creation,
    so the PUT has to come after that rule has fired - otherwise the rule wins
    and the ticket stays in the wrong group. The result is read back because
    the create response cannot be trusted here.
    """
    if not FRESHDESK_GROUP_ID:
        return True

    want = int(FRESHDESK_GROUP_ID)
    for attempt in range(1, GROUP_FIX_ATTEMPTS + 1):
        time.sleep(GROUP_FIX_DELAY)

        status, _ = api_request("PUT", f"/tickets/{ticket_id}", {"group_id": want})
        if status != 200:
            log(f"WARN: group fix PUT on #{ticket_id} returned {status} "
                f"(attempt {attempt}/{GROUP_FIX_ATTEMPTS})")
            continue

        ticket = fetch_ticket(ticket_id)
        if ticket and ticket.get("group_id") == want:
            debug(f"Ticket #{ticket_id} group confirmed: {want}")
            return True

        got = ticket.get("group_id") if ticket else "unknown"
        log(f"WARN: ticket #{ticket_id} still in group {got}, expected {want} "
            f"(attempt {attempt}/{GROUP_FIX_ATTEMPTS})")

    log(f"ERROR: could not move ticket #{ticket_id} to group {want}")
    return False


def create_ticket(subject, description, priority):
    """Open a ticket and return its id, or None on failure.

    'type' is intentionally not sent: the helpdesk automation sets it, and the
    value it picks is the wanted one. Sending it only causes it to be
    overwritten a second later.
    """
    if not FRESHDESK_REQUESTER_EMAIL:
        log("ERROR: FRESHDESK_REQUESTER_EMAIL not set")
        return None

    payload = {
        "email": FRESHDESK_REQUESTER_EMAIL,
        "subject": subject,
        "description": description,
        "status": STATUS_OPEN,
        "priority": priority,
        "custom_fields": {"tipo_intervento": FRESHDESK_TIPO_INTERVENTO},
    }
    if FRESHDESK_GROUP_ID:
        payload["group_id"] = int(FRESHDESK_GROUP_ID)

    status, body = api_request("POST", "/tickets", payload)
    if status != 201 or not isinstance(body, dict):
        log(f"ERROR: create ticket failed (status {status}): {json.dumps(body)[:300]}")
        return None

    ticket_id = body.get("id")
    if not ticket_id:
        log(f"ERROR: no ticket id in response: {json.dumps(body)[:300]}")
        return None

    fix_ticket_group(ticket_id)
    return int(ticket_id)


def add_private_note(ticket_id, note):
    """Add a private note. Returns 0 on success, 2 when the ticket is gone, 1 otherwise."""
    status, body = api_request("POST", f"/tickets/{ticket_id}/notes",
                               {"body": note, "private": True})
    if status == 201:
        return 0
    if status == 404:
        log(f"WARN: ticket #{ticket_id} not found (404)")
        return 2
    log(f"ERROR: add note to #{ticket_id} failed (status {status}): {json.dumps(body)[:300]}")
    return 1


## Self-test


def self_test():
    """Exercise the pure helpers against known inputs and report PASS/FAIL."""
    global AGGREGATE_BY_HOST

    failures = 0

    def check(name, got, want):
        nonlocal failures
        if got == want:
            print(f"PASS: {name}")
        else:
            print(f"FAIL: {name}: got {got!r}, want {want!r}")
            failures += 1

    check("detect_alert_type refused",
          detect_alert_type("Connection refused by peer"), "HOST_OFFLINE_REFUSED")
    check("detect_alert_type network",
          detect_alert_type("Network unreachable"), "HOST_OFFLINE_NETWORK")
    check("detect_alert_type timeout",
          detect_alert_type("Request timed out"), "HOST_OFFLINE_TIMEOUT")
    check("detect_alert_type nodata",
          detect_alert_type("No data from piggyback source"), "HOST_NODATA")
    check("detect_alert_type unknown",
          detect_alert_type("CPU utilization 95%"), "UNKNOWN")

    check("get_alert_label known",
          get_alert_label("HOST_NODATA"), "No Data")
    check("get_alert_label fallback",
          get_alert_label("SOMETHING_ELSE"), "Alert")

    check("get_state_icon ok", get_state_icon("OK"), "\U0001F7E2")
    check("get_state_icon warn", get_state_icon("WARNING"), "\U0001F7E1")
    check("get_state_icon crit", get_state_icon("CRITICAL"), "\U0001F534")

    saved = AGGREGATE_BY_HOST
    AGGREGATE_BY_HOST = 1
    check("get_ticket_key aggregated", get_ticket_key("host1", "CPU"), "host1")
    AGGREGATE_BY_HOST = 0
    check("get_ticket_key per service", get_ticket_key("host1", "CPU"), "host1:CPU")
    AGGREGATE_BY_HOST = saved

    check("build_cmk_marker",
          build_cmk_marker("host1", "192.0.2.10"), "[CMK HOST=host1 IP=192.0.2.10]")

    # A deleted ticket answers 200 with its original status, so the deleted
    # flag is the only thing separating it from a live one.
    check("is_ticket_usable live",
          is_ticket_usable({"status": 2, "deleted": False, "spam": False}), True)
    check("is_ticket_usable deleted",
          is_ticket_usable({"status": 2, "deleted": True, "spam": False}), False)
    check("is_ticket_usable spam",
          is_ticket_usable({"status": 2, "deleted": False, "spam": True}), False)
    check("is_ticket_usable missing", is_ticket_usable(None), False)

    # An env file must not clobber a value CheckMK already exported, and a
    # missing file must stay silent rather than abort the notification.
    env_probe = f"FRESHDESK_SELFTEST_{os.getpid()}"
    os.environ[env_probe] = "from-environment"
    tmp_env = os.path.join(os.path.dirname(TICKET_CACHE) or ".", f".selftest.{os.getpid()}.env")
    try:
        os.makedirs(os.path.dirname(tmp_env) or ".", exist_ok=True)
        with open(tmp_env, "w") as f:
            f.write("# comment\n")
            f.write(f'export {env_probe}="from-file"\n')
            f.write("FRESHDESK_SELFTEST_ONLY_IN_FILE='file-value'\n")
        load_env(tmp_env)
        check("load_env keeps existing value",
              os.environ.get(env_probe), "from-environment")
        check("load_env sets missing value",
              os.environ.get("FRESHDESK_SELFTEST_ONLY_IN_FILE"), "file-value")
    except Exception as e:
        print(f"FAIL: load_env file cases: {e}")
        failures += 1
    finally:
        for name in (env_probe, "FRESHDESK_SELFTEST_ONLY_IN_FILE"):
            os.environ.pop(name, None)
        if os.path.exists(tmp_env):
            os.remove(tmp_env)

    load_env("/nonexistent/freshdesk/env/file")
    check("load_env tolerates missing file", True, True)

    check("is_transient_network_error true",
          is_transient_network_error("Temporary failure in name resolution"), True)
    check("is_transient_network_error false",
          is_transient_network_error("401 Unauthorized"), False)

    # HTML injection from check output must not break out of the ticket body.
    desc = build_description("host1", "192.0.2.10", "CPU", "CRITICAL",
                             "<script>alert(1)</script>", "[CMK HOST=host1 IP=192.0.2.10]")
    check("build_description escapes output", "<script>" in desc, False)
    check("build_description keeps marker", "CMK HOST=host1" in desc, True)

    note = build_note("host1", "192.0.2.10", "CPU", "OK", "CRITICAL", "recovered", "")
    check("build_note shows transition", "CRITICAL -&gt; OK" in note, True)
    check("build_note cleared header", "ALERT CLEARED" in note, True)

    flap = build_note("host1", "192.0.2.10", "CPU", "CRITICAL", "OK", "down",
                      "6 state changes in 10 minutes")
    check("build_note flapping header", "FLAPPING DETECTED" in flap, True)

    print(f"\n{'OK' if failures == 0 else 'FAILED'}: {failures} failure(s)")
    return 1 if failures else 0


## Notify


def notify():
    """Handle one CheckMK notification."""
    init_cache()

    hostname = os.environ.get("NOTIFY_HOSTNAME", "unknown")
    real_ip = os.environ.get("NOTIFY_HOSTLABEL_real_ip",
                             os.environ.get("NOTIFY_HOSTADDRESS", "N/A"))
    what = os.environ.get("NOTIFY_WHAT", "SERVICE")

    if what == "SERVICE":
        service = os.environ.get("NOTIFY_SERVICEDESC", "SERVICE")
        state = os.environ.get("NOTIFY_SERVICESHORTSTATE", "UNKNOWN")
        last_state = os.environ.get("NOTIFY_PREVIOUSSERVICEHARDSHORTSTATE", "OK")
        output = os.environ.get("NOTIFY_SERVICEOUTPUT", "N/A")
        long_output = os.environ.get("NOTIFY_SERVICELONGOUTPUT", "").replace("\\n", "\n")
    else:
        service = "HOST"
        state = os.environ.get("NOTIFY_HOSTSHORTSTATE", "UNKNOWN")
        last_state = os.environ.get("NOTIFY_PREVIOUSHOSTHARDSHORTSTATE", "UP")
        output = os.environ.get("NOTIFY_HOSTOUTPUT", "N/A")
        long_output = os.environ.get("NOTIFY_LONGHOSTOUTPUT", "").replace("\\n", "\n")

    full_output = output + ("\n" + long_output if long_output else "")

    key = get_ticket_key(hostname, service)
    record_state_change(key, state)
    _, flap_msg = is_flapping(key)

    ticket_id = get_ticket_id(key)

    # A ticket already resolved or closed in the helpdesk must not be reopened
    # or annotated: drop it so the next alert opens a fresh one. Checked on
    # every state, recoveries included - a flapping service can come back after
    # a technician has already closed the ticket.
    if ticket_id:
        ticket = fetch_ticket(ticket_id)
        if not is_ticket_usable(ticket):
            log(f"Ticket #{ticket_id} is gone (missing, deleted or spam), removing from cache")
            remove_ticket_from_cache(key)
            ticket_id = None
        elif ticket.get("status") in RESOLVED_STATUSES:
            log(f"Ticket #{ticket_id} is resolved/closed, removing from cache")
            log_ticket_event("CLOSED", ticket_id,
                             f"{hostname}/{service} - next alert opens a new ticket")
            remove_ticket_from_cache(key)
            ticket_id = None

    if ticket_id:
        log(f"Updating existing ticket #{ticket_id}")
        note = build_note(hostname, real_ip, service, state, last_state,
                          full_output, flap_msg)
        result = add_private_note(ticket_id, note)

        if result == 0:
            log_ticket_event("NOTE", ticket_id, f"{hostname}/{service} {last_state} -> {state}")
            update_ticket_state(key, state)
            if state in ("OK", "UP") and (AGGREGATE_BY_HOST != 1 or RESOLVE_ON_SERVICE_OK == 1):
                mark_ticket_resolved(key)
        elif result == 2:
            remove_ticket_from_cache(key)
        return 0

    if state not in ("CRITICAL", "CRIT", "DOWN"):
        # WARNING and recoveries only annotate an existing ticket; they never
        # open one, otherwise every transient warning becomes a ticket.
        debug(f"No ticket for {key} and state is {state}, nothing to do")
        return 0

    log(f"Creating new ticket for {hostname}/{service}")
    alert_type = detect_alert_type(output)
    subject = f"[{state} - {get_alert_label(alert_type)}] {hostname}"
    if what == "SERVICE":
        subject += f" - {service}"

    description = build_description(hostname, real_ip, service, state, full_output,
                                    build_cmk_marker(hostname, real_ip))

    new_id = create_ticket(subject, description, PRIORITY_HIGH)
    if new_id:
        save_ticket_cache(key, new_id, state)
        log_ticket_event("CREATED", new_id, f"{hostname}/{service} {state}")
    else:
        log("Failed to create ticket")
        return 1

    return 0


if "--self-test" in sys.argv:
    sys.exit(self_test())
else:
    sys.exit(notify())
