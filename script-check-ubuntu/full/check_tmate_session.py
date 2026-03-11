#!/usr/bin/env python3
"""
check_tmate_session.py - CheckMK Local Check per sessioni tmate attive

Mostra tutti i token SSH delle sessioni tmate in esecuzione,
interrogando direttamente ogni socket tmate trovato nei processi attivi.

Version: 1.2.0
"""

import sys
import os
import socket
import subprocess
import glob

VERSION = "1.2.0"
SERVICE = "Tmate.Session"
TOKEN_FILE = "/run/tmate-ssh.txt"


def get_hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


def get_tmate_sockets() -> list:
    """Trova tutti i socket tmate attivi dai processi in esecuzione."""
    sockets = []
    try:
        result = subprocess.run(
            ["ps", "aux"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if "tmate" in line and "-S" in line and "grep" not in line:
                parts = line.split()
                for i, p in enumerate(parts):
                    if p == "-S" and i + 1 < len(parts):
                        sock = parts[i + 1]
                        if os.path.exists(sock):
                            sockets.append(sock)
    except Exception:
        pass

    # Fallback: cerca socket in posizioni standard
    if not sockets:
        for pattern in ["/run/tmate/*.sock", "/tmp/tmate-*.sock"]:
            sockets.extend(glob.glob(pattern))

    return list(set(sockets))


def get_token_from_socket(sock: str) -> str:
    """Legge il token SSH da un socket tmate."""
    try:
        result = subprocess.run(
            ["tmate", "-S", sock, "display", "-p", "#{tmate_ssh}"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=5
        )
        token = result.stdout.strip()
        if token and result.returncode == 0:
            return token
    except Exception:
        pass
    return ""


def main() -> int:
    hostname = get_hostname()

    # Verifica che tmate sia in esecuzione
    try:
        result = subprocess.run(["pgrep", "-x", "tmate"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        tmate_running = result.returncode == 0
    except Exception:
        tmate_running = False

    if not tmate_running:
        print(f"2 {SERVICE} - CRITICAL: [{hostname}] tmate non in esecuzione")
        return 0

    # Cerca tutti i socket attivi
    sockets = get_tmate_sockets()

    tokens = []
    for sock in sockets:
        token = get_token_from_socket(sock)
        if token:
            tokens.append(token)

    # Fallback al file token se non trovato via socket
    if not tokens and os.path.exists(TOKEN_FILE):
        try:
            token = open(TOKEN_FILE).read().strip()
            if token:
                tokens.append(token)
        except Exception:
            pass

    if not tokens:
        print(f"1 {SERVICE} - WARNING: [{hostname}] tmate in esecuzione ma nessun token disponibile")
        return 0

    if len(tokens) == 1:
        print(f"0 {SERVICE} - OK: [{hostname}] {tokens[0]}")
    else:
        token_list = " | ".join(tokens)
        print(f"0 {SERVICE} - OK: [{hostname}] {len(tokens)} sessioni: {token_list}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
