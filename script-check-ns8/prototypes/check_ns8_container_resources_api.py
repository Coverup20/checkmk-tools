#!/usr/bin/env python3
"""check_ns8_container_resources_api.py - NS8 container resources for CheckMK, API only (PROTOTYPE)

Same CheckMK local-check output as check_ns8_container_resources.py, but no
subprocess at all:
- module list: NS8 REST API (cluster/list-installed-modules), token read from
  NS8_TOKEN_FILE (default /root/.ns8-token-ro, a reader-role user is enough)
- stats: each rootless module's own podman REST API socket
  (/run/user/<uid>/podman/podman.sock, needs `systemctl --user enable --now
  podman.socket` in every module)

The podman API returns cumulative CPU counters, so CPU % is computed from two
readings taken SAMPLE_INTERVAL seconds apart (all modules are sampled once,
then once more) - the delta of container CPU time over the delta of wall time,
100% = one full core, like podman stats.

Version: 0.1.0"""

import http.client
import json
import os
import pwd
import socket
import sys
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Tuple

VERSION = "0.1.0"
SERVICE = "NS8.Container.Resources"
NODE_AGENT_ENV = "/var/lib/nethserver/node/state/agent.env"
NS8_API = os.environ.get("NS8_API", "http://127.0.0.1:9311/api")
TOKEN_FILE = os.environ.get("NS8_TOKEN_FILE", "/root/.ns8-token-ro")
SAMPLE_INTERVAL = float(os.environ.get("NS8_SAMPLE_INTERVAL", "1.0"))
CPU_WARN = 80.0
CPU_CRIT = 95.0
MEM_WARN = 80.0
MEM_CRIT = 95.0


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
        with urllib.request.urlopen(req, timeout=10) as resp:
            task_id = json.load(resp)["data"]["id"]
    except urllib.error.HTTPError as exc:
        return None, "permission-denied" if exc.code in (401, 403) else f"api-http-{exc.code}"
    except (urllib.error.URLError, KeyError, ValueError, OSError):
        return None, "api-unreachable"

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(f"{NS8_API}/{agent}/task/{task_id}/status", headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
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


def read_stats(instance: str) -> Tuple[str, List[dict]]:
    """One podman stats reading for a module. Returns (error, [stat dicts])."""
    try:
        uid = pwd.getpwnam(instance).pw_uid
    except KeyError:
        return "no-user", []
    sock_path = f"/run/user/{uid}/podman/podman.sock"
    if not os.path.exists(sock_path):
        return "no-podman-socket", []
    try:
        conn = UnixHTTPConnection(sock_path)
        conn.request("GET", "/v5.0.0/libpod/containers/stats?stream=false")
        resp = conn.getresponse()
        data = json.loads(resp.read().decode())
        conn.close()
    except (OSError, ValueError, http.client.HTTPException):
        return "podman-api-error", []
    if data.get("Error"):
        return "podman-api-error", []
    return "", data.get("Stats") or []


def sample_all(instances: List[str]) -> Tuple[Dict[str, List[dict]], Dict[str, str]]:
    stats: Dict[str, List[dict]] = {}
    errors: Dict[str, str] = {}
    for instance in instances:
        error, rows = read_stats(instance)
        if error:
            errors[instance] = error
        else:
            stats[instance] = rows
    return stats, errors


def cpu_percent(first: dict, second: dict) -> float:
    d_cpu = second.get("CPUNano", 0) - first.get("CPUNano", 0)
    d_wall = second.get("SystemNano", 0) - first.get("SystemNano", 0)
    if d_cpu < 0 or d_wall <= 0:
        return 0.0
    return d_cpu / d_wall * 100.0


def state_for(cpu: float, mem: float) -> int:
    if cpu >= CPU_CRIT or mem >= MEM_CRIT:
        return 2
    if cpu >= CPU_WARN or mem >= MEM_WARN:
        return 1
    return 0


def label_for(state: int) -> str:
    if state == 2:
        return "CRIT"
    if state == 1:
        return "WARN"
    return "OK"


def top_entries(entries: List[Tuple[str, float]], size: int = 3) -> str:
    if not entries:
        return "n/a"
    ordered = sorted(entries, key=lambda item: item[1], reverse=True)[:size]
    return ", ".join(f"{name}:{value:.1f}%" for name, value in ordered)


def main() -> int:
    instances = get_instances()
    if not instances:
        print(f"3 {SERVICE} - UNKNOWN: no NS8 instance found (REST API unreachable or token invalid)")
        return 0

    first, errors = sample_all(instances)
    time.sleep(SAMPLE_INTERVAL)
    second, errors2 = sample_all(instances)
    errors.update(errors2)

    total = 0
    warn_count = 0
    crit_count = 0
    max_cpu = 0.0
    max_mem = 0.0
    cpu_items: List[Tuple[str, float]] = []
    mem_items: List[Tuple[str, float]] = []

    for instance, rows in second.items():
        before = {r["ContainerID"]: r for r in first.get(instance, [])}
        for row in rows:
            prev = before.get(row["ContainerID"])
            cpu = cpu_percent(prev, row) if prev else 0.0
            mem = float(row.get("MemPerc", 0.0))
            total += 1
            state = state_for(cpu, mem)
            if state == 2:
                crit_count += 1
            elif state == 1:
                warn_count += 1
            max_cpu = max(max_cpu, cpu)
            max_mem = max(max_mem, mem)
            cpu_items.append((f"{instance}/{row['Name']}", cpu))
            mem_items.append((f"{instance}/{row['Name']}", mem))

    if total == 0:
        detail = ", ".join(f"{k}:{v}" for k, v in sorted(errors.items())[:8])
        print(f"1 {SERVICE} - WARNING: no container metrics available | {detail}")
        return 0

    overall_state = 2 if crit_count > 0 else 1 if warn_count > 0 else 0
    label = label_for(overall_state)
    note = f" unreadable_modules={len(errors)}" if errors else ""
    print(
        f"{overall_state} {SERVICE} - {label}: total={total} warn={warn_count} crit={crit_count}{note} "
        f"top_cpu=[{top_entries(cpu_items)}] top_mem=[{top_entries(mem_items)}] | "
        f"max_cpu={max_cpu:.2f};{CPU_WARN};{CPU_CRIT};0;100 max_mem={max_mem:.2f};{MEM_WARN};{MEM_CRIT};0;100"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
