#!/usr/bin/env python3
"""check_ovpn_host2net.py - CheckMK OpenVPN check.

Scans /proc for OpenVPN processes.
Reads OpenVPN status files directly.
"""

import sys
from pathlib import Path

VERSION = "1.1.0"
SERVICE = "OVPN.HostToNet"


def find_openvpn_processes():
    openvpn_pids = []
    try:
        for proc in Path("/proc").iterdir():
            if not proc.name.isdigit():
                continue
            try:
                cmdline = (proc / "cmdline").read_bytes()
                if b"openvpn" in cmdline and b"--config" in cmdline:
                    openvpn_pids.append(int(proc.name))
            except (PermissionError, FileNotFoundError):
                pass
    except PermissionError:
        pass
    return openvpn_pids


def find_status_files():
    status_files = []
    candidates = [
        Path("/var/run/openvpn"),
        Path("/var/run/openvpn-server"),
        Path("/tmp/openvpn"),
    ]
    for d in candidates:
        if d.is_dir():
            for f in d.iterdir():
                if f.name.endswith(".status"):
                    status_files.append(f)
    return status_files


def read_status_file(path):
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        clients = 0
        for line in text.splitlines():
            if "," in line and "Connected" in line:
                clients += 1
        return clients
    except Exception:
        return 0


def main():
    pids = find_openvpn_processes()
    status_files = find_status_files()
    if not pids and not status_files:
        print(f"0 {SERVICE} - OpenVPN not configured or not running")
        return 0
    total_clients = 0
    for sf in status_files:
        total_clients += read_status_file(sf)
    pid_count = len(pids)
    print(
        f"0 {SERVICE} - Active: {pid_count} process(es), {total_clients} client(s)"
        f" | processes={pid_count} clients={total_clients}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
