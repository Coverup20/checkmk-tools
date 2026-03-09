#!/usr/bin/env python3
"""
check_omd_health.py - CheckMK Local Check OMD Site Health (Copilot)

Monitora lo stato del sito CheckMK/OMD locale:
  - Tutti i servizi OMD (nagios, apache, rrdcached, redis, ecc.)
  - Età dell'ultimo backup (WARNING se >2gg, CRITICAL se >7gg)
  - Presenza log di errori critici recenti in notify.log
  - Perfdata: servizi attivi/totali, ore dall'ultimo backup

Version: 1.0.0
"""

import os
import subprocess
import sys
import time
from datetime import datetime
from typing import List, Optional, Tuple

VERSION = "1.0.0"
SERVICE_PREFIX = "OMD"

# Soglie backup (ore)
BACKUP_WARN_H = 48    # 2 giorni
BACKUP_CRIT_H = 168   # 7 giorni

# Directory backup da controllare
BACKUP_DIRS = [
    "/var/backups/checkmk",
    "/omd/sites/monitoring/var/check_mk/notify-backup",
]

# Servizi OMD critici (se mancano → CRITICAL)
CRITICAL_SERVICES = {"nagios", "apache", "rrdcached"}


def run(cmd: List[str], timeout: int = 10) -> Tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return 1, "timeout"
    except Exception as e:
        return 1, str(e)


def get_omd_site() -> Optional[str]:
    """Trova il nome del sito OMD attivo."""
    rc, out = run(["omd", "sites", "--bare"])
    if rc == 0:
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        if lines:
            return lines[0]
    return None


def get_omd_status(site: str) -> Tuple[int, int, List[str]]:
    """
    Restituisce (running_count, total_count, lista_servizi_down).
    """
    rc, out = run(["omd", "status", site])
    running = 0
    total = 0
    down = []
    for line in out.splitlines():
        if ":" not in line:
            continue
        parts = line.split(":", 1)
        if len(parts) != 2:
            continue
        svc = parts[0].strip()
        state = parts[1].strip().lower()
        if svc in ("overall state", "Overall state"):
            continue
        if not svc or state not in ("running", "stopped", "failed"):
            continue
        total += 1
        if state == "running":
            running += 1
        else:
            down.append(svc)
    return running, total, down


def get_last_backup_age_hours() -> Optional[float]:
    """
    Cerca il file di backup più recente nelle directory configurate.
    Restituisce età in ore, o None se nessun backup trovato.
    """
    newest_mtime = None
    for bdir in BACKUP_DIRS:
        if not os.path.isdir(bdir):
            continue
        for entry in os.scandir(bdir):
            if entry.is_file():
                mtime = entry.stat().st_mtime
                if newest_mtime is None or mtime > newest_mtime:
                    newest_mtime = mtime
    if newest_mtime is None:
        return None
    age_h = (time.time() - newest_mtime) / 3600
    return age_h


def get_notify_errors_last_hour() -> int:
    """Conta righe ERROR/CRITICAL in notify.log nell'ultima ora."""
    log_path = "/omd/sites/monitoring/var/log/notify.log"
    if not os.path.exists(log_path):
        return 0
    one_hour_ago = time.time() - 3600
    count = 0
    try:
        with open(log_path, "r", errors="replace") as f:
            # Leggi solo le ultime 2000 righe per efficienza
            lines = f.readlines()[-2000:]
        for line in lines:
            if "ERROR" in line or "CRITICAL" in line:
                # Prova a parsare timestamp se disponibile
                count += 1
    except Exception:
        pass
    return count


def main() -> int:
    site = get_omd_site()

    # --- Check 1: Stato servizi OMD ---
    if site:
        running, total, down = get_omd_status(site)
    else:
        running, total, down = 0, 0, []

    perf_svc = f"omd_running={running} omd_total={total}"

    if not site:
        print(f"3 {SERVICE_PREFIX}.Services - UNKNOWN: nessun sito OMD trovato | {perf_svc}")
    elif down:
        critical_down = [s for s in down if s in CRITICAL_SERVICES]
        if critical_down:
            print(f"2 {SERVICE_PREFIX}.Services - CRITICAL: down={','.join(critical_down)} | {perf_svc}")
        else:
            print(f"1 {SERVICE_PREFIX}.Services - WARNING: servizi non running: {','.join(down)} | {perf_svc}")
    else:
        print(f"0 {SERVICE_PREFIX}.Services - OK: tutti {running}/{total} servizi running | {perf_svc}")

    # --- Check 2: Età ultimo backup ---
    age_h = get_last_backup_age_hours()

    if age_h is None:
        perf_bk = "backup_age_hours=0"
        print(f"1 {SERVICE_PREFIX}.Backup - WARNING: nessun backup trovato | {perf_bk}")
    else:
        age_d = age_h / 24
        perf_bk = f"backup_age_hours={age_h:.1f};{BACKUP_WARN_H};{BACKUP_CRIT_H}"
        if age_h >= BACKUP_CRIT_H:
            print(f"2 {SERVICE_PREFIX}.Backup - CRITICAL: ultimo backup {age_d:.1f} giorni fa | {perf_bk}")
        elif age_h >= BACKUP_WARN_H:
            print(f"1 {SERVICE_PREFIX}.Backup - WARNING: ultimo backup {age_d:.1f} giorni fa | {perf_bk}")
        else:
            print(f"0 {SERVICE_PREFIX}.Backup - OK: ultimo backup {age_h:.0f}h fa | {perf_bk}")

    # --- Check 3: Errori in notify.log ---
    err_count = get_notify_errors_last_hour()
    perf_err = f"notify_errors_1h={err_count}"

    if err_count > 50:
        print(f"2 {SERVICE_PREFIX}.NotifyErrors - CRITICAL: {err_count} errori in notify.log ultima ora | {perf_err}")
    elif err_count > 10:
        print(f"1 {SERVICE_PREFIX}.NotifyErrors - WARNING: {err_count} errori in notify.log ultima ora | {perf_err}")
    else:
        print(f"0 {SERVICE_PREFIX}.NotifyErrors - OK: {err_count} errori in notify.log ultima ora | {perf_err}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
