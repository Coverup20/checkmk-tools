#!/usr/bin/env python3
"""
check_arp_watch.py - CheckMK Local Check per monitoraggio ARP

Rileva:
  - CRITICAL: ARP spoofing (stesso IP, MAC cambiato)
  - WARNING:  Nuovo host mai visto prima
  - OK:       Tutti gli host noti, nessuna anomalia

Baseline: /var/lib/check_mk_agent/arp_watch_state.json
  {
    "10.155.100.1": {"mac": "aa:bb:cc:dd:ee:ff", "seen": 5, "first_seen": "2026-03-06T10:00:00"},
    ...
  }

Version: 1.0.0
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from typing import Dict, Tuple

VERSION = "1.0.0"
SERVICE = "ARPWatch"

STATE_FILE = "/var/lib/check_mk_agent/arp_watch_state.json"
# Numero di check consecutivi prima di promuovere un host a "noto" (no più WARNING)
LEARN_THRESHOLD = 3


def get_arp_table() -> Dict[str, str]:
    """
    Legge la ARP table dal kernel via 'ip neigh show'.
    Ritorna dict {ip: mac} solo per entry REACHABLE/STALE/DELAY/PROBE.
    """
    result: Dict[str, str] = {}
    try:
        proc = subprocess.run(
            ["ip", "neigh", "show"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        for line in proc.stdout.splitlines():
            # Es: "10.155.100.1 dev eth0 lladdr aa:bb:cc:dd:ee:ff REACHABLE"
            m = re.match(
                r"^(\d+\.\d+\.\d+\.\d+)\s+dev\s+\S+\s+lladdr\s+([0-9a-f:]{17})\s+(\w+)",
                line.strip(),
                re.IGNORECASE,
            )
            if m:
                ip, mac, state = m.group(1), m.group(2).lower(), m.group(3).upper()
                if state in ("REACHABLE", "STALE", "DELAY", "PROBE", "PERMANENT"):
                    result[ip] = mac
    except Exception:
        pass
    return result


def load_state() -> dict:
    """Carica la baseline dal file JSON."""
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state: dict) -> None:
    """Salva la baseline su file JSON."""
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


def main() -> int:
    arp_table = get_arp_table()

    if not arp_table:
        print(f"3 {SERVICE} - UNKNOWN: impossibile leggere ARP table (ip neigh show fallito)")
        return 0

    state = load_state()
    now = datetime.now().isoformat(timespec="seconds")

    spoofed = []   # CRITICAL
    new_hosts = [] # WARNING (non ancora promossi)
    known = 0

    for ip, mac in arp_table.items():
        if ip not in state:
            # Nuovo host mai visto
            state[ip] = {"mac": mac, "seen": 1, "first_seen": now}
            new_hosts.append((ip, mac))
        else:
            entry = state[ip]
            if entry["mac"] != mac:
                # MAC cambiato → spoofing
                spoofed.append((ip, entry["mac"], mac))
                # Aggiorna comunque il MAC (per non lanciare alert infiniti)
                state[ip]["mac"] = mac
                state[ip]["seen"] = 1
                state[ip]["first_seen"] = now
            else:
                # Host noto, incrementa contatore
                entry["seen"] = entry.get("seen", 0) + 1
                if entry["seen"] >= LEARN_THRESHOLD:
                    known += 1
                else:
                    new_hosts.append((ip, mac))

    save_state(state)

    total = len(arp_table)

    # Determina stato finale
    if spoofed:
        details = "; ".join(
            f"SPOOFING {ip}: {old} -> {new}" for ip, old, new in spoofed
        )
        print(
            f"2 {SERVICE} - {details} | "
            f"spoofed={len(spoofed)} new={len(new_hosts)} known={known} total={total}"
        )
    elif new_hosts:
        details = ", ".join(f"{ip} ({mac})" for ip, mac in new_hosts[:5])
        if len(new_hosts) > 5:
            details += f" +{len(new_hosts)-5} altri"
        print(
            f"1 {SERVICE} - {len(new_hosts)} nuovo/i: {details} | "
            f"spoofed=0 new={len(new_hosts)} known={known} total={total}"
        )
    else:
        print(
            f"0 {SERVICE} - OK: {known} host noti, nessuna anomalia | "
            f"spoofed=0 new=0 known={known} total={total}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
