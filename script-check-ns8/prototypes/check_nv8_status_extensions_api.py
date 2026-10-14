#!/usr/bin/env python3
"""check_nv8_status_extensions_api.py - CheckMK Local Check for NethVoice NS8 extension registration, API only (PROTOTYPE, UNTESTED)

Same CheckMK local-check output, thresholds and `pjsip show endpoints` parser
as check_nv8_status_extensions.py, but no subprocess at all:
- module list: NS8 REST API (cluster/list-installed-modules), token read from
  NS8_TOKEN_FILE (default /root/.ns8-token-ro, a reader-role user is enough)
- containers and `asterisk -rx "pjsip show endpoints"`: the module's own
  podman REST API socket (/run/user/<uid>/podman/podman.sock, needs
  `systemctl --user enable --now podman.socket` in the module); the command
  goes through POST /containers/<id>/exec + POST /exec/<id>/start

UNTESTED: written without a running NethVoice module (nethvoice1 is stopped on
the lab node). Verified only that it compiles, that the exec stream decoder
works on synthetic frames and that the parser gives the same result as the
original on sample text. Like the original, a NethVoice module that is stopped
is reported as "no NethVoice module found" (CRITICAL).

Version: 0.1.0"""

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

VERSION = "0.1.0"
SERVICE_SUMMARY = "NV8.Status.Extensions"
SERVICE_EXT = "NV8.Status.Extension"

SCRIPT_TIMEOUT = 25       # seconds, total budget
WARN_PCT = 10             # % extensions not registered -> WARNING
CRIT_PCT = 30             # % extensions not registered -> CRITICAL

NODE_AGENT_ENV = "/var/lib/nethserver/node/state/agent.env"
NS8_API = os.environ.get("NS8_API", "http://127.0.0.1:9311/api")
TOKEN_FILE = os.environ.get("NS8_TOKEN_FILE", "/root/.ns8-token-ro")
PODMAN = "/v5.0.0/libpod"
NETHVOICE_KEYWORDS = ("nethvoice", "asterisk", "freepbx", "pbx")

_START = time.monotonic()

# Endpoint states indicating active registration
REGISTERED_STATES = {
    "not in use",
    "in use",
    "ringing",
    "ring",
    "busy",
    "on hold",
}

