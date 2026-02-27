#!/usr/bin/env python3
"""
check_wan_throughput.py - CheckMK Local Check per throughput WAN su NethSecurity 8

Misura il throughput RX/TX sull'interfaccia WAN in Mbps.
Usa ubus per rilevare l'interfaccia WAN (via default route 0.0.0.0)
e leggere i contatori rx_bytes/tx_bytes da statistics.

Stato persistente salvato in /tmp/wan_throughput_state.json.
Prima esecuzione: inizializza stato e output WARNING "Initializing".

Version: 1.0.0
"""

import json
import os
import subprocess
import sys
import time
from typing import Optional, Tuple

SCRIPT_VERSION = "1.0.0"
SERVICE = "WAN_Throughput"
STATE_FILE = "/tmp/wan_throughput_state.json"


def run_command(cmd: list) -> Tuple[int, str, str]:
    """Esegui comando e ritorna (exit_code, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return 1, "", "Command timeout"
    except FileNotFoundError:
        return 127, "", f"Command not found: {cmd[0]}"
    except Exception as e:
        return 1, "", str(e)


def get_wan_interface() -> Optional[str]:
    """
    Rileva il nome dell'interfaccia WAN cercando la default route (0.0.0.0)
    nel dump di ubus. Fallback su prefissi comuni wan/wwan/vwan.
    """
    rc, out, err = run_command(["ubus", "call", "network.interface", "dump"])
    if rc != 0 or not out:
        return None

    try:
        data = json.loads(out)
        interfaces = data.get("interface", [])

        # Prima passata: cerca interfaccia con route target 0.0.0.0
        for iface in interfaces:
            routes = iface.get("route", [])
            for route in routes:
                if route.get("target") == "0.0.0.0":
                    return iface.get("interface")

        # Fallback: cerca per prefissi comuni
        for iface in interfaces:
            name = iface.get("interface", "")
            if name.lower().startswith(("wan", "wwan", "vwan")):
                return name

    except (json.JSONDecodeError, KeyError):
        pass

    return None


def get_iface_bytes(iface_name: str) -> Optional[Tuple[int, int]]:
    """
    Legge rx_bytes e tx_bytes dall'interfaccia via ubus.
    Ritorna (rx_bytes, tx_bytes) oppure None se non disponibile.
    """
    rc, out, err = run_command(["ubus", "call", f"network.interface.{iface_name}", "status"])
    if rc != 0 or not out:
        return None

    try:
        data = json.loads(out)
        stats = data.get("statistics", {})
        rx = stats.get("rx_bytes")
        tx = stats.get("tx_bytes")
        if rx is not None and tx is not None:
            return int(rx), int(tx)
    except (json.JSONDecodeError, KeyError, ValueError):
        pass

    return None


def load_state() -> Optional[dict]:
    """Carica stato precedente da file JSON."""
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r") as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError):
        pass
    return None


def save_state(iface: str, rx_bytes: int, tx_bytes: int, timestamp: float) -> None:
    """Salva stato corrente su file JSON."""
    state = {
        "iface": iface,
        "rx_bytes": rx_bytes,
        "tx_bytes": tx_bytes,
        "timestamp": timestamp
    }
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except IOError:
        pass


def bytes_to_mbps(delta_bytes: int, delta_seconds: float) -> float:
    """Converti delta bytes in Mbps."""
    if delta_seconds <= 0:
        return 0.0
    return (delta_bytes * 8) / (delta_seconds * 1_000_000)


def main() -> int:
    # 1. Trova interfaccia WAN
    iface = get_wan_interface()
    if not iface:
        print(f"2 {SERVICE} rx_mbps=0 tx_mbps=0 - No WAN interface found [v{SCRIPT_VERSION}]")
        return 0

    # 2. Leggi contatori attuali
    now = time.time()
    counters = get_iface_bytes(iface)
    if counters is None:
        print(f"3 {SERVICE} rx_mbps=0 tx_mbps=0 - Cannot read bytes for {iface} [v{SCRIPT_VERSION}]")
        return 0

    rx_now, tx_now = counters

    # 3. Carica stato precedente
    state = load_state()

    # Prima esecuzione o interfaccia cambiata: inizializza
    if state is None or state.get("iface") != iface:
        save_state(iface, rx_now, tx_now, now)
        print(f"1 {SERVICE} rx_mbps=0 tx_mbps=0 - {iface}: Initializing, wait next check [v{SCRIPT_VERSION}]")
        return 0

    # 4. Calcola delta
    delta_seconds = now - state["timestamp"]
    if delta_seconds < 1:
        # Esecuzioni troppo ravvicinate
        save_state(iface, rx_now, tx_now, now)
        print(f"1 {SERVICE} rx_mbps=0 tx_mbps=0 - {iface}: Interval too short ({delta_seconds:.1f}s) [v{SCRIPT_VERSION}]")
        return 0

    rx_prev = state["rx_bytes"]
    tx_prev = state["tx_bytes"]

    # Gestisci counter wrap (32-bit: max ~4GB, 64-bit: molto maggiore)
    delta_rx = rx_now - rx_prev if rx_now >= rx_prev else rx_now
    delta_tx = tx_now - tx_prev if tx_now >= tx_prev else tx_now

    rx_mbps = bytes_to_mbps(delta_rx, delta_seconds)
    tx_mbps = bytes_to_mbps(delta_tx, delta_seconds)

    # 5. Salva nuovo stato
    save_state(iface, rx_now, tx_now, now)

    # 6. Output CheckMK
    # Soglie: WARNING a 80 Mbps, CRITICAL a 95 Mbps (su 100 Mbps tipici)
    warn_mbps = 80
    crit_mbps = 95

    state_code = 0
    if rx_mbps >= crit_mbps or tx_mbps >= crit_mbps:
        state_code = 2
    elif rx_mbps >= warn_mbps or tx_mbps >= warn_mbps:
        state_code = 1

    perfdata = (
        f"rx_mbps={rx_mbps:.2f};{warn_mbps};{crit_mbps};0 "
        f"tx_mbps={tx_mbps:.2f};{warn_mbps};{crit_mbps};0"
    )

    print(
        f"{state_code} {SERVICE} {perfdata} - "
        f"{iface}: RX={rx_mbps:.2f} Mbps TX={tx_mbps:.2f} Mbps "
        f"(interval {delta_seconds:.0f}s) [v{SCRIPT_VERSION}]"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
