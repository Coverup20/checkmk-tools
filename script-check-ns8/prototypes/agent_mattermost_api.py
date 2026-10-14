#!/usr/bin/env python3
"""agent_mattermost_api.py - CheckMK special agent (datasource program) for Mattermost, public endpoints only (PROTOTYPE)

Runs on the CheckMK server and prints CheckMK local-check lines. It deliberately
uses NO credentials: only the unauthenticated endpoints
  /api/v4/system/ping?get_server_status=true   status, database_status, filestore_status
  /api/v4/config/client?format=old             public client config (version, edition)
Mattermost has no end-to-end encryption and a system-admin token can read the
posts of any channel, so by default NO token is used: the agent sees only the
public endpoints and fewer metrics.

Optional --token-file (a personal access token of a system-admin user): adds
the metrics that need admin rights, read from /analytics/old, /jobs and
/plugins (counts and states only, never message or channel content). Use it
only where an admin token stored in the monitoring system is acceptable (a test
instance); Team Edition has no read-only admin role.

Certificate pinning (--pin-sha256): the lab's certificate is self-signed, so
normal CA validation is off (--insecure) and by itself that means ANY
certificate is accepted - a machine-in-the-middle on the same network could
present its own certificate, go unnoticed, and receive the token straight from
the "Authorization" header. --pin-sha256 closes that: give it the SHA-256
fingerprint (hex) of the real certificate (computed once, e.g. with
`openssl s_client -connect host:443 | openssl x509 -noout -fingerprint -sha256`,
or the small helper in this repo), and every connection then fails closed
unless the server presents EXACTLY that certificate, byte for byte. Not a
secret - a fingerprint identifies a certificate, it cannot be used to
impersonate it - so it is a plain CLI argument, not a token file.

Checks:
- Mattermost.Status    ping: overall status, database and file store
- Mattermost.Version   version and edition (informational)
- Mattermost.ApiTime   response time of the ping
With --token-file:
- Mattermost.Usage     users, teams, channels, posts, active users, sessions, websocket connections
- Mattermost.Database  database connections (informational)
- Mattermost.Jobs      background jobs that ended in error in the last 24 h
- Mattermost.Plugins   active plugins (informational)

Usage (datasource program):
  agent_mattermost_api.py --url https://mattermost.example.org --insecure \
      --pin-sha256 <fingerprint> [--token-file /path/token]

Version: 0.3.0"""

import argparse
import hashlib
import http.client
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from typing import List, Optional, Tuple

VERSION = "0.3.0"
RESPONSE_SECONDS = (1.0, 3.0)
JOB_WINDOW_MS = 24 * 3600 * 1000

_OUT: List[str] = []


def emit(state: int, name: str, text: str, metrics: Optional[List[str]] = None) -> None:
    name = re.sub(r"\s+", "_", name)
    _OUT.append("%d %s %s %s" % (state, name, "|".join(metrics) if metrics else "-", text.replace("\n", " ")))


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Like HTTPSConnection, but after the TLS handshake refuses to proceed unless the
    peer certificate's SHA-256 fingerprint matches exactly. Set via the class attribute
    (not __init__) because urllib's HTTPSHandler constructs these through a factory."""

    pinned_sha256 = ""

    def connect(self) -> None:
        super().connect()
        der = self.sock.getpeercert(binary_form=True)  # type: ignore[union-attr]
        if not der:
            raise ssl.SSLError("certificate pinning: no peer certificate available to check")
        actual = hashlib.sha256(der).hexdigest()
        if actual != self.pinned_sha256:
            raise ssl.SSLCertVerificationError(
                "certificate pin mismatch: expected %s, got %s (server certificate changed or a different host answered)"
                % (self.pinned_sha256, actual)
            )


def _opener(insecure: bool, pin_sha256: str) -> urllib.request.OpenerDirector:
    ctx = ssl.create_default_context()
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    if not pin_sha256:
        return urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))

    class PinnedHandler(urllib.request.HTTPSHandler):
        def https_open(self, req):  # noqa: ANN001 - matches urllib's own (untyped) signature
            def factory(host, **kwargs):
                conn = _PinnedHTTPSConnection(host, context=ctx, **kwargs)
                conn.pinned_sha256 = pin_sha256
                return conn

            return self.do_open(factory, req)

    return urllib.request.build_opener(PinnedHandler())


