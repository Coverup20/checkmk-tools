#!/usr/bin/env python3
"""check_stunnel_agent_tls_proxmox.py - CheckMK Local Check + self-remediation
for Agent TLS wrapping via Stunnel, on Proxmox VE (Debian-based, apt).

Verifies that the classic CheckMK plain-TCP agent (port 6556) is not
reachable in clear text: the real agent socket must be rebound to
127.0.0.1:6555 and a local Stunnel instance must terminate TLS on
0.0.0.0:6556 in front of it. If the host is not yet compliant, configures
it (apt-get install stunnel4, rebind the socket, generate a cert if
needed, start the tunnel) and re-verifies. Idempotent and safe to run
every check cycle: already-compliant hosts do nothing beyond a handful of
read-only checks.

Compatible with CheckMK local check format (always exits 0, encodes the
result as "<status> <SERVICE> - message").

Version: 1.0.0"""

import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

VERSION = "1.0.0"
SERVICE = "Agent.TLS.Stunnel"

SYSTEMD_DIR = Path("/etc/systemd/system")
AGENT_SOCKET_UNIT = SYSTEMD_DIR / "check-mk-agent-plain.socket"
AGENT_SERVICE_UNIT = SYSTEMD_DIR / "check-mk-agent-plain@.service"
STUNNEL_CONF_DIR = Path("/etc/stunnel")
CERT_FILE = STUNNEL_CONF_DIR / "checkmk-agent.pem"
CONF_FILE = STUNNEL_CONF_DIR / "checkmk-agent.conf"
CUSTOM_STUNNEL_SERVICE = "stunnel-checkmk.service"

LOCAL_AGENT_PORT = "127.0.0.1:6555"
TLS_PUBLIC_PORT = "0.0.0.0:6556"

_AGENT_SOCKET_UNIT_CONTENT = f"""[Unit]
Description=Checkmk Agent (plain TCP, local-only, wrapped by Stunnel)
Documentation=https://docs.checkmk.com/

[Socket]
ListenStream={LOCAL_AGENT_PORT}
Accept=yes
MaxConnections=20
MaxConnectionsPerSource=10

[Install]
WantedBy=sockets.target
"""

_AGENT_SERVICE_UNIT_CONTENT = """[Unit]
Description=Checkmk Agent (plain TCP, local-only) connection

[Service]
ExecStart=-/usr/bin/check_mk_agent
StandardInput=socket
"""

_STUNNEL_CONF_TEMPLATE = f"""pid = /var/run/stunnel-checkmk.pid
cert = {CERT_FILE}
sslVersionMin = TLSv1.2

[checkmk-agent]
accept = {TLS_PUBLIC_PORT}
connect = {LOCAL_AGENT_PORT}
"""

_CUSTOM_STUNNEL_SERVICE_CONTENT = """[Unit]
Description=Stunnel TLS Tunnel for Checkmk Agent
After=network.target

[Service]
ExecStart=/usr/bin/stunnel /etc/stunnel/checkmk-agent.conf
Type=forking
PIDFile=/var/run/stunnel-checkmk.pid
Restart=always

[Install]
WantedBy=multi-user.target
"""


def run_command(cmd: list, timeout: int = 15) -> Tuple[int, str, str]:
    """Execute a shell command and return exit code, stdout, stderr."""
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 1, "", "Command timeout"
    except FileNotFoundError:
        return 127, "", "Command not found"
    except Exception as exc:  # pragma: no cover - defensive catch-all
        return 1, "", str(exc)


def is_stunnel_installed() -> bool:
    return bool(shutil.which("stunnel") or shutil.which("stunnel3"))


def stunnel_service_name() -> str:
    """We always run our own dedicated unit rather than Debian's native
    stunnel4 service: stunnel4 reads every *.conf under /etc/stunnel/ via
    /etc/default/stunnel4's FILES glob, which would also pick up our file,
    but relying on that distro-specific default is one more thing that can
    silently change - a dedicated unit that explicitly names our config is
    simpler to reason about and keeps this script's behavior identical to
    its RHEL-family siblings (check_stunnel_agent_tls_ns7/ns8.py)."""
    return CUSTOM_STUNNEL_SERVICE.replace(".service", "")


def install_stunnel() -> bool:
    run_command(["apt-get", "update", "-y"], timeout=60)
    code, _, _ = run_command(["apt-get", "install", "-y", "stunnel4"], timeout=120)
    # The stunnel4 package registers its own systemd unit - stop/disable it
    # so it can never race our dedicated unit over the same config/port.
    run_command(["systemctl", "stop", "stunnel4"])
    run_command(["systemctl", "disable", "stunnel4"])
    return code == 0


def is_socket_rebound() -> bool:
    """True if check-mk-agent-plain.socket exists and binds to the
    local-only agent port (i.e. is not reachable in clear text)."""
    if not AGENT_SOCKET_UNIT.is_file():
        return False
    try:
        content = AGENT_SOCKET_UNIT.read_text()
    except OSError:
        return False
    return f"ListenStream={LOCAL_AGENT_PORT}" in content


