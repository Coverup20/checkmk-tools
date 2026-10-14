#!/usr/bin/env python3
"""agent_nextcloud_api.py - CheckMK special agent (datasource program) for Nextcloud, REST API only (PROTOTYPE)

Runs on the CheckMK server and reads the Nextcloud *serverinfo* app endpoint
(/ocs/v2.php/apps/serverinfo/api/v1/info) with the monitoring token
(header NC-Token, set on the server with
`occ config:app:set serverinfo token --value <token>`). Prints CheckMK
local-check lines, so no check plugin is needed. Nothing is installed on the
Nextcloud host. The token is read from a file (--token-file, mode 600).

Checks:
- Nextcloud.Status    API reachable, Nextcloud / PHP / webserver / database versions
- Nextcloud.Fpm       PHP-FPM pool: listen queue, max children reached, active/idle/total processes, slow requests
- Nextcloud.Opcache   OPcache: cache full, hit rate, memory used, OOM restarts
- Nextcloud.Database  database type, version and size
- Nextcloud.System    CPU load per core, free space of the data volume
- Nextcloud.Usage     users, active users, files, shares (informational)

The update check is skipped (skipUpdate=true) and so is the app list: both would
make Nextcloud call out to the app store.

Certificate pinning (--pin-sha256): the lab certificate is self-signed, so normal
CA validation is off (--insecure) and by itself that means ANY certificate is
accepted - a machine-in-the-middle on the same network could present its own
certificate unnoticed and receive the NC-Token straight from the request header.
--pin-sha256 closes that: give the SHA-256 fingerprint (hex) of the real
certificate and every connection then fails closed unless the server presents
exactly that certificate. Not a secret - a fingerprint cannot be used to
impersonate a certificate - so it is a plain CLI argument, not a token file.

Usage (datasource program):
  agent_nextcloud_api.py --url https://nextcloud.example.org --token-file /path/token \
      --insecure --pin-sha256 <fingerprint>

Version: 0.2.0"""

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

VERSION = "0.2.0"
ENDPOINT = "/ocs/v2.php/apps/serverinfo/api/v1/info?format=json&skipApps=true&skipUpdate=true"

# thresholds (WARN, CRIT)
LOAD_PER_CORE = (1.5, 2.5)
OPCACHE_HIT_MIN = (95.0, 85.0)  # lower is worse: WARN below the first, CRIT below the second
OPCACHE_MEM_PCT = (85.0, 95.0)
FREE_GB_MIN = (20.0, 5.0)  # lower is worse
LISTEN_QUEUE = (1, 10)

_OUT: List[str] = []


def emit(state: int, name: str, text: str, metrics: Optional[List[str]] = None) -> None:
    name = re.sub(r"\s+", "_", name)
    _OUT.append("%d %s %s %s" % (state, name, "|".join(metrics) if metrics else "-", text.replace("\n", " ")))


def high(value: float, limits: Tuple[float, float]) -> int:
    """State when a higher value is worse."""
    return 2 if value >= limits[1] else 1 if value >= limits[0] else 0


def low(value: float, limits: Tuple[float, float]) -> int:
    """State when a lower value is worse (limits = (warn_below, crit_below))."""
    return 2 if value < limits[1] else 1 if value < limits[0] else 0


def metric(name: str, value: float, limits: Optional[Tuple[float, float]] = None, vmin: Optional[float] = None, vmax: Optional[float] = None) -> str:
    w, c = ("%g" % limits[0], "%g" % limits[1]) if limits else ("", "")
    return "%s=%.6g;%s;%s;%s;%s" % (name, value, w, c, "" if vmin is None else "%g" % vmin, "" if vmax is None else "%g" % vmax)


