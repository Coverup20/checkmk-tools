#!/usr/bin/env python3
"""check_stunnel_agent_tls_ns7.py - CheckMK Local Check + self-remediation
for Agent TLS wrapping via Stunnel, on NethServer 7 (RHEL7-based, yum only
- this generation never has dnf).

Verifies that the classic CheckMK plain-TCP agent (port 6556) is not
reachable in clear text: the real agent socket must be rebound to
127.0.0.1:6555 and a local Stunnel instance must terminate TLS on
0.0.0.0:6556 in front of it. If the host is not yet compliant, configures
it (yum install stunnel, rebind the socket, generate a cert if needed,
start the tunnel) and re-verifies. Idempotent and safe to run every check
cycle: already-compliant hosts do nothing beyond a handful of read-only
checks.

Uses a dedicated stunnel-checkmk.service rather than the distro's native
stunnel.service: on RHEL7-family systems that unit hardcodes a single
config path (/etc/stunnel/stunnel.conf) and fails outright with any other
filename (confirmed on the RHEL9-based NethServer 8 sibling of this
script, same stunnel packaging).

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
MaxConnections=5
MaxConnectionsPerSource=3

[Install]
WantedBy=sockets.target
"""

_AGENT_SERVICE_UNIT_CONTENT = """[Unit]
Description=Checkmk Agent (plain TCP, local-only) connection

[Service]
ExecStart=-/usr/bin/check_mk_agent
StandardInput=socket
"""

# NethServer 7's EL7 stunnel package is 4.56 (2015) - it predates
# sslVersionMin (added in stunnel 5.x) and rejects it outright ("Specified
# option name is not valid here"). sslVersion pins a single version rather
# than a minimum, but TLSv1.2 is also the highest this build supports, so
# the effect is the same.
_STUNNEL_CONF_TEMPLATE = f"""pid = /var/run/stunnel-checkmk.pid
cert = {CERT_FILE}
sslVersion = TLSv1.2

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
    """We always run our own dedicated unit rather than the distro's native
    stunnel.service, which hardcodes /etc/stunnel/stunnel.conf as the only
    config file it will load and fails outright on any other filename."""
    return CUSTOM_STUNNEL_SERVICE.replace(".service", "")


VAULT_REPO_FILE = Path("/etc/yum.repos.d/centos7-vault-stunnel-fallback.repo")
VAULT_REPO_ID = "centos7-vault-stunnel-fallback"
_VAULT_REPO_CONTENT = f"""[{VAULT_REPO_ID}]
name=CentOS-7 vault base (fallback source for stunnel only)
baseurl=http://vault.centos.org/centos/7/os/x86_64/
enabled=0
gpgcheck=0
"""


def install_stunnel() -> bool:
    code, _, _ = run_command(["yum", "install", "-y", "stunnel"], timeout=120)

    if code != 0:
        # NethServer 7's own package mirrors (sb-base/sb-epel/... on
        # nethserver.com) can go down or reject requests (403 seen live on
        # ns-lab00) independently of this host's actual subscription state.
        # CentOS 7 is EOL, so the vault is the only other place stunnel is
        # still fetchable from - used only as a fallback, and only for this
        # one package (--disablerepo='*' so nothing else is ever pulled
        # from it), never enabled outside of this single install attempt.
        VAULT_REPO_FILE.write_text(_VAULT_REPO_CONTENT)
        code, _, _ = run_command(
            ["yum", "--disablerepo=*", f"--enablerepo={VAULT_REPO_ID}",
             "install", "-y", "stunnel"],
            timeout=120,
        )

    # The distro package registers its own native stunnel.service - stop
    # and disable it so it can never race our dedicated unit over the same
    # config file/port.
    run_command(["systemctl", "stop", "stunnel"])
    run_command(["systemctl", "disable", "stunnel"])
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
        if not shutil.which("yum"):
            return "yum not found (not a NethServer 7 system?)"
        if not install_stunnel():
            return "stunnel package installation failed"

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
