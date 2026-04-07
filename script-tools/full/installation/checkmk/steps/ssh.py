from __future__ import annotations

import re
import shlex
from pathlib import Path

from lib.common import backup_file, command_exists, log_header, log_info, log_success, log_warn, run as run_cmd
from lib.config import InstallerConfig


def _set_sshd_option(sshd_config: Path, key: str, value: str) -> None:
    key_re = re.compile(rf"^\s*#?\s*{re.escape(key)}\s+.*$", re.IGNORECASE)
    lines = sshd_config.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    replaced = False
    out: list[str] = []
    for line in lines:
        if key_re.match(line):
            out.append(f"{key} {value}\n")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        if out and not out[-1].endswith("\n"):
            out[-1] = out[-1] + "\n"
        out.append(f"\n{key} {value}\n")
    sshd_config.write_text("".join(out), encoding="utf-8")


def run_step(cfg: InstallerConfig) -> None:
    log_header("10-SSH")
    log_info("Configuring SSH...")

    sshd_config = Path("/etc/ssh/sshd_config")
    if not sshd_config.exists():
        raise RuntimeError("/etc/ssh/sshd_config not found")

    backup = backup_file(sshd_config)
    log_info(f"Backup created: {backup}")

    _set_sshd_option(sshd_config, "Port", str(cfg.ssh_port))
    _set_sshd_option(sshd_config, "PermitRootLogin", cfg.permit_root_login)
    _set_sshd_option(sshd_config, "PasswordAuthentication", "no")
    _set_sshd_option(sshd_config, "PubkeyAuthentication", "yes")
    _set_sshd_option(sshd_config, "X11Forwarding", "no")
    _set_sshd_option(sshd_config, "ClientAliveInterval", str(cfg.client_alive_interval))
    _set_sshd_option(sshd_config, "ClientAliveCountMax", str(cfg.client_alive_countmax))
    _set_sshd_option(sshd_config, "LoginGraceTime", str(cfg.login_grace_time))

    if cfg.root_password and not cfg.root_password.upper().startswith("INSERISCI_"):
        log_info("Setting root password (value not shown)...")
        run_cmd(["bash", "-lc", f"echo 'root:{shlex.quote(cfg.root_password)}' | chpasswd"], check=True)
    elif cfg.root_password:
        log_warn("ROOT_PASSWORD looks like a placeholder; skipping root password change.")

    if command_exists("systemctl"):
        run_cmd(["systemctl", "restart", "sshd"], check=False)
        run_cmd(["systemctl", "restart", "ssh"], check=False)

    log_success("SSH configured")


def run(cfg: InstallerConfig) -> None:
    run_step(cfg)
