#!/usr/bin/env python3
"""check_ns8_container_status_api.py - NS8 container status for CheckMK, API only (PROTOTYPE)

Same CheckMK local-check output as check_ns8_container_status.py, but no
subprocess at all:
- module list: NS8 REST API (cluster/list-installed-modules), token read from
  NS8_TOKEN_FILE (default /root/.ns8-token-ro, a reader-role user is enough)
- containers: each rootless module's own podman REST API socket
  (/run/user/<uid>/podman/podman.sock, needs `systemctl --user enable --now
  podman.socket` in every module)

A stopped service removes its container, so podman alone cannot see it. The
NS8 API (module get-status) is used for that: CRIT on failed=1, and CRIT on a
service that was seen active on a previous run and is now inactive while still
enabled. The "seen active" memory is a small JSON state file; disabling a
service drops it from the memory. A stop that happened before the first run
cannot be detected.

get-status's "services" list mixes two different things under one name: a
systemd unit that wraps an actual podman container (e.g. "mariadb"), and a
plain systemd unit/timer with no container at all (e.g. a report-generation
timer). A problem coming from the second kind is labelled "(service)" in the
output below, never shown as if it were a container - found 2026-10-09 on a
real NS8-RL98 run, where a failed systemd timer with no matching container
(reports-scheduler, nethvoice1) was printed exactly like a dead container
before this fix, which is misleading when deciding what to actually restart.

Per-module work (one get-status call + one podman call) runs in a thread pool
(MAX_WORKERS) instead of sequentially: on an 11-module node the sequential
version took ~9-10s (each get-status is a submit+poll round trip to the NS8
API), which starts to matter once this runs as a real agent local check every
minute.

Version: 0.4.0"""

import concurrent.futures
import http.client
import json
import os
import pwd
import random
import socket
import sys
import time
import urllib.error
import urllib.request
from typing import List, Optional, Tuple

VERSION = "0.4.0"
SERVICE = "NS8.Container.Status"
STATE_FILE = os.environ.get("NS8_STATE_FILE", "/var/tmp/ns8_container_status_api.state.json")
STATUS_TIMEOUT_SECONDS = 8
NODE_AGENT_ENV = "/var/lib/nethserver/node/state/agent.env"
NS8_API = os.environ.get("NS8_API", "http://127.0.0.1:9311/api")
TOKEN_FILE = os.environ.get("NS8_TOKEN_FILE", "/root/.ns8-token-ro")
SCRIPT_TIMEOUT_SECONDS = 40
MAX_WORKERS = 8  # found empirically 2026-10-09: the NS8 API itself returns 429 (rate limit) above this on an 11-module node
_SCRIPT_START = time.monotonic()


class UnixHTTPConnection(http.client.HTTPConnection):
    """HTTP over a unix socket, for the podman REST API."""

    def __init__(self, path: str, timeout: float = 10):
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._path)


def get_local_node_id() -> str:
    """Reads this node's own ID from NODE_AGENT_ENV (AGENT_ID=node/<id>)."""
    try:
        with open(NODE_AGENT_ENV, encoding="utf-8") as f:
            for line in f:
                if line.startswith("AGENT_ID=node/"):
                    return line.strip().split("/", 1)[1]
    except OSError:
        pass
    return ""


def _http_error_label(code: int) -> str:
    return "permission-denied" if code in (401, 403) else f"api-http-{code}"


# The NS8 API itself rate-limits (HTTP 429) once enough modules' get-status calls
# overlap in time - found 2026-10-09 once this script's own per-module calls were
# parallelized (never seen in the original sequential version). A 429 is retried
# with a short randomized backoff instead of being treated as a hard failure, so
# a burst of concurrent callers (this script's own thread pool, or two of these
# API-only scripts happening to run close together) degrades to "a bit slower",
# not to a false CRIT/WARNING.
RETRY_ON_429 = 4
RETRY_BACKOFF_BASE = 0.3


def _urlopen_with_retry(req: urllib.request.Request, timeout: float):
    """urlopen, retrying on HTTP 429 with jittered backoff. Raises like urlopen otherwise."""
    for attempt in range(RETRY_ON_429 + 1):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == RETRY_ON_429:
                raise
            time.sleep(RETRY_BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 0.2))


