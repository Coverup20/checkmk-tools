#!/usr/bin/env python3
"""check_ns8_services_api.py - CheckMK Local Check for NS8 Mail Services, API only (PROTOTYPE)

Same CheckMK local-check output as check_ns8_services.py (clamav, rspamd,
dovecot, postfix + the dovecot extras), but no subprocess at all:
- mail module list: NS8 REST API (cluster/list-installed-modules), token read
  from NS8_TOKEN_FILE (default /root/.ns8-token-ro, a reader-role user is enough)
- container state and the dovecot extras: the mail module's own podman REST API
  socket (/run/user/<uid>/podman/podman.sock, needs `systemctl --user enable
  --now podman.socket` in the module); `exec` goes through
  POST /containers/<id>/exec + POST /exec/<id>/start
- service state: NS8 module get-status, so a stopped service (whose container
  has disappeared) is CRIT instead of "not found"

Validated on NS8-RL98 with mail1 running (service states, doveadm, doveconf,
postfix stopped); NOT validated: real IMAP sessions, and the vsz_limit log
check cannot work there (see DEVIATIONS).
Deviations from the original are listed in DEVIATIONS below.

DEVIATIONS from check_ns8_services.py:
- a service with no container: CRIT "not active" if get-status says it is
  enabled (or failed) and not running; UNKNOWN "not found" otherwise (as before)
- VszLimit: the original ran `config show dovecot` on the host, a command that
  does not exist on the NS8 node tested; here the effective value is read inside
  the container with `doveconf -h default_vsz_limit`. Dovecot always has a
  default for it, so "limit not set" only triggers on an empty value or 0.
- IMAP sessions: the header line printed by `doveadm who` is no longer counted
  as a session (the original reported 1 session with nobody connected)
- vsz_limit errors: counted in the last 500 lines of the dovecot container log
  (podman logs API). KNOWN LIMIT: on NS8-RL98 the container uses the journald
  log driver and `podman logs dovecot` is empty (CLI and API alike), so this
  count is always 0 there, exactly like the original (/var/log/dovecot* does
  not exist in the container). A real detection needs journald or the NS8 Loki
  module; not implemented.

Version: 0.2.0"""

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

VERSION = "0.2.0"
LOG_LINES = 500
NODE_AGENT_ENV = "/var/lib/nethserver/node/state/agent.env"
TARGET_SERVICES = ["clamav", "rspamd", "dovecot", "postfix"]
NS8_API = os.environ.get("NS8_API", "http://127.0.0.1:9311/api")
TOKEN_FILE = os.environ.get("NS8_TOKEN_FILE", "/root/.ns8-token-ro")
STATUS_TIMEOUT_SECONDS = 8
PODMAN = "/v5.0.0/libpod"


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


def get_mail_instances() -> List[str]:
    """Mail instances installed on this node (REST API, no redis-cli)."""
    out, _ = ns8_task("cluster", "list-installed-modules")
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
    """Decodes a podman exec/attach/logs stream (8-byte frame headers) into text.

    Frame: [stream type, 0, 0, 0, payload size as big-endian uint32] + payload.
    stream type 1 = stdout, 2 = stderr; only the listed streams are returned
    (stdout by default)."""
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


def get_imap_sessions(sock_path: str) -> int:
    """Number of IMAP sessions listed by `doveadm who`.

    `doveadm who` always prints a header line ("username # proto (pids) (ips)"),
    which the original counted as a session; it is skipped here."""
    code, out = exec_in_container(sock_path, "dovecot", ["doveadm", "who"])
    if code != 0 or not out.strip():
        return 0
    lines = [ln for ln in out.strip().split("\n") if ln.strip()]
    return len([ln for ln in lines if not ln.lstrip().lower().startswith("username")])


def get_vsz_limit(sock_path: str) -> Optional[str]:
    """Effective dovecot vsz_limit, read inside the container (see DEVIATIONS)."""
    code, out = exec_in_container(sock_path, "dovecot", ["doveconf", "-h", "default_vsz_limit"])
    value = out.strip()
    if code != 0 or not value or value == "0":
        return None
    return value


VSZ_ERROR = "Cannot allocate memory due to vsz_limit"


def count_log_matches(sock_path: str, container: str, text: str, lines: int = LOG_LINES) -> int:
    """Occurrences of `text` in the last `lines` log lines of the container.

    Uses the podman logs API: dovecot in the NS8 mail container logs to stdout,
    /var/log/dovecot* (read by the original) does not exist there."""
    try:
        status, raw = podman_call(sock_path, "GET",
                                  f"/containers/{container}/logs?stdout=true&stderr=true&tail={lines}")
        if status != 200:
            return 0
        return demux_stream(raw, (1, 2)).count(text)
    except (OSError, http.client.HTTPException):
        return 0


def count_vsz_errors(sock_path: str) -> int:
    return count_log_matches(sock_path, "dovecot", VSZ_ERROR)


def check_dovecot_extras(sock_path: str) -> None:
    imap_count = get_imap_sessions(sock_path)
    if imap_count > 0:
        print(f"0 imap_sessions - Active IMAP sessions: {imap_count}")
    else:
        print("1 imap_sessions - No active IMAP sessions")

    vsz_limit = get_vsz_limit(sock_path)
    error_count = count_vsz_errors(sock_path)
    if error_count > 0:
        if vsz_limit:
            print(f"2 dovecot_vszlimit - CRIT: vsz_limit detected ({error_count} occurrences in last {LOG_LINES} lines, configured limit={vsz_limit})")
        else:
            print(f"2 dovecot_vszlimit - CRIT: vsz_limit detected ({error_count} occurrences in last {LOG_LINES} lines, limit not set)")
    else:
        if vsz_limit:
            print(f"0 dovecot_vszlimit - No alarms in logs (configured limit={vsz_limit})")
        else:
            print("1 dovecot_vszlimit - WARNING: No alarms in logs (limit not set)")


def main() -> int:
    mail_instances = get_mail_instances()
    if not mail_instances:
        # No mail instances found, silent exit (same as the original)
        return 0

    for instance in mail_instances:
        error, sock_path = podman_socket(instance)
        container_status = get_container_status(sock_path) if not error else None
        reason = error or ("podman-api-error" if container_status is None else "")
        container_status = container_status or {}
        svc_states = get_service_states(instance)

        for service in TARGET_SERVICES:
            if service in container_status:
                if container_status[service] == "Up":
                    print(f"0 {service} - {service} active")
                    if service == "dovecot":
                        check_dovecot_extras(sock_path)
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
    sys.exit(main())
