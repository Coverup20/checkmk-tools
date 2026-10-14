#!/usr/bin/env python3
"""check_sos_api.py - CheckMK Local Check for SOS session, API only (PROTOTYPE)

Same CheckMK local-check output as check-sos.py, but instead of parsing
/var/log/messages for start-support-session / stop-support-session lines it
asks the node: NS8 REST API, action get-support-session on node/<id> (fields
active, session_id, expires_at). Token read from NS8_TOKEN_FILE (default
/root/.ns8-token-ro, a reader-role user is enough).

Differences from the original:
- the state comes from the node itself, not from log lines, so it does not
  depend on /var/log/messages existing or on log rotation
- if the node cannot be queried the result is UNKNOWN (3) with the reason; the
  original reported INACTIVE (0) when the log was missing or unreadable
- the action prints a harmless "support.env: No such file" error when no
  session exists (seen on NS8-RL98); only its JSON output is used
- only the ACTIVE case was never exercised: starting a support session opens a
  remote tunnel, so it was not provoked

Version: 0.1.0"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Optional, Tuple

VERSION = "0.1.0"
SERVICE = "SOS.Session"
NODE_AGENT_ENV = "/var/lib/nethserver/node/state/agent.env"
NS8_API = os.environ.get("NS8_API", "http://127.0.0.1:9311/api")
TOKEN_FILE = os.environ.get("NS8_TOKEN_FILE", "/root/.ns8-token-ro")


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


def get_session_status() -> Tuple[str, str, int, str]:
    """Support session status from the node.

    Returns (status, session_id, state, error): status ACTIVE/INACTIVE/UNKNOWN,
    state 0=OK (inactive), 1=WARNING (active), 3=UNKNOWN."""
    node_id = get_local_node_id()
    if not node_id:
        return "UNKNOWN", "N/A", 3, "no-node-id"
    out, err = ns8_task(f"node/{node_id}", "get-support-session")
    if err or not isinstance(out, dict):
        return "UNKNOWN", "N/A", 3, err or "bad-output"
    session_id = out.get("session_id") or "N/A"
    if out.get("active"):
        return "ACTIVE", str(session_id), 1, ""
    return "INACTIVE", str(session_id), 0, ""


def main() -> int:
    status, session_id, state, error = get_session_status()
    if error:
        print(f"{state} {SERVICE} - SOS Session: {status} ({error})")
    else:
        print(f"{state} {SERVICE} - SOS Session: {status} (ID: {session_id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