NS8_MODULES_CACHE = os.environ.get("NS8_MODULES_CACHE", "/var/lib/ns8-modules-cache.json")
NS8_MODULES_TTL = int(os.environ.get("NS8_MODULES_TTL", "3600"))


def cached_ns8_task(agent, action, timeout=15.0):
    """ns8_task() with a one-hour cache shared by all the local checks: the module list is the same for everybody, so the
    NS8 API gets one call per hour instead of one per check and per agent run (the API answers HTTP 503 when the
    ~15 checks hit it together: Redis 'max number of clients reached'). Falls back to the stale cache when the API
    does not answer."""
    key = "%s|%s" % (agent, action)
    cache = {}
    try:
        with open(NS8_MODULES_CACHE, encoding="utf-8") as fh:
            cache = json.load(fh)
    except (OSError, ValueError):
        pass
    if not isinstance(cache, dict):
        cache = {}
    hit = cache.get(key)
    if hit and time.time() - hit.get("ts", 0) <= NS8_MODULES_TTL:
        return hit["out"], ""
    out, err = ns8_task(agent, action, timeout)
    if err or out is None:
        return (hit["out"], "") if hit else (out, err)
    try:
        cache[key] = {"ts": time.time(), "out": out}
        tmp = "%s.%d.tmp" % (NS8_MODULES_CACHE, os.getpid())
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(cache, fh)
        os.replace(tmp, NS8_MODULES_CACHE)
    except OSError:
        pass
    return out, err


def ns8_task(agent: str, action: str, timeout: float = 15.0) -> Tuple[Optional[object], str]:
    """Runs a no-input NS8 action through the REST API.

    Returns (output, error). error is '' on success, otherwise a short label
    (no-token, permission-denied, api-unreachable, task-failed, task-timeout...)."""
    try:
        with open(TOKEN_FILE, encoding="utf-8") as f:
            token = f.read().strip()
    except OSError:
        return None, "no-token"
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    body = json.dumps({"action": action, "data": None, "parent": "", "extra": {}}).encode()
    try:
        req = urllib.request.Request(f"{NS8_API}/{agent}/tasks", data=body, headers=headers, method="POST")
        with _urlopen_with_retry(req, 10) as resp:
            task_id = json.load(resp)["data"]["id"]
    except urllib.error.HTTPError as exc:
        return None, _http_error_label(exc.code)
    except (urllib.error.URLError, KeyError, ValueError, OSError):
        return None, "api-unreachable"

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(f"{NS8_API}/{agent}/task/{task_id}/status", headers=headers)
            with _urlopen_with_retry(req, 10) as resp:
                data = json.load(resp)["data"]
            if data.get("exit_code") == 0:
                return data.get("output"), ""
            return None, "task-failed"
        except urllib.error.HTTPError as exc:
            if exc.code != 400:  # 400 "redis: nil" = task still running
                return None, _http_error_label(exc.code)
        except (urllib.error.URLError, ValueError, OSError):
            return None, "api-unreachable"
        time.sleep(0.1)
    return None, "task-timeout"


def get_instances() -> List[str]:
    """Module instances installed on this node (REST API, no redis-cli)."""
    out, _ = cached_ns8_task("cluster", "list-installed-modules")
    if not isinstance(out, dict):
        return []
    node_id = get_local_node_id()
    result = []
    for instances in out.values():
        for inst in instances:
            if not node_id or str(inst.get("node")) == node_id:
                result.append(inst["id"])
    return sorted(result)


def get_containers(instance: str) -> Tuple[str, List[Tuple[str, str]]]:
    """Returns (error, [(name, state)]). error is '' when the podman API answered."""
    try:
        uid = pwd.getpwnam(instance).pw_uid
    except KeyError:
        return "no-user", []
    sock_path = f"/run/user/{uid}/podman/podman.sock"
    if not os.path.exists(sock_path):
        return "no-podman-socket", []
    try:
        conn = UnixHTTPConnection(sock_path)
        conn.request("GET", "/v5.0.0/libpod/containers/json?all=true")
        resp = conn.getresponse()
        data = json.loads(resp.read().decode())
        conn.close()
    except (OSError, ValueError, http.client.HTTPException):
        return "podman-api-error", []
    rows = []
    for c in data:
        if c.get("IsInfra"):
            continue
        state = c.get("State", "unknown")
        if state == "exited":
            state = "exited({})".format(c.get("ExitCode"))
        rows.append((c["Names"][0], state))
    return "", rows


