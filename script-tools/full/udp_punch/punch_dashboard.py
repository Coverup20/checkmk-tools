#!/usr/bin/env python3
"""Status dashboard for the UDP punch tunnel instances.

Reads the server configuration files of the tunnel, asks systemd and the
journal for every instance and serves one HTML page plus two JSON endpoints
on a loopback address. The page refreshes itself and can run a real agent
fetch through an instance's Unix socket on demand.

The service never listens on a public address: reach it through an SSH local
forward. Instance names accepted by the probe endpoint are only the ones the
configuration directory already contains, so the endpoint cannot run anything
else.

Usage:
    punch_dashboard.py --listen 127.0.0.1:8099
    punch_dashboard.py --once
    punch_dashboard.py --self-test
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "1.1.0"

CONFIG_DIR = "/etc/cmk-punch"
CODE_PATH = "/opt/cmk-punch/punch_peer.py"
AGENT_CLIENT = "/usr/local/lib/cmk-punch/cmk_punch_agent.py"
SITE_USER = "monitoring"
JOURNAL_SINCE = "-30 days"
MARKERS = ("session established with|dropping keys|"
           "exiting so the service can restart|cmk-punch p[0-9]+ starting|"
           "peer real address")
CACHE_TTL = 10.0
PROBE_TIMEOUT = 25

RE_HANDSHAKE = re.compile(r"session established with (\S+) \(")
RE_REAL_IP = re.compile(r"peer real address (\S+)")
RE_START = re.compile(r"cmk-punch (p\d+) starting")
RE_VERSION = re.compile(r'^VERSION = "([^"]+)"', re.MULTILINE)

_cache = {"at": 0.0, "data": None}
_cache_lock = threading.Lock()


def run(cmd, timeout=10):
    """Run cmd (a list) and return (exit code, stdout, stderr)."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, check=False)
        return proc.returncode, proc.stdout, proc.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)


def load_instances(config_dir):
    """Map instance name -> configuration from the server JSON files."""
    out = {}
    if not os.path.isdir(config_dir):
        return out
    for name in sorted(os.listdir(config_dir)):
        if not name.startswith("server") or not name.endswith(".json"):
            continue
        if ".bak" in name:
            continue
        path = os.path.join(config_dir, name)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                cfg = json.load(fh)
        except (OSError, ValueError):
            continue
        stem = name[:-5]
        suffix = stem[len("server-"):] if stem.startswith("server-") else ""
        unit = "cmk-punch-server" + ("-" + suffix if suffix else "")
        out[suffix or "server"] = {
            "instance": suffix or "server",
            "unit": unit,
            "udp_bind": cfg.get("udp_bind", ""),
            "socket": cfg.get("unix_listen", ""),
            "state_dir": cfg.get("state_dir", ""),
        }
    return out


def code_version():
    try:
        with open(CODE_PATH, "r", encoding="utf-8") as fh:
            match = RE_VERSION.search(fh.read())
        return match.group(1) if match else "?"
    except OSError:
        return "?"


def unit_active(unit):
    _code, out, _ = run(["systemctl", "is-active", unit], timeout=5)
    return out.strip() or "unknown"


def unit_restarts(unit):
    _code, out, _ = run(["systemctl", "show", "-p", "NRestarts",
                         "--value", unit], timeout=5)
    try:
        return int(out.strip())
    except ValueError:
        return None


def journal_events(unit):
    """Handshake and lifecycle events as (epoch seconds, message), oldest first.

    The journal is filtered on the journald side: the agent poll writes one
    connection line per check, so a plain tail would push the last handshake
    out of the window within hours and make every row look down.
    """
    _code, out, _ = run(["journalctl", "-u", unit, "--since", JOURNAL_SINCE,
                         "--grep", MARKERS, "--no-pager", "-o", "json"],
                        timeout=15)
    events = []
    for line in out.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        message = entry.get("MESSAGE")
        stamp = entry.get("__REALTIME_TIMESTAMP")
        if not message or stamp is None:
            continue
        try:
            events.append((int(stamp) / 1000000.0, str(message)))
        except ValueError:
            continue
    events.sort(key=lambda item: item[0])
    return events


