#!/usr/bin/env python3
"""monitor_podman_events_api.py - Daemon for monitoring Podman events, API only (PROTOTYPE)

Same job as monitor_podman_events.py (record container create/start/stop/remove
events, excluding redis containers, to a log file), but no `podman events`
subprocess: it follows the events stream of the podman REST API.

Why it differs: the original runs `podman events` as root, which only sees the
root podman. NS8 modules are rootless and each one has its own podman, so the
original does not see their containers. Here one thread per module follows
GET /v5.0.0/libpod/events?stream=true&filters={"type":["container"]} on that
module's socket (/run/user/<uid>/podman/podman.sock, needs `systemctl --user
enable --now podman.socket` in the module). The module list comes from the NS8
REST API (cluster/list-installed-modules, token read from NS8_TOKEN_FILE,
default /root/.ns8-token-ro) and is refreshed every REFRESH_SECONDS, so modules
installed later (or whose socket is enabled later) are picked up. A dropped
stream is reopened after RECONNECT_SECONDS.

Log line: "<now> - <event time> <action> <container> (<container id>)" - the
event time is ISO 8601 with the local offset, not Go's default time format.
The log path can be overridden with PODMAN_EVENTS_LOG (default
/var/log/podman_events.log).

This is a DAEMON (follows a stream forever) and must run as its own systemd
service (see ns8-podman-events.service), NEVER as a CheckMK local check: a
local check must return in a few seconds, and an earlier attempt to run this
script directly from /usr/lib/check_mk_agent/local/ left the agent hanging
and piling up processes on every polling cycle (found 2026-10-09 on NS8-RL98).
The companion script check_ns8_podman_events_local.py is the actual local
check: it only reads the STATE_FILE this daemon writes below, in well under a
second, and reports whether the daemon itself is alive and recent.

STATE_FILE (default /var/lib/ns8-podman-events/state.json, overridable with
NS8_EVENTS_STATE_FILE) is rewritten every HEARTBEAT_SECONDS regardless of
whether any event happened, plus right after logging an event, so its mtime
alone proves the daemon is not stuck. Content: updated_at, pid, modules
currently followed, count of logged events in the last EVENT_WINDOW_SECONDS,
and the last few (RECENT_EVENTS_KEPT) logged events for context.

Version: 0.2.0"""

import functools
import http.client
import json
import os
import pwd
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime
from typing import Dict, List, Optional, Tuple

VERSION = "0.2.0"
LOGFILE = os.environ.get("PODMAN_EVENTS_LOG", "/var/log/podman_events.log")
STATE_FILE = os.environ.get("NS8_EVENTS_STATE_FILE", "/var/lib/ns8-podman-events/state.json")
NODE_AGENT_ENV = "/var/lib/nethserver/node/state/agent.env"
NS8_API = os.environ.get("NS8_API", "http://127.0.0.1:9311/api")
TOKEN_FILE = os.environ.get("NS8_TOKEN_FILE", "/root/.ns8-token-ro")
REFRESH_SECONDS = 60
RECONNECT_SECONDS = 5
HEARTBEAT_SECONDS = 30
EVENT_WINDOW_SECONDS = 3600
RECENT_EVENTS_KEPT = 20
LOGGED_ACTIONS = ("create", "start", "stop", "remove")

# Daemon output is usually redirected to a file: flush every message
print = functools.partial(print, flush=True)

_log_lock = threading.Lock()
_state_lock = threading.Lock()
_stop = threading.Event()
_recent_events: "deque[tuple]" = deque(maxlen=RECENT_EVENTS_KEPT)  # (epoch, module, action, name)
_followed_modules: Dict[str, bool] = {}  # module -> currently connected to its socket


class UnixHTTPConnection(http.client.HTTPConnection):
    """HTTP over a unix socket, for the podman REST API."""

    def __init__(self, path: str, timeout: Optional[float] = None):
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


def get_instances() -> List[str]:
    """Module instances installed on this node (REST API)."""
    out, _ = ns8_task("cluster", "list-installed-modules")
    if not isinstance(out, dict):
        return []
    node_id = get_local_node_id()
    result = []
    for instances in out.values():
        for inst in instances:
            if not node_id or str(inst.get("node")) == node_id:
                result.append(inst["id"])
    return sorted(result)


def podman_socket(module: str) -> str:
    """Path of the module's podman API socket, '' if missing."""
    try:
        uid = pwd.getpwnam(module).pw_uid
    except KeyError:
        return ""
    path = f"/run/user/{uid}/podman/podman.sock"
    return path if os.path.exists(path) else ""


def should_log_event(action: str, name: str, container_id: str) -> bool:
    """Same filter as the original: only create/start/stop/remove, never redis containers."""
    if "redis" in f"{name} {container_id}".lower():
        return False
    return action in LOGGED_ACTIONS


