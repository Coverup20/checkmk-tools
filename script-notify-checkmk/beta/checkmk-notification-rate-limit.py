#!/usr/bin/env python3
# Notification rate-limiter
# Bulk: yes
# CheckMK notification script — wraps M@il-compatible mail delivery with a
# fail2ban-inspired rate limiter for HOST STATE and SERVICE STATE PING.
#
# Mode audit (default):  every notification is sent; the rate-limit decision
#                         is calculated and logged but never enforced.
# Mode enforce:          notifications are suppressed once the transition
#                         threshold is reached within the observation window.
#
# Version: 1.0.0-beta

import os
import sys
import json
import time
import fcntl
import shutil
import logging
import tempfile
import subprocess
from pathlib import Path
from urllib.parse import quote

VERSION = "1.0.0-beta"

# ---------------------------------------------------------------------------
# Configuration — defaults (overridden by config file values)
# ---------------------------------------------------------------------------
CONFIG = {
    "mode": "audit",
    "host_state": {
        "enabled": True,
        "observation_window": 1800,
        "max_transitions": 4,
        "suppression_time": 3600,
    },
    "service_state_ping": {
        "enabled": True,
        "observation_window": 1800,
        "max_transitions": 6,
        "suppression_time": 3600,
    },
}

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
OMD_ROOT = os.environ.get("OMD_ROOT", "")
STATE_DIR = os.environ.get(
    "NOTIFY_RATE_LIMIT_STATE_DIR",
    os.path.join(OMD_ROOT, "var", "check_mk", "notification-rate-limit"),
)
LOG_DIR = os.environ.get(
    "NOTIFY_RATE_LIMIT_LOG_DIR",
    os.path.join(OMD_ROOT, "var", "log"),
)
CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "rate_limit_config.json",
)

# Override CONFIG_PATH via env for tests
CONFIG_PATH = os.environ.get(
    "NOTIFY_RATE_LIMIT_CONFIG",
    CONFIG_PATH,
)

# ---------------------------------------------------------------------------
# Mail constants (M@il compatible)
# ---------------------------------------------------------------------------
CMK_URL = os.environ.get("CMK_URL", "https://<your-checkmk-server>/monitoring")
FROM_EMAIL = os.environ.get("FROM_EMAIL", "checkmk@example.com")


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logger():
    """Configure a file logger under the Checkmk site log area.

    Falls back to stderr when the log directory is unavailable or outside
    an OMD site — this is safe for testing and development.
    """
    log = logging.getLogger("notification_rate_limit")
    log.setLevel(logging.DEBUG)
    log.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if LOG_DIR and os.path.isdir(LOG_DIR):
        log_path = os.path.join(LOG_DIR, "notification-rate-limit.log")
        handler = logging.FileHandler(log_path)
    else:
        handler = logging.StreamHandler(sys.stderr)

    handler.setFormatter(fmt)
    log.addHandler(handler)
    return log


LOG = setup_logger()


# ---------------------------------------------------------------------------
# Configuration loading
# ---------------------------------------------------------------------------

def load_config():
    """Load configuration from JSON file, falling back to defaults.

    The config file is optional.  Missing or corrupt files produce a logged
    warning and fall back to CONFIG — this is a fail-open behaviour.

    Returns a dict with the same top-level keys as CONFIG.
    """
    cfg = dict(CONFIG)
    path = Path(CONFIG_PATH)
    if not path.is_file():
        LOG.debug("Config file %s not found — using defaults", CONFIG_PATH)
        return cfg

    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            LOG.warning("Config file %s: root is not a dict — using defaults", CONFIG_PATH)
            return cfg

        # Merge top-level keys
        for key in ("mode",):
            if key in data:
                cfg[key] = data[key]

        # Merge nested sections
        for section in ("host_state", "service_state_ping"):
            if section in data and isinstance(data[section], dict):
                for opt in ("enabled", "observation_window", "max_transitions", "suppression_time"):
                    if opt in data[section]:
                        cfg[section][opt] = data[section][opt]

        LOG.info("Configuration loaded from %s", CONFIG_PATH)
    except (json.JSONDecodeError, OSError) as exc:
        LOG.warning("Cannot load config %s: %s — using defaults", CONFIG_PATH, exc)

    return cfg


