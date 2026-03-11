#!/usr/bin/env python3
"""
check_tmate_session.py - CheckMK Local Check per sessione tmate attiva

Legge il token SSH da /run/tmate-ssh.txt e lo espone come servizio
CheckMK, mostrando la stringa di connessione nella dashboard.

Version: 1.1.0
"""

import sys
import os
import socket
import subprocess

VERSION = "1.1.0"
SERVICE = "Tmate.Session"
TOKEN_FILE = "/run/tmate-ssh.txt"


def get_hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


def main() -> int:
    hostname = get_hostname()

    # Verifica che tmate sia in esecuzione
    try:
        result = subprocess.run(["pgrep", "-x", "tmate"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        tmate_running = result.returncode == 0
    except Exception:
        tmate_running = False

    if not tmate_running:
        print(f"2 {SERVICE} - CRITICAL: [{hostname}] tmate non in esecuzione")
        return 0

    # Leggi token
    if not os.path.exists(TOKEN_FILE):
        print(f"1 {SERVICE} - WARNING: [{hostname}] tmate in esecuzione ma token non ancora disponibile")
        return 0

    try:
        token = open(TOKEN_FILE).read().strip()
    except Exception as e:
        print(f"2 {SERVICE} - CRITICAL: [{hostname}] impossibile leggere {TOKEN_FILE}: {e}")
        return 0

    if not token:
        print(f"1 {SERVICE} - WARNING: [{hostname}] tmate in esecuzione ma token vuoto")
        return 0

    print(f"0 {SERVICE} - OK: [{hostname}] {token}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