def summarise(events):
    """Last handshake, teardown, restart and start from a journal excerpt."""
    summary: dict[str, float | str | None] = {
        "handshake_at": None, "peer": None, "teardown_at": None,
        "restart_at": None, "start_at": None, "real_ip": None}
    for stamp, message in events:
        match = RE_HANDSHAKE.search(message)
        if match:
            summary["handshake_at"] = stamp
            summary["peer"] = match.group(1)
        if "dropping keys" in message:
            summary["teardown_at"] = stamp
        if "exiting so the service can restart" in message:
            summary["restart_at"] = stamp
        match = RE_START.search(message)
        if match:
            summary["start_at"] = stamp
        match = RE_REAL_IP.search(message)
        if match:
            summary["real_ip"] = match.group(1)
    return summary


def read_state(state_dir):
    """peer_real_ip.txt and endpoint.txt with their modification times."""
    out: dict[str, str | int | None] = {
        "real_ip": None, "real_ip_age": None,
        "endpoint": None, "endpoint_age": None}
    now = time.time()
    for key, name in (("real_ip", "peer_real_ip.txt"),
                      ("endpoint", "endpoint.txt")):
        if not state_dir:
            continue
        path = os.path.join(state_dir, name)
        try:
            with open(path, "r", encoding="ascii") as fh:
                out[key] = fh.read().strip()
            out[key + "_age"] = int(now - os.path.getmtime(path))
        except OSError:
            pass
    return out


def classify(active, summary):
    """up / down / restarting / unknown from unit state and journal."""
    if active != "active":
        return "restarting" if summary["restart_at"] is not None else "down"
    handshake = summary["handshake_at"]
    if not isinstance(handshake, float):
        if any(summary[key] is not None
               for key in ("teardown_at", "restart_at", "start_at")):
            return "down"
        return "unknown"
    for key in ("teardown_at", "restart_at"):
        stamp = summary[key]
        if isinstance(stamp, float) and stamp > handshake:
            return "down"
    return "up"


def age(now, value):
    """Seconds since value, or None when it is missing."""
    return int(now - value) if isinstance(value, float) else None


def collect(config_dir=CONFIG_DIR):
    """Status of every configured instance."""
    instances = load_instances(config_dir)
    version = code_version()
    now = time.time()
    rows = []
    for inst in instances.values():
        active = unit_active(inst["unit"])
        summary = summarise(journal_events(inst["unit"]))
        state = read_state(inst["state_dir"])
        row = {
            "instance": inst["instance"],
            "unit": inst["unit"],
            "udp_bind": inst["udp_bind"],
            "socket": inst["socket"],
            "active": active,
            "restarts": unit_restarts(inst["unit"]),
            "status": classify(active, summary),
            "peer": summary["peer"],
            "real_ip": state["real_ip"] or summary["real_ip"],
            "real_ip_age": state["real_ip_age"],
            "endpoint": state["endpoint"],
            "endpoint_age": state["endpoint_age"],
            "next": None,
        }
        row["started_ago"] = age(now, summary["start_at"])
        row["handshake_ago"] = age(now, summary["handshake_at"])
        row["teardown_ago"] = age(now, summary["teardown_at"])
        rows.append(row)
    return {"now": now, "version": version, "instances": rows}


def cached_status(config_dir=CONFIG_DIR):
    with _cache_lock:
        if _cache["data"] is not None and time.time() - _cache["at"] < CACHE_TTL:
            return _cache["data"]
        data = collect(config_dir)
        _cache["at"] = time.time()
        _cache["data"] = data
        return data


def probe(inst, timeout=PROBE_TIMEOUT):
    """Run the agent client through one instance's Unix socket."""
    data = cached_status()
    target = None
    for row in data["instances"]:
        if row["instance"] == inst:
            target = row
            break
    if target is None or not target["socket"]:
        return {"ok": False, "error": "unknown instance"}
    code, out, err = run(["runuser", "-u", SITE_USER, "--", "/usr/bin/python3",
                          AGENT_CLIENT, target["socket"]], timeout=timeout)
    head = [line for line in out.splitlines()[:4]]
    return {
        "instance": inst,
        "ok": code == 0 and "<<<check_mk>>>" in out,
        "exit": code,
        "bytes": len(out),
        "head": head,
        "error": (err.strip()[:400] if err.strip() else None),
    }


HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>UDP punch tunnels</title>
<style>
:root{--bg:#f6f7f9;--fg:#16181d;--muted:#5b6270;--card:#fff;--line:#dfe3ea;
--ok:#1a7f37;--warn:#9a6700;--bad:#cf222e;--chip:#eef1f5}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--fg:#e6e8ee;--muted:#9aa3b2;
--card:#171a21;--line:#262b35;--ok:#3fb950;--warn:#d29922;--bad:#f85149;--chip:#1f242e}}
*{box-sizing:border-box}
body{margin:0;padding:24px;background:var(--bg);color:var(--fg);
font:14px/1.45 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
h1{font-size:18px;margin:0 0 4px}
.sub{color:var(--muted);margin:0 0 18px}
.wrap{max-width:1200px;margin:0 auto}
table{border-collapse:collapse;width:100%;background:var(--card);
border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{padding:10px 12px;text-align:left;border-bottom:1px solid var(--line);
vertical-align:top}
th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);
font-weight:600}
tr:last-child td{border-bottom:0}
td.mono,.mono{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12.5px}
.chip{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;
font-weight:600;background:var(--chip)}
.up{color:var(--ok)}.down{color:var(--bad)}.restarting{color:var(--warn)}.unknown{color:var(--warn)}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;
margin-right:6px;background:currentColor}
button{font:inherit;padding:4px 10px;border-radius:8px;border:1px solid var(--line);
background:var(--chip);color:var(--fg);cursor:pointer}
button:disabled{opacity:.5;cursor:default}
.result{color:var(--muted);font-size:12.5px}
.bar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:0 0 12px}
.bar .chip{background:var(--card);border:1px solid var(--line)}
</style>
</head>
<body><div class="wrap">
<h1>UDP punch tunnels</h1>
<p class="sub">One row per server instance. Status comes from systemd and the
journal; the test button runs a real agent fetch through the instance socket.</p>
<div class="bar"><span class="chip" id="version">version ?</span>
<span class="chip" id="updated">loading</span>
<span class="chip" id="counts"></span></div>
<table><thead><tr>
<th>Instance</th><th>Status</th><th>Peer seen as</th><th>UDP</th>
<th>Session</th><th>Restarts</th><th>Since</th><th>Test</th>
</tr></thead><tbody id="rows"></tbody></table>
</div>
<script>
const rows=document.getElementById('rows');
function fmtAge(s){if(s===null||s===undefined)return 'never';
if(s<90)return s+' s';if(s<5400)return Math.round(s/60)+' min';
return Math.round(s/3600)+' h'}
function cell(tr,tag,text,cls){const td=document.createElement(tag);
td.textContent=text;if(cls)td.className=cls;tr.appendChild(td);return td}
async function refresh(){
 try{const res=await fetch('api/status',{cache:'no-store'});
 const data=await res.json();
 document.getElementById('version').textContent='code '+data.version;
 document.getElementById('updated').textContent='updated '+new Date().toLocaleTimeString();
 let up=0,down=0,restarting=0,unknown=0;
 rows.textContent='';
 for(const r of data.instances){
  const tr=document.createElement('tr');
  cell(tr,'td',r.instance,'mono');
  const st=cell(tr,'td');const dot=document.createElement('span');
  dot.className='dot';st.appendChild(dot);
  st.appendChild(document.createTextNode(r.status));
  st.className=r.status;
  cell(tr,'td',(r.real_ip||'-')+(r.peer?('  '+r.peer):''),'mono');
  cell(tr,'td',r.udp_bind||'-','mono');
  cell(tr,'td',(r.handshake_ago!==null?('up since '+fmtAge(r.handshake_ago)):'no session')+
    (r.teardown_ago!==null?' · teardown '+fmtAge(r.teardown_ago)+' ago':''),
    'mono');
  cell(tr,'td',String(r.restarts===null?'-':r.restarts));
  cell(tr,'td',(r.started_ago!==null?('started '+fmtAge(r.started_ago)+' ago'):'-'),'mono');
  const td=document.createElement('td');
  const btn=document.createElement('button');btn.textContent='test';
  const out=document.createElement('div');out.className='result';
  btn.onclick=async()=>{btn.disabled=true;out.textContent='running...';
   try{const r2=await fetch('api/probe?inst='+encodeURIComponent(r.instance));
   const p=await r2.json();
   out.textContent=p.ok?('ok, '+p.bytes+' bytes'):('failed: '+(p.error||('exit '+p.exit)));
   if(p.head&&p.head.length)out.textContent+=' · '+p.head[0];
   }catch(e){out.textContent='error '+e}
   btn.disabled=false};
  td.appendChild(btn);td.appendChild(out);tr.appendChild(td);
  rows.appendChild(tr);
  if(r.status==='up')up++;else if(r.status==='down')down++;
  else if(r.status==='restarting')restarting++;else unknown++;
 }
 document.getElementById('counts').textContent=
  up+' up · '+down+' down · '+restarting+' restarting'+
  (unknown?(' · '+unknown+' unknown'):'');
 }catch(e){document.getElementById('updated').textContent='error '+e}
}
refresh();setInterval(refresh,15000);
</script>
</body></html>
"""


class Handler(BaseHTTPRequestHandler):
    config_dir = CONFIG_DIR

    def log_message(self, *_args):
        pass

    def send_json(self, payload, code=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/status":
            self.send_json(cached_status(self.config_dir))
            return
        if parsed.path == "/api/probe":
            query = urllib.parse.parse_qs(parsed.query)
            self.send_json(probe((query.get("inst") or [""])[0]))
            return
        self.send_json({"error": "not found"}, code=404)


def self_test():
    events = [
        (100.0, "cmk-punch p9 starting (role=server)"),
        (110.0, "no session for 120s, exiting so the service can restart"),
        (120.0, "cmk-punch p9 starting (role=server)"),
        (130.0, "session established with 203.0.113.5:6016 (HELLO, #1)"),
        (131.0, "peer real address 192.0.2.10"),
    ]
    summary = summarise(events)
    assert summary["handshake_at"] == 130.0, summary
    assert summary["peer"] == "203.0.113.5:6016", summary
    assert summary["real_ip"] == "192.0.2.10", summary
    assert summary["teardown_at"] is None, summary
    assert summary["restart_at"] == 110.0, summary
    assert classify("active", summary) == "up", summary
    events.append((140.0, "session with 203.0.113.5:6016 silent for 45s: "
                          "dropping keys and re-handshaking"))
    summary = summarise(events)
    assert classify("active", summary) == "down", summary
    assert classify("activating", {"restart_at": 150.0, "handshake_at": None,
                                   "teardown_at": None}) == "restarting"
    assert classify("inactive", {"restart_at": None, "handshake_at": None,
                                 "teardown_at": None}) == "down"
    assert classify("active", {"restart_at": None, "handshake_at": None,
                               "teardown_at": None, "start_at": None}) == "unknown"
    assert classify("active", {"restart_at": None, "handshake_at": None,
                               "teardown_at": None,
                               "start_at": 90.0}) == "down"
    assert load_instances("/nonexistent") == {}
    print("SELFTEST PASS")
    return 0


def main():
    parser = argparse.ArgumentParser(description="UDP punch status dashboard")
    parser.add_argument("--listen", default="127.0.0.1:8099")
    parser.add_argument("--config-dir", default=CONFIG_DIR)
    parser.add_argument("--once", action="store_true",
                        help="print the status JSON and exit")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        sys.exit(self_test())
    if args.once:
        print(json.dumps(collect(args.config_dir), indent=2))
        return
    host, port = args.listen.rsplit(":", 1)
    Handler.config_dir = args.config_dir
    server = ThreadingHTTPServer((host, int(port)), Handler)
    print("punch dashboard %s on http://%s:%s" % (VERSION, host, port),
          file=sys.stderr, flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
