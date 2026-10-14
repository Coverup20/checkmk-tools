#!/usr/bin/env python3
"""check_ns8_container_inventory_api.py - NS8 container inventory for CheckMK, API only (PROTOTYPE)

Same CheckMK local-check output as check_ns8_container_inventory.py (total /
running / stopped containers plus a preview of "module:container" names), but
no subprocess at all:
- module list: NS8 REST API (cluster/list-installed-modules), token read from
  NS8_TOKEN_FILE (default /root/.ns8-token-ro, a reader-role user is enough)
- containers: each rootless module's own podman REST API socket
  (/run/user/<uid>/podman/podman.sock, needs `systemctl --user enable --now
  podman.socket` in every module)

This is a pure inventory like the original: a service that was stopped cleanly
removes its container and simply disappears from the list. Use the status or
health prototypes (NS8 get-status) to be alerted on that.

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
from typing import List, Optional, Tuple

VERSION = "0.1.0"
SERVICE = "NS8.Container.Inventory"
NODE_AGENT_ENV = "/var/lib/nethserver/node/state/agent.env"
NS8_API = os.environ.get("NS8_API", "http://127.0.0.1:9311/api")
TOKEN_FILE = os.environ.get("NS8_TOKEN_FILE", "/root/.ns8-token-ro")


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


def get_container_list(instance: str) -> Tuple[str, List[Tuple[str, str]]]:
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
    return "", [(c["Names"][0], c.get("State", "unknown")) for c in data]


def main() -> int:
    instances = get_instances()
    if not instances:
        print(f"3 {SERVICE} - UNKNOWN: no NS8 instance found (REST API unreachable or token invalid)")
        return 0

    total = 0
    running = 0
    stopped = 0
    names: List[str] = []
    unreadable: List[str] = []

    for instance in instances:
        error, containers = get_container_list(instance)
        if error:
            unreadable.append(f"{instance}:{error}")
            continue
        for container_name, container_state in containers:
            total += 1
            names.append(f"{instance}:{container_name}")
            if container_state == "running":
                running += 1
            else:
                stopped += 1

    if total == 0:
        detail = ", ".join(unreadable[:8])
        suffix = f" | {detail}" if detail else ""
        print(f"1 {SERVICE} - WARNING: no containers found{suffix}")
        return 0

    preview = ", ".join(names[:8])
    if len(names) > 8:
        preview = f"{preview}, ... (+{len(names) - 8} more)"
    state = 0 if stopped == 0 else 1
    state_label = "OK" if state == 0 else "WARNING"
    unread = f" unreadable_modules={len(unreadable)}" if unreadable else ""
    print(
        f"{state} {SERVICE} - {state_label}: total={total} running={running} stopped={stopped}{unread} | "
        f"total={total} running={running} stopped={stopped}; {preview}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
