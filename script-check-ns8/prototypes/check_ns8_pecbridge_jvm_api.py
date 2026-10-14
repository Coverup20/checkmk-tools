#!/usr/bin/env python3
"""check_ns8_pecbridge_jvm_api.py - CheckMK Local Check for the WebTop pecbridge JVM, API only

Built 2026-10-12 after the user asked about PEC connector failures, following a
read of recent Ydea tickets (a PEC "Connection reset" complaint among them).
pecbridge (`com.sonicle.pecbridge.Main`, webtop1's PEC-to-mailbox bridge) turned
out to be its own Java process, same situation as webapp/Tomcat - same JVM
visibility approach applies: /proc/1/status (VmRSS) and /proc/1/cmdline (-Xmx if
set) inside the container, no jcmd/jstat available (same slim-JRE image family).

PROTOTYPE CAVEAT: no PEC account is configured on this lab node (verified: no
config beyond the default etc/config.xml, no log output ever produced by the
process), so the actual "connector failed to reach a PEC provider" case this was
originally asked about could NOT be observed or validated here - there is
nothing to parse a real error out of. This script covers only the JVM-health
angle (memory/thread leak crashing the bridge), which is independently useful
but is NOT a check for "is this specific PEC account's connector working".
That would need a configured PEC account and a look at pecbridge's real error
output when one fails, on a node where that is actually set up.

Piggybacked to NS8-RL98-WEBTOP (pecbridge lives inside webtop1, not mail1).

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
from typing import List, Optional, Tuple

VERSION = "1.0.0"
NODE_AGENT_ENV = "/var/lib/nethserver/node/state/agent.env"
NS8_API = os.environ.get("NS8_API", "http://127.0.0.1:9311/api")
TOKEN_FILE = os.environ.get("NS8_TOKEN_FILE", "/root/.ns8-token-ro")
PODMAN = "/v5.0.0/libpod"

JVM_MEM_WARN_RATIO = 1.3
JVM_MEM_CRIT_RATIO = 1.6
JVM_THREADS_WARN = 150
JVM_THREADS_CRIT = 300


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float = 15):
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._path)


def get_local_node_id() -> str:
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


def ns8_task(agent: str, action: str, timeout: float = 15.0):
    import urllib.error
    import urllib.request
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
            if exc.code != 400:
                return None, "permission-denied" if exc.code in (401, 403) else f"api-http-{exc.code}"
        except (urllib.error.URLError, ValueError, OSError):
            return None, "api-unreachable"
        time.sleep(0.1)
    return None, "task-timeout"


def get_webtop_instances() -> List[str]:
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
    out, pos = b"", 0
    while pos + 8 <= len(raw):
        stream_type, size = raw[pos], struct.unpack(">I", raw[pos + 4:pos + 8])[0]
        chunk = raw[pos + 8:pos + 8 + size]
        if stream_type in streams:
            out += chunk
        pos += 8 + size
    return out.decode("utf-8", errors="replace")


def exec_in_container(sock_path: str, container: str, cmd: List[str]) -> Tuple[int, str]:
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


def main() -> int:
    instances = get_webtop_instances()
    if not instances:
        return 0

    for instance in instances:
        error, sock_path = podman_socket(instance)
        if error:
            print(f"3 pecbridge_jvm_memory - UNKNOWN: {error}")
            print(f"3 pecbridge_jvm_threads - UNKNOWN: {error}")
            continue

        code, out = exec_in_container(sock_path, "pecbridge", ["sh", "-c", "grep -E 'VmRSS' /proc/1/status; ls /proc/1/task | wc -l"])
        if code != 0 or not out.strip():
            print("3 pecbridge_jvm_memory - UNKNOWN: cannot read /proc/1 inside pecbridge (container not found or not running)")
            print("3 pecbridge_jvm_threads - UNKNOWN: cannot read /proc/1 inside pecbridge")
            continue

        rss_kb, threads = 0.0, 0
        for ln in out.strip().splitlines():
            m = re.match(r"VmRSS:\s+(\d+)", ln)
            if m:
                rss_kb = float(m.group(1))
            elif ln.strip().isdigit():
                threads = int(ln.strip())
        rss_mb = rss_kb / 1024.0

        _, cmdline = exec_in_container(sock_path, "pecbridge", ["sh", "-c", "tr '\\0' ' ' < /proc/1/cmdline"])
        xmx_match = re.search(r"-Xmx(\d+)([mMgG])", cmdline or "")
        xmx_mb = None
        if xmx_match:
            value, unit = float(xmx_match.group(1)), xmx_match.group(2).lower()
            xmx_mb = value * 1024 if unit == "g" else value

        if xmx_mb:
            warn, crit = xmx_mb * JVM_MEM_WARN_RATIO, xmx_mb * JVM_MEM_CRIT_RATIO
            state = 2 if rss_mb >= crit else (1 if rss_mb >= warn else 0)
            print(f"{state} pecbridge_jvm_memory - resident memory {rss_mb:.0f} MB (-Xmx {xmx_mb:.0f} MB) | rss_mb={rss_mb:.0f};{warn:.0f};{crit:.0f};0;")
        else:
            print(f"0 pecbridge_jvm_memory - resident memory {rss_mb:.0f} MB (no -Xmx found, JVM default heap sizing) | rss_mb={rss_mb:.0f};;;0;")

        t_state = 2 if threads >= JVM_THREADS_CRIT else (1 if threads >= JVM_THREADS_WARN else 0)
        print(f"{t_state} pecbridge_jvm_threads - {threads} live threads | threads={threads};{JVM_THREADS_WARN};{JVM_THREADS_CRIT};0;")
    return 0


if __name__ == "__main__":
    # Piggyback to NS8-RL98-WEBTOP: pecbridge lives inside webtop1, not mail1
    # (see memory ns8_rl98 local check reorganisation, 2026-10-12)
    print("<<<<NS8-RL98-WEBTOP>>>>")
    print("<<<local:sep(0)>>>")
    _rc = main()
    print("<<<<>>>>")
    sys.exit(_rc)
