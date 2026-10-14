#!/usr/bin/env python3
"""agent_ns8_api.py - CheckMK special agent (datasource program) for NethServer 8, REST API only (PROTOTYPE)

Runs on the CheckMK server, not on the NS8 node: it logs in to the cluster-admin
REST API (through Traefik, e.g. https://NS8-RL98.nethlab.it/cluster-admin/api)
with a reader-role user and prints CheckMK local-check lines (same output format
as the check_ns8_*_api.py prototypes, so no check plugin is needed).

Checks:
- NS8.Cluster                     cluster/get-cluster-status (initialized, nodes online)
- NS8.Node.<id>.Load/Cpu/Memory/Swap and NS8.Node.<id>.Disk.<mount>
                                  node/<id>/get-node-status
- NS8.Module.<id>.Services        module/<id>/get-status (systemd services failed)

Read-only: only get-/list- actions are called. The password is read from a file
(--pass-file, mode 600), never from the command line.

Usage (datasource program):
  agent_ns8_api.py --url https://NS8-RL98.nethlab.it/cluster-admin/api --user claude-ro --pass-file /path --insecure

Version: 0.1.0"""

import argparse
import concurrent.futures
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple

VERSION = "0.1.0"
TASK_TIMEOUT = 20.0
WORKERS = 3

# thresholds (WARN, CRIT). Load is per CPU core on the 5 min average.
LOAD_PER_CORE = (1.5, 2.5)
CPU_PCT = (85.0, 95.0)
MEM_PCT = (85.0, 95.0)
SWAP_PCT = (50.0, 80.0)
DISK_PCT = (80.0, 90.0)

_OUT: List[str] = []


def emit(state: int, name: str, text: str, metrics: Optional[List[str]] = None) -> None:
    """One CheckMK local-check line."""
    name = re.sub(r"\s+", "_", name)
    _OUT.append("%d %s %s %s" % (state, name, "|".join(metrics) if metrics else "-", text.replace("\n", " ")))


def state_for(value: float, limits: Tuple[float, float]) -> int:
    if value >= limits[1]:
        return 2
    if value >= limits[0]:
        return 1
    return 0


def metric(name: str, value: float, limits: Optional[Tuple[float, float]] = None, vmin: Optional[float] = None, vmax: Optional[float] = None) -> str:
    w, c = ("%g" % limits[0], "%g" % limits[1]) if limits else ("", "")
    return "%s=%.4g;%s;%s;%s;%s" % (name, value, w, c, "" if vmin is None else "%g" % vmin, "" if vmax is None else "%g" % vmax)


class Api:
    def __init__(self, base: str, insecure: bool):
        self.base = base.rstrip("/")
        self.ctx = ssl.create_default_context()
        if insecure:
            self.ctx.check_hostname = False
            self.ctx.verify_mode = ssl.CERT_NONE
        self.token = ""

    def _req(self, path: str, body: Optional[dict] = None) -> Tuple[int, dict]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=15, context=self.ctx) as resp:
                return resp.status, json.load(resp)
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.load(exc)
            except (ValueError, OSError):
                return exc.code, {}

    def login(self, user: str, password: str) -> str:
        """Returns '' on success, else a short error string."""
        try:
            status, js = self._req("/login", {"username": user, "password": password})
        except (urllib.error.URLError, OSError, ValueError):
            return "api-unreachable"
        data = js.get("data")
        token = data.get("token") if isinstance(data, dict) else js.get("token")
        if status != 200 or not token:
            return "login-failed" if status in (400, 401, 403) else "api-http-%d" % status
        self.token = token
        return ""

    def task(self, agent: str, action: str, data: Optional[dict] = None) -> Tuple[Optional[object], str]:
        """Runs an action, returns (output, error)."""
        try:
            status, js = self._req("/%s/tasks" % agent, {"action": action, "data": data, "parent": "", "extra": {}})
            if status in (401, 403):
                return None, "permission-denied"
            task_id = (js.get("data") or {}).get("id")
            if not task_id:
                return None, "api-http-%d" % status
            deadline = time.monotonic() + TASK_TIMEOUT
            while time.monotonic() < deadline:
                status, js = self._req("/%s/task/%s/status" % (agent, task_id))
                if status == 200:
                    d = js.get("data") or {}
                    return (d.get("output"), "") if d.get("exit_code") == 0 else (None, "task-failed")
                if status in (401, 403):
                    return None, "permission-denied"
                time.sleep(0.2)  # 400 "redis: nil" = still running
            return None, "task-timeout"
        except (urllib.error.URLError, OSError, ValueError):
            return None, "api-unreachable"


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return "%.1f %s" % (n, unit)
        n /= 1024.0
    return "%.1f TB" % n


def check_cluster(api: Api) -> List[int]:
    out, err = api.task("cluster", "get-cluster-status")
    if not isinstance(out, dict):
        emit(3 if err == "permission-denied" else 2, "NS8.Cluster", "cannot read cluster status: %s" % err)
        return []
    nodes = out.get("nodes") or []
    online = [n for n in nodes if n.get("online")]
    state, notes = 0, []
    if not out.get("initialized"):
        state, notes = 2, ["cluster not initialized"]
    if len(online) < len(nodes):
        state = 2
        notes.append("offline: " + ",".join(str(n.get("id")) for n in nodes if not n.get("online")))
    if out.get("default_password"):
        state = max(state, 1)
        notes.append("default admin password still in use")
    text = "%s, %d/%d node(s) online%s" % (out.get("ui_name") or "cluster", len(online), len(nodes), (", " + "; ".join(notes)) if notes else "")
    emit(state, "NS8.Cluster", text, [metric("nodes_online", len(online), None, 0, len(nodes)), metric("nodes_total", len(nodes), None, 0)])
    return [int(n["id"]) for n in online if str(n.get("id", "")).isdigit()]


