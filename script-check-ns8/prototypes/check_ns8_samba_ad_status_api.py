#!/usr/bin/env python3
"""check_ns8_samba_ad_status_api.py - CheckMK Local Check for Samba AD domain controller health, API only

Built 2026-10-12 alongside check_ns8_samba_password_expiry_api.py, after the
user pointed out that password expiry alone is not "the AD status" - a domain
controller can be structurally broken in ways that have nothing to do with any
one user's password. Same exec pattern (podman REST API socket on samba1, no
subprocess/SSH).

Checks three things a broken AD would show, deliberately NOT a dbcheck/FSMO
dump (slow / rarely the first symptom / needs an admin to interpret, not a
periodic alert):
- AD.Shares: `smbclient -L localhost -N` lists SYSVOL and NETLOGON - domain
  members cannot process Group Policy or logon scripts without them; CRIT if
  either is missing, or if smbclient itself cannot connect.
- AD.Replication: `samba-tool drs showrepl`, looking for failure markers
  (WERR_ error codes, "fail"/"error"/"unreachable") among inbound/outbound
  neighbours. CRIT if any neighbour shows a failure. PROTOTYPE CAVEAT: this
  lab has exactly one DC, so there are zero replication neighbours to ever
  fail - verified the command runs and parses cleanly, but the CRIT branch is
  unverified here. On a real multi-DC site this is the single most useful of
  the three checks (a DC silently falling out of replication is a classic,
  easy-to-miss failure mode).
- AD.Winbind: `wbinfo -p` (winbind ping) - a quick, standard binary signal
  that the winbind daemon backing NTLM/trust lookups is alive.

Piggybacked to NS8-RL98-SAMBA.

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
REQUIRED_SHARES = ("sysvol", "netlogon")
FAILURE_MARKERS = ("werr_", "fail", "error", "unreachable", "denied")


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


def get_samba_instances() -> List[str]:
    out, _ = cached_ns8_task("cluster", "list-installed-modules")
    if not isinstance(out, dict):
        return []
    node_id = get_local_node_id()
    result = []
    for instances in out.values():
        for inst in instances:
            is_samba = inst.get("module") == "samba" or inst["id"].startswith("samba")
            if is_samba and (not node_id or str(inst.get("node")) == node_id):
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


def demux_stream(raw: bytes, streams: Tuple[int, ...] = (1, 2)) -> str:
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


def check_shares(sock_path: str) -> None:
    code, out = exec_in_container(sock_path, "samba-dc", ["smbclient", "-L", "localhost", "-N"])
    if code != 0 or not out.strip():
        print(f"2 AD.Shares - CRITICAL: smbclient could not list shares (exit {code})")
        return
    low = out.lower()
    missing = [s for s in REQUIRED_SHARES if re.search(rf"\b{s}\b", low) is None]
    if missing:
        print(f"2 AD.Shares - CRITICAL: missing share(s): {', '.join(missing)} (domain members cannot process GPOs/logon scripts without them)")
    else:
        print("0 AD.Shares - sysvol and netlogon shares present")


def check_replication(sock_path: str) -> None:
    code, out = exec_in_container(sock_path, "samba-dc", ["samba-tool", "drs", "showrepl"])
    if code != 0:
        print(f"3 AD.Replication - UNKNOWN: samba-tool drs showrepl failed (exit {code})")
        return
    inbound = re.search(r"==== INBOUND NEIGHBORS ====(.*?)====", out, re.S)
    inbound_text = inbound.group(1) if inbound else ""
    neighbour_count = len(re.findall(r"^\S.*\\.*$", inbound_text, re.M))
    low = out.lower()
    failures = [m for m in FAILURE_MARKERS if m in low]
    if failures:
        print(f"2 AD.Replication - CRITICAL: failure indicator(s) found in drs showrepl: {', '.join(failures)}")
    elif neighbour_count == 0:
        print("0 AD.Replication - no replication partners (single DC)")
    else:
        print(f"0 AD.Replication - {neighbour_count} inbound partner(s), no failures reported")


def check_winbind(sock_path: str) -> None:
    code, out = exec_in_container(sock_path, "samba-dc", ["wbinfo", "-p"])
    if code == 0 and "succeeded" in out.lower():
        print("0 AD.Winbind - winbindd responding")
    else:
        print(f"2 AD.Winbind - CRITICAL: winbind ping failed (exit {code}): {out.strip()[:100]}")


def main() -> int:
    instances = get_samba_instances()
    if not instances:
        return 0
    for instance in instances:
        error, sock_path = podman_socket(instance)
        if error:
            for name in ("AD.Shares", "AD.Replication", "AD.Winbind"):
                print(f"3 {name} - UNKNOWN: {error}")
            continue
        check_shares(sock_path)
        check_replication(sock_path)
        check_winbind(sock_path)
    return 0


if __name__ == "__main__":
    # Piggyback to NS8-RL98-SAMBA (see memory ns8_rl98 local check reorganisation, 2026-10-12)
    print("<<<<NS8-RL98-SAMBA>>>>")
    print("<<<local:sep(0)>>>")
    _rc = main()
    print("<<<<>>>>")
    sys.exit(_rc)
