"""Tests for steps/checkmk.py's package-install command choice.

Regression coverage for the 2026-08-03 change: gdebi -n <path> was replaced
with apt-get -o Dpkg::Progress-Fancy=1 install -y <path> for installing the
CheckMK .deb (local or downloaded), because gdebi has no progress feedback
for a long unpack. A first attempt added a custom elapsed-time ticker
instead, but that interleaved badly with apt's own terminal output and was
reverted in favor of just requesting apt's real Dpkg::Progress-Fancy bar.
gdebi-core is no longer installed as a prerequisite either, since nothing
needs it anymore.
"""

import sys
from pathlib import Path

import pytest

PACKAGE_DIR = (
    Path(__file__).resolve().parents[2]
    / "script-tools"
    / "full"
    / "installation"
    / "checkmk"
)
if str(PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGE_DIR))

import steps.checkmk as checkmk_module  # noqa: E402
from lib.config import InstallerConfig  # noqa: E402


def _minimal_config(**overrides) -> InstallerConfig:
    base = dict(
        timezone="Europe/Rome",
        ssh_port=22,
        permit_root_login="yes",
        client_alive_interval=600,
        client_alive_countmax=2,
        login_grace_time=30,
        root_password="",
        open_http_https=True,
        letsencrypt_email="",
        letsencrypt_domains="",
        webserver="apache",
        ntp_servers=["0.pool.ntp.org"],
        checkmk_admin_password="",
        checkmk_deb_url="",
        cmk_version="latest",
        site_name="monitoring",
        redirect_to_site=True,
        deploy_local_checks=True,
        enable_auto_git_sync=True,
        auto_git_sync_interval_sec=60,
        auto_git_sync_repo_url="https://github.com/nethesis/checkmk-tools.git",
        auto_git_sync_target_dir="/opt/checkmk-tools",
        smtp_relayhost="",
        smtp_relay_user="",
        smtp_relay_password="",
        smtp_from_address="",
        fail2ban_ignoreip="",
    )
    base.update(overrides)
    return InstallerConfig(**base)


@pytest.fixture()
def recorded_commands(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, check=True):
        calls.append(list(cmd))

        class _R:
            returncode = 0

        return _R()

    monkeypatch.setattr(checkmk_module, "run_cmd", fake_run)
    monkeypatch.setattr(checkmk_module, "run_capture", lambda cmd, check=False: "monitoring")
    monkeypatch.setattr(checkmk_module, "run_stdin", lambda cmd, text, check=False: None)
    monkeypatch.setattr(checkmk_module, "command_exists", lambda name: True)
    return calls


def test_local_deb_install_uses_apt_get_with_progress_fancy_not_gdebi(tmp_path, recorded_commands):
    deb_file = tmp_path / "check-mk-community-2.5.0p10_0.jammy_amd64.deb"
    deb_file.write_bytes(b"fake deb content")

    cfg = _minimal_config(checkmk_deb_url=str(deb_file))
    checkmk_module.run_step(cfg)

    install_calls = [c for c in recorded_commands if str(deb_file) in c]
    assert len(install_calls) == 1
    assert install_calls[0] == [
        "apt-get",
        "-o",
        "Dpkg::Progress-Fancy=1",
        "install",
        "-y",
        str(deb_file),
    ]
    assert not any("gdebi" in c for c in recorded_commands)


def test_gdebi_core_is_no_longer_installed(tmp_path, recorded_commands):
    deb_file = tmp_path / "check-mk-community-2.5.0p10_0.jammy_amd64.deb"
    deb_file.write_bytes(b"fake deb content")

    cfg = _minimal_config(checkmk_deb_url=str(deb_file))
    checkmk_module.run_step(cfg)

    assert not any("gdebi-core" in c for c in recorded_commands)
