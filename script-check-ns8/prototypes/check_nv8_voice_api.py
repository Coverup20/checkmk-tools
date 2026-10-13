#!/usr/bin/env python3
"""check_nv8_voice_api.py - NethVoice (NS8) monitoring for CheckMK: extensions, trunks, NethCTI and log size. REST API only (PROTOTYPE)

CheckMK local check, to run ON the NS8 node. No subprocess. Everything goes through REST:
- NS8 API (NS8_API, default http://127.0.0.1:9311/api), logged in with NS8_USER / NS8_PASSWORD_FILE:
  module list, the NethCTI / NethVoice host names (get-configuration) and the node FQDN;
- the module's own podman REST API socket (/run/user/<uid>/podman/podman.sock, needs
  `systemctl --user enable --now podman.socket` in the module): container state, uptime, health, writable-layer
  size, and exec of `asterisk -rx ...` / `find` inside the freepbx container;
- NethCTI over HTTPS through the node's Traefik (connect to 127.0.0.1:443 with SNI/Host = the NethCTI host);
- Grafana -> Loki through the same Traefik, for the volume of log lines each container wrote.

It replaces check_nv8_status_extensions_api.py and check_nv8_status_trunk_api.py (same service names, so the
CheckMK history is kept; remove the two old scripts when this one is installed).

Services (piggybacked to NS8_PIGGYBACK_HOST, default NS8-RL98-NETHVOICE):
- NV8.Status.Extensions     registered / unregistered extensions. WARN >= EXT_WARN_PCT %, CRIT >= EXT_CRIT_PCT %.
- NV8.Status.Extension.<n>  one service per extension: OK when registered, CRIT when not (always present, so it does
                            not vanish when the phone registers again).
- NV8.Status.Trunks         outbound trunks registered. Worst trunk state wins.
- NV8.Status.Trunk.<name>   one service per trunk (Registered OK; Not Registered/Trying WARN; Rejected/Failed/... CRIT).
- NV8.CTI.Status            nethcti-server, nethcti-middleware, nethcti-ui: container running and healthy, not just
                            restarted (WARN under CTI_RECENT_RESTART_MIN minutes), and answering over HTTPS
                            (UI 2xx/3xx, webrest 200/401/403, middleware anything below 500 except 404).
- NV8.Logs.Size             Asterisk log files (/var/log/asterisk inside freepbx) against LOG_WARN_MB / LOG_CRIT_MB,
                            size of every container's writable layer (where logs written inside a container end up)
                            against LAYER_WARN_MB / LAYER_CRIT_MB, and the volume of journal lines written by each
                            container in the last JOURNAL_HOURS hours against JOURNAL_WARN_MB / JOURNAL_CRIT_MB.

Known limits:
- container logs go to journald: Podman does not expose their size, so the check measures how much each container
  logged in the last day through Loki (bytes of the log lines, JSON wrapper included), not the size on disk;
- a stopped NethVoice module is reported as CRITICAL ("no NethVoice module found"), like the old checks;
- calls, queues and CTI sessions are not covered.

Version: 0.1.0"""

import base64
import http.client
import json
import os
import pwd
import re
import socket
import ssl
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

VERSION = "0.1.0"
NS8_API = os.environ.get("NS8_API", "http://127.0.0.1:9311/api")
NS8_USER = os.environ.get("NS8_USER", "claude-rw")
NS8_PASSWORD_FILE = os.environ.get("NS8_PASSWORD_FILE", "/root/.ns8-rw-pass")
NODE_FQDN = os.environ.get("NS8_NODE_FQDN", "")
PIGGYBACK_HOST = os.environ.get("NS8_PIGGYBACK_HOST", "NS8-RL98-NETHVOICE")
NODE_AGENT_ENV = "/var/lib/nethserver/node/state/agent.env"
PODMAN = "/v5.0.0/libpod"
CTI_CONTAINERS = ("nethcti-server", "nethcti-middleware", "nethcti-ui")
AST_LOG_DIR = "/var/log/asterisk"


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