def is_stunnel_conf_correct() -> bool:
    if not CONF_FILE.is_file():
        return False
    try:
        content = CONF_FILE.read_text()
    except OSError:
        return False
    return (
        f"accept = {TLS_PUBLIC_PORT}" in content
        and f"connect = {LOCAL_AGENT_PORT}" in content
    )


def is_port_listening(port: int, host: str = "127.0.0.1", timeout: float = 1.5) -> bool:
    """Real TCP connectivity probe. systemd can report a socket unit as
    "active (listening)" even after it has silently lost its listening file
    descriptor (e.g. right after its ListenStream was changed without a
    restart) - only an actual connection attempt tells the truth."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def is_compliant() -> Tuple[bool, str]:
    """Check whether the host is already fully configured.

    Returns (compliant, reason) - reason explains the first thing found
    missing/wrong when not compliant, for the check's plugin output."""
    if not is_socket_rebound():
        return False, "agent socket not rebound to 127.0.0.1"
    if not is_port_listening(6555):
        return False, "agent plain socket not actually listening on 127.0.0.1:6555"
    if not CERT_FILE.is_file():
        return False, "stunnel certificate missing"
    if not is_stunnel_conf_correct():
        return False, "stunnel.conf missing or misconfigured"
    if not is_stunnel_installed():
        return False, "stunnel not installed"
    if not is_port_listening(6556):
        return False, f"{stunnel_service_name()} not actually listening on {TLS_PUBLIC_PORT}"

    return True, "compliant"


def configure_agent_socket() -> None:
    for unit in ("check-mk-agent.socket", "cmk-agent-ctl-daemon.service"):
        run_command(["systemctl", "stop", unit])
        run_command(["systemctl", "disable", unit])

    AGENT_SOCKET_UNIT.write_text(_AGENT_SOCKET_UNIT_CONTENT)
    AGENT_SERVICE_UNIT.write_text(_AGENT_SERVICE_UNIT_CONTENT)
    run_command(["systemctl", "daemon-reload"])
    run_command(["systemctl", "reset-failed", "check-mk-agent-plain.socket"])
    run_command(["systemctl", "enable", "check-mk-agent-plain.socket"])
    # A plain "enable --now" is a no-op if the socket was already active
    # under its OLD ListenStream (systemd does not rebind a running socket
    # unit just because its file changed) - an explicit restart is required.
    run_command(["systemctl", "restart", "check-mk-agent-plain.socket"])


def generate_certificate() -> None:
    if CERT_FILE.is_file():
        return
    STUNNEL_CONF_DIR.mkdir(parents=True, exist_ok=True)
    run_command(
        [
            "openssl", "req", "-new", "-x509", "-days", "3650", "-nodes",
            "-out", str(CERT_FILE),
            "-keyout", str(CERT_FILE),
            "-subj", "/CN=checkmk-agent",
        ],
        timeout=30,
    )
    try:
        CERT_FILE.chmod(0o600)
    except OSError:
        pass


def configure_stunnel() -> None:
    STUNNEL_CONF_DIR.mkdir(parents=True, exist_ok=True)
    CONF_FILE.write_text(_STUNNEL_CONF_TEMPLATE)

    service = stunnel_service_name()
    SYSTEMD_DIR.joinpath(CUSTOM_STUNNEL_SERVICE).write_text(_CUSTOM_STUNNEL_SERVICE_CONTENT)
    run_command(["systemctl", "daemon-reload"])
    run_command(["systemctl", "reset-failed", service])
    run_command(["systemctl", "enable", service])
    # restart (not "enable --now"): stunnel.conf may have changed while the
    # service was already running, and it will not pick up the new config
    # without an explicit restart.
    run_command(["systemctl", "restart", service])


def remediate() -> Optional[str]:
    """Attempt to bring the host into compliance. Returns an error message
    if remediation could not even be attempted, None otherwise (the caller
    re-checks compliance afterwards regardless of this return value)."""
    if not is_stunnel_installed():
        if not shutil.which("apt-get"):
            return "apt-get not found (not a Debian-based Proxmox VE system?)"
        if not install_stunnel():
            return "stunnel4 package installation failed"

    configure_agent_socket()
    generate_certificate()
    configure_stunnel()
    return None


def main() -> int:
    compliant, reason = is_compliant()
    if compliant:
        print(f"0 {SERVICE} - OK - agent TLS-wrapped via stunnel ({TLS_PUBLIC_PORT} -> {LOCAL_AGENT_PORT})")
        return 0

    error = remediate()
    if error:
        print(f"2 {SERVICE} - CRITICAL - remediation failed: {error}")
        return 0

    compliant, reason = is_compliant()
    if compliant:
        print(f"0 {SERVICE} - OK - agent TLS-wrapped via stunnel (just configured)")
    else:
        print(f"2 {SERVICE} - CRITICAL - still not compliant after remediation: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
