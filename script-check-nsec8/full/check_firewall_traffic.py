#!/usr/bin/env python3
"""check_firewall_traffic.py - CheckMK local check firewall traffic (Python puro)."""

VERSION = "1.1.0"

import json
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False)
    return (result.stdout or "").strip()


def get_iface_list() -> tuple[list[str], list[str]]:
    ubus_lines = run(["ubus", "list"]).splitlines()
    interfaces = [line.replace("network.interface.", "") for line in ubus_lines if line.startswith("network.interface.")]
    wan = [i for i in interfaces if i.startswith("wan") or i.startswith("wwan")]
    lan = [i for i in interfaces if i in {"lan", "br-lan"}]
    return wan, lan


def get_device(iface: str) -> str:
    data = run(["ubus", "call", f"network.interface.{iface}", "status"])
    if not data:
        return ""
    try:
        parsed = json.loads(data)
        return str(parsed.get("device", ""))
    except Exception:
        return ""


def read_stat(device: str, metric: str) -> int:
    path = Path(f"/sys/class/net/{device}/statistics/{metric}")
    if not path.exists():
        return 0
    value = path.read_text(encoding="utf-8", errors="ignore").strip()
    return int(value) if value.isdigit() else 0


def emit_for_iface(iface: str) -> None:
    device = get_device(iface)
    if not device:
        return

    rx_bytes = read_stat(device, "rx_bytes")
    tx_bytes = read_stat(device, "tx_bytes")
    rx_packets = read_stat(device, "rx_packets")
    tx_packets = read_stat(device, "tx_packets")
    rx_errors = read_stat(device, "rx_errors")
    tx_errors = read_stat(device, "tx_errors")

    status = 1 if (rx_errors > 100 or tx_errors > 100) else 0
    print(
        f"{status} {iface}.Traffic - RX: {rx_bytes} bytes, TX: {tx_bytes} bytes "
        f"| rx_bytes={rx_bytes} tx_bytes={tx_bytes} rx_packets={rx_packets} tx_packets={tx_packets} rx_errors={rx_errors} tx_errors={tx_errors}"
    )


def main() -> int:
    wan_ifaces, lan_ifaces = get_iface_list()
    for iface in wan_ifaces + lan_ifaces:
        emit_for_iface(iface)
    return 0


if __name__ == "__main__":
    sys.exit(main())
