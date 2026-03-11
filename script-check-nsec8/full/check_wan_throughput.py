#!/usr/bin/env python3
"""
check_wan_throughput.py - CheckMK Local Check per throughput WAN su NethSecurity 8

Misura il throughput RX/TX sull'interfaccia WAN in Mbps.
Usa ubus dump per rilevare l'interfaccia WAN (via default route 0.0.0.0)
e leggere i contatori rx_bytes/tx_bytes.

Strategia lettura bytes (in ordine di priorità):
1. statistics nel dump ubus (rx_bytes/tx_bytes)
2. /proc/net/dev via campo "device" nel dump (interfaccia fisica sottostante)

Stato persistente salvato in /tmp/wan_throughput_state.json.
Prima esecuzione: inizializza stato e output WARNING "Initializing".

Version: 1.1.0
"""

import json
import os
import subprocess
import sys
import time
from typing import Optional, Tuple

SCRIPT_VERSION = "1.1.0"
SERVICE = "WAN.Throughput"
STATE_FILE = "/tmp/wan_throughput_state.json"
PROC_NET_DEV = "/proc/net/dev"


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


def get_proc_net_dev_bytes(device: str) -> Optional[Tuple[int, int]]:
    """
    Legge rx_bytes e tx_bytes da /proc/net/dev per il device fisico specificato.
    Formato righe: Interface: rx_bytes rx_packets ... tx_bytes tx_packets ...
    """
    try:
        with open(PROC_NET_DEV, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith(device + ":"):
                    # Rimuovi "device:" e splitta
                    parts = line.split(":", 1)[1].split()
                    # Colonne: [0]=rx_bytes [1]=rx_packets ... [8]=tx_bytes ...
                    if len(parts) >= 9:
                        return int(parts[0]), int(parts[8])
    except (IOError, ValueError, IndexError):
        pass
    return None


def get_wan_info() -> Optional[Tuple[str, str, int, int]]:
    """
    Usa ubus dump per trovare interfaccia WAN e leggere i byte RX/TX.
    Ritorna (iface_name, device_name, rx_bytes, tx_bytes) oppure None.

    Strategia bytes:
    1. statistics.rx_bytes / statistics.tx_bytes dal dump
    2. /proc/net/dev via campo "device" (interfaccia fisica)
    """
    rc, out, err = run_command(["ubus", "call", "network.interface", "dump"])
    if rc != 0 or not out:
        return None

    try:
        data = json.loads(out)
        interfaces = data.get("interface", [])

        wan_iface = None
        wan_data = None

        # Prima passata: cerca interfaccia con default route
        for iface in interfaces:
            routes = iface.get("route", [])
            for route in routes:
                if route.get("target") == "0.0.0.0":
                    wan_iface = iface.get("interface", "")
                    wan_data = iface
                    break
            if wan_iface:
                break

        # Fallback su prefissi comuni
        if not wan_iface:
            for iface in interfaces:
                name = iface.get("interface", "")
                if name.lower().startswith(("wan", "wwan", "vwan")):
                    wan_iface = name
                    wan_data = iface
                    break

        if not wan_iface or wan_data is None:
            return None

        # Leggi device fisico
        device = wan_data.get("device", "")

        # Strategia 1: statistics nel dump
        stats = wan_data.get("statistics", {})
        rx = stats.get("rx_bytes")
        tx = stats.get("tx_bytes")
        if rx is not None and tx is not None:
            return wan_iface, device, int(rx), int(tx)

        # Strategia 2: /proc/net/dev via device fisico
        if device:
            result = get_proc_net_dev_bytes(device)
            if result is not None:
                return wan_iface, device, result[0], result[1]

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


def bytes_to_bps(delta_bytes: int, delta_seconds: float) -> float:
    """Converti delta bytes in bytes/s."""
    if delta_seconds <= 0:
        return 0.0
    return delta_bytes / delta_seconds


def fmt_bps(bps: float) -> str:
    """Formatta bytes/s in formato human-readable (B/s, KiB/s, MiB/s, GiB/s)."""
    if bps < 1024:
        return f"{bps:.1f} B/s"
    elif bps < 1024 ** 2:
        return f"{bps / 1024:.1f} KiB/s"
    elif bps < 1024 ** 3:
        return f"{bps / 1024 ** 2:.2f} MiB/s"
    else:
        return f"{bps / 1024 ** 3:.2f} GiB/s"


def get_device_speed_mbps(device: str) -> int:
    """Legge velocità interfaccia in Mbps da sysfs. Fallback: 1000 Mbps."""
    try:
        with open(f"/sys/class/net/{device}/speed") as f:
            speed = int(f.read().strip())
            return speed if speed > 0 else 1000
    except Exception:
        return 1000


def main() -> int:
    # 1. Trova interfaccia WAN e leggi contatori attuali
    now = time.time()
    wan_info = get_wan_info()
    if wan_info is None:
        print(f"2 {SERVICE} - No WAN interface or bytes not available [v{SCRIPT_VERSION}] | in_traffic=0 out_traffic=0")
        return 0

    iface, device, rx_now, tx_now = wan_info

    # 3. Carica stato precedente
    state = load_state()

    # Prima esecuzione o interfaccia cambiata: inizializza
    if state is None or state.get("iface") != iface:
        save_state(iface, rx_now, tx_now, now)
        print(f"0 {SERVICE} - [{iface}], (up), Initializing, wait next check [v{SCRIPT_VERSION}] | in_traffic=0 out_traffic=0")
        return 0

    # 4. Calcola delta
    delta_seconds = now - state["timestamp"]
    if delta_seconds < 1:
        save_state(iface, rx_now, tx_now, now)
        print(f"0 {SERVICE} - [{iface}], (up), Interval too short ({delta_seconds:.1f}s) | in_traffic=0 out_traffic=0")
        return 0

    rx_prev = state["rx_bytes"]
    tx_prev = state["tx_bytes"]

    # Gestisci counter wrap
    delta_rx = rx_now - rx_prev if rx_now >= rx_prev else rx_now
    delta_tx = tx_now - tx_prev if tx_now >= tx_prev else tx_now

    rx_bps = bytes_to_bps(delta_rx, delta_seconds)
    tx_bps = bytes_to_bps(delta_tx, delta_seconds)

    # 5. Salva nuovo stato
    save_state(iface, rx_now, tx_now, now)

    # 6. Velocità interfaccia e percentuale utilizzo
    speed_mbps = get_device_speed_mbps(device or iface)
    speed_bps = speed_mbps * 125_000  # Mbps → bytes/s
    if speed_mbps >= 1000:
        speed_str = f"{speed_mbps // 1000} GBit/s"
    else:
        speed_str = f"{speed_mbps} MBit/s"

    rx_pct = (rx_bps / speed_bps * 100) if speed_bps > 0 else 0.0
    tx_pct = (tx_bps / speed_bps * 100) if speed_bps > 0 else 0.0

    # Soglie in bytes/s (WARNING 80%, CRITICAL 95% della velocità linea)
    warn_bps = speed_bps * 0.80
    crit_bps = speed_bps * 0.95

    state_code = 0
    if rx_bps >= crit_bps or tx_bps >= crit_bps:
        state_code = 2
    elif rx_bps >= warn_bps or tx_bps >= warn_bps:
        state_code = 1

    print(
        f"{state_code} {SERVICE} - "
        f"[{iface}], (up), Speed: {speed_str}, "
        f"In: {fmt_bps(rx_bps)} ({rx_pct:.2f}%), "
        f"Out: {fmt_bps(tx_bps)} ({tx_pct:.2f}%)"
        f" | in_traffic={rx_bps:.2f};{warn_bps:.0f};{crit_bps:.0f};0 "
        f"out_traffic={tx_bps:.2f};{warn_bps:.0f};{crit_bps:.0f};0"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
