#!/usr/bin/env python3
"""
check_brute_force.py - CheckMK Local Check Brute Force Detection (Copilot)

Analizza /var/log/auth.log per rilevare:
  - Tentativi SSH falliti per IP (ultima ora e ultime 24h)
  - Successivo login riuscito dopo molti fallimenti (possibile breach)
  - IP attualmente bannati da fail2ban
  - Tentativi su utenti inesistenti (invalid user)

Soglie per IP singolo nell'ultima ora:
  WARNING:  >= 10 tentativi
  CRITICAL: >= 50 tentativi, oppure login riuscito dopo >= 5 fallimenti

Perfdata: failed_1h, failed_24h, top_ip_count, banned_ips

Version: 1.0.0
"""

import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

VERSION = "1.0.0"
SERVICE = "BruteForce.SSH"

AUTH_LOG = "/var/log/auth.log"

WARN_ATTEMPTS_1H = 10
CRIT_ATTEMPTS_1H = 50
CRIT_SUCCESS_AFTER_FAIL = 5


def parse_auth_log() -> Tuple[Dict[str, int], Dict[str, int], List[str]]:
    """
    Legge auth.log e restituisce:
      - failed_1h:  {ip: count} per ultima ora
      - failed_24h: {ip: count} per ultime 24h
      - success_after_fail: lista IP con login riuscito dopo molti fallimenti
    """
    now = datetime.now()
    cutoff_1h  = now - timedelta(hours=1)
    cutoff_24h = now - timedelta(hours=24)

    year = now.year

    failed_1h:  Dict[str, int] = defaultdict(int)
    failed_24h: Dict[str, int] = defaultdict(int)
    # Per rilevare login riuscito dopo fallimenti: traccia fail per IP
    failed_recent: Dict[str, int] = defaultdict(int)
    suspicious_logins: List[str] = []

    # Pattern per riga auth.log
    re_failed  = re.compile(r"(\w+\s+\d+\s+\d+:\d+:\d+).*sshd.*[Ff]ailed.*from\s+([\d.]+)")
    re_invalid = re.compile(r"(\w+\s+\d+\s+\d+:\d+:\d+).*sshd.*[Ii]nvalid user.*from\s+([\d.]+)")
    re_success = re.compile(r"(\w+\s+\d+\s+\d+:\d+:\d+).*sshd.*[Aa]ccepted.*from\s+([\d.]+)")

    month_map = {m: i+1 for i, m in enumerate(
        ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    )}

    def parse_ts(ts_str: str) -> datetime:
        parts = ts_str.split()
        # "Mar  9 19:00:00"
        month = month_map.get(parts[0], 1)
        day   = int(parts[1])
        h, m, s = map(int, parts[2].split(":"))
        return datetime(year, month, day, h, m, s)

    try:
        with open(AUTH_LOG, "r", errors="replace") as f:
            # Leggi le ultime 50000 righe per efficienza
            lines = f.readlines()[-50000:]
    except (FileNotFoundError, PermissionError):
        return {}, {}, []

    for line in lines:
        for pattern, is_fail, is_success in [
            (re_failed,  True,  False),
            (re_invalid, True,  False),
            (re_success, False, True),
        ]:
            m = pattern.search(line)
            if not m:
                continue
            try:
                ts = parse_ts(m.group(1))
            except (ValueError, IndexError):
                continue
            ip = m.group(2)

            if is_fail:
                if ts >= cutoff_1h:
                    failed_1h[ip] += 1
                if ts >= cutoff_24h:
                    failed_24h[ip] += 1
                    failed_recent[ip] += 1
            elif is_success:
                if ts >= cutoff_24h:
                    # Login riuscito: controlla se ci sono stati molti fail recenti
                    if failed_recent.get(ip, 0) >= CRIT_SUCCESS_AFTER_FAIL:
                        suspicious_logins.append(
                            f"{ip} (login OK dopo {failed_recent[ip]} fail)"
                        )
                    # Reset fail counter dopo login riuscito
                    failed_recent[ip] = 0

    return dict(failed_1h), dict(failed_24h), suspicious_logins


def get_fail2ban_banned() -> Tuple[int, List[str]]:
    """Restituisce (count_bannati, lista_ip) da fail2ban."""
    try:
        r = subprocess.run(
            ["fail2ban-client", "status", "sshd"],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode != 0:
            return 0, []
        # Cerca "Banned IP list: 1.2.3.4 5.6.7.8"
        m = re.search(r"Banned IP list:\s*(.*)", r.stdout)
        if m:
            ips = m.group(1).strip().split()
            return len(ips), ips
    except Exception:
        pass
    return 0, []


def main() -> int:
    failed_1h, failed_24h, suspicious = parse_auth_log()
    banned_count, banned_ips = get_fail2ban_banned()

    # Totali
    total_1h  = sum(failed_1h.values())
    total_24h = sum(failed_24h.values())

    # IP con più tentativi nell'ultima ora
    top_ip = ""
    top_count = 0
    if failed_1h:
        top_ip, top_count = max(failed_1h.items(), key=lambda x: x[1])

    perf = (
        f"failed_1h={total_1h} "
        f"failed_24h={total_24h} "
        f"top_ip_count={top_count} "
        f"banned_ips={banned_count}"
    )

    # CRITICAL: login riuscito dopo molti fail
    if suspicious:
        susp_str = "; ".join(suspicious[:3])
        print(f"2 {SERVICE} - CRITICAL: possibile breach! {susp_str} | {perf}")
        return 0

    # CRITICAL: IP con troppi tentativi in 1h
    if top_count >= CRIT_ATTEMPTS_1H:
        print(
            f"2 {SERVICE} - CRITICAL: {top_ip} ha fatto "
            f"{top_count} tentativi nell'ultima ora | {perf}"
        )
        return 0

    # WARNING: IP con molti tentativi in 1h
    if top_count >= WARN_ATTEMPTS_1H:
        print(
            f"1 {SERVICE} - WARNING: {top_ip} ha fatto "
            f"{top_count} tentativi nell'ultima ora | {perf}"
        )
        return 0

    # Tutto OK — fornisci comunque contesto
    if total_24h > 0:
        top_24h_ip, top_24h_cnt = max(failed_24h.items(), key=lambda x: x[1])
        banned_str = f", {banned_count} IP bannati" if banned_count else ""
        print(
            f"0 {SERVICE} - OK: {total_24h} tentativi 24h "
            f"(max {top_24h_cnt} da {top_24h_ip})"
            f"{banned_str} | {perf}"
        )
    else:
        print(f"0 {SERVICE} - OK: nessun tentativo fallito nelle ultime 24h | {perf}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