def num(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Like HTTPSConnection, but after the TLS handshake refuses to proceed unless the
    peer certificate's SHA-256 fingerprint matches exactly."""

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


def _opener(ctx: ssl.SSLContext, pin_sha256: str) -> urllib.request.OpenerDirector:
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


def fetch(url: str, token: str, insecure: bool, pin_sha256: str = "") -> Tuple[Optional[dict], str]:
    ctx = ssl.create_default_context()
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url.rstrip("/") + ENDPOINT, headers={"NC-Token": token, "OCS-APIRequest": "true", "Accept": "application/json"})
    try:
        with _opener(ctx, pin_sha256).open(req, timeout=20) as resp:
            body = json.load(resp)
    except urllib.error.HTTPError as exc:
        return None, "token-rejected" if exc.code in (401, 403) else "api-http-%d" % exc.code
    except (urllib.error.URLError, OSError, ValueError) as exc:
        cause = getattr(exc, "reason", exc)
        if isinstance(cause, ssl.SSLCertVerificationError):
            return None, "PIN MISMATCH (possible machine-in-the-middle): %s" % cause
        return None, "api-unreachable"
    data = (body.get("ocs") or {}).get("data")
    return (data, "") if isinstance(data, dict) else (None, "bad-answer")


def check_status(d: dict) -> None:
    nc, srv = d.get("nextcloud", {}), d.get("server", {})
    db = srv.get("database") or {}
    emit(0, "Nextcloud.Status", "Nextcloud %s, PHP %s, %s, %s %s" % (
        (nc.get("system") or {}).get("version", "?"), (srv.get("php") or {}).get("version", "?"),
        srv.get("webserver", "?"), db.get("type", "db"), db.get("version", "?")))


def check_fpm(d: dict) -> None:
    f = (d.get("server") or {}).get("fpm")
    if not isinstance(f, dict) or not f:
        emit(0, "Nextcloud.Fpm", "no PHP-FPM statistics (not running under FPM)")
        return
    queue, reached = int(num(f.get("listen-queue"))), int(num(f.get("max-children-reached")))
    active, idle, total = int(num(f.get("active-processes"))), int(num(f.get("idle-processes"))), int(num(f.get("total-processes")))
    slow = int(num(f.get("slow-requests")))
    state, notes = high(queue, LISTEN_QUEUE), []
    if queue:
        notes.append("listen queue %d" % queue)
    if reached:  # counter since the pool started: the pool hit its limit at least once
        state = max(state, 1)
        notes.append("max children reached %d time(s) since start" % reached)
    text = "pool %s (%s): %d active, %d idle, %d total%s" % (f.get("pool", "?"), f.get("process-manager", "?"), active, idle, total, ("; " + "; ".join(notes)) if notes else "")
    emit(state, "Nextcloud.Fpm", text, [
        metric("fpm_listen_queue", queue, LISTEN_QUEUE, 0), metric("fpm_active_processes", active, None, 0), metric("fpm_idle_processes", idle, None, 0),
        metric("fpm_total_processes", total, None, 0), metric("fpm_max_children_reached", reached, None, 0), metric("fpm_slow_requests", slow, None, 0)])


def check_opcache(d: dict) -> None:
    oc = ((d.get("server") or {}).get("php") or {}).get("opcache") or {}
    if not oc:
        emit(0, "Nextcloud.Opcache", "no OPcache data")
        return
    if not oc.get("opcache_enabled", True):
        emit(1, "Nextcloud.Opcache", "OPcache is disabled")
        return
    mem = oc.get("memory_usage") or {}
    used, free = num(mem.get("used_memory")), num(mem.get("free_memory"))
    pct = used * 100.0 / (used + free) if used + free else 0.0
    stats = oc.get("opcache_statistics") or {}
    hit, oom = num(stats.get("opcache_hit_rate"), 100.0), int(num(stats.get("oom_restarts")))
    state, notes = max(high(pct, OPCACHE_MEM_PCT), low(hit, OPCACHE_HIT_MIN)), []
    if oc.get("cache_full"):
        state = max(state, 1)
        notes.append("cache full")
    if oom:
        state = max(state, 1)
        notes.append("%d OOM restart(s)" % oom)
    emit(state, "Nextcloud.Opcache", "hit rate %.2f%%, memory %.1f%% used%s" % (hit, pct, ("; " + "; ".join(notes)) if notes else ""),
         [metric("opcache_hit_rate", hit, None, 0, 100), metric("opcache_memory_percent", pct, OPCACHE_MEM_PCT, 0, 100), metric("opcache_oom_restarts", oom, None, 0)])


