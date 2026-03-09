#!/usr/bin/env python3
"""
check_network_ports.py - CheckMK Local Check Network Ports Monitoring (Copilot)

Monitora le porte in ascolto con rilevamento anomalie.
Prima esecuzione: crea baseline delle porte attuali.
Esecuzioni successive: alert su nuove porte non in baseline.

Alert speciali:
  - CRITICAL: porta C2 nota in ascolto (4444, 1337, 31337, 6667, ...)
  - CRITICAL: connessione ESTABLISHED verso porta C2
  - CRITICAL: nuova porta in ascolto su tutte le interfacce (non in baseline)
  - WARNING:  nuova porta in ascolto su loopback (anomalia meno critica)
  - OK:       solo porte note dalla baseline

STATE: /var/lib/check_mk_agent/network_ports.state.json

Porte attese su questo server (baseline iniziale):
  - 22    (SSH)
  - 25    (SMTP postfix, loopback)
  - 80    (HTTP Apache)
  - 111   (rpcbind)
  - 443   (HTTPS Apache)
  - 4369  (epmd Erlang)
  - 5000  (Apache local proxy, loopback)
  - 6556  (CheckMK agent)
  - 8000  (gunicorn)

Version: 1.0.0
"""

import json
import os
import subprocess
import sys
import time
from typing import Dict, List, Optional, Set, Tuple

VERSION = "1.0.0"
SERVICE = "Security.NetworkPorts"
STATE_FILE = "/var/lib/check_mk_agent/network_ports.state.json"

# Porte C2 note — CRITICAL se in ascolto o se si tenta connessione verso di esse
C2_PORTS: Set[int] = {
    4444, 1337, 31337, 6667, 6697, 9001, 9030,  # common C2
    1234, 4321, 5555, 7777, 8080, 3333, 8888,   # common shells
    2222, 6000, 6001, 6002,                      # backdoors
}

# Porte "pericolose" rilevate nella ricognizione — WARNING se in ascolto su 0.0.0.0
RISKY_EXPOSED = {111, 4369}


