#!/usr/bin/env python3
"""
check_tmate_session.py - CheckMK Local Check per sessione tmate attiva

Legge il token SSH da /run/tmate-ssh.txt e lo espone come servizio
CheckMK, mostrando la stringa di connessione nella dashboard.

Version: 1.0.0
"""

import sys
import os
import subprocess

VERSION = "1.0.0"
SERVICE = "Tmate.Session"
TOKEN_FILE = "/run/tmate-ssh.txt"
SOCK = "/run/tmate/tmate.sock"


def main() -> int:
    # Verifica che tmate sia in esecuzione
    try:
        result = subprocess.run(["pgrep", "-x", "tmate"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        tmate_running = result.returncode == 0
    except Exception:
        tmate_running = False

    if not tmate_running:
        print(f"2 {SERVICE} - CRITICAL: tmate non in esecuzione")
        return 0

    # Leggi token
    if not os.path.exists(TOKEN_FILE):
        print(f"1 {SERVICE} - WARNING: tmate in esecuzione ma token non ancora disponibile ({TOKEN_FILE} assente)")
        return 0

    try:
        token = open(TOKEN_FILE).read().strip()
    except Exception as e:
        print(f"2 {SERVICE} - CRITICAL: impossibile leggere {TOKEN_FILE}: {e}")
        return 0

    if not token:
        print(f"1 {SERVICE} - WARNING: tmate in esecuzione ma token vuoto")
        return 0

    # Estrai host dal token (es: ssh -p10022 TOKEN@143.110.148.110)
    parts = token.split("@")
    host = parts[-1] if len(parts) > 1 else "unknown"

    print(f"0 {SERVICE} - OK: {token} | host={host}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
