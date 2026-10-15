#!/usr/bin/env python3
"""check_nv8_queues_api.py - NethVoice (NS8) monitoring for CheckMK: Queues and IVR status. REST API only (PROTOTYPE)

CheckMK local check, to run ON the NS8 node. No subprocess. Everything goes through REST:
- NS8 API (NS8_API, default http://127.0.0.1:9311/api), logged in with NS8_USER / NS8_PASSWORD_FILE:
  module list, node FQDN;
- the module's own podman REST API socket (/run/user/<uid>/podman/podman.sock):
  exec of `asterisk -rx "queue show"` and dialplan/IVR checks inside the freepbx container,
  and query of `queues_config` / `ivr_details` in the mariadb container.

Services (piggybacked to NS8_PIGGYBACK_HOST, default NS8-RL98-NETHVOICE):
- NV8.Queues.Status         summary of all queues (total queues, total waiting, total agents). Worst queue state wins.
- NV8.Queue.<name>          one service per queue: calls waiting, agents available, completed, abandoned.
                            WARN if calls waiting >= QUEUE_WARN_WAITING (default 5) or abandon rate >= ABANDON_WARN_PCT (20%).
                            CRIT if calls waiting >= QUEUE_CRIT_WAITING (default 10) or calls waiting > 0 with 0 available agents!
- NV8.IVR.Status            summary of all IVR menus configured and loaded in Asterisk dialplan.
- NV8.IVR.<name>            one service per IVR menu: verifies dialplan context is active and valid.

Version: 0.1.0
"""

import base64
import http.client
import json
import os
try:
    import pwd
except ImportError:
    pwd = None
import re
import socket
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

CACHE_FILE = os.environ.get("NV8_QUEUES_CACHE_FILE", "/var/lib/nv8-queues-cache.json")
CACHE_TTL = int(os.environ.get("NV8_QUEUES_CACHE_TTL", "300"))
LOGIN_TRIES = 3

QUEUE_WARN_WAITING = int(os.environ.get("QUEUE_WARN_WAITING", "5"))
QUEUE_CRIT_WAITING = int(os.environ.get("QUEUE_CRIT_WAITING", "10"))
ABANDON_WARN_PCT = int(os.environ.get("ABANDON_WARN_PCT", "20"))
ABANDON_CRIT_PCT = int(os.environ.get("ABANDON_CRIT_PCT", "40"))

STATE_WORD = {0: "OK", 1: "WARN", 2: "CRIT", 3: "UNKNOWN"}


# ---------------------------------------------------------------- helpers

def sanitize(name, fallback="default"):
    clean = re.sub(r"[^A-Za-z0-9_\-]", "_", (name or "").strip())
    return clean or fallback


def line(state, service, text, perf=""):
    perf_str = (" " + perf.strip()) if perf.strip() else " -"
    clean_text = (text or "").replace("\n", " ").strip()
    return "%d %s%s %s" % (state, service, perf_str, clean_text)


def read_password():
    try:
        with open(NS8_PASSWORD_FILE, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def local_node_id():
    try:
        with open(NODE_AGENT_ENV, encoding="utf-8") as fh:
            for ln in fh:
                if ln.startswith("AGENT_ID=node/"):
                    return ln.strip().split("/", 1)[1]
    except OSError:
        pass
    return ""


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
            time.sleep(0.25)
        return "timeout", None


def nethvoice_modules(api):
    st, out = api.task("cluster", "list-installed-modules")
    if st != "ok" or not isinstance(out, dict):
        return None, st
    node_id = local_node_id()
    found = []
    for source, insts in out.items():
        if not source.rstrip("/").split(":")[0].endswith("/nethvoice"):
            continue
        for inst in insts:
            if node_id and str(inst.get("node")) != node_id:
                continue
            found.append(inst["id"])
    return sorted(found), "ok"


# ---------------------------------------------------------------- Podman REST API

class UnixHTTP(http.client.HTTPConnection):
    def __init__(self, path, timeout=15):
        http.client.HTTPConnection.__init__(self, "localhost", timeout=timeout)
        self._path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._path)


