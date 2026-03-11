#!/usr/bin/env python3
"""check_ovpn_host2net.py - CheckMK local check OVPN host-to-net (Python puro)."""

VERSION = "1.1.0"

import subprocess
import sys
from pathlib import Path

STATUS_DIR = Path("/var/run/openvpn")


def main() -> int:
    if not STATUS_DIR.is_dir():
        print("0 OVPN.HostToNet - OpenVPN non configurato o non in esecuzione")
        return 0

    status_files = sorted(STATUS_DIR.glob("*.status"))
    if not status_files:
        print("0 OVPN.HostToNet - Nessun server OpenVPN host-to-net attivo")
        return 0

    total_servers = len(status_files)
    total_clients = 0
    details: list[str] = []

    for status_file in status_files:
        server_name = status_file.stem
        client_count = 0
        for line in status_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("CLIENT_LIST,"):
                client_count += 1
        total_clients += client_count
        if client_count == 0:
            details.append(f"{server_name}:0_clients")
        else:
            details.append(f"{server_name}:{client_count}_clients")

    if total_clients >= 50:
        status, status_text = 1, f"WARNING - Molti client connessi: {total_clients}"
    else:
        status, status_text = 0, f"OK - {total_clients} client connessi su {total_servers} server"

    print(
        f"{status} OVPN.HostToNet clients={total_clients};50;100;0 servers={total_servers} - {status_text} "
        f"| total_clients={total_clients} total_servers={total_servers}"
    )
    print(f"0 OVPN.Servers - Active servers: {' '.join([f.stem for f in status_files])}")
    if details:
        print(f"0 OVPN.ClientDetails - {', '.join(details[:10])}")

    ps = subprocess.run(["ps"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False)
    openvpn_processes = sum(1 for line in (ps.stdout or "").splitlines() if "openvpn" in line and "grep" not in line)
    if openvpn_processes == 0:
        print("2 OVPN.Process - CRITICAL - Nessun processo OpenVPN in esecuzione")
    else:
        print(f"0 OVPN.Process - OK - {openvpn_processes} processi OpenVPN attivi")
    return 0


if __name__ == "__main__":
    sys.exit(main())
