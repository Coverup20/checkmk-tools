#!/usr/bin/env python3
"""
check_tmate_server.py - CheckMK Local Check per il SERVER tmate

Gira SOLO sul server tmate (checkmk-vps-02 / monitor01).
Mostra TUTTI gli host client connessi con il loro SSH token completo,
leggendo i file in /opt/tmate-tokens/<hostname>.txt (scritti dai client
via push SSH al momento della connessione).
Per ogni client mostra anche se un viewer e' attualmente connesso.

Prerequisiti:
  - /opt/tmate-tokens/ con file token per ogni client (setup-tmate-token-push.sh)
  - tmate-token.service su ogni client configurato per pushare il token

Output:
  OK      = host connessi, nessun viewer
  WARNING = qualcuno sta visualizzando una sessione (viewer connesso)
  CRITICAL = nessun host connesso

Version: 1.0.0
"""

import sys
import os
import subprocess
import glob
import re
import time

VERSION = "1.0.0"
SERVICE = "Tmate.Clients"
TOKENS_DIR = "/opt/tmate-tokens"
TOKEN_MAX_AGE = 600  # 10 minuti - token piu' vecchi considerati stale


def get_active_sessions() -> dict:
    """
    Legge i processi tmate-ssh-server attivi e i log per ottenere
    { token_prefix -> {nodename, ip, pid, viewers} }
    """
    sessions = {}

    # Legge processi attivi: tmate-ssh-server [XXXX...] (daemon) IP
    try:
        result = subprocess.run(
            ["ps", "ax", "--no-header", "-o", "pid=,args="],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            m = re.search(r'^\s*(\d+)\s+tmate-ssh-server \[(\w+)\.\.\.\] \(daemon\) (\S+)', line)
            if m:
                pid, prefix, ip = m.group(1), m.group(2), m.group(3)
                sessions[prefix] = {'pid': pid, 'ip': ip, 'nodename': None, 'viewers': 0}
    except Exception:
        pass

    if not sessions:
        return sessions

    # Dal journal: ottieni nodename e conteggio viewer per ogni sessione attiva
    try:
        result = subprocess.run(
            ["journalctl", "-u", "tmate-ssh-server", "--no-pager", "-n", "500"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=10
        )
        # Track viewer state per prefix
        viewer_state = {p: 0 for p in sessions}
        for line in result.stdout.splitlines():
            # Spawning daemon: prende nodename
            m = re.search(r'\[(\w+)\.\.\.\].*nodename=(\S+)', line)
            if m and m.group(1) in sessions:
                sessions[m.group(1)]['nodename'] = m.group(2)
            # Client joined
            m = re.search(r'\[(\w+)\.\.\.\] Client joined', line)
            if m and m.group(1) in viewer_state:
                viewer_state[m.group(1)] += 1
            # Client left
            m = re.search(r'\[(\w+)\.\.\.\] Client left', line)
            if m and m.group(1) in viewer_state:
                viewer_state[m.group(1)] = max(0, viewer_state[m.group(1)] - 1)
        for prefix in sessions:
            sessions[prefix]['viewers'] = viewer_state.get(prefix, 0)
    except Exception:
        pass

    return sessions


def read_token_files() -> dict:
    """
    Legge /opt/tmate-tokens/<hostname>.txt scritti dai client.
    Ignora file piu' vecchi di TOKEN_MAX_AGE secondi.
    Returna { hostname -> token_ssh_string }
    """
    tokens = {}
    now = time.time()
    for path in glob.glob(os.path.join(TOKENS_DIR, "*.txt")):
        # Salta chiavi SSH (receiver_key.pub etc.)
        if "receiver_key" in path:
            continue
        try:
            mtime = os.path.getmtime(path)
            if now - mtime > TOKEN_MAX_AGE:
                continue
            hostname = os.path.basename(path).replace('.txt', '')
            token = open(path).read().strip()
            if token and token.startswith("ssh "):
                tokens[hostname] = token
        except Exception:
            pass
    return tokens


def main() -> int:
    sessions = get_active_sessions()
    token_files = read_token_files()

    if not sessions and not token_files:
        print(f"2 {SERVICE} - CRITICAL: nessun host connesso al server tmate")
        return 0

    # Combina: per ogni sessione attiva, cerca il token completo
    parts = []
    total_viewers = 0

    for prefix, sess in sorted(sessions.items(), key=lambda x: x[1].get('nodename') or x[1]['ip']):
        nodename = sess.get('nodename') or sess['ip']
        token = token_files.get(nodename)
        viewers = sess.get('viewers', 0)
        total_viewers += viewers

        viewer_str = " [VIEWER CONNESSO]" if viewers > 0 else ""
        if token:
            parts.append(f"{nodename}: {token}{viewer_str}")
        else:
            # Token non ancora ricevuto (client non ha ancora pushato)
            parts.append(f"{nodename}: [token in attesa...]{viewer_str}")

    # Aggiungi anche token ricevuti da host non piu' nel ps (connessione persa da poco)
    active_nodenames = {s.get('nodename') or s['ip'] for s in sessions.values()}
    for hostname, token in sorted(token_files.items()):
        if hostname not in active_nodenames:
            parts.append(f"{hostname}: {token} [DISCONNESSO - token valido]")

    if not parts:
        print(f"1 {SERVICE} - WARNING: dati insufficienti")
        return 0

    msg = " | ".join(parts)
    n = len(sessions)

    if total_viewers > 0:
        print(f"1 {SERVICE} - WARNING: {total_viewers} viewer connesso - {msg}")
    else:
        print(f"0 {SERVICE} - OK: {n} host connessi - {msg}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