EXT_WARN_PCT, EXT_CRIT_PCT = env_int("EXT_WARN_PCT", 10), env_int("EXT_CRIT_PCT", 30)
LOG_WARN_MB, LOG_CRIT_MB = env_int("LOG_WARN_MB", 500), env_int("LOG_CRIT_MB", 1024)
LAYER_WARN_MB, LAYER_CRIT_MB = env_int("LAYER_WARN_MB", 2048), env_int("LAYER_CRIT_MB", 5120)
JOURNAL_WARN_MB, JOURNAL_CRIT_MB = env_int("JOURNAL_WARN_MB", 200), env_int("JOURNAL_CRIT_MB", 1024)
JOURNAL_HOURS = env_int("JOURNAL_HOURS", 24)
CTI_RECENT_RESTART_MIN = env_int("CTI_RECENT_RESTART_MIN", 10)
SVC_EXT, SVC_EXT_ONE = "NV8.Status.Extensions", "NV8.Status.Extension"
SVC_TRUNKS, SVC_TRUNK_ONE = "NV8.Status.Trunks", "NV8.Status.Trunk"
SVC_CTI, SVC_LOGS = "NV8.CTI.Status", "NV8.Logs.Size"
SUMMARY_SERVICES = [SVC_EXT, SVC_TRUNKS, SVC_CTI, SVC_LOGS]
MB = 1024 * 1024
CACHE_FILE = os.environ.get("NV8_CACHE_FILE", "/var/lib/nv8-voice-cache.json")
CACHE_TTL = env_int("NV8_CACHE_TTL", 3600)
LOGIN_TRIES = 3

STATE_WORD = {0: "OK", 1: "WARN", 2: "CRIT", 3: "UNKNOWN"}

# PJSIP registration state -> CheckMK state
TRUNK_STATE = {"Registered": 0, "Not Registered": 1, "Trying": 1, "No Auth": 2, "Rejected": 2, "Failed": 2, "Stopped": 2, "Unregistered": 2}
TRUNK_STATUS_RE = re.compile(r"\b(Not\s+Registered|No\s+Auth|Registered|Trying|Rejected|Failed|Stopped|Unregistered)\b", re.IGNORECASE)
REGISTERED_STATES = {"not in use", "in use", "ringing", "ring", "busy", "on hold"}
# "  Endpoint:  200/200              Unavailable   0 of inf"
ENDPOINT_RE = re.compile(r"^\s+Endpoint:\s+(\S+)\s+(.*?)\s+\d+\s+of\s+", re.IGNORECASE)


# ---------------------------------------------------------------- helpers