CFG = load_config()


# ---------------------------------------------------------------------------
# M@il-compatible mail delivery
# ---------------------------------------------------------------------------

def get_color(state):
    """Return an HTML colour for a state label."""
    s = state.upper()
    if s in ("OK", "UP"):
        return "#13d389"
    if s in ("WARNING", "WARN"):
        return "#ffd700"
    if s in ("CRITICAL", "CRIT", "DOWN"):
        return "#ff5151"
    return "#ff9800"


def get_label(state):
    """Return an abbreviated state label."""
    s = state.upper()
    if s == "WARNING":
        return "WARN"
    if s == "CRITICAL":
        return "CRIT"
    if s == "UNKNOWN":
        return "UNKN"
    return s


def build_email_content(to_email, hostname, service, old_state, new_state,
                        output, long_output, host_address, real_ip, frp,
                        site, date):
    """Build a complete MIME-HTML email matching the M@il format."""
    # Replace IP in output
    safe_output = output
    safe_long = long_output
    if host_address and host_address != real_ip:
        safe_output = safe_output.replace(host_address, real_ip)
        safe_long = safe_long.replace(host_address, real_ip)

    full_output = safe_output
    if safe_long:
        full_output += "<br>" + safe_long.replace("\n", "<br>")

    old_color = get_color(old_state)
    new_color = get_color(new_state)
    old_label = get_label(old_state)
    new_label = get_label(new_state)

    frp_row = ""
    if frp == "yes":
        frp_row = (
            '<tr><td>FRP Tunnel:</td><td>'
            '<span style="color:#00d4aa;font-weight:600"> Active</span>'
            f' (Real IP: {real_ip})</td></tr>'
        )

    cmk_url = CMK_URL.rstrip("/")
    h_enc = quote(hostname)
    srv_enc = quote(service)

    is_host_check = (service in ("Host Check", ""))
    if is_host_check:
        srv_link = f"{cmk_url}/check_mk/view.py?view_name=host&host={h_enc}"
    else:
        srv_link = f"{cmk_url}/check_mk/view.py?view_name=service&host={h_enc}&service={srv_enc}"

    host_link = f"{cmk_url}/check_mk/view.py?view_name=host&host={h_enc}"
    output_summary = safe_output.replace("\n", "<br>")

    subject = f"Checkmk: {hostname}"
    if not is_host_check:
        subject += f"/{service}"
    subject += f" {new_label}"

    email = (
        f"To: {to_email}\n"
        f"From: {FROM_EMAIL}\n"
        f"Subject: {subject}\n"
        "Content-Type: text/html; charset=UTF-8\n"
        "MIME Version: 1.0\n"
        "\n"
        "<!DOCTYPE html>\n"
        '<html><head><meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<style>"
        "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,"
        "sans-serif;background:#f5f5f5;margin:0;padding:20px}"
        ".container{max-width:650px;margin:0 auto;background:#fff;"
        "border-radius:8px;overflow:hidden;box-shadow:0 2px 8px "
        "rgba(0,0,0,.1);border:2px solid #e0e0e0}"
        ".header{background:#f8f9fa;padding:20px;display:flex;"
        "align-items:center;gap:10px;border-bottom:2px solid #d0d0d0}"
        ".logo-icon{width:24px;height:24px;background:#00d4aa;"
        "border-radius:4px;color:#fff;display:flex;align-items:center;"
        "justify-content:center;font-weight:bold;font-size:14px}"
        ".logo-text{color:#00d4aa;font-size:18px;font-weight:600}"
        ".status-bar{background:linear-gradient(90deg,"
        f"{old_color} 0%,{old_color} 48%,#666 48%,#666 52%,"
        f"{new_color} 52%,{new_color} 100%);"
        "height:6px;border-bottom:1px solid rgba(0,0,0,.15)}"
        ".content{padding:30px}"
        ".event-row{background:#f8f9fa;padding:15px 20px;border-radius:6px;"
        "margin-bottom:20px;display:flex;justify-content:space-between;"
        "align-items:center;flex-wrap:wrap;gap:10px;border:1px solid #e0e0e0}"
        ".event-label{color:#666;font-size:14px;font-weight:500}"
        ".event-value{color:#333;font-size:14px;word-break:break-word}"
        ".state-badge{padding:6px 14px;border-radius:4px;font-weight:600;"
        "font-size:13px;color:#fff;background-color:"
        f"{new_color};white-space:nowrap}}"
        ".section-title{color:#999;font-size:18px;font-weight:600;"
        "margin:20px 0 15px}"
        ".info-table{width:100%;border-collapse:collapse;margin-bottom:25px}"
        ".info-table td{padding:10px 0;border-bottom:1px solid #e0e0e0;"
        "word-break:break-word}"
        ".info-table td:first-child{color:#333;font-weight:600;width:140px}"
        ".info-table td:last-child{color:#666}"
        ".service-details{background:linear-gradient(135deg,#fafafa 0%,"
        "#f5f5f5 100%);padding:20px;border-radius:8px;border:1px solid "
        f"{new_color};border-left:6px solid {new_color};"
        "margin-top:15px;overflow-x:auto;box-shadow:0 2px 4px "
        "rgba(0,0,0,.05)}"
        ".service-details pre{margin:0;white-space:pre-wrap;word-wrap:break-word;"
        "font-family:'Courier New',monospace;font-size:13px;color:#333;"
        "line-height:1.6}"
        ".footer{background:#f8f8f8;padding:20px;text-align:center;"
        "color:#666;font-size:13px}"
        ".buttons{margin-top:15px;display:flex;gap:10px;"
        "justify-content:center;flex-wrap:wrap}"
        ".btn{display:inline-block;padding:12px 24px;"
        f"background:{new_color};color:#fff;text-decoration:none;"
        "border-radius:4px;font-weight:600;font-size:14px;min-width:120px;"
        "border:2px solid #000;transition:filter 0.2s}"
        ".btn:hover{filter:brightness(0.85)}"
        "</style></head><body>"
        '<div class="container">'
        '<div class="header"><div class="logo-icon">C</div>'
        '<span class="logo-text">checkmk</span></div>'
        '<div class="status-bar"></div>'
        '<div class="content">'
        '<div class="event-row">'
        '<span class="event-label">Event:</span>'
        '<div><span class="state-badge" style="background:'
        f"{old_color}\">{old_label}</span>"
        f' → <span class="state-badge">{new_label}</span></div></div>'
        '<div class="event-row">'
        f'<span class="event-label">Service:</span>'
        f'<span class="event-value">{service}</span></div>'
        '<div class="event-row">'
        f'<span class="event-label">Host:</span>'
        f'<span class="event-value">{hostname}</span></div>'
        '<h2 class="section-title">Event overview</h2>'
        '<table class="info-table">'
        f"<tr><td>Event date:</td><td>{date}</td></tr>"
        f"<tr><td>Address:</td><td>{real_ip}</td></tr>"
        f"{frp_row}"
        f"<tr><td>Site:</td><td>{site}</td></tr>"
        f"<tr><td>Summary:</td><td>{output_summary}</td></tr>"
        "</table>"
        '<h2 class="section-title">Service details:</h2>'
        '<div class="service-details">'
        f"<pre>{full_output}</pre></div></div>"
        '<div class="footer">Sent by Checkmk'
        '<div class="buttons">'
        f'<a href="{srv_link}" class="btn">Service</a>'
        f'<a href="{host_link}" class="btn">Host</a>'
        "</div></div></div></body></html>"
    )

    return email


