#!/usr/bin/env python3
"""check_wan_throughput.py - CheckMK WAN throughput check.

Uses /proc/net/route for default route, /proc/net/dev for byte counters.
State persistence via JSON file (/tmp/wan_throughput_state.json).
"""

import json
import re
import subprocess
import sys
import time
from pathlib import Path

VERSION = "1.12.0"
SERVICE = "WAN.Throughput"
STATE_FILE = "/tmp/wan_throughput_state.json"
PROC_NET_DEV = "/proc/net/dev"

try:
    from euci import EUci
    EUCI_AVAILABLE = True
except ImportError:
    EUci = None
    EUCI_AVAILABLE = False


def _ubus_interface_status(section):
    """Call `ubus call network.interface.<section> status` and return parsed JSON, or None."""
    try:
        result = subprocess.run(
            ["ubus", "call", f"network.interface.{section}", "status"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except Exception:
        pass
    return None


def _resolve_runtime_device(uci, section, configured_device):
    """Resolve the runtime device for a UCI interface section (see check_wan_status.py)."""
    status = _ubus_interface_status(section)
    if status:
        l3_device = status.get("l3_device")
        if l3_device:
            return l3_device
    return configured_device


def get_wan_device():
    """Get primary WAN device using nethsec library.

    Primary: nethsec.inventory.get_networks() with role == "red", resolved to
    its runtime device via ubus (handles PPPoE/dynamic protocols correctly).
    Fallback: /proc/net/route for backward compatibility
    """
    wan_iface = None

    # Method 1: Use nethsec library (primary, robust)
    if EUCI_AVAILABLE:
        try:
            from nethsec.inventory import get_networks
            from nethsec.utils import get_all_by_type
            with EUci() as u:
                networks = get_networks(u)
                for dev, net in networks.items():
                    if net.get("props", {}).get("role") != "red":
                        continue
                    section = None
                    for s in get_all_by_type(u, "network", "interface"):
                        if u.get("network", s, "device", default=None) == dev:
                            section = s
                            break
                    wan_iface = _resolve_runtime_device(u, section, dev) if section else dev
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
    """Return link speed in Mbps, or None if it cannot be determined.

    Does NOT default to a guessed value: a wrong assumed speed silently masks
    real saturation (thresholds become unreachable) or causes false alarms on
    devices without a meaningful /sys speed file (pppoe-*, virtual devices).
    """
    try:
        speed = int(Path(f"/sys/class/net/{device}/speed").read_text().strip())
        if speed > 0:
            return speed
    except Exception:
        pass
    try:
        result = subprocess.run(
            ["ethtool", device], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            m = re.search(r"Speed:\s*(\d+)Mb/s", result.stdout)
            if m:
                return int(m.group(1))
    except Exception:
        pass
    return None


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
        print(f'2 {SERVICE} if_in_octets=0|if_out_octets=0 No WAN device found')
        return 0
    result = get_proc_net_dev_bytes(device)
    if result is None:
        print(f'2 {SERVICE} if_in_octets=0|if_out_octets=0 Cannot read counters for {device}')
        return 0
    rx_now, tx_now = result
    state = load_state()
    if state is None or state.get("iface") != device:
        save_state(device, rx_now, tx_now, now)
        print(f'1 {SERVICE} if_in_octets=0|if_out_octets=0 [{device}] Initializing')
        return 0
    delta_sec = now - state["timestamp"]
    if delta_sec < 1:
        save_state(device, rx_now, tx_now, now)
        print(f'0 {SERVICE} if_in_octets=0|if_out_octets=0 [{device}] Interval too short ({delta_sec:.1f}s)')
        return 0
    if rx_now < state["rx_bytes"] or tx_now < state["tx_bytes"]:
        # Counter reset (driver reload/hotplug): the new counter value is NOT
        # a valid delta for this interval - computing "delta = new - 0" would
        # fabricate a bogus multi-gigabyte spike. Re-baseline instead.
        save_state(device, rx_now, tx_now, now)
        print(f'0 {SERVICE} if_in_octets=0|if_out_octets=0 [{device}] Counters reset, re-baselining')
        return 0
    d_rx = rx_now - state["rx_bytes"]
    d_tx = tx_now - state["tx_bytes"]
    rx_bps = d_rx / delta_sec
    tx_bps = d_tx / delta_sec
    save_state(device, rx_now, tx_now, now)
    speed_mbps = get_device_speed(device)
    if speed_mbps is None:
        # Unknown link speed: report raw throughput without a %-of-speed
        # threshold rather than assuming a default that could either mask
        # real saturation or make thresholds unreachable.
        print(
            f'0 {SERVICE} if_in_octets={rx_bps:.2f}|if_out_octets={tx_bps:.2f} '
            f'[{device}] Speed: unknown, In: {fmt_bps(rx_bps)}, Out: {fmt_bps(tx_bps)}'
        )
        return 0
    speed_bps = speed_mbps * 125_000
    speed_str = f"{speed_mbps // 1000} GBit/s" if speed_mbps >= 1000 else f"{speed_mbps} MBit/s"
    rx_pct = (rx_bps / speed_bps * 100) if speed_bps > 0 else 0.0
    tx_pct = (tx_bps / speed_bps * 100) if speed_bps > 0 else 0.0
    warn_bps = speed_bps * 0.80
    crit_bps = speed_bps * 0.95
    st = 2 if (rx_bps >= crit_bps or tx_bps >= crit_bps) else (1 if (rx_bps >= warn_bps or tx_bps >= warn_bps) else 0)
    print(
        f'{st} {SERVICE} if_in_octets={rx_bps:.2f}|if_out_octets={tx_bps:.2f} '
        f'[{device}] Speed: {speed_str}, In: {fmt_bps(rx_bps)} ({rx_pct:.2f}%), '
        f'Out: {fmt_bps(tx_bps)} ({tx_pct:.2f}%)'
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
