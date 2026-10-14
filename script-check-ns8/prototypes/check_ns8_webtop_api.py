#!/usr/bin/env python3
"""check_ns8_webtop_api.py - CheckMK Local Check for WebTop NS8, API only (PROTOTYPE)

Same CheckMK local-check output as check_ns8_webtop.py, but no subprocess:
- WebTop instance detection: NS8 REST API (cluster/list-installed-modules),
  token read from NS8_TOKEN_FILE (default /root/.ns8-token-ro, a reader-role
  user is enough), instead of `runagent -l`
- the HTTP availability check is unchanged (it never used a CLI)

Version: 0.1.0"""

import json
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from typing import Optional, Tuple

VERSION = "0.1.0"
SERVICE = "Webtop5"
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


def get_domain_from_fqdn() -> Optional[str]:
    """Domain part of this host's FQDN (like `hostname -f`), None if there is none."""
    try:
        fqdn = socket.getfqdn()
        parts = fqdn.split('.', 1)
        if len(parts) > 1:
            return parts[1]
        return None
    except Exception:
        return None


def check_webtop_instances() -> Tuple[bool, str]:
    """True if a WebTop instance is installed on this node (REST API).

    Returns (found, error); error is '' unless the API could not be queried."""
    out, err = ns8_task("cluster", "list-installed-modules")
    if err or not isinstance(out, dict):
        return False, err or "api-error"
    node_id = get_local_node_id()
    for instances in out.values():
        for inst in instances:
            is_webtop = inst.get("module") == "webtop" or inst["id"].startswith("webtop")
            if is_webtop and (not node_id or str(inst.get("node")) == node_id):
                return True, ""
    return False, ""


def check_webtop_http(domain: str) -> Tuple[int, int]:
    """Check WebTop HTTP availability with SSL verification disabled.

    Returns (state, http_code): state 0=OK, 2=CRITICAL; http_code 0 on connection error."""
    url = f"https://webtop.{domain}/webtop/"
    try:
        # SSL context that doesn't verify certificates (like curl -k)
        ssl_context = ssl._create_unverified_context()
        req = urllib.request.Request(url, method='GET')
        with urllib.request.urlopen(req, timeout=10, context=ssl_context) as response:
            code = response.getcode()
            if code == 200:
                return 0, code
            return 2, code
    except urllib.error.HTTPError as e:
        return 2, e.code
    except Exception:
        return 2, 0


def main() -> int:
    domain = get_domain_from_fqdn()
    if not domain:
        print(f"1 {SERVICE} - No domain detected from hostname -f")
        return 0

    found, error = check_webtop_instances()
    if error:
        print(f"3 {SERVICE} - UNKNOWN: cannot list NS8 modules ({error})")
        return 0
    if not found:
        print(f"1 {SERVICE} - No WebTop instance found (module not installed)")
        return 0

    state, http_code = check_webtop_http(domain)
    url = f"https://webtop.{domain}/webtop/"

    if state == 0:
        print(f"0 {SERVICE} - WebTop responding at {url} (HTTP {http_code})")
    elif http_code == 0:
        print(f"2 {SERVICE} - WebTop NOT responding at {url} (Connection Error)")
    else:
        print(f"2 {SERVICE} - WebTop NOT responding at {url} (HTTP {http_code})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
