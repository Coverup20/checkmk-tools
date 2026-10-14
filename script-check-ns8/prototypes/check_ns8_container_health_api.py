#!/usr/bin/env python3
"""check_ns8_container_health_api.py - NS8 container health for CheckMK, API only (PROTOTYPE)

Same CheckMK local-check output and rules as check_ns8_container_health.py
(total / running / problem containers, a module without containers counts as
a problem), but no subprocess at all:
- module list and per-module service state: NS8 REST API (cluster
  list-installed-modules, module get-status), token read from NS8_TOKEN_FILE
  (default /root/.ns8-token-ro, a reader-role user is enough)
- containers: each rootless module's own podman REST API socket
  (/run/user/<uid>/podman/podman.sock, needs `systemctl --user enable --now
  podman.socket` in every module)

A stopped service removes its container, so podman alone cannot see it: the
NS8 get-status is used for that (CRIT on failed=1, and on a service seen
active on a previous run that is now inactive while still enabled; the "seen
active" memory is a JSON state file, a stop before the first run is invisible).

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

Version: 0.2.0"""

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

VERSION = "0.2.0"
SERVICE = "NS8.Containers"
NODE_AGENT_ENV = "/var/lib/nethserver/node/state/agent.env"
NS8_API = os.environ.get("NS8_API", "http://127.0.0.1:9311/api")
TOKEN_FILE = os.environ.get("NS8_TOKEN_FILE", "/root/.ns8-token-ro")
STATE_FILE = os.environ.get("NS8_STATE_FILE", "/var/tmp/ns8_container_health_api.state.json")
STATUS_TIMEOUT_SECONDS = 8
SCRIPT_TIMEOUT_SECONDS = 40
MAX_WORKERS = 8  # found empirically 2026-10-09: the NS8 API itself returns 429 (rate limit) above this on an 11-module node


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


def ns8_task(agent: str, action: str, timeout: float = 15.0) -> Tuple[Optional[object], str]:
    """Runs a no-input NS8 action through the REST API; returns (output, error)."""
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
        return None, "permission-denied" if exc.code in (401, 403) else f"api-http-{exc.code}"
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
                return None, "permission-denied" if exc.code in (401, 403) else f"api-http-{exc.code}"
        except (urllib.error.URLError, ValueError, OSError):
            return None, "api-unreachable"
        time.sleep(0.1)
    return None, "task-timeout"


def get_instances() -> List[str]:
    """Module instances installed on this node (REST API, no redis-cli)."""
    out, _ = ns8_task("cluster", "list-installed-modules")
    if not isinstance(out, dict):
        return []
    node_id = get_local_node_id()
    result = []
    for instances in out.values():
        for inst in instances:
            if not node_id or str(inst.get("node")) == node_id:
                result.append(inst["id"])
    return sorted(result)


def get_instance_containers(instance: str) -> Tuple[str, List[Tuple[str, str]]]:
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
    with a real podman container problem found separately by get_instance_containers()."""
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


def check_instance(instance: str, prev_seen: List[str]) -> Tuple[str, List[str], List[str], int, int]:
    """Runs both checks for one module; returns (instance, problems, new_seen_active, total, running)."""
    svc_error, svc_problems, new_seen = check_services(instance, prev_seen)
    problems = list(svc_problems)
    if svc_error:
        problems.append(f"{instance}:{svc_error}")

    error, containers = get_instance_containers(instance)
    total = running = 0
    if error:
        problems.append(f"{instance}:{error}")
    elif not containers:
        problems.append(f"{instance}:no-containers")
    else:
        for name, cstate in containers:
            total += 1
            if cstate == "running":
                running += 1
            else:
                problems.append(f"{instance}:{name}({cstate})")
    return instance, problems, new_seen, total, running


def main() -> int:
    instances = get_instances()
    if not instances:
        print(f"3 {SERVICE} - UNKNOWN: no NS8 instance found (REST API unreachable or token invalid)")
        return 0

    total = 0
    running = 0
    problems: List[str] = []
    state = load_state()
    new_state = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(check_instance, inst, state.get(inst, [])): inst for inst in instances}
        try:
            for future in concurrent.futures.as_completed(futures, timeout=SCRIPT_TIMEOUT_SECONDS):
                instance, inst_problems, new_seen, t, r = future.result()
                new_state[instance] = new_seen
                problems.extend(inst_problems)
                total += t
                running += r
        except concurrent.futures.TimeoutError:
            problems.append("scan-timed-out(partial)")

    save_state({k: v for k, v in new_state.items() if k in instances})

    problem_count = len(problems)
    if problem_count > 0:
        detail = ", ".join(problems[:8])
        if problem_count > 8:
            detail = f"{detail}, ... (+{problem_count - 8} altri)"
        print(f"2 {SERVICE} - CRIT: total={total} running={running} problem={problem_count} | {detail}")
    else:
        print(f"0 {SERVICE} - OK: total={total} running={running} problem=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