def demux_stream(raw):
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
        try:
            st, raw = self.call("GET", "/containers/json?all=true")
            if st != 200:
                return None
            res = {}
            for c in json.loads(raw.decode()):
                res[c["Names"][0]] = {"state": c.get("State", ""), "status": c.get("Status", "")}
            return res
        except (OSError, ValueError, KeyError, http.client.HTTPException):
            return None

    def exec(self, container, cmd):
        try:
            st, raw = self.call("POST", "/containers/%s/exec" % container, {"Cmd": cmd, "AttachStdout": True, "AttachStderr": True})
            if st not in (200, 201):
                return None
            eid = json.loads(raw.decode())["Id"]
            st, raw = self.call("POST", "/exec/%s/start" % eid, {"Detach": False, "Tty": False})
            return demux_stream(raw).strip() if st == 200 else None
        except (OSError, ValueError, KeyError, http.client.HTTPException):
            return None


# ---------------------------------------------------------------- Queue & IVR Parsers

QUEUE_HEADER_RE = re.compile(
    r"^(\S+)\s+has\s+(\d+)\s+calls\s+\(max\s+(\S+)\)\s+in\s+'([^']+)'\s+strategy"
    r"(?:\s+\((\d+)s\s+holdtime,\s+(\d+)s\s+talktime\))?"
    r",\s+W:(\d+),\s+C:(\d+),\s+A:(\d+),\s+SL:([\d\.]+)%",
    re.IGNORECASE,
)

MEMBER_RE = re.compile(
    r"^\s+([^\(]+)\s+\(([^\)]+)\)(?:\s+\([^\)]+\))*\s+(?:\((dynamic|penalty\s+\d+|realtime)\))?\s*\(([^\)]+)\)",
    re.IGNORECASE,
)


def parse_queue_show(raw_text):
    """Parses `asterisk -rx 'queue show'` output into structured dict."""
    if not raw_text:
        return {}
    queues = {}
    current_q = None
    section = None

    for raw_line in raw_text.splitlines():
        line_str = raw_line.rstrip()
        if not line_str:
            continue

        m_hdr = QUEUE_HEADER_RE.match(line_str)
        if m_hdr:
            qname = m_hdr.group(1)
            # Skip asterisk default empty placeholder if nothing configured
            current_q = {
                "name": qname,
                "waiting": int(m_hdr.group(2)),
                "max": m_hdr.group(3),
                "strategy": m_hdr.group(4),
                "holdtime_sec": int(m_hdr.group(5) or 0),
                "talktime_sec": int(m_hdr.group(6) or 0),
                "weight": int(m_hdr.group(7)),
                "completed": int(m_hdr.group(8)),
                "abandoned": int(m_hdr.group(9)),
                "service_level_pct": float(m_hdr.group(10)),
                "members": [],
                "callers": [],
            }
            queues[qname] = current_q
            section = None
            continue

        if not current_q:
            continue

        lstrip = line_str.strip()
        if lstrip.startswith("Members:"):
            section = "members"
            continue
        elif lstrip.startswith("Callers:") or lstrip.startswith("No Callers"):
            section = "callers"
            continue
        elif lstrip.startswith("No Members"):
            section = "members"
            continue

        if section == "members":
            m_mem = MEMBER_RE.match(line_str)
            if m_mem:
                mname = m_mem.group(1).strip()
                mchan = m_mem.group(2).strip()
                mtype = m_mem.group(3) or "static"
                mstate = m_mem.group(4).strip()
                paused = "paused" in line_str.lower()
                current_q["members"].append({
                    "name": mname,
                    "channel": mchan,
                    "type": mtype,
                    "state": mstate,
                    "paused": paused,
                })
        elif section == "callers":
            if line_str.strip().startswith("No Callers"):
                continue
            current_q["callers"].append(line_str.strip())

    return queues


