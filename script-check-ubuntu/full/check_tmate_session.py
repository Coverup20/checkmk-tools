#!/usr/bin/env python3
"""
check_tmate_session.py - CheckMK Local Check per sessioni tmate attive

Mostra tutti i token SSH delle sessioni tmate in esecuzione e i client
attualmente collegati (con IP/TTY), per identificare chi è connesso.

Version: 1.3.0
"""

import sys
import os
import socket
import subprocess
import glob
import re

VERSION = "1.3.0"
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


def get_clients_from_socket(sock: str) -> list:
    """
    Restituisce lista di client collegati al socket tmate.
    Output di list-clients: /dev/pts/0: 0 [80x24 xterm-256color] (utf8)
    Per client remoti tmate mostra l'IP nella parte iniziale.
    """
    clients = []
    try:
        result = subprocess.run(
            ["tmate", "-S", sock, "list-clients", "-F",
             "#{client_name} #{client_width}x#{client_height} #{client_termname}"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=5
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                line = line.strip()
                if line:
                    clients.append(line)
    except Exception:
        pass
    return clients


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

    sessions = []
    for sock in sockets:
        token = get_token_from_socket(sock)
        if not token:
            continue
        clients = get_clients_from_socket(sock)
        sessions.append((token, clients))

    # Fallback al file token se non trovato via socket
    if not sessions and os.path.exists(TOKEN_FILE):
        try:
            token = open(TOKEN_FILE).read().strip()
            if token:
                sessions.append((token, []))
        except Exception:
            pass

    if not sessions:
        print(f"1 {SERVICE} - WARNING: [{hostname}] tmate in esecuzione ma nessun token disponibile")
        return 0

    parts = []
    for token, clients in sessions:
        if clients:
            client_str = "clients: " + ", ".join(clients)
            parts.append(f"{token} [{client_str}]")
        else:
            parts.append(f"{token} [nessun client]")

    msg = " | ".join(parts)
    print(f"0 {SERVICE} - OK: [{hostname}] {msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