def parse_ss_listen() -> List[Dict]:
    """Parsing delle porte in ascolto via ss -tlnpu."""
    ports = []
    try:
        result = subprocess.run(
            ["ss", "-tlnpu"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        for line in result.stdout.splitlines():
            if "LISTEN" not in line:
                continue
            parts = line.split()
            if len(parts) < 5:
                continue
            proto = parts[0]  # tcp / udp
            local_addr = parts[4]  # [::]:443 or 0.0.0.0:443 or 127.0.0.1:25

            # Estrai porta
            if local_addr.startswith("["):
                # IPv6: [::]:port
                port_str = local_addr.split(":")[-1]
                addr = "[::]"
            elif ":" in local_addr:
                addr, port_str = local_addr.rsplit(":", 1)
            else:
                continue

            try:
                port = int(port_str)
            except ValueError:
                continue

            loopback = addr in ("127.0.0.1", "::1", "[::1]")
            all_ifaces = addr in ("0.0.0.0", "::", "[::]", "*")

            ports.append({
                "port": port,
                "proto": proto,
                "addr": addr,
                "loopback": loopback,
                "all_ifaces": all_ifaces,
                "key": f"{proto}:{port}:{addr}",
            })
    except Exception:
        pass
    return ports


def parse_ss_established() -> List[Dict]:
    """Connessioni ESTABLISHED (cerchiamo destinazioni sospette)."""
    conns = []
    try:
        result = subprocess.run(
            ["ss", "-tnp", "state", "established"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        for line in result.stdout.splitlines():
            if not line.strip() or line.startswith("Recv-Q"):
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            peer = parts[3]  # remote addr:port
            if ":" in peer:
                peer_port_str = peer.rsplit(":", 1)[-1]
                try:
                    peer_port = int(peer_port_str)
                    conns.append({"peer": peer, "peer_port": peer_port})
                except ValueError:
                    pass
    except Exception:
        pass
    return conns


def load_baseline() -> Optional[dict]:
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return None


def save_baseline(ports: List[Dict], timestamp: float) -> None:
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        baseline_keys = [p["key"] for p in ports]
        with open(STATE_FILE, "w") as f:
            json.dump({"timestamp": timestamp, "ports": baseline_keys}, f, indent=2)
    except Exception:
        pass


def main() -> int:
    now = time.time()
    current_ports = parse_ss_listen()
    established = parse_ss_established()

    # --- Controlla connessioni ESTABLISHED verso porte C2 ---
    c2_conns = [c for c in established if c["peer_port"] in C2_PORTS]

    # --- Carica baseline ---
    baseline_data = load_baseline()

    if baseline_data is None:
        # Prima esecuzione: salva baseline
        save_baseline(current_ports, now)
        # Segnala porte esposte ma non blocca
        exposed = [p for p in current_ports if p["all_ifaces"]]
        exposed_str = ", ".join(str(p["port"]) for p in sorted(exposed, key=lambda x: x["port"]))
        print(
            f"0 {SERVICE} - OK: baseline creata ({len(current_ports)} porte). "
            f"Esposte: {exposed_str} "
            f"| listening={len(current_ports)} exposed={len(exposed)} new=0 c2=0"
        )
        return 0

    baseline_keys: Set[str] = set(baseline_data.get("ports", []))
    baseline_age_h = (now - baseline_data.get("timestamp", now)) / 3600

    # Aggiorna sempre la baseline con lo stato corrente
    save_baseline(current_ports, now)

    # Trova porte nuove (non nella baseline)
    current_keys = {p["key"] for p in current_ports}
    new_keys = current_keys - baseline_keys
    new_ports = [p for p in current_ports if p["key"] in new_keys]

    # Classifica nuove porte
    new_c2 = [p for p in new_ports if p["port"] in C2_PORTS]
    new_exposed = [p for p in new_ports if p["all_ifaces"] and p["port"] not in C2_PORTS]
    new_loopback = [p for p in new_ports if p["loopback"] and p["port"] not in C2_PORTS]

    total_listening = len(current_ports)
    exposed_count = sum(1 for p in current_ports if p["all_ifaces"])
    perf = (
        f"listening={total_listening} "
        f"exposed={exposed_count} "
        f"new={len(new_ports)} "
        f"c2={len(c2_conns)}"
    )

    # CRITICAL: connessioni attive verso C2
    if c2_conns:
        targets = ", ".join(c["peer"] for c in c2_conns[:3])
        print(f"2 {SERVICE} - CRITICAL: connessioni C2 attive: {targets} | {perf}")
        return 0

    # CRITICAL: porte C2 in ascolto
    if new_c2:
        ports_str = ", ".join(str(p["port"]) for p in new_c2)
        print(f"2 {SERVICE} - CRITICAL: porte C2 in ascolto: {ports_str} | {perf}")
        return 0

    # CRITICAL: nuove porte esposte su 0.0.0.0 (backdoor nuova)
    if new_exposed:
        risky = [p for p in new_exposed if p["port"] in RISKY_EXPOSED]
        normal_new = [p for p in new_exposed if p["port"] not in RISKY_EXPOSED]
        if normal_new:
            ports_str = ", ".join(f"{p['port']}/{p['proto']}" for p in normal_new[:5])
            print(
                f"2 {SERVICE} - CRITICAL: nuove porte esposte: {ports_str} | {perf}"
            )
            return 0
        if risky:
            ports_str = ", ".join(f"{p['port']}" for p in risky[:3])
            print(
                f"1 {SERVICE} - WARNING: porte rischiose ora in ascolto: {ports_str} | {perf}"
            )
            return 0

    # WARNING: nuove porte loopback (meno critico)
    if new_loopback:
        ports_str = ", ".join(f"{p['port']}/{p['proto']}" for p in new_loopback[:5])
        print(
            f"1 {SERVICE} - WARNING: nuove porte loopback: {ports_str} | {perf}"
        )
        return 0

    # OK
    age_str = f"{baseline_age_h:.0f}h fa"
    print(
        f"0 {SERVICE} - OK: {total_listening} porte note "
        f"(baseline {age_str}) | {perf}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
