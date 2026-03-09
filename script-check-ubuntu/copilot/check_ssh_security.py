#!/usr/bin/env python3
"""
check_ssh_security.py - CheckMK Local Check SSH Security (Copilot)

Monitoraggio unificato sessioni SSH:
  - Totale sessioni attive (tutte le utenze)
  - Sessioni root attive con IP sorgente
  - Rilevamento nuovi login root via state file (alert al primo ciclo)
  - Perfdata per grafici

STATE: /var/lib/check_mk_agent/ssh_security.state.json

Version: 1.0.0
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from typing import Dict, List, Set, Tuple

VERSION = "1.0.0"
SERVICE = "SSH.Security"
STATE_FILE = "/var/lib/check_mk_agent/ssh_security.state.json"

# Soglie root sessions
WARN_ROOT = 1
CRIT_ROOT = 5


def run(cmd: List[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return r.stdout
    except Exception:
        return ""


def parse_who() -> Tuple[int, List[dict]]:
    """
    Restituisce (totale_sessioni, lista_root_sessions).
    Ogni root_session: {"ip": str, "since": str}
    """
    out = run(["who"])
    total = 0
    root_sessions = []
    for line in out.splitlines():
        parts = line.split()
        if not parts:
            continue
        total += 1
        if parts[0] == "root":
            ip = ""
            since = ""
            if len(parts) >= 5:
                ip = parts[4].strip("()")
            if len(parts) >= 3:
                since = f"{parts[2]} {parts[3]}" if len(parts) >= 4 else parts[2]
            root_sessions.append({"ip": ip, "since": since})
    return total, root_sessions


def load_state() -> dict:
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {"root_ips": []}


def save_state(state: dict) -> None:
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception:
        pass


def main() -> int:
    total, root_sessions = parse_who()
    root_count = len(root_sessions)
    current_ips: Set[str] = {s["ip"] for s in root_sessions if s["ip"]}

    state = load_state()
    prev_ips: Set[str] = set(state.get("root_ips", []))
    new_logins = current_ips - prev_ips
    logouts = prev_ips - current_ips

    save_state({"root_ips": sorted(current_ips), "updated": datetime.now().isoformat()})

    # Perfdata
    perfdata = f"total_sessions={total} root_sessions={root_count}"

    # Nuovo login root → CRITICAL
    if new_logins:
        ips_str = ",".join(sorted(new_logins))
        print(f"2 {SERVICE} - NUOVO login root da: {ips_str} | {perfdata}")
        return 0

    # Logout root → OK informativo
    if logouts and not root_count:
        print(f"0 {SERVICE} - root logout, nessuna sessione root attiva | {perfdata}")
        return 0

    # Sessioni root sostenute
    if root_count >= CRIT_ROOT:
        ips_str = ",".join(sorted(current_ips))
        print(f"2 {SERVICE} - {root_count} sessioni root attive: {ips_str} | {perfdata}")
        return 0

    if root_count >= WARN_ROOT:
        ips_str = ",".join(sorted(current_ips))
        print(f"1 {SERVICE} - {root_count} sessione root da {ips_str}, {total} totali | {perfdata}")
        return 0

    # Tutto OK
    if total > 0:
        # Estrai utenti unici
        out = run(["who"])
        users = sorted({l.split()[0] for l in out.splitlines() if l.split()})
        print(f"0 {SERVICE} - {total} sessioni attive: {','.join(users)}, nessuna root | {perfdata}")
    else:
        print(f"0 {SERVICE} - nessuna sessione attiva | {perfdata}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
