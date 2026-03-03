#!/usr/bin/env python3
"""
install_frpc2.py - Configura agent Checkmk plaintext socket su Debian/Proxmox.

Version: 1.0.0
"""

import os
import subprocess
import sys
from pathlib import Path

VERSION = "1.0.0"

SOCKET_UNIT = """[Unit]
Description=Checkmk Agent (Plaintext Socket)
Documentation=https://docs.checkmk.com/latest/en/agent_linux.html

[Socket]
ListenStream=6556
Accept=yes

[Install]
WantedBy=sockets.target
"""

SERVICE_UNIT = """[Unit]
Description=Checkmk Agent (Plaintext)
Documentation=https://docs.checkmk.com/latest/en/agent_linux.html

[Service]
ExecStart=/usr/bin/check_mk_agent
StandardInput=socket
"""


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def is_root() -> bool:
    return os.geteuid() == 0


def write_file(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def main() -> int:
    print(f"install_frpc2.py v{VERSION}")

    if not is_root():
        print("ERRORE: eseguire come root", file=sys.stderr)
        return 1

    os_type = os.getenv("OS_TYPE", "")
    if os_type not in {"debian", "proxmox"}:
        print(f"Skip: OS_TYPE={os_type!r} (script applicabile solo a debian/proxmox)")
        return 0

    print(f">>> Verifica stato agent Checkmk su {os_type}")

    active = run(["systemctl", "is-active", "--quiet", "cmk-agent-ctl-daemon.service"], check=False)
    if active.returncode == 0:
        print(">>> Disattivo agent TLS (non supportato su Raw Edition)...")
        run(["systemctl", "stop", "cmk-agent-ctl-daemon.service"], check=False)
        run(["systemctl", "disable", "cmk-agent-ctl-daemon.service"], check=False)
        run(["pkill", "-9", "-f", "cmk-agent-ctl"], check=False)

    print(">>> Configuro agent in modalita Plaintext")
    write_file(Path("/etc/systemd/system/check-mk-agent-plain.socket"), SOCKET_UNIT)
    write_file(Path("/etc/systemd/system/check-mk-agent-plain@.service"), SERVICE_UNIT)

    run(["systemctl", "daemon-reexec"], check=False)
    run(["systemctl", "enable", "--now", "check-mk-agent-plain.socket"], check=False)

    print(">>> Test agent locale:")
    test = run(["bash", "-lc", "nc 127.0.0.1 6556 | head"], check=False)
    if test.stdout:
        print(test.stdout.strip())

    return 0


if __name__ == "__main__":
    sys.exit(main())