def format_event(event: dict) -> Optional[Tuple[str, str, str]]:
    """(action, name, log line), or None if the event is not wanted."""
    actor = event.get("Actor") or {}
    attrs = actor.get("Attributes") or {}
    action = event.get("Action") or event.get("status") or ""
    name = attrs.get("name", "")
    container_id = actor.get("ID") or event.get("id") or ""
    if not should_log_event(action, name, container_id):
        return None
    when = datetime.fromtimestamp(event.get("time", time.time())).astimezone().isoformat(timespec="seconds")
    return action, name, f"{when} {action} {name} ({container_id})"


def write_log(module: str, line: str, log_fp) -> None:
    entry = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {line} [{module}]\n"
    with _log_lock:
        log_fp.write(entry)
        log_fp.flush()


def write_state() -> None:
    """Rewrites STATE_FILE with a snapshot: this is the ONLY thing the companion
    local check reads, so its mtime alone proves the daemon is alive. Written
    to a temp file and renamed (atomic), so the check never sees a half-written file."""
    now = time.time()
    with _state_lock:
        recent = [{"time": t, "module": m, "action": a, "name": n} for t, m, a, n in _recent_events]
        events_last_window = sum(1 for t, *_ in _recent_events if now - t <= EVENT_WINDOW_SECONDS)
        modules = sorted(_followed_modules.keys())
    state = {
        "updated_at": now, "pid": os.getpid(), "version": VERSION,
        "heartbeat_seconds": HEARTBEAT_SECONDS, "event_window_seconds": EVENT_WINDOW_SECONDS,
        "modules_followed": modules, "events_in_window": events_last_window, "recent_events": recent,
    }
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.replace(tmp, STATE_FILE)
    except OSError as exc:
        print(f"[WARN] could not write {STATE_FILE}: {exc}")


def heartbeat_loop() -> None:
    """Keeps STATE_FILE fresh even when no events happen at all."""
    while not _stop.is_set():
        write_state()
        _stop.wait(HEARTBEAT_SECONDS)


def follow_module(module: str, log_fp) -> None:
    """Follows the events stream of one module until the daemon is stopped."""
    filters = urllib.parse.quote(json.dumps({"type": ["container"]}))
    path = f"/v5.0.0/libpod/events?stream=true&filters={filters}"
    while not _stop.is_set():
        sock_path = podman_socket(module)
        if sock_path:
            conn = UnixHTTPConnection(sock_path)
            try:
                conn.request("GET", path)
                resp = conn.getresponse()
                _followed_modules[module] = True
                while not _stop.is_set():
                    raw = resp.readline()
                    if not raw:
                        break
                    try:
                        parsed = format_event(json.loads(raw.decode("utf-8", errors="replace")))
                    except ValueError:
                        continue
                    if parsed:
                        action, name, line = parsed
                        write_log(module, line, log_fp)
                        with _state_lock:
                            _recent_events.append((time.time(), module, action, name))
                        write_state()
            except (OSError, http.client.HTTPException):
                pass
            finally:
                _followed_modules[module] = False
                conn.close()
        _stop.wait(RECONNECT_SECONDS)


def run_podman_events_daemon() -> int:
    """Follow the podman events of every NS8 module and log the filtered ones."""
    log_dir = os.path.dirname(LOGFILE)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    threading.Thread(target=heartbeat_loop, daemon=True).start()
    threads: Dict[str, threading.Thread] = {}
    try:
        with open(LOGFILE, "a", encoding="utf-8") as log_fp:
            print(f"[INFO] Podman events daemon started (PID: {os.getpid()})")
            print(f"[INFO] Logging to: {LOGFILE}")
            print(f"[INFO] State for the CheckMK local check: {STATE_FILE}")
            while not _stop.is_set():
                for module in get_instances():
                    thread = threads.get(module)
                    if thread is None or not thread.is_alive():
                        thread = threading.Thread(target=follow_module, args=(module, log_fp), daemon=True)
                        thread.start()
                        threads[module] = thread
                        print(f"[INFO] Following events of module {module}")
                _stop.wait(REFRESH_SECONDS)
        return 0
    except KeyboardInterrupt:
        _stop.set()
        print("\n[INFO] Daemon stopped by user")
        return 0
    except PermissionError:
        print(f"[ERROR] Permission denied writing to {LOGFILE}")
        return 1
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")
        return 1


def main() -> int:
    print(f"monitor_podman_events_api.py v{VERSION}")
    print("Starting Podman events monitoring daemon...")
    print("Press Ctrl+C to stop\n")
    return run_podman_events_daemon()


if __name__ == "__main__":
    sys.exit(main())
