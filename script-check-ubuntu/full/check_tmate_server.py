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
from typing import Optional

VERSION = "1.1.1"
EXCLUDE_IPS = {"127.0.0.1", "::1"}  # esclude il server stesso
SERVICE = "Tmate.Clients"
TOKENS_DIR = "/opt/tmate-tokens"
TOKEN_MAX_AGE = 7200  # 2 ore - token piu' vecchi considerati stale


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
                if ip in EXCLUDE_IPS:
                    continue  # salta il server stesso (127.0.0.1)
                sessions[prefix] = {'pid': pid, 'ip': ip, 'nodename': None, 'viewers': 0}
    except Exception:
        pass

    if not sessions:
        return sessions

    # Dal journal: ottieni nodename e conteggio viewer per ogni sessione attiva
    try:
        result = subprocess.run(
            ["journalctl", "-u", "tmate-ssh-server", "--no-pager", "-n", "2000"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=10
        )
        # Track viewer state per prefix - conta solo DOPO "Spawning daemon" della sessione corrente
        viewer_state = {p: 0 for p in sessions}
        spawn_seen = {p: False for p in sessions}
        for line in result.stdout.splitlines():
            # Spawning daemon: marca inizio sessione corrente e prende nodename
            m = re.search(r'\[(\w+)\.\.\.\].*nodename=(\S+)', line)
            if m and m.group(1) in sessions:
                sessions[m.group(1)]['nodename'] = m.group(2)
                # Reset contatore al momento dello spawn (ignora eventi di sessioni precedenti)
                spawn_seen[m.group(1)] = True
                viewer_state[m.group(1)] = 0
                continue
            # Client joined - solo se la sessione corrente e' gia' stata vista
            m = re.search(r'\[(\w+)\.\.\.\] Client joined', line)
            if m and m.group(1) in viewer_state and spawn_seen.get(m.group(1)):
                viewer_state[m.group(1)] += 1
            # Client left - solo se la sessione corrente e' gia' stata vista
            m = re.search(r'\[(\w+)\.\.\.\] Client left', line)
            if m and m.group(1) in viewer_state and spawn_seen.get(m.group(1)):
                viewer_state[m.group(1)] = max(0, viewer_state[m.group(1)] - 1)
        for prefix in sessions:
            sessions[prefix]['viewers'] = viewer_state.get(prefix, 0)
    except Exception:
        pass

    return sessions


def read_token_files(active_ips: set = None) -> dict:
    """
    Legge /opt/tmate-tokens/<hostname>.txt scritti dai client.
    Per file il cui nome corrisponde a un IP attivo (in active_ips) ignora TOKEN_MAX_AGE.
    Per gli altri (host offline da poco) applica il limite di eta'.
    Returna { hostname -> token_ssh_string }
    """
    tokens = {}
    now = time.time()
    if active_ips is None:
        active_ips = set()
    for path in glob.glob(os.path.join(TOKENS_DIR, "*.txt")):
        # Salta chiavi SSH (receiver_key.pub etc.)
        if "receiver_key" in path:
            continue
        try:
            hostname = os.path.basename(path).replace('.txt', '')
            mtime = os.path.getmtime(path)
            # Se l'host e' attivo in ps, ignora l'eta' del file
            if hostname not in active_ips and now - mtime > TOKEN_MAX_AGE:
                continue
            token = open(path).read().strip()
            if token and token.startswith("ssh "):
                tokens[hostname] = token
        except Exception:
            pass
    return tokens


def get_local_token() -> Optional[str]:
    """Legge il token della sessione tmate locale (il server stesso)."""
    sock = "/run/tmate/tmate.sock"
    if not os.path.exists(sock):
        return None
    try:
        result = subprocess.run(
            ["tmate", "-S", sock, "display", "-p", "#{tmate_ssh}"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=5
        )
        token = result.stdout.strip()
        return token if token.startswith("ssh ") else None
    except Exception:
        return None


def main() -> int:
    sessions = get_active_sessions()
    active_ips = {sess['ip'] for sess in sessions.values() if sess.get('ip')}
    token_files = read_token_files(active_ips)

    # Normalizza: risolve chiavi IP -> hostname usando i dati di sessione
    ip_to_hostname = {
        sess['ip']: (sess.get('nodename') or sess['ip'])
        for sess in sessions.values() if sess.get('ip')
    }
    normalized_tokens = {}
    for key, token in token_files.items():
        resolved = ip_to_hostname.get(key, key)
        normalized_tokens[resolved] = token
    token_files = normalized_tokens

    if not sessions and not token_files:
        print(f"2 {SERVICE} - CRITICAL: nessun host connesso al server tmate")
        return 0

    # Una riga per host attivo
    active_nodenames = set()
    for prefix, sess in sorted(sessions.items(), key=lambda x: x[1].get('nodename') or x[1]['ip']):
        nodename = sess.get('nodename') or sess['ip']
        active_nodenames.add(nodename)
        svc = f"Tmate.{nodename}"
        token = token_files.get(nodename) or token_files.get(sess['ip'])

        # Fallback: cerca per prefix nel contenuto dei file
        if not token:
            for _, t in token_files.items():
                m = re.search(r'ssh -p\d+ (\w+)@', t)
                if m and m.group(1).startswith(prefix):
                    token = t
                    break

        viewers = sess.get('viewers', 0)

        if viewers > 0:
            msg = f"{token} [VIEWER CONNESSO]" if token else "token atteso [VIEWER CONNESSO]"
            print(f"1 {svc} - WARNING: {msg}")
        elif not token:
            print(f"1 {svc} - WARNING: token atteso")
        else:
            print(f"0 {svc} - OK: {token}")

    # Host offline (token salvato ma non piu' in ps)
    for hostname, token in sorted(token_files.items()):
        if hostname not in active_nodenames:
            svc = f"Tmate.{hostname}"
            print(f"1 {svc} - WARNING: [offline] {token}")

    # Sessione locale del server stesso
    local_token = get_local_token()
    local_hostname = subprocess.run(
        ["hostname", "-s"], stdout=subprocess.PIPE, text=True
    ).stdout.strip() or "localhost"
    svc = f"Tmate.{local_hostname}"
    if local_token:
        # Sostituisce IP con FQDN nel token
        local_token_display = re.sub(r'@[\d.]+', '@monitor01.nethlab.it', local_token)
        print(f"0 {svc} - OK: {local_token_display}")
    else:
        print(f"1 {svc} - WARNING: sessione locale non attiva")

    return 0


if __name__ == "__main__":
    sys.exit(main())