def check_database(d: dict) -> None:
    db = (d.get("server") or {}).get("database") or {}
    size = num(db.get("size"))
    emit(0, "Nextcloud.Database", "%s %s, size %.1f MB" % (db.get("type", "?"), db.get("version", "?"), size / 1048576.0), [metric("db_size_bytes", size, None, 0)])


def check_system(d: dict) -> None:
    s = (d.get("nextcloud") or {}).get("system") or {}
    load = s.get("cpuload") or []
    cores = max(int(num(s.get("cpunum"), 1)), 1)
    free_gb = num(s.get("freespace"), -1) / 1e9
    state, parts, metrics = 0, [], []
    if len(load) >= 3:
        l1, l5, l15 = (num(x) for x in load[:3])
        per_core = l5 / cores
        state = high(per_core, LOAD_PER_CORE)
        parts.append("load %.2f %.2f %.2f on %d cores (5 min: %.2f per core)" % (l1, l5, l15, cores, per_core))
        metrics += [metric("load1", l1, None, 0), metric("load5", l5, (LOAD_PER_CORE[0] * cores, LOAD_PER_CORE[1] * cores), 0), metric("load15", l15, None, 0)]
    if free_gb >= 0:
        state = max(state, low(free_gb, FREE_GB_MIN))
        parts.append("%.1f GB free on the data volume" % free_gb)
        metrics.append(metric("data_free_bytes", free_gb * 1e9, None, 0))
    emit(state, "Nextcloud.System", "; ".join(parts) or "no system data", metrics)


def check_usage(d: dict) -> None:
    nc = d.get("nextcloud") or {}
    st, sh, au = nc.get("storage") or {}, nc.get("shares") or {}, d.get("activeUsers") or {}
    users, files, shares = int(num(st.get("num_users"))), int(num(st.get("num_files"))), int(num(sh.get("num_shares")))
    a1h, a24h = int(num(au.get("last1hour"))), int(num(au.get("last24hours")))
    emit(0, "Nextcloud.Usage", "%d users (%d active in 24 h, %d in 1 h), %d files, %d shares" % (users, a24h, a1h, files, shares),
         [metric("users", users, None, 0), metric("users_active_1h", a1h, None, 0), metric("users_active_24h", a24h, None, 0), metric("files", files, None, 0), metric("shares", shares, None, 0)])


def main() -> int:
    ap = argparse.ArgumentParser(description="CheckMK special agent for Nextcloud (serverinfo API)")
    ap.add_argument("--url", required=True, help="Nextcloud base URL, e.g. https://nextcloud.example.org")
    ap.add_argument("--token-file", required=True, help="file with the serverinfo token (mode 600)")
    ap.add_argument("--insecure", action="store_true", help="do not verify the TLS certificate against a CA (needed for a self-signed lab certificate)")
    ap.add_argument("--pin-sha256", default="", help="SHA-256 fingerprint (hex) of the expected certificate; with --insecure this is what actually stops a machine-in-the-middle, not a secret")
    args = ap.parse_args()
    pin = args.pin_sha256.strip().lower().replace(":", "")

    print("<<<check_mk>>>")
    print("Version: nextcloud-api-special-agent-%s" % VERSION)
    print("AgentOS: nextcloud-api")
    print("<<<local:sep(0)>>>")
    try:
        with open(args.token_file, encoding="utf-8") as fh:
            token = fh.read().strip()
    except OSError as exc:
        emit(3, "Nextcloud.Status", "cannot read token file: %s" % exc.strerror)
        print("\n".join(_OUT))
        return 0

    t0 = time.monotonic()
    data, err = fetch(args.url, token, args.insecure, pin_sha256=pin)
    if data is None:
        emit(3 if err == "token-rejected" else 2, "Nextcloud.Status", "serverinfo API error: %s" % err)
        print("\n".join(_OUT))
        return 0
    for fn in (check_status, check_fpm, check_opcache, check_database, check_system, check_usage):
        try:
            fn(data)
        except (TypeError, ValueError, KeyError) as exc:
            emit(3, "Nextcloud." + fn.__name__.replace("check_", "").capitalize(), "cannot parse the answer: %s" % exc)
    _OUT.append("0 Nextcloud.ApiTime response_seconds=%.3f;;;0; API answered in %.2f s" % (time.monotonic() - t0, time.monotonic() - t0))
    print("\n".join(_OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