def get(url: str, insecure: bool, timeout: float = 15.0, token: str = "", any_json: bool = False, pin_sha256: str = "") -> Tuple[Optional[object], str, float]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, headers=headers)
    t0 = time.monotonic()
    try:
        with _opener(insecure, pin_sha256).open(req, timeout=timeout) as resp:
            body = json.load(resp)
        return (body if (any_json or isinstance(body, dict)) else None), "", time.monotonic() - t0
    except urllib.error.HTTPError as exc:
        return None, "token-rejected" if (token and exc.code in (401, 403)) else "http-%d" % exc.code, time.monotonic() - t0
    except (urllib.error.URLError, OSError, ValueError) as exc:
        # urlopen wraps a raised ssl.SSLCertVerificationError inside URLError.reason rather than
        # letting it propagate directly, so the pin-mismatch case must be detected this way to
        # avoid reporting a security-relevant certificate mismatch as a generic "unreachable".
        cause = getattr(exc, "reason", exc)
        if isinstance(cause, ssl.SSLCertVerificationError):
            return None, "PIN MISMATCH (possible machine-in-the-middle): %s" % cause, time.monotonic() - t0
        return None, "unreachable", time.monotonic() - t0


def admin_checks(base: str, token: str, insecure: bool, pin_sha256: str) -> None:
    """Metrics that need a system-admin token: counts and states only."""
    std, err, _ = get(base + "/api/v4/analytics/old?name=standard", insecure, token=token, any_json=True, pin_sha256=pin_sha256)
    if not isinstance(std, list):
        for name in ("Usage", "Database", "Jobs", "Plugins"):
            emit(3, "Mattermost." + name, "cannot read the admin API: %s" % err)
        return
    s = {row.get("name"): row.get("value") for row in std if isinstance(row, dict)}
    extra, _, _ = get(base + "/api/v4/analytics/old?name=extra_counts", insecure, token=token, any_json=True, pin_sha256=pin_sha256)
    e = {row.get("name"): row.get("value") for row in extra if isinstance(row, dict)} if isinstance(extra, list) else {}

    def n(d: dict, key: str) -> int:
        try:
            return int(float(d.get(key) or 0))
        except (TypeError, ValueError):
            return 0

    users, inactive = n(s, "unique_user_count"), n(s, "inactive_user_count")
    emit(0, "Mattermost.Usage", "%d users (%d inactive), %d team(s), %d public + %d private channels, %d posts, %d active today, %d sessions, %d websocket connections" % (
        users, inactive, n(s, "team_count"), n(s, "channel_open_count"), n(s, "channel_private_count"), n(s, "post_count"),
        n(s, "daily_active_users"), n(e, "session_count"), n(s, "total_websocket_connections")),
        ["users=%d;;;0;" % users, "users_inactive=%d;;;0;" % inactive, "teams=%d;;;0;" % n(s, "team_count"),
         "channels_public=%d;;;0;" % n(s, "channel_open_count"), "channels_private=%d;;;0;" % n(s, "channel_private_count"),
         "posts=%d;;;0;" % n(s, "post_count"), "users_active_daily=%d;;;0;" % n(s, "daily_active_users"),
         "users_active_monthly=%d;;;0;" % n(s, "monthly_active_users"), "sessions=%d;;;0;" % n(e, "session_count"),
         "websocket_connections=%d;;;0;" % n(s, "total_websocket_connections"), "files=%d;;;0;" % n(e, "total_file_count")])
    emit(0, "Mattermost.Database", "%d master and %d read connections" % (n(s, "total_master_db_connections"), n(s, "total_read_db_connections")),
         ["db_master_connections=%d;;;0;" % n(s, "total_master_db_connections"), "db_read_connections=%d;;;0;" % n(s, "total_read_db_connections")])

    jobs, jerr, _ = get(base + "/api/v4/jobs?per_page=50", insecure, token=token, any_json=True, pin_sha256=pin_sha256)
    if isinstance(jobs, list):
        now_ms = int(time.time() * 1000)
        failed = [j for j in jobs if j.get("status") == "error" and now_ms - int(j.get("last_activity_at") or 0) <= JOB_WINDOW_MS]
        kinds = sorted({str(j.get("type")) for j in failed})
        emit(1 if failed else 0, "Mattermost.Jobs", ("%d job(s) ended in error in the last 24 h: %s" % (len(failed), ", ".join(kinds))) if failed else "no job in error in the last 24 h (%d recent jobs checked)" % len(jobs),
             ["jobs_failed_24h=%d;1;;0;" % len(failed)])
    else:
        emit(3, "Mattermost.Jobs", "cannot read the jobs: %s" % jerr)

    plugins, perr, _ = get(base + "/api/v4/plugins", insecure, token=token, pin_sha256=pin_sha256)
    if isinstance(plugins, dict):
        active = sorted(str(p.get("id")) for p in (plugins.get("active") or []))
        emit(0, "Mattermost.Plugins", "%d active: %s" % (len(active), ", ".join(active) or "-"), ["plugins_active=%d;;;0;" % len(active)])
    else:
        emit(3, "Mattermost.Plugins", "cannot read the plugins: %s" % perr)