def sanitize(name, strip_reg=False, fallback="x"):
    name = name.split("/")[0] if not strip_reg else name
    if strip_reg:
        name = re.sub(r"^reg[-_]", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[^a-zA-Z0-9]", ".", name)
    name = re.sub(r"\.{2,}", ".", name)
    return name.strip(".") or fallback


def state_for(value, warn, crit):
    return 2 if value >= crit else 1 if value >= warn else 0


def line(state, name, text, perf="-"):
    return "%d %s %s %s: %s" % (state, name, perf or "-", STATE_WORD[state], text.replace("\n", " "))


def human(nbytes):
    if nbytes >= 1024 ** 3:
        return "%.1f GB" % (nbytes / 1024.0 ** 3)
    if nbytes >= MB:
        return "%.1f MB" % (nbytes / float(MB))
    return "%d KB" % (nbytes // 1024)


def emit_local(text):
    print("<<<<%s>>>>" % PIGGYBACK_HOST)
    print("<<<local:sep(0)>>>")
    print(text)
    print("<<<<>>>>")


# ---------------------------------------------------------------- NS8 REST API

class Api(object):
    def __init__(self, base=NS8_API):
        self.base = base
        self.token = ""

    def _req(self, method, path, body=None):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(self.base + path, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, json.loads(r.read().decode("utf-8", "replace") or "{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode("utf-8", "replace") or "{}")
            except ValueError:
                return e.code, {}
        except (urllib.error.URLError, OSError, ValueError):
            return 0, {}

    def login(self, user, password):
        st, js = self._req("POST", "/login", json.dumps({"username": user, "password": password}).encode())
        data = js.get("data")
        tok = data.get("token") if isinstance(data, dict) else js.get("token")
        if st == 200 and tok:
            self.token = tok
            return ""
        return "login failed (HTTP %s)" % st if st else "NS8 API unreachable at %s" % self.base

    def task(self, agent, action, data=None, timeout=20):
        """Run an action; returns (state, output) with state ok|denied|validation|timeout|error."""
        st, js = self._req("POST", "/%s/tasks" % agent, json.dumps({"action": action, "data": data, "parent": "", "extra": {}}).encode())
        if st in (401, 403):
            return "denied", None
        tid = (js.get("data") or {}).get("id") if isinstance(js.get("data"), dict) else None
        if not tid:
            return "error", None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            st, js = self._req("GET", "/%s/task/%s/status" % (agent, tid))
            if st == 200:
                d = js.get("data") or {}
                out = d.get("output")
                if isinstance(out, str):
                    try:
                        out = json.loads(out)
                    except ValueError:
                        pass
                ec = d.get("exit_code")
                return ("ok" if ec == 0 else "validation" if ec == 2 else "error"), out
            if st in (401, 403):
                return "denied", None
            time.sleep(0.25)  # 400 "redis: nil" = still running
        return "timeout", None


def local_node_id():
    try:
        with open(NODE_AGENT_ENV, encoding="utf-8") as fh:
            for ln in fh:
                if ln.startswith("AGENT_ID=node/"):
                    return ln.strip().split("/", 1)[1]
    except OSError:
        pass
    return ""


def nethvoice_modules(api):
    st, out = api.task("cluster", "list-installed-modules")
    if st != "ok" or not isinstance(out, dict):
        return None, st
    node_id = local_node_id()
    found = []
    for source, insts in out.items():
        if not source.rstrip("/").split(":")[0].endswith("/nethvoice"):  # the NethVoice image, not nethvoice-proxy
            continue
        for inst in insts:
            if node_id and str(inst.get("node")) != node_id:
                continue
            found.append(inst["id"])
    return sorted(found), "ok"


# ---------------------------------------------------------------- podman REST API

class UnixHTTP(http.client.HTTPConnection):
    def __init__(self, path, timeout=15):
        http.client.HTTPConnection.__init__(self, "localhost", timeout=timeout)
        self._path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._path)


def demux_stream(raw):
    """podman exec stream: 8-byte frame headers [type,0,0,0,size BE]; only stdout (type 1) is returned."""
    out, pos = b"", 0
    while pos + 8 <= len(raw):
        stype, size = raw[pos], struct.unpack(">I", raw[pos + 4:pos + 8])[0]
        if stype == 1:
            out += raw[pos + 8:pos + 8 + size]
        pos += 8 + size
    return out.decode("utf-8", errors="replace")


class Podman(object):
    def __init__(self, module):
        self.sock = ""
        try:
            path = "/run/user/%d/podman/podman.sock" % pwd.getpwnam(module).pw_uid
            self.sock = path if os.path.exists(path) else ""
        except KeyError:
            pass

    def call(self, method, path, body=None):
        conn = UnixHTTP(self.sock)
        try:
            payload = json.dumps(body).encode() if body is not None else None
            conn.request(method, PODMAN + path, body=payload, headers={"Content-Type": "application/json"} if payload else {})
            r = conn.getresponse()
            return r.status, r.read()
        finally:
            conn.close()

    def containers(self):
        """All containers of the module: {name: {state, status, started, rw}} or None on error."""
        try:
            st, raw = self.call("GET", "/containers/json?all=true&size=true")
            if st != 200:
                return None
            res = {}
            for c in json.loads(raw.decode()):
                size = c.get("Size") or {}
                res[c["Names"][0]] = {"state": c.get("State", ""), "status": c.get("Status", ""), "started": c.get("StartedAt") or 0,
                                      "rw": (size.get("rwSize") or size.get("RwSize") or 0) if isinstance(size, dict) else 0}
            return res
        except (OSError, ValueError, KeyError, http.client.HTTPException):
            return None

    def exec(self, container, cmd):
        """Run a command in a container; returns stdout, or None if the exec could not be run."""
        try:
            st, raw = self.call("POST", "/containers/%s/exec" % container, {"Cmd": cmd, "AttachStdout": True, "AttachStderr": True})
            if st not in (200, 201):
                return None
            eid = json.loads(raw.decode())["Id"]
            st, raw = self.call("POST", "/exec/%s/start" % eid, {"Detach": False, "Tty": False})
            return demux_stream(raw).strip() if st == 200 else None
        except (OSError, ValueError, KeyError, http.client.HTTPException):
            return None


# ---------------------------------------------------------------- HTTPS through Traefik, Grafana -> Loki

class LocalHttps(http.client.HTTPSConnection):
    """Connects to 127.0.0.1:443 but presents the given host name (SNI and Host), like a browser would."""

    def __init__(self, sni, timeout=10):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE  # self-signed certificate, local connection
        http.client.HTTPSConnection.__init__(self, "127.0.0.1", 443, context=ctx, timeout=timeout)
        self._sni = sni

    def connect(self):
        sock = socket.create_connection(("127.0.0.1", 443), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self._sni)


def http_status(host, path):
    """HTTP status code of https://host/path through the local Traefik, None if it did not answer."""
    c = LocalHttps(host)
    try:
        c.request("GET", path, headers={"Host": host, "User-Agent": "checkmk-nv8-voice"})
        r = c.getresponse()
        r.read(1024)
        return r.status
    except (OSError, ssl.SSLError, http.client.HTTPException):
        return None
    finally:
        c.close()


class Loki(object):
    def __init__(self, fqdn, user, password):
        self.fqdn = fqdn
        self.auth = "Basic " + base64.b64encode(("%s:%s" % (user, password)).encode()).decode()
        self.uid = None

    def _get(self, path):
        c = LocalHttps(self.fqdn, 30)
        try:
            c.request("GET", path, headers={"Host": self.fqdn, "Authorization": self.auth, "Accept": "application/json"})
            r = c.getresponse()
            return r.status, r.read().decode("utf-8", "replace")
        except (OSError, ssl.SSLError, http.client.HTTPException):
            return 0, ""
        finally:
            c.close()

    def open(self):
        st, raw = self._get("/grafana/api/datasources")
        if st != 200:
            return "Grafana answered HTTP %s" % st if st else "Grafana unreachable"
        try:
            self.uid = next((d["uid"] for d in json.loads(raw) if d.get("type") == "loki"), None)
        except (ValueError, KeyError):
            self.uid = None
        return "" if self.uid else "no Loki data source in Grafana"

    def bytes_per_container(self, module_id, hours):
        """Bytes of journal lines written by each container of a module in the last N hours: ({name: bytes}, error)."""
        q = 'sum by (CONTAINER_NAME) (bytes_over_time({module_id="%s"} | json CONTAINER_NAME="CONTAINER_NAME" [%dh]))' % (module_id, hours)
        st, raw = self._get("/grafana/api/datasources/proxy/uid/%s/loki/api/v1/query?query=%s&time=%d" % (self.uid, urllib.parse.quote(q), int(time.time())))
        if st != 200:
            return {}, "Loki answered HTTP %s" % st if st else "Loki unreachable"
        try:
            res = {}
            for s in json.loads(raw)["data"]["result"]:
                res[s["metric"].get("CONTAINER_NAME") or "module-units"] = float(s["value"][1])
            return res, ""
        except (ValueError, KeyError, TypeError):
            return {}, "unexpected Loki answer"


# ---------------------------------------------------------------- parsing and evaluation (pure)

def parse_endpoints(output):
    eps = []
    for ln in output.splitlines():
        m = ENDPOINT_RE.match(ln)
        if not m:
            continue
        raw_name, raw_state = m.group(1).strip(), m.group(2).strip()
        base = raw_name.split("/")[0]
        # NethVoice extensions are numbers; anything else is a trunk endpoint (e.g. CI-00) or a system endpoint
        if any(kw in base.lower() for kw in ("trunk", "reg-", "reg_", "sip:", "anonymous")) or not re.match(r"^[0-9]+$", base):
            continue
        eps.append({"name": base, "state": raw_state, "registered": raw_state.lower() in REGISTERED_STATES})
    return eps


def parse_registrations(output):
    trunks = []
    for ln in output.splitlines():
        s = ln.strip()
        if not s or s.startswith("=") or s.startswith("<") or re.match(r"^\d+\s+registration", s, re.I) or "no registrations" in s.lower():
            continue
        m = TRUNK_STATUS_RE.search(s)
        if not m:
            continue
        status = re.sub(r"\s+", " ", m.group(1)).strip()
        for k in TRUNK_STATE:  # normalise the case
            if k.lower() == status.lower():
                status = k
        uri = re.split(r"\s{2,}", s)[0].strip()
        name = uri.split("/")[0] if "/" in uri else uri
        server = uri.split("/", 1)[1] if "/" in uri else ""
        server = re.sub(r"^sips?:", "", server).split("@")[-1].split(";")[0].strip()
        trunks.append({"name": name, "server": server, "status": status})
    return trunks


def parse_find(output):
    """`find -printf '%s %p\\n'` output -> [(size, path)]."""
    files = []
    for ln in output.splitlines():
        m = re.match(r"^(\d+) (.+)$", ln.strip())
        if m:
            files.append((int(m.group(1)), m.group(2)))
    return files


def eval_extensions(eps, module_label=""):
    """-> (service lines list)"""
    total = len(eps)
    if not total:
        return [line(1, SVC_EXT, "no PJSIP extension found")]
    unreg = [e for e in eps if not e["registered"]]
    pct = len(unreg) * 100.0 / total
    state = state_for(pct, EXT_WARN_PCT, EXT_CRIT_PCT) if unreg else 0
    # one service per extension, always present (OK when registered): a service that only exists while the extension
    # is down would vanish every time the phone registers again
    out = [line(0 if e["registered"] else 2, "%s.%s" % (SVC_EXT_ONE, sanitize(e["name"], fallback="ext")), "extension %s is %s" % (e["name"], e["state"]),
                "registered=%d;;;0;1" % (1 if e["registered"] else 0)) for e in eps]
    txt = "%d/%d extensions registered, %d unregistered (%.0f%%)" % (total - len(unreg), total, len(unreg), pct)
    if unreg:
        txt += ": " + ", ".join(e["name"] for e in unreg[:10]) + (" ..." if len(unreg) > 10 else "")
    out.append(line(state, SVC_EXT, txt, "registered=%d;;;0;%d|unregistered=%d;;;0;%d|total=%d" % (total - len(unreg), total, len(unreg), total, total)))
    return out


def eval_trunks(trunks):
    if not trunks:
        return [line(1, SVC_TRUNKS, "no PJSIP outbound trunk configured")]
    out, worst, ok = [], 0, 0
    for t in trunks:
        st = TRUNK_STATE.get(t["status"], 1)
        worst = max(worst, st)
        ok += st == 0
        out.append(line(st, "%s.%s" % (SVC_TRUNK_ONE, sanitize(t["name"], strip_reg=True, fallback="trunk")),
                        "%s (server %s)" % (t["status"], t["server"] or "?"), "registered=%d;;;0;1" % (1 if st == 0 else 0)))
    txt = "all %d trunks registered" % len(trunks) if worst == 0 else "%d/%d trunks registered, %d with issues" % (ok, len(trunks), len(trunks) - ok)
    out.append(line(worst, SVC_TRUNKS, txt, "registered_trunks=%d;;;0;%d|total_trunks=%d" % (ok, len(trunks), len(trunks))))
    return out


def http_ok(kind, code):
    if code is None:
        return False
    if kind == "ui":
        return 200 <= code < 400
    if kind == "webrest":
        return code in (200, 401, 403)  # 401/403 = the NethCTI server is up and asking for a login
    return code < 500 and code != 404


def eval_cti(containers, probes, now):
    """containers: {name: {state,status,started}}; probes: {kind: code|None} or None if the host is unknown."""
    problems, warns, up, uptimes = [], [], 0, []
    for name in CTI_CONTAINERS:
        c = containers.get(name)
        if not c:
            problems.append("%s is not running (container absent)" % name)
        elif c["state"] != "running":
            problems.append("%s is %s" % (name, c["state"] or "not running"))
        elif "unhealthy" in c["status"]:
            problems.append("%s unhealthy" % name)
        else:
            up += 1
            if "starting" in c["status"]:
                warns.append("%s still starting" % name)
            if c["started"]:
                mins = max(0, (now - c["started"]) / 60.0)
                uptimes.append(mins)
                if mins < CTI_RECENT_RESTART_MIN:
                    warns.append("%s restarted %d min ago" % (name, mins))
    http_up = 0
    if probes is not None:
        for kind, label in (("ui", "NethCTI UI"), ("webrest", "NethCTI server (webrest)"), ("middleware", "NethCTI middleware")):
            code = probes.get(kind)
            if http_ok(kind, code):
                http_up += 1
            else:
                problems.append("%s does not answer over HTTPS (%s)" % (label, "no answer" if code is None else "HTTP %d" % code))
    state = 2 if problems else 1 if warns else 0
    txt = "%d/%d NethCTI containers up" % (up, len(CTI_CONTAINERS))
    txt += ", HTTPS %d/3 answering" % http_up if probes is not None else ", HTTPS probe skipped (NethCTI host unknown)"
    if problems or warns:
        txt += ": " + "; ".join(problems + warns)
    perf = "cti_containers_up=%d;;;0;%d|cti_https_ok=%d;;;0;3|cti_min_uptime_min=%d;;;0;" % (up, len(CTI_CONTAINERS), http_up, min(uptimes) if uptimes else 0)
    return state, txt, perf


def eval_logs(ast_files, journal, layers):
    """ast_files [(size,path)] or None; journal {container: bytes} or None; layers {container: bytes} or None."""
    parts, state, perf = [], 0, []
    if ast_files is None:
        parts.append("Asterisk log files unavailable")
    else:
        total = sum(s for s, _ in ast_files)
        big = max(ast_files) if ast_files else (0, "")
        st = state_for(total / float(MB), LOG_WARN_MB, LOG_CRIT_MB)
        state = max(state, st)
        parts.append("Asterisk logs %s in %d files%s%s" % (human(total), len(ast_files), (", largest %s %s" % (os.path.basename(big[1]), human(big[0]))) if big[0] else "",
                                                           " [%s]" % STATE_WORD[st] if st else ""))
        perf += ["asterisk_log_bytes=%d;%d;%d;0;" % (total, LOG_WARN_MB * MB, LOG_CRIT_MB * MB), "asterisk_largest_file_bytes=%d;;;0;" % big[0]]
    if layers is None:
        parts.append("container layer sizes unavailable")
    elif layers:
        name, size = max(layers.items(), key=lambda kv: kv[1])
        st = state_for(size / float(MB), LAYER_WARN_MB, LAYER_CRIT_MB)
        state = max(state, st)
        parts.append("largest container layer %s (%s)%s" % (human(size), name, " [%s]" % STATE_WORD[st] if st else ""))
        perf.append("container_layer_max_bytes=%d;%d;%d;0;" % (size, LAYER_WARN_MB * MB, LAYER_CRIT_MB * MB))
    if journal is None:
        parts.append("journal volume unavailable")
    elif journal:
        name, size = max(journal.items(), key=lambda kv: kv[1])
        st = state_for(size / float(MB), JOURNAL_WARN_MB, JOURNAL_CRIT_MB)
        state = max(state, st)
        parts.append("journal in last %dh: %s total, busiest %s (%s)%s" % (JOURNAL_HOURS, human(sum(journal.values())), name, human(size), " [%s]" % STATE_WORD[st] if st else ""))
        perf += ["journal_total_bytes=%d;;;0;" % sum(journal.values()), "journal_max_container_bytes=%d;%d;%d;0;" % (size, JOURNAL_WARN_MB * MB, JOURNAL_CRIT_MB * MB)]
    if ast_files is None and layers is None and journal is None:
        return 3, "no log size information available", "-"
    return state, "; ".join(parts), "|".join(perf) if perf else "-"


# ---------------------------------------------------------------- self test

def self_test():
    fails, count = [], [0]

    def check(name, cond):
        count[0] += 1
        if not cond:
            fails.append(name)
    eps = parse_endpoints("  Endpoint:  200/200              Unavailable   0 of inf\n  Endpoint:  201/201   Not in use    0 of inf\n  Endpoint:  trunk1   Unavailable 0 of inf\n")
    check("endpoints parsed", [(e["name"], e["registered"]) for e in eps] == [("200", False), ("201", True)])
    check("trunk endpoint is not an extension", parse_endpoints("  Endpoint:  CI-00   Not in use    0 of inf\n") == [])
    ln = eval_extensions(eps)
    check("ext one crit + one ok + summary crit", ln[0].startswith("2 NV8.Status.Extension.200 ") and ln[1].startswith("0 NV8.Status.Extension.201 ") and ln[-1].startswith("2 NV8.Status.Extensions ") and len(ln) == 3)
    check("ext all ok", eval_extensions([{"name": "1", "state": "Not in use", "registered": True}])[-1].startswith("0 "))
    check("ext 1 of 20 unregistered is ok", eval_extensions([{"name": str(i), "state": "Not in use", "registered": i > 0} for i in range(20)])[-1].startswith("0 NV8.Status.Extensions "))
    check("ext none", eval_extensions([])[0].startswith("1 "))
    tr = parse_registrations("<Registration/ServerURI..>  <Auth..>  <Status>\n====\n reg-CI.00/sip:voip.x.it:5060  auth-1  Rejected (exp. 28s)\n reg-b/sip:u@h:5060  auth-2  Registered (exp. 100s)\n 2 registrations.\n")
    check("trunks parsed", [(t["name"], t["status"]) for t in tr] == [("reg-CI.00", "Rejected"), ("reg-b", "Registered")])
    tl = eval_trunks(tr)
    check("trunk service names", tl[0].startswith("2 NV8.Status.Trunk.CI.00 ") and tl[1].startswith("0 NV8.Status.Trunk.b ") and tl[2].startswith("2 NV8.Status.Trunks "))
    check("trunk none", eval_trunks([])[0].startswith("1 "))
    check("find parsed", parse_find("100 /var/log/asterisk/full\n2048 /var/log/asterisk/x y\n") == [(100, "/var/log/asterisk/full"), (2048, "/var/log/asterisk/x y")])
    now = 1_000_000
    up = {n: {"state": "running", "status": "Up 4 days", "started": now - 4 * 86400} for n in CTI_CONTAINERS}
    ok_probes = {"ui": 200, "webrest": 401, "middleware": 308}
    check("cti ok", eval_cti(up, ok_probes, now)[0] == 0)
    down = dict(up)
    down["nethcti-server"] = {"state": "exited", "status": "Exited", "started": 0}
    check("cti stopped crit", eval_cti(down, ok_probes, now)[0] == 2)
    check("cti 502 crit", eval_cti(up, {"ui": 200, "webrest": 502, "middleware": 308}, now)[0] == 2)
    check("cti no answer crit", eval_cti(up, {"ui": None, "webrest": 401, "middleware": 308}, now)[0] == 2)
    rec = dict(up)
    rec["nethcti-ui"] = {"state": "running", "status": "Up 2 minutes", "started": now - 120}
    check("cti recent restart warn", eval_cti(rec, ok_probes, now)[0] == 1)
    unh = dict(up)
    unh["nethcti-ui"] = {"state": "running", "status": "Up 2 days (unhealthy)", "started": now - 99999}
    check("cti unhealthy crit", eval_cti(unh, ok_probes, now)[0] == 2)
    check("cti missing crit", eval_cti({}, None, now)[0] == 2)
    check("cti no probes still ok", eval_cti(up, None, now)[0] == 0)
    check("logs ok", eval_logs([(2 * MB, "/var/log/asterisk/full")], {"freepbx": 6.0 * MB}, {"freepbx": 200.0 * MB})[0] == 0)
    check("logs ast warn", eval_logs([(600 * MB, "/var/log/asterisk/full")], {}, {})[0] == 1)
    check("logs ast crit", eval_logs([(2000 * MB, "/var/log/asterisk/full")], {}, {})[0] == 2)
    check("logs journal warn", eval_logs([], {"nethcti-server": 300.0 * MB}, {})[0] == 1)
    check("logs layer crit", eval_logs([], {}, {"freepbx": 6000.0 * MB})[0] == 2)
    check("logs all unavailable", eval_logs(None, None, None)[0] == 3)
    check("logs partial", eval_logs(None, {"a": 1.0}, None)[0] == 0)
    if fails:
        print("SELF-TEST FAILED: " + ", ".join(fails))
        return 1
    print("self-test ok (%d checks)" % count[0])
    return 0


# ---------------------------------------------------------------- main

def load_cache():
    try:
        with open(CACHE_FILE, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) and d.get("modules") else None
    except (OSError, ValueError):
        return None


def save_cache(d):
    try:
        tmp = CACHE_FILE + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(d, fh)
        os.replace(tmp, CACHE_FILE)
    except OSError:
        pass


def discover(password):
    """Ask the NS8 API for what rarely changes (NethVoice modules, their NethCTI host, the node FQDN).

    The NS8 API can be saturated by the other local checks (Redis 'max number of clients reached' -> HTTP 503),
    so the login is retried and the answer is cached by the caller. Returns (dict | None, error)."""
    api, err = Api(), ""
    for attempt in range(LOGIN_TRIES):
        err = api.login(NS8_USER, password)
        if not err:
            break
        time.sleep(2 * (attempt + 1))
    if err:
        return None, err
    mods, why = nethvoice_modules(api)
    if mods is None:
        return None, "list-installed-modules: %s" % why
    hosts = {}
    for mod in mods:
        st, cfg = api.task("module/%s" % mod, "get-configuration", None, timeout=15)
        hosts[mod] = cfg.get("nethcti_ui_host") or "" if st == "ok" and isinstance(cfg, dict) else ""
    fqdn = NODE_FQDN
    if not fqdn:
        s5, cl = api.task("cluster", "get-cluster-status")
        url = (cl.get("leader_url") or (cl.get("cluster") or {}).get("leader_url")) if s5 == "ok" and isinstance(cl, dict) else None
        fqdn = urllib.parse.urlparse(url).hostname if url else ""
    return {"ts": time.time(), "modules": mods, "cti_hosts": hosts, "fqdn": fqdn}, ""


def unknown_all(reason):
    return [line(3, n, reason) for n in SUMMARY_SERVICES]


def collect_module(mod, cti_host, loki, now):
    """Service lines of one module, as {service_key: (state, text, perf)} plus per-item lines."""
    pm = Podman(mod)
    if not pm.sock:
        return None, "podman socket of %s missing (systemctl --user enable --now podman.socket in the module)" % mod
    conts = pm.containers()
    if conts is None:
        return None, "podman API of %s did not answer" % mod
    res = {"items": []}
    running = {n: c for n, c in conts.items() if c["state"] == "running"}
    freepbx = next((n for n in running if "freepbx" in n.lower() or "asterisk" in n.lower()), None)
    if freepbx:
        out = pm.exec(freepbx, ["asterisk", "-rx", "pjsip show endpoints"])
        res["eps"] = parse_endpoints(out) if out else None
        out = pm.exec(freepbx, ["asterisk", "-rx", "pjsip show registrations outbound"])
        res["trunks"] = parse_registrations(out) if out is not None else None
        out = pm.exec(freepbx, ["find", AST_LOG_DIR, "-type", "f", "-printf", "%s %p\\n"])
        res["ast_files"] = parse_find(out) if out is not None else None
    else:
        res["eps"], res["trunks"], res["ast_files"] = None, None, None
    probes = None
    if cti_host:
        probes = {"ui": http_status(cti_host, "/"), "webrest": http_status(cti_host, "/webrest/"), "middleware": http_status(cti_host, "/middleware/")}
    res["cti"] = eval_cti(conts, probes, now)
    res["layers"] = {n: c["rw"] for n, c in conts.items()}
    if loki:
        res["journal"], res["journal_err"] = loki.bytes_per_container(mod, JOURNAL_HOURS)
    else:
        res["journal"], res["journal_err"] = None, "no Loki"
    return res, ""


def main():
    if "--self-test" in sys.argv:
        return self_test()
    try:
        with open(NS8_PASSWORD_FILE, encoding="utf-8") as fh:
            password = fh.read().strip()
    except OSError as exc:
        emit_local("\n".join(unknown_all("cannot read the password file %s: %s" % (NS8_PASSWORD_FILE, exc.strerror))))
        return 0
    cfg = load_cache()
    if not cfg or time.time() - cfg.get("ts", 0) > CACHE_TTL:
        fresh, err = discover(password)
        if fresh and fresh["modules"]:
            cfg = fresh
            save_cache(cfg)
        elif fresh:  # the API answered and there is no NethVoice module: do not hide that behind an old cache
            emit_local("\n".join(line(2, n, "no NethVoice module found on this NS8 node") for n in SUMMARY_SERVICES))
            return 0
        elif not cfg:
            emit_local("\n".join(unknown_all("NS8 API: %s" % err)))
            return 0
        # else: the API is saturated or down, keep working with the cached (older) discovery
    mods, fqdn = cfg["modules"], cfg.get("fqdn", "")
    loki = None
    if fqdn:
        loki = Loki(fqdn, NS8_USER, password)
        if loki.open():
            loki = None
    now = time.time()
    out, eps, trunks, ast_files, layers, journal = [], [], [], [], {}, {}
    cti, ast_ok, eps_ok, trunks_ok, journal_ok, errors = [], True, True, True, loki is not None, []
    for mod in mods:
        res, err = collect_module(mod, cfg.get("cti_hosts", {}).get(mod, ""), loki, now)
        if res is None:
            errors.append(err)
            continue
        if res["eps"] is None:
            eps_ok = False
        else:
            eps += res["eps"]
        if res["trunks"] is None:
            trunks_ok = False
        else:
            trunks += res["trunks"]
        if res["ast_files"] is None:
            ast_ok = False
        else:
            ast_files += res["ast_files"]
        layers.update(("%s/%s" % (mod, k) if len(mods) > 1 else k, v) for k, v in res["layers"].items())
        if res["journal_err"] or res["journal"] is None:
            journal_ok = False
        else:
            journal.update(("%s/%s" % (mod, k) if len(mods) > 1 else k, v) for k, v in res["journal"].items())
        cti.append((mod, res["cti"]))
    if errors and not cti:
        emit_local("\n".join(unknown_all("; ".join(errors))))
        return 0
    out += eval_extensions(eps) if eps_ok else [line(3, SVC_EXT, "cannot read the Asterisk endpoints (freepbx container not running or exec failed)")]
    out += eval_trunks(trunks) if trunks_ok else [line(3, SVC_TRUNKS, "cannot read the Asterisk registrations (freepbx container not running or exec failed)")]
    worst = max(c[1][0] for c in cti)
    out.append(line(worst, SVC_CTI, " ; ".join(("%s: %s" % (m, c[1]) if len(cti) > 1 else c[1]) for m, c in cti) + ((" ; " + "; ".join(errors)) if errors else ""),
                    cti[0][1][2] if len(cti) == 1 else "-"))
    s_, t_, p_ = eval_logs(ast_files if ast_ok else None, journal if journal_ok else None, layers or None)
    out.append(line(s_, SVC_LOGS, t_, p_))
    emit_local("\n".join(sorted(out, key=lambda x: x.split(" ", 2)[1])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