def check_node(api: Api, node_id: int) -> None:
    out, err = api.task("node/%d" % node_id, "get-node-status")
    prefix = "NS8.Node.%d" % node_id
    status = None
    if isinstance(out, dict):
        status = out.get("status") if isinstance(out.get("status"), dict) else out  # raw answer has no "status" wrapper
    if not isinstance(status, dict) or not ("load" in status or "cpu" in status):
        emit(3 if err == "permission-denied" else 2, prefix + ".Status", "cannot read node status: %s" % (err or "empty answer"))
        return
    cpu = status.get("cpu") or {}
    cores = max(int(cpu.get("count") or 1), 1)
    load = status.get("load") or {}
    # get-node-status reports the load as percent of the cores (load average / cores * 100), not the raw load average
    l1, l5, l15 = (float(load.get(k, 0)) * cores / 100.0 for k in ("1min", "5min", "15min"))
    per_core = l5 / cores
    emit(state_for(per_core, LOAD_PER_CORE), prefix + ".Load", "load %.2f %.2f %.2f on %d cores (5 min: %.2f per core)" % (l1, l5, l15, cores, per_core),
         [metric("load1", l1, None, 0), metric("load5", l5, (LOAD_PER_CORE[0] * cores, LOAD_PER_CORE[1] * cores), 0), metric("load15", l15, None, 0)])
    usage = float(cpu.get("usage") or 0)  # get-node-status reports a percentage
    emit(state_for(usage, CPU_PCT), prefix + ".Cpu", "CPU usage %.1f%%" % usage, [metric("cpu_percent", usage, CPU_PCT, 0, 100)])
    for key, label, limits in (("memory", "Memory", MEM_PCT), ("swap", "Swap", SWAP_PCT)):
        m = status.get(key) or {}
        total, used = float(m.get("total") or 0), float(m.get("used") or 0)
        if total <= 0:
            emit(0, "%s.%s" % (prefix, label), "%s not present" % label.lower())
            continue
        pct = used * 100.0 / total
        emit(state_for(pct, limits), "%s.%s" % (prefix, label), "%.1f%% used (%s of %s)" % (pct, human(used), human(total)),
             [metric("%s_used_percent" % key, pct, limits, 0, 100), metric("%s_used_bytes" % key, used, None, 0, total)])
    for disk in status.get("disks") or []:
        mount, total, used = disk.get("mountpoint") or disk.get("device"), float(disk.get("total") or 0), float(disk.get("used") or 0)
        if not mount or total <= 0:
            continue
        pct = used * 100.0 / total
        name = "%s.Disk.%s" % (prefix, "root" if mount == "/" else mount.strip("/").replace("/", "_"))
        emit(state_for(pct, DISK_PCT), name, "%s %.1f%% used (%s of %s)" % (mount, pct, human(used), human(total)),
             [metric("disk_used_percent", pct, DISK_PCT, 0, 100), metric("disk_used_bytes", used, None, 0, total)])


def check_module(api: Api, module_id: str) -> None:
    name = "NS8.Module.%s.Services" % module_id
    out, err = api.task("module/%s" % module_id, "get-status")
    services = out.get("services") if isinstance(out, dict) else None
    if not isinstance(services, list):
        emit(3, name, "cannot read services: %s" % (err or "empty answer"))
        return
    failed = sorted(s.get("name", "?") for s in services if s.get("failed"))
    active = sum(1 for s in services if s.get("active"))
    metrics = [metric("services_total", len(services), None, 0), metric("services_active", active, None, 0), metric("services_failed", len(failed), (1, 1), 0)]
    if failed:
        emit(2, name, "%d failed: %s" % (len(failed), ", ".join(failed)), metrics)
    else:
        emit(0, name, "no failed services (%d active of %d)" % (active, len(services)), metrics)


def main() -> int:
    ap = argparse.ArgumentParser(description="CheckMK special agent for NethServer 8 (API only)")
    ap.add_argument("--url", required=True, help="cluster-admin API base, e.g. https://host/cluster-admin/api")
    ap.add_argument("--user", required=True)
    ap.add_argument("--pass-file", required=True, help="file with the password (mode 600)")
    ap.add_argument("--insecure", action="store_true", help="do not verify the TLS certificate")
    args = ap.parse_args()

    print("<<<check_mk>>>")
    print("Version: ns8-api-special-agent-%s" % VERSION)
    print("AgentOS: ns8-api")
    print("<<<local:sep(0)>>>")

    try:
        with open(args.pass_file, encoding="utf-8") as fh:
            password = fh.read().strip()
    except OSError as exc:
        emit(3, "NS8.Cluster", "cannot read password file: %s" % exc.strerror)
        print("\n".join(_OUT))
        return 0

    api = Api(args.url, args.insecure)
    err = api.login(args.user, password)
    if err:
        emit(2 if err == "api-unreachable" else 3, "NS8.Cluster", "NS8 API login failed: %s" % err)
        print("\n".join(_OUT))
        return 0

    node_ids = check_cluster(api)
    modules, merr = api.task("cluster", "list-installed-modules")
    module_ids: List[str] = []
    if isinstance(modules, dict):
        module_ids = sorted(inst["id"] for insts in modules.values() for inst in insts if "id" in inst)
    else:
        emit(3, "NS8.Modules", "cannot list modules: %s" % merr)

    # nodes first and alone: running the module checks in parallel would raise the very CPU/load being measured
    for n in node_ids:
        check_node(api, n)
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for f in [pool.submit(check_module, api, m) for m in module_ids]:
            f.result()

    _OUT.sort(key=lambda line: line.split(" ", 2)[1])
    print("\n".join(_OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