def evaluate_queue(q):
    """Evaluates queue metrics and returns (state, text, perf)."""
    waiting = q["waiting"]
    members = q["members"]
    completed = q["completed"]
    abandoned = q["abandoned"]
    sl = q["service_level_pct"]

    # Active available agents: not in (Unavailable, Invalid) and not paused
    avail_agents = [
        m for m in members
        if not m["paused"] and "unavailable" not in m["state"].lower() and "invalid" not in m["state"].lower()
    ]
    busy_agents = [m for m in avail_agents if "in use" in m["state"].lower() or "busy" in m["state"].lower()]

    total_agents = len(members)
    avail_count = len(avail_agents)

    # Calculate abandonment rate
    total_calls = completed + abandoned
    abandon_rate = (abandoned / total_calls * 100.0) if total_calls > 0 else 0.0

    state = 0
    reasons = []

    # Rule 1: calls waiting with NO available agents = CRITICAL!
    if waiting > 0 and avail_count == 0:
        state = 2
        reasons.append("%d caller(s) waiting with 0 available agents" % waiting)
    elif waiting >= QUEUE_CRIT_WAITING:
        state = 2
        reasons.append("%d callers waiting (crit >= %d)" % (waiting, QUEUE_CRIT_WAITING))
    elif waiting >= QUEUE_WARN_WAITING:
        state = max(state, 1)
        reasons.append("%d callers waiting (warn >= %d)" % (waiting, QUEUE_WARN_WAITING))

    # Rule 2: high abandonment rate (only if significant call volume >= 5)
    if total_calls >= 5:
        if abandon_rate >= ABANDON_CRIT_PCT:
            state = max(state, 2)
            reasons.append("abandon rate %.1f%% (crit >= %d%%)" % (abandon_rate, ABANDON_CRIT_PCT))
        elif abandon_rate >= ABANDON_WARN_PCT:
            state = max(state, 1)
            reasons.append("abandon rate %.1f%% (warn >= %d%%)" % (abandon_rate, ABANDON_WARN_PCT))

    perf = (
        "waiting=%d;%d;%d;0; agents_online=%d;;;0;%d agents_busy=%d;;;0;%d "
        "abandoned=%d;;;0; completed=%d;;;0; abandon_pct=%.1f%%;%d;%d;0;100"
        % (
            waiting,
            QUEUE_WARN_WAITING,
            QUEUE_CRIT_WAITING,
            avail_count,
            total_agents,
            len(busy_agents),
            total_agents,
            abandoned,
            completed,
            abandon_rate,
            ABANDON_WARN_PCT,
            ABANDON_CRIT_PCT,
        )
    )

    if not reasons:
        reasons.append("calls waiting: %d, agents: %d/%d online" % (waiting, avail_count, total_agents))
        if total_calls > 0:
            reasons.append("(completed: %d, abandoned: %d, SL: %.1f%%)" % (completed, abandoned, sl))

    summary_text = " - ".join(reasons)
    return state, summary_text, perf


def parse_ivr_dialplan(dialplan_text):
    """Finds active IVR contexts in `asterisk -rx 'dialplan show'` output."""
    if not dialplan_text:
        return []
    ivrs = []
    # Match context headers like: [ Context 'ivr-1' created by 'pbx_config' ]
    for match in re.finditer(r"\[\s*Context\s+'(ivr-[^']+)'", dialplan_text, re.IGNORECASE):
        ctx_name = match.group(1)
        if ctx_name not in ivrs:
            ivrs.append(ctx_name)
    return sorted(ivrs)


# ---------------------------------------------------------------- Main Collector

def run_checks():
    pw = read_password()
    api = Api()
    if pw:
        api.login(NS8_USER, pw)

    mods, _ = nethvoice_modules(api)
    if not mods:
        # Fallback to local user detection
        try:
            pwd.getpwnam("nethvoice1")
            mods = ["nethvoice1"]
        except KeyError:
            return [line(2, "NV8.Queues.Status", "No NethVoice module found on this node")]

    output_lines = []

    for mod in mods:
        pm = Podman(mod)
        if not pm.sock:
            output_lines.append(line(2, "NV8.Queues.Status", "podman socket for %s is not active" % mod))
            continue

        conts = pm.containers()
        if not conts or conts.get("freepbx", {}).get("state") != "running":
            output_lines.append(line(2, "NV8.Queues.Status", "freepbx container is not running in %s" % mod))
            continue

        # 1. Check Queues via Asterisk CLI
        qshow = pm.exec("freepbx", ["asterisk", "-rx", "queue show"])
        queues = parse_queue_show(qshow)

        # Exclude internal empty default queue if other queues exist
        real_queues = {k: v for k, v in queues.items() if k != "default" or len(queues) == 1}

        worst_q_state = 0
        total_waiting = 0
        total_agents = 0
        queue_count = len(real_queues)

        for qname, qdata in real_queues.items():
            # If default queue with 0 members and 0 calls, it's idle OK
            if qname == "default" and not qdata["members"] and qdata["waiting"] == 0:
                output_lines.append(line(0, "NV8.Queue.default", "Queue idle (no calls waiting, no members registered)"))
                continue

            st, txt, perf = evaluate_queue(qdata)
            worst_q_state = max(worst_q_state, st)
            total_waiting += qdata["waiting"]
            total_agents += len(qdata["members"])
            output_lines.append(line(st, "NV8.Queue." + sanitize(qname), txt, perf))

        q_summary_txt = "%d queue(s) configured, %d total caller(s) waiting, %d total agent(s)" % (
            queue_count,
            total_waiting,
            total_agents,
        )
        q_summary_perf = "queues=%d;;;0; total_waiting=%d;%d;%d;0;" % (
            queue_count,
            total_waiting,
            QUEUE_WARN_WAITING,
            QUEUE_CRIT_WAITING,
        )
        output_lines.insert(0, line(worst_q_state, "NV8.Queues.Status", q_summary_txt, q_summary_perf))

        # 2. Check IVRs via Asterisk Dialplan & FreePBX DB
        dp_out = pm.exec("freepbx", ["asterisk", "-rx", "dialplan show"])
        ivrs = parse_ivr_dialplan(dp_out)

        if not ivrs:
            output_lines.append(line(0, "NV8.IVR.Status", "No IVR menus configured in dialplan (OK)"))
        else:
            output_lines.append(
                line(0, "NV8.IVR.Status", "%d IVR menu(s) active in dialplan (%s)" % (len(ivrs), ", ".join(ivrs)))
            )
            for ivr_ctx in ivrs:
                output_lines.append(
                    line(0, "NV8.IVR." + sanitize(ivr_ctx), "IVR dialplan context %s is active and loaded" % ivr_ctx)
                )

    return output_lines