# Regex for Endpoint line in the output of `pjsip show endpoints`
# Example: "Endpoint: 100 Not in use 0 of inf"
#          "  Endpoint:  200/200              Unavailable   0 of inf"
ENDPOINT_RE = re.compile(
    r"^\s+Endpoint:\s+(\S+)\s+(.*?)\s+\d+\s+of\s+",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def elapsed() -> float:
    return time.monotonic() - _START


def sanitize_name(name: str) -> str:
    """Converts an extension name to CheckMK service name dot format."""
    name = name.split("/")[0]
    name = re.sub(r"[^a-zA-Z0-9]", ".", name)
    name = re.sub(r"\.{2,}", ".", name)
    return name.strip(".") or "ext"


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


def podman_socket(module: str) -> str:
    """Path of the module's podman API socket, '' if missing."""
    try:
        uid = pwd.getpwnam(module).pw_uid
    except KeyError:
        return ""
    path = f"/run/user/{uid}/podman/podman.sock"
    return path if os.path.exists(path) else ""


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


def demux_stream(raw: bytes) -> str:
    """Decodes a podman exec/attach stream (8-byte frame headers) into stdout text.

    Frame: [stream type, 0, 0, 0, payload size as big-endian uint32] + payload.
    stream type 1 = stdout, 2 = stderr; only stdout is returned."""
    out = b""
    pos = 0
    while pos + 8 <= len(raw):
        stream_type, size = raw[pos], struct.unpack(">I", raw[pos + 4:pos + 8])[0]
        chunk = raw[pos + 8:pos + 8 + size]
        if stream_type == 1:
            out += chunk
        pos += 8 + size
    return out.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Discovery modules and containers
# ---------------------------------------------------------------------------

def get_modules() -> List[str]:
    """NethVoice-looking module instances installed on this node (REST API)."""
    out, _ = ns8_task("cluster", "list-installed-modules")
    if not isinstance(out, dict):
        return []
    node_id = get_local_node_id()
    result = []
    for instances in out.values():
        for inst in instances:
            if node_id and str(inst.get("node")) != node_id:
                continue
            if any(kw in inst["id"].lower() for kw in NETHVOICE_KEYWORDS):
                result.append(inst["id"])
    return sorted(result)


def get_running_containers(module: str) -> List[str]:
    """Names of the RUNNING containers of the module (like `podman ps`)."""
    sock_path = podman_socket(module)
    if not sock_path:
        return []
    try:
        status, raw = podman_call(sock_path, "GET", "/containers/json")
        if status != 200:
            return []
        return [c["Names"][0] for c in json.loads(raw.decode())]
    except (OSError, ValueError, KeyError, http.client.HTTPException):
        return []


def find_nethvoice_containers() -> List[Tuple[str, str]]:
    """Find all FreePBX/Asterisk containers in NethVoice modules.
    Returns list of (module_name, container_name)."""
    results = []
    for module in get_modules():
        if elapsed() >= SCRIPT_TIMEOUT - 5:
            break
        for cname in get_running_containers(module):
            if "freepbx" in cname.lower() or "asterisk" in cname.lower():
                results.append((module, cname))
    return results


# ---------------------------------------------------------------------------
# Query Asterisk CLI
# ---------------------------------------------------------------------------

def run_asterisk_cmd(module: str, container: str, asterisk_cmd: str) -> Optional[str]:
    """Executes an Asterisk CLI command through the podman exec API.

    Returns stdout, or None if the exec could not be run. Like the original, a
    non-zero Asterisk exit code is not an error as long as the exec ran."""
    sock_path = podman_socket(module)
    if not sock_path:
        return None
    try:
        status, raw = podman_call(sock_path, "POST", f"/containers/{container}/exec",
                                  {"Cmd": ["asterisk", "-rx", asterisk_cmd],
                                   "AttachStdout": True, "AttachStderr": True})
        if status not in (200, 201):
            return None
        exec_id = json.loads(raw.decode())["Id"]
        status, raw = podman_call(sock_path, "POST", f"/exec/{exec_id}/start", {"Detach": False, "Tty": False})
        if status != 200:
            return None
        return demux_stream(raw).strip()
    except (OSError, ValueError, KeyError, http.client.HTTPException):
        return None


# ---------------------------------------------------------------------------
# Parsing `pjsip show endpoints` (unchanged from the original)
# ---------------------------------------------------------------------------

def parse_endpoints(output: str) -> List[Dict[str, str]]:
    """Parse the output of `pjsip show endpoints`.
    Returns list of dicts with: name, raw_name, state, registered."""
    endpoints = []
    for line in output.splitlines():
        m = ENDPOINT_RE.match(line)
        if not m:
            continue

        raw_name = m.group(1).strip()
        raw_state = m.group(2).strip()
        state_lc = raw_state.lower()

        # Skip endpoints that appear to be trunk or system endpoints
        base_name = raw_name.split("/")[0]
        if any(kw in base_name.lower() for kw in ("trunk", "reg-", "reg_", "sip:", "anonymous")):
            continue

        # Skip non-endpoint entries (headers, separators, counts)
        if not re.match(r"^[a-zA-Z0-9]", base_name):
            continue

        registered = state_lc in REGISTERED_STATES

        endpoints.append({
            "name": base_name,
            "raw_name": raw_name,
            "state": raw_state,
            "registered": registered,
        })

    return endpoints


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    containers = find_nethvoice_containers()
    if not containers:
        print(f"2 {SERVICE_SUMMARY} - CRITICAL: no NethVoice module found on this NS8 host")
        return 0

    all_endpoints: List[Dict[str, str]] = []
    modules_checked: List[str] = []

    for module, container in containers:
        if elapsed() >= SCRIPT_TIMEOUT - 3:
            break

        output = run_asterisk_cmd(module, container, "pjsip show endpoints")
        if not output or not output.strip():
            continue

        eps = parse_endpoints(output)
        for ep in eps:
            ep["module"] = module
        all_endpoints.extend(eps)
        modules_checked.append(module)

    if not all_endpoints:
        print(
            f"1 {SERVICE_SUMMARY} - WARNING: no PJSIP extension found "
            f"| modules={','.join(modules_checked) or 'none'}"
        )
        return 0

    total = len(all_endpoints)
    registered = [e for e in all_endpoints if e["registered"]]
    unreg = [e for e in all_endpoints if not e["registered"]]
    reg_count = len(registered)
    unreg_count = len(unreg)
    unreg_pct = (unreg_count / total * 100) if total > 0 else 0.0

    # One CRIT line for each unregistered extension -> separate service -> individual notification
    for ep in unreg:
        svc = f"{SERVICE_EXT}.{sanitize_name(ep['name'])}"
        print(f"2 {svc} - Unregistered | name={ep['name']} state={ep['state']} module={ep['module']}")

    # Concise summary (counts only)
    if unreg_count == 0:
        overall = 0
        msg = f"OK: all {total} extensions registered"
    elif unreg_pct >= CRIT_PCT:
        overall = 2
        msg = f"CRITICAL: {reg_count}/{total} registered, {unreg_count} unregistered ({unreg_pct:.0f}%)"
    elif unreg_pct >= WARN_PCT:
        overall = 1
        msg = f"WARNING: {reg_count}/{total} registered, {unreg_count} unregistered ({unreg_pct:.0f}%)"
    else:
        overall = 0
        msg = f"OK: {reg_count}/{total} registered, {unreg_count} unregistered ({unreg_pct:.0f}%)"

    perf = f"registered={reg_count};;;0;{total} unregistered={unreg_count};;;0;{total} total={total}"
    modules_str = ",".join(modules_checked)
    print(f"{overall} {SERVICE_SUMMARY} - {msg} | {perf} modules={modules_str}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
