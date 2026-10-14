#!/usr/bin/env python3
"""check_ns8_samba_password_expiry_api.py - CheckMK Local Check for AD password expiry, API only

Built 2026-10-12 from one real Ydea ticket found reading the last ~5 weeks of
tickets: a user's AD password was expiring, the self-service reset link in the
notification email was broken, and the ticket had to be handled manually
("il dominio risulta ad.confidicoopmarche.it ma non è un utente amministratore...
pensavo di cambiare manualmente la password da ns8"). Nothing today warns BEFORE
that point - this check catches an expiring password early enough to renew it
the normal way, instead of only after the self-service flow has already failed
for the user.

Runs one `ldbsearch` query (fast, see below) inside the samba1 domain controller
container via the module's own podman REST API socket - same exec pattern as
check_ns8_services_api.py. No subprocess, no SSH, and no per-user `samba-tool
user show` loop (tried first, works but is one exec call per user - `ldbsearch`
returns every account's sAMAccountName/pwdLastSet/userAccountControl in a single
call, the only approach that scales to a real domain with hundreds of users).
Also reads the domain's Maximum password age via `samba-tool domain
passwordsettings show` (one more exec call).

Excludes, same as Windows' own "net user" / AD Users and Computers would:
- disabled accounts (userAccountControl bit 0x2) - krbtgt and Guest here
- computer/machine accounts (sAMAccountName ending in "$") - DC1$ here
- accounts with "password never expires" set (bit 0x10000) - note PROTOTYPE
  CAVEAT below: every single human/service account on this lab node has this
  bit set (marzio, luca, ldapservice, Administrator), so there is currently
  NOTHING this check can ever flag here - it has never actually been exercised
  against a real expiring password. The FILETIME math and the domain-policy
  read are both verified correct against live data; only the "someone is
  actually approaching expiry" branch is unverified. Check again on a real
  customer domain with normal (expiring) password policy.

pwdLastSet is a Windows FILETIME (100 ns ticks since 1601-01-01 UTC); converted
to Unix time with the standard EPOCH_DELTA offset.

Checks:
- AD.PasswordExpiry: WARN if a user's password expires within 14 days, CRIT if
  within 3 days or already expired; otherwise OK with the count of accounts
  that do expire (so "0 accounts ever expire" is visibly different from
  "12 accounts, all healthy").

Piggybacked to NS8-RL98-SAMBA (new host - samba1 had no dedicated host before
this).

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
from typing import Dict, List, Optional, Tuple

VERSION = "1.0.0"
NODE_AGENT_ENV = "/var/lib/nethserver/node/state/agent.env"
NS8_API = os.environ.get("NS8_API", "http://127.0.0.1:9311/api")
TOKEN_FILE = os.environ.get("NS8_TOKEN_FILE", "/root/.ns8-token-ro")
PODMAN = "/v5.0.0/libpod"

WARN_DAYS = 14
CRIT_DAYS = 3
ACCOUNTDISABLE = 0x2
DONT_EXPIRE_PASSWORD = 0x10000
FILETIME_EPOCH_DELTA = 11644473600  # seconds between 1601-01-01 and 1970-01-01


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


def parse_ldif_records(text: str) -> List[Dict[str, str]]:
    """Minimal LDIF-style parser for ldbsearch output: blank-line-separated
    records of 'attr: value' lines (comment lines starting with '#' skipped)."""
    records: List[Dict[str, str]] = []
    current: Dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            if current:
                records.append(current)
                current = {}
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            current[key.strip()] = value.strip()
    if current:
        records.append(current)
    return records


def filetime_to_unix(value: str) -> Optional[float]:
    try:
        ft = int(value)
    except (TypeError, ValueError):
        return None
    if ft <= 0:
        return None
    return ft / 10_000_000.0 - FILETIME_EPOCH_DELTA


def main() -> int:
    instances = get_samba_instances()
    if not instances:
        return 0

    for instance in instances:
        error, sock_path = podman_socket(instance)
        if error:
            print(f"3 AD.PasswordExpiry - UNKNOWN: {error}")
            continue

        code, pol_out = exec_in_container(sock_path, "samba-dc", ["samba-tool", "domain", "passwordsettings", "show"])
        max_age_days = None
        if code == 0:
            m = re.search(r"Maximum password age \(days\):\s*(\d+)", pol_out)
            if m:
                max_age_days = int(m.group(1))
        if not max_age_days:
            print("0 AD.PasswordExpiry - domain policy has no maximum password age (passwords never expire)")
            continue

        code, out = exec_in_container(sock_path, "samba-dc", [
            "ldbsearch", "-H", "/var/lib/samba/private/sam.ldb",
            "(objectClass=user)", "sAMAccountName", "pwdLastSet", "userAccountControl"])
        if code != 0:
            print(f"3 AD.PasswordExpiry - UNKNOWN: ldbsearch failed (exit {code})")
            continue

        now = time.time()
        expiring_count = 0
        worst_state, worst_notes = 0, []
        for rec in parse_ldif_records(out):
            name = rec.get("sAMAccountName", "")
            if not name or name.endswith("$"):
                continue  # computer/machine account
            try:
                uac = int(rec.get("userAccountControl", "0"))
            except ValueError:
                continue
            if uac & ACCOUNTDISABLE or uac & DONT_EXPIRE_PASSWORD:
                continue
            last_set = filetime_to_unix(rec.get("pwdLastSet", "0"))
            if last_set is None:
                continue
            expiring_count += 1
            days_left = (last_set + max_age_days * 86400 - now) / 86400.0
            if days_left <= CRIT_DAYS:
                worst_state = 2
                worst_notes.append(f"{name} ({days_left:.0f}d)" if days_left >= 0 else f"{name} (SCADUTA da {-days_left:.0f}g)")
            elif days_left <= WARN_DAYS:
                worst_state = max(worst_state, 1)
                worst_notes.append(f"{name} ({days_left:.0f}d)")

        if worst_notes:
            print(f"{worst_state} AD.PasswordExpiry accounts_expiring={expiring_count};;;0; - "
                  f"{len(worst_notes)}/{expiring_count} account(s) close to expiry: {', '.join(worst_notes)}")
        else:
            print(f"0 AD.PasswordExpiry accounts_expiring={expiring_count};;;0; - "
                  f"no account within {WARN_DAYS} days of password expiry ({expiring_count} account(s) subject to expiry)")
    return 0


if __name__ == "__main__":
    # Piggyback to NS8-RL98-SAMBA (new host; see memory ns8_rl98 local check reorganisation, 2026-10-12)
    print("<<<<NS8-RL98-SAMBA>>>>")
    print("<<<local:sep(0)>>>")
    _rc = main()
    print("<<<<>>>>")
    sys.exit(_rc)
