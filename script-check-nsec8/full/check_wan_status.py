#!/usr/bin/env python3
"""check_wan_status.py - CheckMK local check WAN status (Python puro).

Version: 1.1.0
"""

import json
import subprocess
import sys

VERSION = "1.1.0"


def run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False)
    return (result.stdout or "").strip()


def find_wan_interfaces() -> list[str]:
    """Rileva interfacce WAN cercando quelle con default route (target 0.0.0.0).
    Fallback su nomi che iniziano con wan/wwan/vwan."""
    wan_ifaces: list[str] = []

    # Metodo 1: dump di tutte le interfacce, cerca quelle con default route
    data = run(["ubus", "call", "network.interface", "dump"])
    if data:
        try:
            parsed = json.loads(data)
            for iface in parsed.get("interface", []):
                name = iface.get("interface", "")
                if not name or name in ("loopback",):
                    continue
                routes = iface.get("route", [])
                for route in routes:
                    if route.get("target") == "0.0.0.0":
                        wan_ifaces.append(name)
                        break
        except Exception:
            pass

    # Fallback: nomi classici wan/wwan/vwan
    if not wan_ifaces:
        lines = run(["ubus", "list"]).splitlines()
        for line in lines:
            if line.startswith("network.interface."):
                name = line.replace("network.interface.", "")
                if name.lower().startswith(("wan", "wwan", "vwan")):
                    wan_ifaces.append(name)

    return wan_ifaces


def iface_status(iface: str) -> tuple[str, str]:
    data = run(["ubus", "call", f"network.interface.{iface}", "status"])
    if not data:
        return "unknown", ""
    try:
        parsed = json.loads(data)
        up = parsed.get("up")
        route = parsed.get("route", [])
        gateway = route[0].get("nexthop", "") if route and isinstance(route, list) else ""
        return ("up" if up else "down"), gateway
    except Exception:
        return "unknown", ""


def ping(target: str) -> bool:
    result = subprocess.run(["ping", "-c", "2", "-W", "2", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return result.returncode == 0


def main() -> int:
    wan_ifaces = find_wan_interfaces()
    if not wan_ifaces:
        print("0 WAN_Status status=ERROR No WAN interfaces found")
        return 0

    overall = 0
    status_messages: list[str] = []
    details: list[str] = []

    for iface in wan_ifaces:
        status, gateway = iface_status(iface)
        if status == "up":
            if gateway:
                if ping(gateway):
                    status_messages.append(f"{iface}=OK")
                    details.append(f"{iface}: UP (gateway {gateway} reachable)")
                else:
                    status_messages.append(f"{iface}=DEGRADED")
                    details.append(f"{iface}: UP but gateway {gateway} unreachable")
                    overall = max(overall, 1)
            elif ping("8.8.8.8") or ping("1.1.1.1"):
                status_messages.append(f"{iface}=OK")
                details.append(f"{iface}: UP (internet reachable)")
            else:
                status_messages.append(f"{iface}=DEGRADED")
                details.append(f"{iface}: UP but no connectivity")
                overall = max(overall, 1)
        elif status == "down":
            status_messages.append(f"{iface}=DOWN")
            details.append(f"{iface}: DOWN")
            overall = max(overall, 2)
        else:
            status_messages.append(f"{iface}=UNKNOWN")
            details.append(f"{iface}: UNKNOWN")
            overall = max(overall, 1)

    final_status = "OK" if overall == 0 else ("WARNING" if overall == 1 else "CRITICAL")
    print(f"{overall} WAN_Status status={final_status} {' '.join(status_messages)} - {', '.join(details)}")

    wan_count = len(wan_ifaces)
    wan_up = sum(1 for s in status_messages if s.endswith("=OK"))
    wan_down = sum(1 for s in status_messages if s.endswith("=DOWN"))
    wan_degraded = sum(1 for s in status_messages if s.endswith("=DEGRADED"))
    print(
        f"0 WAN_Metrics - Total={wan_count} Up={wan_up} Down={wan_down} Degraded={wan_degraded} "
        f"| total={wan_count} up={wan_up} down={wan_down} degraded={wan_degraded}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
