#!/usr/bin/env python3
"""check_ns8_mail_queue_api.py - CheckMK Local Check for the NS8 mail1 Postfix queue, API only

Built 2026-10-12 after a read of the last ~5 weeks of Ydea tickets showed outbound
mail delivery failures ("mancato invio", "problemi invio posta", specific
attachments/recipients timing out) as the single most common mail-related
complaint - something no existing check looks at (they only verify postfix is
*running*, never whether mail is actually moving through it).

Runs `postqueue -j` (Postfix JSON queue listing, one JSON object per queued
message: queue_name, queue_id, arrival_time, message_size, sender, recipients)
inside the postfix container via the module's own podman REST API socket - same
pattern as check_ns8_services_api.py. No subprocess, no SSH.

PROTOTYPE CAVEAT: the queue on NS8-RL98 is empty at the time this was written
(a healthy lab system, no test messages queued) - the parser follows Postfix's
documented `postqueue -j` schema (postqueue(1)) but has never been exercised
against a real deferred/held message here. Validate the field names against a
real deferred message the first time this fires for real.

Checks:
- MailQueue.Depth: message counts by queue (incoming/active/deferred/hold/corrupt)
- MailQueue.Oldest: age of the oldest deferred message (WARN >=30min, CRIT >=2h) -
  a healthy queue drains in seconds; anything sitting in "deferred" that long
  means the destination is consistently rejecting or timing out.

Piggybacked to NS8-RL98-MAIL.

Version: 1.0.0"""

import http.client
import json
import os
import pwd
import socket
import struct
import sys
import time
from typing import Dict, List, Optional, Tuple

VERSION = "1.0.0"
NODE_AGENT_ENV = "/var/lib/nethserver/node/state/agent.env"
NS8_API = os.environ.get("NS8_API", "http://127.0.0.1:9311/api")
TOKEN_FILE = os.environ.get("NS8_TOKEN_FILE", "/root/.ns8-token-ro")
PODMAN = "/v5.0.0/libpod"

DEFERRED_WARN_SECONDS = 30 * 60
DEFERRED_CRIT_SECONDS = 2 * 60 * 60
DEPTH_WARN = 20
DEPTH_CRIT = 100


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


def get_mail_instances() -> List[str]:
    out, _ = cached_ns8_task("cluster", "list-installed-modules")
    if not isinstance(out, dict):
        return []
    node_id = get_local_node_id()
    result = []
    for instances in out.values():
        for inst in instances:
            is_mail = inst.get("module") == "mail" or inst["id"].startswith("mail")
            if is_mail and (not node_id or str(inst.get("node")) == node_id):
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
    instances = get_mail_instances()
    if not instances:
        return 0

    for instance in instances:
        error, sock_path = podman_socket(instance)
        if error:
            print(f"3 MailQueue.Depth - UNKNOWN: {error}")
            print(f"3 MailQueue.Oldest - UNKNOWN: {error}")
            continue

        code, out = exec_in_container(sock_path, "postfix", ["postqueue", "-j"])
        if code != 0:
            print(f"3 MailQueue.Depth - UNKNOWN: postqueue -j failed (exit {code})")
            print(f"3 MailQueue.Oldest - UNKNOWN: postqueue -j failed (exit {code})")
            continue

        by_queue: Dict[str, int] = {}
        oldest_deferred_age = 0.0
        now = time.time()
        total_size = 0
        parse_errors = 0
        for line in out.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                parse_errors += 1
                continue
            qname = msg.get("queue_name", "unknown")
            by_queue[qname] = by_queue.get(qname, 0) + 1
            total_size += int(msg.get("message_size") or 0)
            if qname == "deferred":
                arrival = msg.get("arrival_time")
                if isinstance(arrival, (int, float)):
                    oldest_deferred_age = max(oldest_deferred_age, now - arrival)

        total = sum(by_queue.values())
        state = 2 if total >= DEPTH_CRIT else (1 if total >= DEPTH_WARN else 0)
        detail = ", ".join(f"{k}={v}" for k, v in sorted(by_queue.items())) or "empty"
        note = f", {parse_errors} line(s) not parsed (unexpected format, see PROTOTYPE CAVEAT)" if parse_errors else ""
        print(f"{state} MailQueue.Depth queue_total={total};{DEPTH_WARN};{DEPTH_CRIT};0; - {detail}{note}")

        d_state = 2 if oldest_deferred_age >= DEFERRED_CRIT_SECONDS else (1 if oldest_deferred_age >= DEFERRED_WARN_SECONDS else 0)
        if by_queue.get("deferred"):
            minutes = oldest_deferred_age / 60.0
            print(f"{d_state} MailQueue.Oldest oldest_deferred_seconds={oldest_deferred_age:.0f};{DEFERRED_WARN_SECONDS};{DEFERRED_CRIT_SECONDS};0; "
                  f"- oldest deferred message is {minutes:.0f} minute(s) old ({by_queue['deferred']} deferred total)")
        else:
            print("0 MailQueue.Oldest oldest_deferred_seconds=0;;;0; - no deferred messages")
    return 0


if __name__ == "__main__":
    # Piggyback to NS8-RL98-MAIL (see memory ns8_rl98 local check reorganisation, 2026-10-12)
    print("<<<<NS8-RL98-MAIL>>>>")
    print("<<<local:sep(0)>>>")
    _rc = main()
    print("<<<<>>>>")
    sys.exit(_rc)
