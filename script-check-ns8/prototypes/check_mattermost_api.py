#!/usr/bin/env python3
"""check_mattermost_api.py - CheckMK local check for Mattermost (mattermost1), runs ON the NS8 node

Converted from the former CheckMK special agent agent_mattermost_api.py (ran on the
CheckMK server, over the public network with certificate pinning) into a local check
that runs here, on the node, and reaches mattermost1 over the loopback interface
through Traefik (SNI mattermost.nethlab.it, connection never leaves the host). No
certificate pinning needed any more: there is no network path for a machine-in-the-
middle to sit on. See memory "ns8_rl98 local check reorganisation", 2026-10-12.

Uses the system-admin personal access token already created for this lab/test
instance (see memory mattermost_admin_can_read_private_messages_2026-10-08: a
system-admin token or root on the node can read any private message regardless -
moving the token here removes the one remaining network-transport exposure it had).
TOKEN_FILE, mode 600, local to this node.

Checks (identical to the former special agent, always with admin metrics since the
token is always available here):
- Mattermost.Status, .ApiTime, .Version, .Usage, .Database, .Jobs, .Plugins

Piggybacked to NS8-RL98-MATTERMOST (this check belongs to that module, not the node).

Version: 1.0.0"""

import http.client
import json
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from typing import List, Optional, Tuple

VERSION = "1.0.0"
HOSTNAME = "mattermost.nethlab.it"
NODE_IP = "127.0.0.1"
TOKEN_FILE = "/root/.mattermost-monitoring-token"
RESPONSE_SECONDS = (1.0, 3.0)
JOB_WINDOW_MS = 24 * 3600 * 1000

_OUT: List[str] = []


def emit(state: int, name: str, text: str, metrics: Optional[List[str]] = None) -> None:
    name = re.sub(r"\s+", "_", name)
    _OUT.append("%d %s %s %s" % (state, name, "|".join(metrics) if metrics else "-", text.replace("\n", " ")))


class _LocalHTTPSConnection(http.client.HTTPSConnection):
    """Connects to NODE_IP over loopback but keeps TLS SNI / Host header as self.host
    (same trick as `curl --resolve`): Traefik still routes by the vhost name."""

    def connect(self) -> None:
        sock = socket.create_connection((NODE_IP, self.port or 443), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)  # type: ignore[attr-defined]


def _opener(ctx: ssl.SSLContext) -> urllib.request.OpenerDirector:
    class LocalHandler(urllib.request.HTTPSHandler):
        def https_open(self, req):  # noqa: ANN001 - matches urllib's own (untyped) signature
            return self.do_open(lambda host, **kw: _LocalHTTPSConnection(host, context=ctx, **kw), req)

    return urllib.request.build_opener(LocalHandler())


def get(path: str, timeout: float = 15.0, token: str = "", any_json: bool = False) -> Tuple[Optional[object], str, float]:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request("https://%s%s" % (HOSTNAME, path), headers=headers)
    t0 = time.monotonic()
    try:
        with _opener(ctx).open(req, timeout=timeout) as resp:
            body = json.load(resp)
        return (body if (any_json or isinstance(body, dict)) else None), "", time.monotonic() - t0
    except urllib.error.HTTPError as exc:
        return None, "token-rejected" if (token and exc.code in (401, 403)) else "http-%d" % exc.code, time.monotonic() - t0
    except (urllib.error.URLError, OSError, ValueError):
        return None, "unreachable", time.monotonic() - t0


def admin_checks(token: str) -> None:
    """Metrics that need a system-admin token: counts and states only, never message content."""
    std, err, _ = get("/api/v4/analytics/old?name=standard", token=token, any_json=True)
    if not isinstance(std, list):
        for name in ("Usage", "Database", "Jobs", "Plugins"):
            emit(3, "Mattermost." + name, "cannot read the admin API: %s" % err)
        return
    s = {row.get("name"): row.get("value") for row in std if isinstance(row, dict)}
    extra, _, _ = get("/api/v4/analytics/old?name=extra_counts", token=token, any_json=True)
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

    jobs, jerr, _ = get("/api/v4/jobs?per_page=50", token=token, any_json=True)
    if isinstance(jobs, list):
        now_ms = int(time.time() * 1000)
        failed = [j for j in jobs if j.get("status") == "error" and now_ms - int(j.get("last_activity_at") or 0) <= JOB_WINDOW_MS]
        kinds = sorted({str(j.get("type")) for j in failed})
        emit(1 if failed else 0, "Mattermost.Jobs", ("%d job(s) ended in error in the last 24 h: %s" % (len(failed), ", ".join(kinds))) if failed else "no job in error in the last 24 h (%d recent jobs checked)" % len(jobs),
             ["jobs_failed_24h=%d;1;;0;" % len(failed)])
    else:
        emit(3, "Mattermost.Jobs", "cannot read the jobs: %s" % jerr)

    plugins, perr, _ = get("/api/v4/plugins", token=token)
    if isinstance(plugins, dict):
        active = sorted(str(p.get("id")) for p in (plugins.get("active") or []))
        emit(0, "Mattermost.Plugins", "%d active: %s" % (len(active), ", ".join(active) or "-"), ["plugins_active=%d;;;0;" % len(active)])
    else:
        emit(3, "Mattermost.Plugins", "cannot read the plugins: %s" % perr)


def main() -> int:
    ping, err, secs = get("/api/v4/system/ping?get_server_status=true")
    if ping is None:
        emit(2, "Mattermost.Status", "ping failed: %s" % err)
        return 0

    parts = {"server": ping.get("status"), "database": ping.get("database_status"), "file store": ping.get("filestore_status")}
    bad = [k for k, v in parts.items() if v != "OK"]
    emit(2 if bad else 0, "Mattermost.Status", ", ".join("%s %s" % (k, v) for k, v in parts.items()) + ((" - PROBLEM: " + ", ".join(bad)) if bad else ""))

    state = 2 if secs >= RESPONSE_SECONDS[1] else 1 if secs >= RESPONSE_SECONDS[0] else 0
    emit(state, "Mattermost.ApiTime", "ping answered in %.2f s" % secs, ["response_seconds=%.3f;%g;%g;0;" % (secs, RESPONSE_SECONDS[0], RESPONSE_SECONDS[1])])

    cfg, cerr, _ = get("/api/v4/config/client?format=old")
    if cfg is None:
        emit(3, "Mattermost.Version", "cannot read the public client config: %s" % cerr)
    else:
        edition = "Enterprise-ready build" if str(cfg.get("BuildEnterpriseReady")).lower() == "true" else "Team Edition"
        emit(0, "Mattermost.Version", "Mattermost %s (%s)" % (cfg.get("Version", "?"), edition))

    try:
        with open(TOKEN_FILE, encoding="utf-8") as fh:
            token = fh.read().strip()
    except OSError as exc:
        emit(3, "Mattermost.Usage", "cannot read token file: %s" % exc.strerror)
    else:
        admin_checks(token)
    return 0


if __name__ == "__main__":
    # Piggyback to NS8-RL98-MATTERMOST: this check belongs to that module, not the node itself
    # (see memory ns8_rl98 local check reorganisation, 2026-10-12)
    print("<<<<NS8-RL98-MATTERMOST>>>>")
    print("<<<local:sep(0)>>>")
    _rc = main()
    print("\n".join(_OUT))
    print("<<<<>>>>")
    sys.exit(_rc)