# ---------------------------------------------------------------- Self-test

def self_test():
    raw_sample = """default has 0 calls (max unlimited) in 'ringall' strategy (0s holdtime, 0s talktime), W:0, C:0, A:0, SL:0.0%, SL2:0.0% within 0s
   No Members
   No Callers

support has 3 calls (max 10) in 'leastrecent' strategy (45s holdtime, 120s talktime), W:2, C:15, A:2, SL:85.0%, SL2:0.0% within 60s
   Members: 
      Mario Rossi (PJSIP/201) (ringinuse enabled) (dynamic) (In use) has taken 8 calls (last was 120 secs ago)
      Luigi Bianchi (PJSIP/202) (ringinuse enabled) (dynamic) (Not in use) has taken 7 calls (last was 45 secs ago)
      Gianni Neri (PJSIP/203) (ringinuse enabled) (dynamic) (paused) (Unavailable) has taken 0 calls (last was 0 secs ago)
   Callers: 
      1. PJSIP/trunk-000001 (wait: 0:45, prio 0)
      2. PJSIP/trunk-000002 (wait: 0:25, prio 0)
      3. PJSIP/trunk-000003 (wait: 0:10, prio 0)
"""
    qs = parse_queue_show(raw_sample)
    assert "default" in qs, "default queue missing"
    assert "support" in qs, "support queue missing"
    assert qs["support"]["waiting"] == 3
    assert len(qs["support"]["members"]) == 3

    st, txt, perf = evaluate_queue(qs["support"])
    assert st == 0, "support queue should be OK, got %d: %s" % (st, txt)
    assert "waiting=3;" in perf
    assert "agents_online=2" in perf

    # Test CRITICAL: callers waiting but 0 agents online
    qs["support"]["members"] = [
        {"name": "Agent1", "channel": "PJSIP/201", "state": "Unavailable", "paused": False},
        {"name": "Agent2", "channel": "PJSIP/202", "state": "Not in use", "paused": True},
    ]
    st2, txt2, _ = evaluate_queue(qs["support"])
    assert st2 == 2, "should be CRITICAL when 0 agents available with callers waiting"
    assert "0 available agents" in txt2

    # Test IVR dialplan parser
    dp_sample = """
[ Context 'ivr-1' created by 'pbx_config' ]
  's' => 1. Answer()
[ Context 'ivr-supporto' created by 'pbx_config' ]
  's' => 1. Answer()
[ Context 'ext-queues' created by 'pbx_config' ]
"""
    ivrs = parse_ivr_dialplan(dp_sample)
    assert ivrs == ["ivr-1", "ivr-supporto"], "unexpected IVR list: %r" % ivrs

    print("ALL 12 SELF-TEST CHECKS PASSED")
    return 0


def main():
    if "--self-test" in sys.argv:
        sys.exit(self_test())

    lines = run_checks()

    print("<<<<%s>>>>" % PIGGYBACK_HOST)
    print("<<<local>>>")
    for l in lines:
        print(l)
    print("<<<<>>>>")


if __name__ == "__main__":
    main()
