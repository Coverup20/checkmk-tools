#!/usr/bin/env python3
"""check_wan_throughput.py - CheckMK WAN throughput check.

Uses /proc/net/route for default route, /proc/net/dev for byte counters.
State persistence via JSON file (/tmp/wan_throughput_state.json).
"""

import json
import sys
import time
from pathlib import Path

VERSION = "1.11.0"
SERVICE = "WAN.Throughput"
STATE_FILE = "/tmp/wan_throughput_state.json"
PROC_NET_DEV = "/proc/net/dev"

try:
    from euci import EUci
    EUCI_AVAILABLE = True
except ImportError:
    EUci = None
    EUCI_AVAILABLE = False


def get_wan_device():
    """Get primary WAN device using nethsec library.

    Primary: nethsec.inventory.get_networks() with role == "red"
    Fallback: /proc/net/route for backward compatibility
    """
    wan_iface = None

    # Method 1: Use nethsec library (primary, robust)
    if EUCI_AVAILABLE:
        try:
            from nethsec.inventory import get_networks
            with EUci() as u:
                networks = get_networks(u)
                for dev, net in networks.items():
                    if net.get("props", {}).get("role") == "red":
                        wan_iface = dev
                        break
                if wan_iface:
                    return wan_iface  # Success - don't fall through
        except (ImportError, Exception):
            pass

    # Method 2: Fallback to /proc/net/route only if library unavailable
    try:
        for line in Path("/proc/net/route").read_text().splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "00000000":
                wan_iface = parts[0].strip()
                if wan_iface:
                    return wan_iface
    except Exception:
        pass

    return wan_iface  # Return None if nothing found


def get_proc_net_dev_bytes(device):
    try:
        for line in Path(PROC_NET_DEV).read_text().splitlines():
            if line.startswith(device + ":"):
                parts = line.split(":", 1)[1].split()
                if len(parts) >= 9:
                    return int(parts[0]), int(parts[8])
    except Exception:
        pass
    return None


def get_device_speed(device):
    try:
        speed = int(Path(f"/sys/class/net/{device}/speed").read_text().strip())
        return speed if speed > 0 else 1000
    except Exception:
        return 1000


def load_state():
    try:
        if Path(STATE_FILE).exists():
            with open(STATE_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return None


def save_state(iface, rx, tx, ts):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({"iface": iface, "rx_bytes": rx, "tx_bytes": tx, "timestamp": ts}, f)
    except Exception:
        pass


def fmt_bps(bps):
    if bps < 1024:
        return f"{bps:.1f} B/s"
    elif bps < 1024 ** 2:
        return f"{bps / 1024:.1f} KiB/s"
    elif bps < 1024 ** 3:
        return f"{bps / 1024 ** 2:.2f} MiB/s"
    else:
        return f"{bps / 1024 ** 3:.2f} GiB/s"


def main():
    now = time.time()
    device = get_wan_device()
    if not device:
        print(f'2 "{SERVICE}" if_in_octets=0|if_out_octets=0 No WAN device found')
        return 0
    result = get_proc_net_dev_bytes(device)
    if result is None:
        print(f'2 "{SERVICE}" if_in_octets=0|if_out_octets=0 Cannot read counters for {device}')
        return 0
    rx_now, tx_now = result
    state = load_state()
    if state is None or state.get("iface") != device:
        save_state(device, rx_now, tx_now, now)
        print(f'1 "{SERVICE}" if_in_octets=0|if_out_octets=0 [{device}] Initializing')
        return 0
    delta_sec = now - state["timestamp"]
    if delta_sec < 1:
        save_state(device, rx_now, tx_now, now)
        print(f'0 "{SERVICE}" if_in_octets=0|if_out_octets=0 [{device}] Interval too short ({delta_sec:.1f}s)')
        return 0
    d_rx = rx_now - state["rx_bytes"] if rx_now >= state["rx_bytes"] else rx_now
    d_tx = tx_now - state["tx_bytes"] if tx_now >= state["tx_bytes"] else tx_now
    rx_bps = d_rx / delta_sec
    tx_bps = d_tx / delta_sec
    save_state(device, rx_now, tx_now, now)
    speed_mbps = get_device_speed(device)
    speed_bps = speed_mbps * 125_000
    speed_str = f"{speed_mbps // 1000} GBit/s" if speed_mbps >= 1000 else f"{speed_mbps} MBit/s"
    rx_pct = (rx_bps / speed_bps * 100) if speed_bps > 0 else 0.0
    tx_pct = (tx_bps / speed_bps * 100) if speed_bps > 0 else 0.0
    warn_bps = speed_bps * 0.80
    crit_bps = speed_bps * 0.95
    st = 2 if (rx_bps >= crit_bps or tx_bps >= crit_bps) else (1 if (rx_bps >= warn_bps or tx_bps >= warn_bps) else 0)
    print(
        f'{st} "{SERVICE}" if_in_octets={rx_bps:.2f}|if_out_octets={tx_bps:.2f} '
        f'[{device}] Speed: {speed_str}, In: {fmt_bps(rx_bps)} ({rx_pct:.2f}%), '
        f'Out: {fmt_bps(tx_bps)} ({tx_pct:.2f}%)'
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
