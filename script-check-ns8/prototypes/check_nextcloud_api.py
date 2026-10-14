#!/usr/bin/env python3
"""check_nextcloud_api.py - CheckMK local check for Nextcloud (nextcloud1), runs ON the NS8 node

Converted from the former CheckMK special agent agent_nextcloud_api.py (ran on the
CheckMK server, reaching the node over the public network with certificate pinning)
into a local check that runs here, on the node, and reaches nextcloud1 over the
loopback interface through Traefik (same TLS vhost, SNI nextcloud.nethlab.it, but the
connection never leaves the host). No certificate pinning is needed any more: there
is no network path left for a machine-in-the-middle to sit on.
See memory "ns8_rl98 local check reorganisation", 2026-10-12.

Reads the Nextcloud *serverinfo* app endpoint with the monitoring token (same token
as before, moved from the CheckMK server to this node, TOKEN_FILE, mode 600).

Checks (identical to the former special agent):
- Nextcloud.Status, .Fpm, .Opcache, .Database, .System, .Usage, .ApiTime

Piggybacked to NS8-RL98-NEXTCLOUD (this check belongs to that module, not the node).

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
HOSTNAME = "nextcloud.nethlab.it"
NODE_IP = "127.0.0.1"
TOKEN_FILE = "/root/.nextcloud-serverinfo-token"
ENDPOINT = "/ocs/v2.php/apps/serverinfo/api/v1/info?format=json&skipApps=true&skipUpdate=true"

# thresholds (WARN, CRIT) - unchanged from the special agent
LOAD_PER_CORE = (1.5, 2.5)
OPCACHE_HIT_MIN = (95.0, 85.0)  # lower is worse
OPCACHE_MEM_PCT = (85.0, 95.0)
FREE_GB_MIN = (20.0, 5.0)  # lower is worse
LISTEN_QUEUE = (1, 10)

_OUT: List[str] = []


def emit(state: int, name: str, text: str, metrics: Optional[List[str]] = None) -> None:
    name = re.sub(r"\s+", "_", name)
    _OUT.append("%d %s %s %s" % (state, name, "|".join(metrics) if metrics else "-", text.replace("\n", " ")))


def high(value: float, limits: Tuple[float, float]) -> int:
    return 2 if value >= limits[1] else 1 if value >= limits[0] else 0


def low(value: float, limits: Tuple[float, float]) -> int:
    return 2 if value < limits[1] else 1 if value < limits[0] else 0


def metric(name: str, value: float, limits: Optional[Tuple[float, float]] = None, vmin: Optional[float] = None, vmax: Optional[float] = None) -> str:
    w, c = ("%g" % limits[0], "%g" % limits[1]) if limits else ("", "")
    return "%s=%.6g;%s;%s;%s;%s" % (name, value, w, c, "" if vmin is None else "%g" % vmin, "" if vmax is None else "%g" % vmax)


def num(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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


def fetch(token: str) -> Tuple[Optional[dict], str]:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request("https://%s%s" % (HOSTNAME, ENDPOINT), headers={"NC-Token": token, "OCS-APIRequest": "true", "Accept": "application/json"})
    try:
        with _opener(ctx).open(req, timeout=15) as resp:
            body = json.load(resp)
    except urllib.error.HTTPError as exc:
        return None, "token-rejected" if exc.code in (401, 403) else "api-http-%d" % exc.code
    except (urllib.error.URLError, OSError, ValueError):
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
    if reached:
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
    try:
        with open(TOKEN_FILE, encoding="utf-8") as fh:
            token = fh.read().strip()
    except OSError as exc:
        emit(3, "Nextcloud.Status", "cannot read token file: %s" % exc.strerror)
        return 0
    t0 = time.monotonic()
    data, err = fetch(token)
    if data is None:
        emit(3 if err == "token-rejected" else 2, "Nextcloud.Status", "serverinfo API error: %s" % err)
        return 0
    for fn in (check_status, check_fpm, check_opcache, check_database, check_system, check_usage):
        try:
            fn(data)
        except (TypeError, ValueError, KeyError) as exc:
            emit(3, "Nextcloud." + fn.__name__.replace("check_", "").capitalize(), "cannot parse the answer: %s" % exc)
    _OUT.append("0 Nextcloud.ApiTime response_seconds=%.3f;;;0; API answered in %.2f s" % (time.monotonic() - t0, time.monotonic() - t0))
    return 0


if __name__ == "__main__":
    # Piggyback to NS8-RL98-NEXTCLOUD: this check belongs to that module, not the node itself
    # (see memory ns8_rl98 local check reorganisation, 2026-10-12)
    print("<<<<NS8-RL98-NEXTCLOUD>>>>")
    print("<<<local:sep(0)>>>")
    _rc = main()
    print("\n".join(_OUT))
    print("<<<<>>>>")
    sys.exit(_rc)