def main() -> int:
    ap = argparse.ArgumentParser(description="CheckMK special agent for Mattermost (public endpoints, no credentials)")
    ap.add_argument("--url", required=True, help="Mattermost base URL, e.g. https://mattermost.example.org")
    ap.add_argument("--insecure", action="store_true", help="do not verify the TLS certificate against a CA (needed for a self-signed lab certificate)")
    ap.add_argument("--pin-sha256", default="", help="SHA-256 fingerprint (hex) of the expected certificate; with --insecure this is what actually stops a machine-in-the-middle, not a secret")
    ap.add_argument("--token-file", default="", help="optional: file with a system-admin personal access token (mode 600) for the admin metrics")
    args = ap.parse_args()
    base = args.url.rstrip("/")
    pin = args.pin_sha256.strip().lower().replace(":", "")

    print("<<<check_mk>>>")
    print("Version: mattermost-api-special-agent-%s" % VERSION)
    print("AgentOS: mattermost-api")
    print("<<<local:sep(0)>>>")

    ping, err, secs = get(base + "/api/v4/system/ping?get_server_status=true", args.insecure, pin_sha256=pin)
    if ping is None:
        emit(2, "Mattermost.Status", "ping failed: %s" % err)
        print("\n".join(_OUT))
        return 0

    parts = {"server": ping.get("status"), "database": ping.get("database_status"), "file store": ping.get("filestore_status")}
    bad = [k for k, v in parts.items() if v != "OK"]
    emit(2 if bad else 0, "Mattermost.Status", ", ".join("%s %s" % (k, v) for k, v in parts.items()) + ((" - PROBLEM: " + ", ".join(bad)) if bad else ""))

    state = 2 if secs >= RESPONSE_SECONDS[1] else 1 if secs >= RESPONSE_SECONDS[0] else 0
    emit(state, "Mattermost.ApiTime", "ping answered in %.2f s" % secs, ["response_seconds=%.3f;%g;%g;0;" % (secs, RESPONSE_SECONDS[0], RESPONSE_SECONDS[1])])

    cfg, cerr, _ = get(base + "/api/v4/config/client?format=old", args.insecure, pin_sha256=pin)
    if cfg is None:
        emit(3, "Mattermost.Version", "cannot read the public client config: %s" % cerr)
    else:
        edition = "Enterprise-ready build" if str(cfg.get("BuildEnterpriseReady")).lower() == "true" else "Team Edition"
        emit(0, "Mattermost.Version", "Mattermost %s (%s)" % (cfg.get("Version", "?"), edition))

    if args.token_file:
        try:
            with open(args.token_file, encoding="utf-8") as fh:
                token = fh.read().strip()
        except OSError as exc:
            emit(3, "Mattermost.Usage", "cannot read token file: %s" % exc.strerror)
        else:
            admin_checks(base, token, args.insecure, pin)
    print("\n".join(_OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
