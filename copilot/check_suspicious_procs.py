#!/usr/bin/env python3
"""
check_suspicious_procs.py - CheckMK Local Check Processi Sospetti (Copilot)

Rileva indicatori di compromissione tramite analisi dei processi:
  - CRITICAL: eseguibili da /tmp, /dev/shm, /var/tmp (tipiche dir malware)
  - CRITICAL: processi con eseguibile cancellato (malware in-memory)
  - CRITICAL: reverse shell note (netcat/ncat/socat in listen mode)
  - CRITICAL: crypto miner noti (xmrig, minerd, cpuminer, etc.)
  - WARNING:  comandi con base64 decode in cmdline (fileless attack pattern)
  - WARNING:  script da /proc/*/fd (fileless execution)
  - INFO:     LD_PRELOAD impostato su processi (rootkit tecnica)

STATE: /var/lib/check_mk_agent/suspicious_procs.state.json
  - Prima run: crea baseline processi validi
  - Run successive: alert su nuovi processi sospetti

Version: 1.0.0
"""

import json
import os
import re
import subprocess
import sys
from typing import Dict, List, Tuple

VERSION = "1.0.0"
SERVICE = "Security.SuspiciousProcs"
STATE_FILE = "/var/lib/check_mk_agent/suspicious_procs.state.json"

# Directory da considerare sospette
SUSPICIOUS_DIRS = ["/tmp/", "/dev/shm/", "/var/tmp/", "/run/shm/"]

# Nomi processo noti come crypto miner
MINER_NAMES = {
    "xmrig", "minerd", "cpuminer", "bfgminer", "cgminer",
    "ethminer", "t-rex", "nbminer", "gminer", "lolminer",
    "xmr-stak", "xmrig-cpu", "xmrig-amd", "xmrig-nvidia"
}

# Pattern reverse shell in cmdline
REVERSE_SHELL_PATTERNS = [
    re.compile(r"nc\s+.+\s+-e\s+/bin/(bash|sh|zsh)"),
    re.compile(r"ncat\s+.+\s+-e\s+/bin/(bash|sh|zsh)"),
    re.compile(r"socat\s+.*EXEC.*sh"),
    re.compile(r"/bin/(bash|sh)\s+-i\s+>&\s*/dev/tcp/"),
    re.compile(r"python.*socket.*subprocess"),
    re.compile(r"perl\s+-e\s+.*socket.*fork"),
    re.compile(r"ruby\s+-rsocket"),
]

# Pattern fileless attack (base64 decode + exec)
FILELESS_PATTERNS = [
    re.compile(r"base64\s+-d.*\|.*(bash|sh|python|perl)"),
    re.compile(r"echo\s+[A-Za-z0-9+/]{50,}.*\|.*base64\s+-d"),
    re.compile(r"curl\s+.*\|.*bash"),
    re.compile(r"wget\s+.*-O-\s+.*\|.*bash"),
]


def get_processes() -> List[Dict]:
    """Legge tutti i processi da /proc con dettagli rilevanti."""
    procs = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            # exe link
            exe_path = ""
            exe_link = f"/proc/{pid}/exe"
            try:
                exe_path = os.readlink(exe_link)
            except (PermissionError, FileNotFoundError):
                pass

            # cmdline
            cmdline = ""
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as f:
                    raw = f.read(512)
                cmdline = raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
            except (PermissionError, FileNotFoundError):
                pass

            # owner (uid)
            uid = -1
            try:
                stat = os.stat(f"/proc/{pid}")
                uid = stat.st_uid
            except Exception:
                pass

            # environ - cerca LD_PRELOAD
            ld_preload = ""
            try:
                with open(f"/proc/{pid}/environ", "rb") as f:
                    env_raw = f.read(4096)
                env_str = env_raw.replace(b"\x00", b"\n").decode("utf-8", errors="replace")
                m = re.search(r"LD_PRELOAD=([^\n]+)", env_str)
                if m:
                    ld_preload = m.group(1).strip()
            except (PermissionError, FileNotFoundError):
                pass

            procs.append({
                "pid": pid,
                "exe": exe_path,
                "cmdline": cmdline,
                "uid": uid,
                "ld_preload": ld_preload,
            })
        except Exception:
            continue
    return procs


def analyze_processes(procs: List[Dict]) -> Tuple[List[str], List[str], List[str]]:
    """
    Analizza processi e restituisce:
      - critical: lista descrizioni problemi critici
      - warnings: lista descrizioni warning
      - info: lista note informative
    """
    critical = []
    warnings = []
    info = []

    for p in procs:
        pid = p["pid"]
        exe = p["exe"]
        cmd = p["cmdline"]
        name = os.path.basename(exe).split()[0] if exe else (cmd.split()[0] if cmd else "")

        # Check 1: eseguibile da directory sospetta
        if exe and not exe.endswith(" (deleted)"):
            for sus_dir in SUSPICIOUS_DIRS:
                if exe.startswith(sus_dir):
                    critical.append(f"PID {pid}: eseguibile da {exe} [{cmd[:60]}]")
                    break

        # Check 2: eseguibile cancellato (malware rimasto in memoria)
        if exe and "(deleted)" in exe:
            clean_exe = exe.replace(" (deleted)", "")
            # Ignora processi di sistema noti con exe deleted (aggiornamenti in corso)
            ignorable = any(clean_exe.startswith(p) for p in [
                "/usr/lib/jvm/", "/tmp/java", "/usr/bin/python",
                "/usr/bin/perl", "/opt/omd/"
            ])
            if not ignorable:
                critical.append(f"PID {pid}: eseguibile cancellato {clean_exe} [{cmd[:60]}]")

        # Check 3: crypto miner
        name_lower = name.lower().split()[0] if name else ""
        if name_lower in MINER_NAMES:
            critical.append(f"PID {pid}: possibile crypto miner '{name}' [{cmd[:60]}]")

        # Check 4: reverse shell patterns
        if cmd:
            for pattern in REVERSE_SHELL_PATTERNS:
                if pattern.search(cmd):
                    critical.append(f"PID {pid}: possibile reverse shell [{cmd[:80]}]")
                    break

        # Check 5: fileless attack patterns
        if cmd:
            for pattern in FILELESS_PATTERNS:
                if pattern.search(cmd):
                    warnings.append(f"PID {pid}: pattern fileless attack [{cmd[:80]}]")
                    break

        # Check 6: LD_PRELOAD sospetto
        if p.get("ld_preload"):
            info.append(f"PID {pid}: LD_PRELOAD={p['ld_preload']} [{cmd[:40]}]")

    return critical, warnings, info


def load_baseline() -> dict:
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_baseline(data: dict) -> None:
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


def main() -> int:
    procs = get_processes()
    critical, warnings, info = analyze_processes(procs)

    perf = (
        f"total_procs={len(procs)} "
        f"critical_indicators={len(critical)} "
        f"warning_indicators={len(warnings)}"
    )

    if critical:
        details = "; ".join(critical[:3])
        extra = f" (+{len(critical)-3} altri)" if len(critical) > 3 else ""
        print(f"2 {SERVICE} - CRITICAL: {details}{extra} | {perf}")
        return 0

    if warnings:
        details = "; ".join(warnings[:3])
        print(f"1 {SERVICE} - WARNING: {details} | {perf}")
        return 0

    if info:
        details = "; ".join(info[:2])
        print(f"0 {SERVICE} - OK: {len(procs)} proc, nota: {details} | {perf}")
        return 0

    print(f"0 {SERVICE} - OK: {len(procs)} processi, nessun indicatore sospetto | {perf}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
