#!/usr/bin/env python3
"""check_nv8_status_trunk_api.py - CheckMK Local Check for NethVoice NS8 trunk status, API only (PROTOTYPE, UNTESTED)

Same CheckMK local-check output, state mapping and `pjsip show registrations`
parser as check_nv8_status_trunk.py, but no subprocess at all:
- module list: NS8 REST API (cluster/list-installed-modules), token read from
  NS8_TOKEN_FILE (default /root/.ns8-token-ro, a reader-role user is enough)
- containers and `asterisk -rx "pjsip show registrations outbound"`: the
  module's own podman REST API socket (/run/user/<uid>/podman/podman.sock,
  needs `systemctl --user enable --now podman.socket` in the module); the
  command goes through POST /containers/<id>/exec + POST /exec/<id>/start

UNTESTED: written without a running NethVoice module (nethvoice1 is stopped on
the lab node). Verified only that it compiles, that the exec stream decoder
works on synthetic frames and that the parser gives the same result as the
original on sample text. Like the original, a NethVoice module that is stopped
is reported as "Asterisk/FreePBX container not found" (CRITICAL).

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
SERVICE_PREFIX = "NV8.Status.Trunk"
SERVICE_SUMMARY = "NV8.Status.Trunks"

SCRIPT_TIMEOUT = 20  # seconds, total budget
NODE_AGENT_ENV = "/var/lib/nethserver/node/state/agent.env"
NS8_API = os.environ.get("NS8_API", "http://127.0.0.1:9311/api")
TOKEN_FILE = os.environ.get("NS8_TOKEN_FILE", "/root/.ns8-token-ro")
PODMAN = "/v5.0.0/libpod"
NETHVOICE_KEYWORDS = ("nethvoice", "asterisk", "freepbx", "pbx")

_START = time.monotonic()

# PJSIP registration states -> CheckMK state (0=OK, 1=WARN, 2=CRIT, 3=UNKNOWN)
STATE_MAP: Dict[str, int] = {
    "Registered": 0,
    "Not Registered": 1,  # may be intentional for IP-based trunks
    "Trying": 1,
    "No Auth": 2,
    "Rejected": 2,
    "Failed": 2,
    "Stopped": 2,
    "Unregistered": 2,
}

# Regex to detect PJSIP status in the line (not necessarily at the end of the line)
# ex: "trunk/sip:host:5060 auth Rejected (exp. 28s)"
STATUS_RE = re.compile(
    r"\b(Not\s+Registered|No\s+Auth|Registered|Trying|Rejected|Failed|Stopped|Unregistered)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def elapsed() -> float:
    """Seconds elapsed since the script was started."""
    return time.monotonic() - _START


def sanitize_name(name: str) -> str:
    """Converts a trunk name into a valid service name for CheckMK.
    - Remove prefix reg- / reg_
    - Replaces non-alphanumeric characters (including _ and -) with dots"""
    name = re.sub(r"^reg[-_]", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[^a-zA-Z0-9]", ".", name)
    name = re.sub(r"\.{2,}", ".", name)
    return name.strip(".") or "trunk"


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
# Discovery of the Asterisk container
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
    """Find ALL FreePBX/Asterisk containers in all nethvoice modules.
    Returns list of (module_name, container_name)."""
    results = []
    for module in get_modules():
        if elapsed() >= SCRIPT_TIMEOUT:
            break
        for cname in get_running_containers(module):
            if "freepbx" in cname.lower() or "asterisk" in cname.lower():
                results.append((module, cname))
    return results


# ---------------------------------------------------------------------------
# Query Asterisk
# ---------------------------------------------------------------------------

def run_asterisk_cmd(module: str, container: str, asterisk_cmd: str) -> Optional[str]:
    """Executes an Asterisk CLI command through the podman exec API.

    Returns stdout, or None if the exec could not be run. Like the original, a
    non-zero Asterisk exit code is not an error as long as the exec ran, and
    "No objects found." is valid output (no trunk configured)."""
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
# Parsing `pjsip show registrations` (unchanged from the original)
# ---------------------------------------------------------------------------

def parse_pjsip_registrations(output: str) -> List[Dict[str, str]]:
    """Parse the output of `asterisk -rx "pjsip show registrations"`.

    Typical format:
        <Registration/ServerURI......> <Auth.......> <Status>
        ========================================================================
        reg-trunk1/sip:user@host auth-t1 Registered
        reg-trunk2/sip:user@host2 auth-t2 Rejected
        2 registrations.

    Returns a list of dicts with keys: name, server, status"""
    trunks: List[Dict[str, str]] = []

    for line in output.splitlines():
        stripped = line.strip()

        # Skip empty lines, separators (===), header (<...>)
        if not stripped:
            continue
        if stripped.startswith("=") or stripped.startswith("<"):
            continue
        # Skip summary line "N registrations."
        if re.match(r"^\d+\s+registration", stripped, re.IGNORECASE):
            continue
        # Skip "No registrations currently exist."
        if "no registrations" in stripped.lower():
            continue

        # Look for PJSIP status in the line
        m = STATUS_RE.search(stripped)
        if not m:
            continue

        status = re.sub(r"\s+", " ", m.group(1)).strip()

        # Column 1: the first part (separated by 2+ spaces)
        parts = re.split(r"\s{2,}", stripped)
        if not parts:
            continue

        reg_uri = parts[0].strip()
        reg_name = reg_uri.split("/")[0] if "/" in reg_uri else reg_uri
        server_uri = reg_uri.split("/", 1)[1] if "/" in reg_uri else ""

        trunks.append({
            "name": reg_name,
            "server": server_uri,
            "status": status,
        })

    return trunks


# ---------------------------------------------------------------------------
# CheckMK state helpers
# ---------------------------------------------------------------------------

def get_state(status: str) -> int:
    """Returns CheckMK status for a PJSIP status (default: 1 WARN for unknown)."""
    return STATE_MAP.get(status, 1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    containers = find_nethvoice_containers()
    if not containers:
        print(
            f"2 {SERVICE_SUMMARY} - CRITICAL: Asterisk/FreePBX container not found "
            f"(NethVoice installed? container running?)"
        )
        return 0

    all_trunks: List[Dict[str, str]] = []
    modules_checked: List[str] = []

    for module, container in containers:
        raw = run_asterisk_cmd(module, container, "pjsip show registrations outbound")
        if raw is None:
            continue
        trunks = parse_pjsip_registrations(raw)
        for t in trunks:
            t["module"] = module
        all_trunks.extend(trunks)
        modules_checked.append(module)

    modules_str = ",".join(modules_checked) if modules_checked else "none"

    if not all_trunks:
        print(
            f"1 {SERVICE_SUMMARY} - WARNING: no PJSIP outbound trunk configured "
            f"| modules={modules_str}"
        )
        return 0

    overall_state = 0
    registered_count = 0

    for trunk in all_trunks:
        state = get_state(trunk["status"])
        overall_state = max(overall_state, state)
        if state == 0:
            registered_count += 1

        svc_name = f"{SERVICE_PREFIX}.{sanitize_name(trunk['name'])}"

        # Shortened server URI: domain[:port] without sip:/sips:
        server = trunk["server"]
        server_clean = re.sub(r"^sips?:", "", server)
        server_clean = server_clean.split("@")[-1]
        server_clean = server_clean.split(";")[0].strip()
        mod = trunk.get("module", "")

        # Perfdata must be the single whitespace-free 3rd field (see the original):
        # "registered" is a 0/1 gauge so the CheckMK graph shows when the trunk went down/up.
        perfdata = f"registered={1 if state == 0 else 0};;;0;1"
        print(f"{state} {svc_name} {perfdata} - {trunk['status']} | server={server_clean} module={mod}")

    total = len(all_trunks)
    not_ok = total - registered_count
    if overall_state == 0:
        summary_msg = f"OK: all trunks registered ({registered_count}/{total})"
    elif overall_state == 1:
        summary_msg = f"WARNING: {registered_count}/{total} registered, {not_ok} with issues"
    else:
        summary_msg = f"CRITICAL: {registered_count}/{total} registered, {not_ok} with issues"

    summary_perfdata = f"registered_trunks={registered_count};;;0;{total}|total_trunks={total}"
    print(
        f"{overall_state} {SERVICE_SUMMARY} {summary_perfdata} - {summary_msg} "
        f"| modules={modules_str}"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
