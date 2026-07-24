#!/usr/bin/env python3
"""check_stunnel_agent_tls.py - CheckMK Local Check + self-remediation for
Agent TLS wrapping via Stunnel.

Verifies that the classic CheckMK plain-TCP agent (port 6556) is not
reachable in clear text: the real agent socket must be rebound to
127.0.0.1:6555 and a local Stunnel instance must terminate TLS on
0.0.0.0:6556 in front of it. If the host is not yet compliant, configures
it (install stunnel, rebind the socket, generate a cert if needed, start
the tunnel) and re-verifies. Idempotent and safe to run every check cycle:
already-compliant hosts do nothing beyond a handful of read-only checks.

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


def detect_stunnel_service_name() -> Optional[str]:
    """Return the systemd unit name that should run stunnel, or None if
    stunnel is not installed."""
    if not shutil.which("stunnel") and not shutil.which("stunnel3"):
        return None

    for candidate in ("stunnel4", "stunnel"):
        code, out, _ = run_command(["systemctl", "list-unit-files", f"{candidate}.service"])
        if code == 0 and candidate in out:
            return candidate

    if AGENT_SOCKET_UNIT.exists():
        # A custom unit may already have been deployed by a previous run.
        code, _, _ = run_command(["systemctl", "list-unit-files", CUSTOM_STUNNEL_SERVICE])
        if code == 0:
            return CUSTOM_STUNNEL_SERVICE.replace(".service", "")

    return None


def detect_package_manager() -> Optional[str]:
    for mgr in ("apt-get", "dnf", "yum"):
        if shutil.which(mgr):
            return mgr
    return None


def install_stunnel(pkg_mgr: str) -> bool:
    if pkg_mgr == "apt-get":
        run_command(["apt-get", "update", "-y"], timeout=60)
        code, _, _ = run_command(["apt-get", "install", "-y", "stunnel4"], timeout=120)
    else:
        code, _, _ = run_command([pkg_mgr, "install", "-y", "stunnel"], timeout=120)
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


def is_unit_active(unit: str) -> bool:
    code, out, _ = run_command(["systemctl", "is-active", unit])
    return code == 0 and out.strip() == "active"


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

    stunnel_service = detect_stunnel_service_name()
    if not stunnel_service:
        return False, "stunnel not installed"
    if not is_port_listening(6556):
        return False, f"{stunnel_service} not actually listening on {TLS_PUBLIC_PORT}"

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


def configure_stunnel(service_name: str) -> str:
    STUNNEL_CONF_DIR.mkdir(parents=True, exist_ok=True)
    CONF_FILE.write_text(_STUNNEL_CONF_TEMPLATE)

    code, out, _ = run_command(["systemctl", "list-unit-files", f"{service_name}.service"])
    has_unit = code == 0 and service_name in out

    if not has_unit:
        SYSTEMD_DIR.joinpath(CUSTOM_STUNNEL_SERVICE).write_text(_CUSTOM_STUNNEL_SERVICE_CONTENT)
        service_name = CUSTOM_STUNNEL_SERVICE.replace(".service", "")
        run_command(["systemctl", "daemon-reload"])
    elif service_name == "stunnel4":
        default_file = Path("/etc/default/stunnel4")
        if default_file.is_file():
            try:
                content = default_file.read_text()
                if "ENABLED=0" in content:
                    default_file.write_text(content.replace("ENABLED=0", "ENABLED=1"))
            except OSError:
                pass

    run_command(["systemctl", "daemon-reload"])
    run_command(["systemctl", "reset-failed", service_name])
    run_command(["systemctl", "enable", service_name])
    # restart (not "enable --now"): stunnel.conf may have changed while the
    # service was already running, and it will not pick up the new config
    # without an explicit restart.
    run_command(["systemctl", "restart", service_name])
    return service_name


def remediate() -> Optional[str]:
    """Attempt to bring the host into compliance. Returns an error message
    if remediation could not even be attempted, None otherwise (the caller
    re-checks compliance afterwards regardless of this return value)."""
    pkg_mgr = detect_package_manager()
    stunnel_service = detect_stunnel_service_name()

    if not stunnel_service:
        if not pkg_mgr:
            return "no supported package manager (apt-get/dnf/yum) found"
        if not install_stunnel(pkg_mgr):
            return "stunnel package installation failed"
        stunnel_service = "stunnel4" if pkg_mgr == "apt-get" else "stunnel"

    configure_agent_socket()
    generate_certificate()
    configure_stunnel(stunnel_service)
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
