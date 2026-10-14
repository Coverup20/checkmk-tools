#!/usr/bin/env python3
"""check_ns8_webtop_services_api.py - CheckMK Local Check for WebTop NS8 internal services, API only

Same pattern as check_ns8_services_api.py (mail1), applied to webtop1's six
containers: postgres, apache, webapp (Tomcat/Java), pecbridge, z-push, webdav.
No subprocess, no SSH:
- webtop module list: NS8 REST API (cluster/list-installed-modules), token
  read from NS8_TOKEN_FILE (default /root/.ns8-token-ro, a reader-role user
  is enough)
- container state: the webtop module's own podman REST API socket
  (/run/user/<uid>/podman/podman.sock; needs `systemctl --user enable --now
  podman.socket` in the module); exec goes through
  POST /containers/<id>/exec + POST /exec/<id>/start
- a container with no entry: CRIT "not active" if NS8 get-status says the
  matching service is enabled (or failed) and not running; UNKNOWN "not
  found" otherwise

webapp extras (JVM visibility without installing anything): the container has
no `jcmd`/`jstat`/`jps` (a slim JRE, not a full JDK - verified empirically on
NS8-RL98), so heap/GC internals are not reachable. Instead reads
/proc/1/status and /proc/1/cmdline inside the container (always available,
no extra tooling):
- webapp_jvm_memory: resident memory (VmRSS) against a threshold derived from
  the JVM's own -Xmx (if present on the command line). RSS naturally runs
  above the declared heap because of metaspace, thread stacks and native
  buffers, so the threshold is deliberately generous (WARN at 1.3x Xmx, CRIT
  at 1.6x Xmx) - a heuristic, not an exact heap reading; if -Xmx is absent,
  reports the value with no threshold.
- webapp_jvm_threads: live thread count from /proc/1/task.

Piggybacked to NS8-RL98-WEBTOP (this check belongs to that module, not the
node itself).

Version: 1.0.0"""

import http.client
import json
import os
import pwd
import re
import socket
import struct
import sys
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Tuple

VERSION = "1.0.0"
NODE_AGENT_ENV = "/var/lib/nethserver/node/state/agent.env"
TARGET_SERVICES = ["postgres", "apache", "webapp", "pecbridge", "z-push", "webdav"]
NS8_API = os.environ.get("NS8_API", "http://127.0.0.1:9311/api")
TOKEN_FILE = os.environ.get("NS8_TOKEN_FILE", "/root/.ns8-token-ro")
STATUS_TIMEOUT_SECONDS = 8
PODMAN = "/v5.0.0/libpod"

# heuristic thresholds for the webapp (Tomcat/Java) extras - see docstring
JVM_MEM_WARN_RATIO = 1.3
JVM_MEM_CRIT_RATIO = 1.6
JVM_THREADS_WARN = 150
JVM_THREADS_CRIT = 300


class UnixHTTPConnection(http.client.HTTPConnection):
    """HTTP over a unix socket, for the podman REST API."""

    def __init__(self, path: str, timeout: float = 15):
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


def get_webtop_instances() -> List[str]:
    """WebTop instances installed on this node (REST API)."""
    out, _ = cached_ns8_task("cluster", "list-installed-modules")
    if not isinstance(out, dict):
        return []
    node_id = get_local_node_id()
    result = []
    for instances in out.values():
        for inst in instances:
            is_webtop = inst.get("module") == "webtop" or inst["id"].startswith("webtop")
            if is_webtop and (not node_id or str(inst.get("node")) == node_id):
                result.append(inst["id"])
    return sorted(result)


def podman_socket(instance: str) -> Tuple[str, str]:
    """Returns (error, socket path) for a module's podman API socket."""
    try:
        uid = pwd.getpwnam(instance).pw_uid
    except KeyError:
        return "no-user", ""
    path = f"/run/user/{uid}/podman/podman.sock"
    if not os.path.exists(path):
        return "no-podman-socket", ""
    return "", path


def podman_call(sock_path: str, method: str, path: str, body: Optional[dict] = None) -> Tuple[int, bytes]:
    conn = UnixHTTPConnection(sock_path)
    try:
        payload = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"} if payload is not None else {}
        conn.request(method, PODMAN + path, body=payload, headers=headers)
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


def demux_stream(raw: bytes, streams: Tuple[int, ...] = (1,)) -> str:
    """Decodes a podman exec stream (8-byte frame headers) into text.

    Frame: [stream type, 0, 0, 0, payload size as big-endian uint32] + payload.
    stream type 1 = stdout, 2 = stderr; only the listed streams are returned."""
    out = b""
    pos = 0
    while pos + 8 <= len(raw):
        stream_type, size = raw[pos], struct.unpack(">I", raw[pos + 4:pos + 8])[0]
        chunk = raw[pos + 8:pos + 8 + size]
        if stream_type in streams:
            out += chunk
        pos += 8 + size
    return out.decode("utf-8", errors="replace")