def send_email(email_content):
    """Deliver an email via /usr/sbin/sendmail.

    Returns an exit code suitable for Checkmk (0 = success).
    """
    try:
        proc = subprocess.run(
            ["/usr/sbin/sendmail", "-t"],
            input=email_content.encode("utf-8"),
            timeout=30,
        )
        return proc.returncode
    except subprocess.TimeoutExpired:
        LOG.error("sendmail timeout")
        return 1
    except FileNotFoundError:
        LOG.error("sendmail not found")
        return 1
    except Exception as exc:
        LOG.error("sendmail error: %s", exc)
        return 1


# ---------------------------------------------------------------------------
# Rate-limit state management
# ---------------------------------------------------------------------------

def get_state_path():
    """Return the path to the shared state file."""
    path = Path(STATE_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path / "state.json"


def read_state(state_path):
    """Read the JSON state file, returning an empty dict on failure."""
    try:
        raw = state_path.read_bytes()
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
        LOG.warning("State file %s is not a dict — resetting", state_path)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        LOG.debug("Cannot read state %s: %s — starting fresh", state_path, exc)
    return {}


def write_state(state_path, state):
    """Atomically write the JSON state file using a temp file + rename.

    Safe against partial writes and concurrent readers.
    """
    tmp = None
    try:
        fd, tmp_name = tempfile.mkstemp(
            dir=str(state_path.parent),
            prefix=".state_tmp_",
        )
        os.close(fd)
        tmp = Path(tmp_name)
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
        tmp.chmod(0o640)
        shutil.move(str(tmp), str(state_path))
    except Exception as exc:
        LOG.error("Cannot write state file %s: %s", state_path, exc)
        if tmp and tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


def get_lock_path(state_path):
    """Return the flock-based lock file path (next to the state file)."""
    return state_path.parent / "state.lock"


class StateLock:
    """Context manager for exclusive access to the state file."""

    def __init__(self, lock_path):
        self._lock_path = lock_path
        self._fd = None

    def __enter__(self):
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = self._lock_path.open("w")
        fcntl.flock(self._fd.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc_info):
        if self._fd:
            fcntl.flock(self._fd.fileno(), fcntl.LOCK_UN)
            self._fd.close()
            self._fd = None
        self._lock_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Transition tracking
# ---------------------------------------------------------------------------

def now():
    """Return current Unix time."""
    return int(time.time())


def classify_notification():
    """Read Checkmk environment variables and classify the event.

    Returns a dict with:
        is_host, hostname, service_desc, old_state, new_state, output,
        long_output, host_address, real_ip, frp, site, date, to_email

    On any reading failure each field defaults to safe values.
    """
    to_email = os.environ.get("NOTIFY_CONTACTEMAIL", "root@localhost")
    hostname = os.environ.get("NOTIFY_HOSTNAME", "Unknown")
    site = os.environ.get("NOTIFY_OMD_SITE", "monitoring")
    date = os.environ.get("NOTIFY_SHORTDATETIME", "")
    host_address = os.environ.get("NOTIFY_HOSTADDRESS", "N/A")
    real_ip = os.environ.get("NOTIFY_HOSTLABEL_real_ip", host_address)
    frp = os.environ.get("NOTIFY_HOSTLABEL_frp_tunnel", "no")
    output = os.environ.get("NOTIFY_HOSTOUTPUT", "N/A")
    long_output = os.environ.get("NOTIFY_LONGHOSTOUTPUT", "")
    service_desc = os.environ.get("NOTIFY_SERVICEDESC", "")

    # Determine if host or service notification
    is_service = bool(service_desc) and not service_desc.startswith("$")

    if is_service:
        old_state = (
            os.environ.get("NOTIFY_PREVIOUSSERVICEHARDSHORTSTATE")
            or os.environ.get("NOTIFY_LASTSERVICESTATE", "OK")
        )
        new_state = (
            os.environ.get("NOTIFY_SERVICESHORTSTATE")
            or os.environ.get("NOTIFY_SERVICESTATE", "UNKNOWN")
        )
        output = os.environ.get("NOTIFY_SERVICEOUTPUT", "N/A")
        long_output = os.environ.get("NOTIFY_LONGSERVICEOUTPUT", "")
    else:
        old_state = (
            os.environ.get("NOTIFY_PREVIOUSHOSTHARDSHORTSTATE")
            or os.environ.get("NOTIFY_LASTHOSTSTATE", "UP")
        )
        new_state = (
            os.environ.get("NOTIFY_HOSTSHORTSTATE")
            or os.environ.get("NOTIFY_HOSTSTATE", "DOWN")
        )

    return {
        "is_host": not is_service,
        "hostname": hostname,
        "service_desc": service_desc,
        "old_state": old_state.upper(),
        "new_state": new_state.upper(),
        "output": output,
        "long_output": long_output,
        "host_address": host_address,
        "real_ip": real_ip,
        "frp": frp,
        "site": site,
        "date": date,
        "to_email": to_email,
    }


def is_supported_transition(event):
    """Determine whether the event is a tracked transition type.

    Returns (category, is_transition) where:
        category  = "host_state" | "service_state_ping" | None
        is_transition = True if this is a real state change
    """
    if event["is_host"]:
        # HOST STATE — track UP ↔ DOWN
        valid_pairs = {("UP", "DOWN"), ("DOWN", "UP")}
        pair = (event["old_state"], event["new_state"])
        if pair in valid_pairs:
            return "host_state", True
        return "host_state", False  # UP→UP, DOWN→DOWN, unsupported states
    else:
        # Service — only PING
        if event["service_desc"] != "PING":
            return None, False
        # SERVICE STATE PING — track OK ↔ CRIT
        valid_pairs = {("OK", "CRIT"), ("CRIT", "OK"),
                       ("OK", "CRITICAL"), ("CRITICAL", "OK")}
        pair = (event["old_state"], event["new_state"])
        if pair in valid_pairs:
            return "service_state_ping", True
        # Log WARN/UNKNOWN but don't count them
        if event["new_state"] in ("WARNING", "WARN", "UNKNOWN", "UNKN"):
            LOG.info("%s/%s PING state %s → %s — not counted",
                     event["hostname"], event["service_desc"],
                     event["old_state"], event["new_state"])
            return "service_state_ping", False
        return "service_state_ping", False


def make_category_record():
    """Return a fresh per-category state record."""
    return {
        "last_state": None,
        "transitions": [],
        "suppression_until": 0,
        "suppressed_count": 0,
    }


def get_host_state(state, hostname):
    """Return the per-host state dict, creating it if absent."""
    if hostname not in state:
        state[hostname] = {
            "host_state": make_category_record(),
            "service_state_ping": make_category_record(),
        }
    return state[hostname]


def prune_transitions(transitions, window):
    """Remove transition timestamps older than `window` seconds ago."""
    cutoff = now() - window
    return [t for t in transitions if t >= cutoff]


def evaluate_rate_limit(event):
    """Evaluate the rate-limit decision for one notification event.

    This is the core logic — it reads state, decides, writes state, and
    returns a decision dict.

    The function is fail-open: any unexpected exception causes a
    FAIL_OPEN decision that sends the mail normally.
    """
    state_path = get_state_path()
    lock_path = get_lock_path(state_path)
    category, is_transition = is_supported_transition(event)

    # Non-tracked events always pass
    if category is None:
        return {
            "decision": "BYPASS",
            "category": None,
            "reason": "Not a tracked notification type",
        }

    cfg_section = CFG.get(category, {})
    enabled = cfg_section.get("enabled", True)
    window = cfg_section.get("observation_window", 1800)
    max_trans = cfg_section.get("max_transitions", 4)
    suppress_time = cfg_section.get("suppression_time", 3600)

    # Scope isolation for future host-group filter
    # (reserved: future allowed_hosts / excluded_hosts check)

    if not enabled:
        return {
            "decision": "BYPASS",
            "category": category,
            "reason": f"{category} rate-limiting disabled",
        }

    try:
        with StateLock(lock_path):
            state = read_state(state_path)
            host_rec = get_host_state(state, event["hostname"])
            cat_rec = host_rec[category]

            last_state = cat_rec.get("last_state")
            transitions = cat_rec.get("transitions", [])
            suppression_until = cat_rec.get("suppression_until", 0)
            suppressed_count = cat_rec.get("suppressed_count", 0)

            # A transition is real only when the new state differs from
            # the last recorded state.  Repeated identical notifications
            # (e.g. second DOWN → DOWN) must NOT be counted.
            if is_transition and last_state is not None:
                if event["new_state"] == last_state:
                    is_transition = False

            ts = now()

            # Update last state
            cat_rec["last_state"] = event["new_state"]

            decision = "SEND"
            reason = "Normal notification"

            if suppression_until > ts:
                # Currently in suppression
                if is_transition:
                    suppressed_count += 1
                    cat_rec["suppressed_count"] = suppressed_count

                mode = CFG.get("mode", "audit")
                if mode == "enforce":
                    decision = "SUPPRESS"
                    reason = (
                        f"Suppression active until "
                        f"{suppression_until} "
                        f"(transition #{suppressed_count} suppressed)"
                    )
                else:
                    decision = "WOULD_SUPPRESS"
                    reason = (
                        f"Audit mode — would suppress (active until "
                        f"{suppression_until}, "
                        f"transition #{suppressed_count} counted)"
                    )
            else:
                # Not in suppression — check if we need to enter it
                if is_transition:
                    # Count this transition
                    transitions.append(ts)
                    transitions = prune_transitions(transitions, window)
                    count = len(transitions)

                    if count >= max_trans:
                        # Enter suppression
                        suppression_until = ts + suppress_time
                        suppressed_count = 0
                        cat_rec["suppression_until"] = suppression_until
                        cat_rec["suppressed_count"] = 0

                        mode = CFG.get("mode", "audit")
                        if mode == "enforce":
                            # First suppression — the transition that
                            # triggers it still sends (first genuine
                            # problem must pass). Subsequent ones are
                            # suppressed within the loop above.
                            decision = "SEND"
                            reason = (
                                f"Suppression entered "
                                f"(transition #{count}/{max_trans} "
                                f"in {window}s)"
                            )
                            LOG.info(
                                "%s/%s %s suppression started — "
                                "%d transitions in %ds, "
                                "ban until %d",
                                event["hostname"],
                                category,
                                category,
                                count,
                                window,
                                suppression_until,
                            )
                        else:
                            decision = "SEND"
                            reason = (
                                f"Audit — threshold reached "
                                f"({count}/{max_trans}) — "
                                f"woULD_SUPPRESS next, "
                                f"suppression_until={suppression_until}"
                            )
                            LOG.info(
                                "%s/%s %s threshold reached "
                                "(audit mode) — %d transitions in %ds",
                                event["hostname"],
                                category,
                                category,
                                count,
                                window,
                            )
                    else:
                        decision = "SEND"
                        reason = (
                            f"Transition #{count}/{max_trans} "
                            f"in {window}s"
                        )
                else:
                    decision = "SEND"
                    reason = (
                        f"State {event['old_state']} → "
                        f"{event['new_state']} — no transition counted"
                    )

            # Persist updated state
            cat_rec["transitions"] = transitions
            cat_rec["suppression_until"] = suppression_until
            cat_rec["suppressed_count"] = suppressed_count
            write_state(state_path, state)

            # Clean up stale records for other hosts
            _cleanup_stale_records(state)

        return {
            "decision": decision,
            "category": category,
            "reason": reason,
            "transition_count": len(transitions),
            "suppression_until": cat_rec.get("suppression_until", 0),
        }

    except Exception as exc:
        LOG.error(
            "FAIL_OPEN: rate-limit state error for %s: %s — "
            "mail will be sent",
            event["hostname"],
            exc,
        )
        return {
            "decision": "FAIL_OPEN",
            "category": category,
            "reason": f"Rate-limit error: {exc} — mail sent anyway",
        }


def _cleanup_stale_records(state):
    """Remove hosts with no recent activity from the in-memory state.

    A record is stale when both categories have an empty transition list
    and no active suppression.
    """
    stale = []
    now_ts = now()
    for hostname, rec in state.items():
        if not isinstance(rec, dict):
            stale.append(hostname)
            continue
        h = rec.get("host_state", {})
        s = rec.get("service_state_ping", {})
        if (not h.get("transitions") and not s.get("transitions")
                and h.get("suppression_until", 0) <= now_ts
                and s.get("suppression_until", 0) <= now_ts):
            stale.append(hostname)
    for hostname in stale:
        del state[hostname]
    if stale:
        LOG.debug("Cleaned up %d stale records", len(stale))


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def log_decision(decision, event, rate_info):
    """Write a structured log line for a rate-limit decision.

    The log entry is always written regardless of the decision so that
    audit and production have a single source of truth.
    """
    LOG.info(
        "DECISION=%s host=%s category=%s old=%s new=%s "
        "transitions=%s window=%s suppress_until=%s reason=%s",
        decision.get("decision", "?"),
        event["hostname"],
        decision.get("category", "?"),
        event["old_state"],
        event["new_state"],
        decision.get("transition_count", "?"),
        CFG.get(decision.get("category", "x"), {}).get(
            "observation_window", "?",
        ) if decision.get("category") else "?",
        decision.get("suppression_until", "?"),
        decision.get("reason", "?"),
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    """Entry point — called by Checkmk for each notification.

    Returns an exit code suitable for Checkmk:
        0 = success (notification handled)
        1 = temporary error (not used, but preserved from M@il)
    """
    event = classify_notification()

    # Determine category and whether it is a tracked transition
    decision = evaluate_rate_limit(event)

    log_decision(decision, event, {})
    LOG.debug(
        "Mode=%s host=%s svc=%s old=%s new=%s decision=%s",
        CFG.get("mode", "audit"),
        event["hostname"],
        event.get("service_desc", "(host)"),
        event["old_state"],
        event["new_state"],
        decision["decision"],
    )

    # Mail delivery logic
    do_suppress = (decision["decision"] == "SUPPRESS")
    if do_suppress:
        LOG.info(
            "SUPPRESS %s/%s: mail NOT sent",
            event["hostname"],
            decision.get("category", "?"),
        )
        return 0

    # Build and send the M@il-compatible message
    service_label = event.get("service_desc", "")
    if event["is_host"]:
        service_label = "Host Check"

    email = build_email_content(
        to_email=event["to_email"],
        hostname=event["hostname"],
        service=service_label,
        old_state=event["old_state"],
        new_state=event["new_state"],
        output=event["output"],
        long_output=event["long_output"],
        host_address=event["host_address"],
        real_ip=event["real_ip"],
        frp=event["frp"],
        site=event["site"],
        date=event["date"],
    )

    rc = send_email(email)

    if decision["decision"] in ("WOULD_SUPPRESS", "FAIL_OPEN"):
        LOG.info(
            "WOULD_SUPPRESS/FAIL_OPEN %s/%s: mail SENT (audit mode)",
            event["hostname"],
            decision.get("category", "?"),
        )

    return rc


if __name__ == "__main__":
    sys.exit(main())