def load_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    try:
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.replace(tmp, STATE_FILE)
    except OSError:
        pass


def check_services(instance: str, seen_active: List[str]) -> Tuple[str, List[str], List[str]]:
    """Returns (error, problems, new_seen_active) from the NS8 module get-status.

    A problem here comes from a systemd unit, which may or may not back an
    actual container - always labelled "(service)" so it is never confused
    with a real podman container problem found separately by get_containers()."""
    out, err = ns8_task(f"module/{instance}", "get-status", timeout=STATUS_TIMEOUT_SECONDS)
    if err:
        return err, [], seen_active
    if not isinstance(out, dict) or "services" not in out:
        return "status-unavailable", [], seen_active
    services = {s["name"]: s for s in out["services"]}
    problems: List[str] = []
    seen = set(seen_active)
    for name, svc in services.items():
        if svc.get("failed"):
            problems.append(f"{instance}:{name}(failed,service)")
        elif svc.get("active"):
            seen.add(name)
    for name in sorted(seen):
        svc = services.get(name)
        if svc is None or not svc.get("enabled"):
            seen.discard(name)  # removed or deliberately disabled: stop watching it
        elif not svc.get("active") and not svc.get("failed"):
            problems.append(f"{instance}:{name}(stopped,service)")
    return "", problems, sorted(seen)


def check_instance(instance: str, prev_seen: List[str]) -> Tuple[str, List[str], List[str], List[str], int]:
    """Runs both checks for one module.

    Returns (instance, critical_problems, notes, new_seen_active, containers_checked).
    critical_problems are real findings (a failed/stopped service, a non-running
    container); notes are collection errors (unreachable, no socket, ...) kept
    separate exactly like the original sequential version did, so a transient
    communication glitch on one module still shows as WARNING, not CRIT."""
    svc_error, svc_problems, new_seen = check_services(instance, prev_seen)
    critical = list(svc_problems)
    notes: List[str] = []
    if svc_error:
        notes.append(f"{instance}:{svc_error}")

    error, containers = get_containers(instance)
    checked = 0
    if error:
        notes.append(f"{instance}:{error}")
    elif not containers:
        if not svc_error:  # already reported with its own reason
            notes.append(f"{instance}:no-containers-or-inactive")
    else:
        for name, cstate in containers:
            checked += 1
            if cstate != "running":
                critical.append(f"{instance}:{name}({cstate})")
    return instance, critical, notes, new_seen, checked


def main() -> int:
    instances = get_instances()
    if not instances:
        print(f"3 {SERVICE} - UNKNOWN: no NS8 instance found (REST API unreachable or token invalid)")
        return 0

    critical: List[str] = []
    notes: List[str] = []
    checked = 0
    timed_out = False
    state = load_state()
    new_state = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(check_instance, inst, state.get(inst, [])): inst for inst in instances}
        try:
            for future in concurrent.futures.as_completed(futures, timeout=SCRIPT_TIMEOUT_SECONDS):
                instance, inst_critical, inst_notes, new_seen, n = future.result()
                new_state[instance] = new_seen
                critical.extend(inst_critical)
                notes.extend(inst_notes)
                checked += n
        except concurrent.futures.TimeoutError:
            timed_out = True

    state.update(new_state)  # modules not reached (timeout) keep their old memory
    save_state({k: v for k, v in state.items() if k in instances})

    partial = " (partial scan)" if timed_out else ""
    if critical:
        detail = ", ".join(critical[:10])
        if len(critical) > 10:
            detail = f"{detail}, ... (+{len(critical) - 10} more)"
        print(f"2 {SERVICE} - CRIT: problematici={len(critical)}/{checked}{partial} | {detail}")
    elif checked == 0:
        detail = ", ".join(notes[:8]) if notes else "no data"
        print(f"1 {SERVICE} - WARNING: no containers detected{partial} | {detail}")
    elif notes:
        detail = ", ".join(notes[:10])
        if len(notes) > 10:
            detail = f"{detail}, ... (+{len(notes) - 10} more)"
        print(f"1 {SERVICE} - WARNING: running={checked}, note={len(notes)}{partial} | {detail}")
    else:
        print(f"0 {SERVICE} - OK: all containers running ({checked}/{checked}){partial}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