def exec_in_container(sock_path: str, container: str, cmd: List[str]) -> Tuple[int, str]:
    """Runs a command in a container through the podman API. Returns (exit code, stdout).

    exit code is -1 when the exec could not be created or started."""
    try:
        status, raw = podman_call(sock_path, "POST", f"/containers/{container}/exec",
                                  {"Cmd": cmd, "AttachStdout": True, "AttachStderr": True})
        if status not in (200, 201):
            return -1, ""
        exec_id = json.loads(raw.decode())["Id"]
        status, raw = podman_call(sock_path, "POST", f"/exec/{exec_id}/start", {"Detach": False, "Tty": False})
        if status != 200:
            return -1, ""
        stdout = demux_stream(raw)
        status, raw = podman_call(sock_path, "GET", f"/exec/{exec_id}/json")
        exit_code = json.loads(raw.decode()).get("ExitCode", -1) if status == 200 else -1
        return exit_code, stdout
    except (OSError, ValueError, KeyError, http.client.HTTPException):
        return -1, ""


def get_container_status(sock_path: str) -> Optional[Dict[str, str]]:
    """container name -> 'Up' / state, from the podman API. None if unreachable."""
    try:
        status, raw = podman_call(sock_path, "GET", "/containers/json?all=true")
        if status != 200:
            return None
        return {c["Names"][0]: ("Up" if c.get("State") == "running" else c.get("State", "unknown"))
                for c in json.loads(raw.decode())}
    except (OSError, ValueError, KeyError, http.client.HTTPException):
        return None


def get_service_states(instance: str) -> Dict[str, dict]:
    """service name -> NS8 get-status entry (active/enabled/failed). {} if unavailable."""
    out, err = ns8_task(f"module/{instance}", "get-status", timeout=STATUS_TIMEOUT_SECONDS)
    if err or not isinstance(out, dict):
        return {}
    return {s["name"]: s for s in out.get("services", [])}


def check_webapp_jvm(sock_path: str) -> None:
    """JVM visibility for the webapp (Tomcat) container without jcmd/jstat (not installed
    in this slim JRE image, verified empirically): /proc/1 inside the container."""
    code, out = exec_in_container(sock_path, "webapp", ["sh", "-c", "grep -E 'VmRSS' /proc/1/status; ls /proc/1/task | wc -l"])
    if code != 0 or not out.strip():
        print("3 webapp_jvm_memory - UNKNOWN: cannot read /proc/1 inside webapp")
        print("3 webapp_jvm_threads - UNKNOWN: cannot read /proc/1 inside webapp")
        return
    lines = out.strip().splitlines()
    rss_kb = 0.0
    threads = 0
    for ln in lines:
        m = re.match(r"VmRSS:\s+(\d+)", ln)
        if m:
            rss_kb = float(m.group(1))
        elif ln.strip().isdigit():
            threads = int(ln.strip())
    rss_mb = rss_kb / 1024.0

    _, cmdline = exec_in_container(sock_path, "webapp", ["sh", "-c", "tr '\\0' ' ' < /proc/1/cmdline"])
    xmx_match = re.search(r"-Xmx(\d+)([mMgG])", cmdline or "")
    xmx_mb = None
    if xmx_match:
        value, unit = float(xmx_match.group(1)), xmx_match.group(2).lower()
        xmx_mb = value * 1024 if unit == "g" else value

    if xmx_mb:
        warn, crit = xmx_mb * JVM_MEM_WARN_RATIO, xmx_mb * JVM_MEM_CRIT_RATIO
        state = 2 if rss_mb >= crit else (1 if rss_mb >= warn else 0)
        print(f"{state} webapp_jvm_memory - resident memory {rss_mb:.0f} MB (-Xmx {xmx_mb:.0f} MB) "
              f"| rss_mb={rss_mb:.0f};{warn:.0f};{crit:.0f};0;")
    else:
        print(f"0 webapp_jvm_memory - resident memory {rss_mb:.0f} MB (no -Xmx found on the command line) | rss_mb={rss_mb:.0f};;;0;")

    t_state = 2 if threads >= JVM_THREADS_CRIT else (1 if threads >= JVM_THREADS_WARN else 0)
    print(f"{t_state} webapp_jvm_threads - {threads} live threads | threads={threads};{JVM_THREADS_WARN};{JVM_THREADS_CRIT};0;")


def main() -> int:
    instances = get_webtop_instances()
    if not instances:
        # No webtop instance found, silent exit (same convention as check_ns8_services_api.py)
        return 0

    for instance in instances:
        error, sock_path = podman_socket(instance)
        container_status = get_container_status(sock_path) if not error else None
        reason = error or ("podman-api-error" if container_status is None else "")
        container_status = container_status or {}
        svc_states = get_service_states(instance)

        for service in TARGET_SERVICES:
            if service in container_status:
                if container_status[service] == "Up":
                    print(f"0 {service} - {service} active")
                    if service == "webapp":
                        check_webapp_jvm(sock_path)
                else:
                    print(f"2 {service} - {service} not active")
                continue
            svc = svc_states.get(service)
            if svc and svc.get("failed"):
                print(f"2 {service} - {service} failed")
            elif svc and svc.get("enabled") and not svc.get("active"):
                print(f"2 {service} - {service} not active")
            else:
                detail = f" ({reason})" if reason else ""
                print(f"3 {service} - {service} not found{detail}")
    return 0


if __name__ == "__main__":
    # Piggyback to NS8-RL98-WEBTOP: this check belongs to that module, not the node itself
    # (see memory ns8_rl98 local check reorganisation, 2026-10-12)
    print("<<<<NS8-RL98-WEBTOP>>>>")
    print("<<<local:sep(0)>>>")
    _rc = main()
    print("<<<<>>>>")
    sys.exit(_rc)
