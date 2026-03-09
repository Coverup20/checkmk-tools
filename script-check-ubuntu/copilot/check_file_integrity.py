#!/usr/bin/env python3
"""
check_file_integrity.py - CheckMK Local Check File Integrity (Copilot)

Monitora l'integrità di file critici di sistema tramite hash SHA256.
Prima esecuzione: crea baseline. Esecuzioni successive: alert su modifiche.

File monitorati:
  - /etc/passwd, /etc/shadow, /etc/group, /etc/sudoers
  - /etc/hosts, /etc/crontab, /etc/ssh/sshd_config
  - /root/.ssh/authorized_keys
  - /etc/cron.d/* (directory intera)
  - /usr/lib/check_mk_agent/local/* (tampering ai nostri check)

CRITICAL: file modificato rispetto alla baseline
WARNING:  file nella lista non esiste più (possibile cancellazione)
INFO:     nuovo file in directory monitorata

STATE: /var/lib/check_mk_agent/file_integrity.state.json

Version: 1.0.0
"""

import hashlib
import json
import os
import sys
import time
from typing import Dict, List, Optional, Tuple

VERSION = "1.0.0"
SERVICE = "Security.FileIntegrity"
STATE_FILE = "/var/lib/check_mk_agent/file_integrity.state.json"

# File singoli da monitorare
WATCHED_FILES = [
    "/etc/passwd",
    "/etc/shadow",
    "/etc/group",
    "/etc/sudoers",
    "/etc/hosts",
    "/etc/crontab",
    "/etc/ssh/sshd_config",
    "/root/.ssh/authorized_keys",
]

# Directory da monitorare (tutti i file figli diretti)
WATCHED_DIRS = [
    "/etc/cron.d",
    "/etc/sudoers.d",
    "/usr/lib/check_mk_agent/local",
]


def sha256_file(path: str) -> Optional[str]:
    """Calcola SHA256 di un file. Ritorna None se non leggibile."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except (FileNotFoundError, PermissionError):
        return None


def collect_hashes() -> Dict[str, Optional[str]]:
    """Raccoglie hash SHA256 di tutti i file monitorati."""
    hashes = {}

    # File singoli
    for path in WATCHED_FILES:
        hashes[path] = sha256_file(path)

    # Directory
    for dpath in WATCHED_DIRS:
        if not os.path.isdir(dpath):
            continue
        try:
            for entry in sorted(os.scandir(dpath), key=lambda e: e.name):
                if entry.is_file():
                    hashes[entry.path] = sha256_file(entry.path)
        except PermissionError:
            pass

    return hashes


def load_baseline() -> Optional[dict]:
    """Carica baseline da state file."""
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return None


def save_baseline(hashes: Dict, timestamp: float) -> None:
    """Salva baseline su state file."""
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump({"timestamp": timestamp, "hashes": hashes}, f, indent=2)
    except Exception:
        pass


def main() -> int:
    current = collect_hashes()
    now = time.time()

    baseline_data = load_baseline()

    # Prima esecuzione: crea baseline e OK
    if baseline_data is None:
        save_baseline(current, now)
        count = sum(1 for v in current.values() if v is not None)
        print(
            f"0 {SERVICE} - OK: baseline creata per {count} file "
            f"| monitored={count} modified=0 missing=0 new=0"
        )
        return 0

    baseline: Dict = baseline_data.get("hashes", {})
    baseline_ts = baseline_data.get("timestamp", 0)
    baseline_age_h = (now - baseline_ts) / 3600

    modified: List[str] = []
    missing:  List[str] = []
    new_files: List[str] = []

    # Confronta con baseline
    all_paths = set(baseline.keys()) | set(current.keys())
    for path in sorted(all_paths):
        old_hash = baseline.get(path)
        new_hash = current.get(path)

        if old_hash is None and new_hash is not None:
            # Nuovo file non in baseline
            new_files.append(os.path.basename(path))

        elif old_hash is not None and new_hash is None:
            # File sparito
            missing.append(path)

        elif old_hash is not None and new_hash is not None:
            if old_hash != new_hash:
                modified.append(path)

    # Aggiorna baseline con stato corrente
    save_baseline(current, now)

    monitored = sum(1 for v in current.values() if v is not None)
    perf = (
        f"monitored={monitored} "
        f"modified={len(modified)} "
        f"missing={len(missing)} "
        f"new={len(new_files)}"
    )

    # CRITICAL: file modificati
    if modified:
        files_str = ", ".join(os.path.basename(f) for f in modified[:5])
        extra = f" (+{len(modified)-5})" if len(modified) > 5 else ""
        print(f"2 {SERVICE} - CRITICAL: file modificati: {files_str}{extra} | {perf}")
        return 0

    # CRITICAL: file critici spariti
    if missing:
        files_str = ", ".join(os.path.basename(f) for f in missing[:3])
        print(f"2 {SERVICE} - CRITICAL: file scomparsi: {files_str} | {perf}")
        return 0

    # WARNING: nuovi file in directory monitorate
    if new_files:
        files_str = ", ".join(new_files[:5])
        print(f"1 {SERVICE} - WARNING: nuovi file: {files_str} | {perf}")
        return 0

    # OK
    age_str = f"{baseline_age_h:.0f}h fa"
    print(
        f"0 {SERVICE} - OK: {monitored} file integri "
        f"(baseline aggiornata {age_str}) | {perf}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
