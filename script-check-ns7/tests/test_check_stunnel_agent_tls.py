"""Tests for check_stunnel_agent_tls.py.

Covers: compliance detection (each missing piece reported distinctly),
the idempotent fast-path (compliant hosts must never call remediate()),
and the remediation path (success, remediation failure, and
"still not compliant after remediation" cases) - all via monkeypatched
filesystem paths and mocked subprocess calls, no dependency on a real
system.
"""

import socket

import check_stunnel_agent_tls as mod


# --- fixtures --------------------------------------------------------------

def _wire_paths(monkeypatch, tmp_path):
    """Redirect all module-level filesystem constants into tmp_path."""
    stunnel_dir = tmp_path / "stunnel"
    monkeypatch.setattr(mod, "SYSTEMD_DIR", tmp_path)
    monkeypatch.setattr(mod, "AGENT_SOCKET_UNIT", tmp_path / "check-mk-agent-plain.socket")
    monkeypatch.setattr(mod, "AGENT_SERVICE_UNIT", tmp_path / "check-mk-agent-plain@.service")
    monkeypatch.setattr(mod, "STUNNEL_CONF_DIR", stunnel_dir)
    monkeypatch.setattr(mod, "CERT_FILE", stunnel_dir / "checkmk-agent.pem")
    monkeypatch.setattr(mod, "CONF_FILE", stunnel_dir / "checkmk-agent.conf")


def _make_compliant(monkeypatch, tmp_path):
    """Write out a fully-compliant filesystem state and stub the systemctl
    checks so is_compliant() returns True."""
    _wire_paths(monkeypatch, tmp_path)
    mod.STUNNEL_CONF_DIR.mkdir(parents=True, exist_ok=True)
    mod.AGENT_SOCKET_UNIT.write_text(mod._AGENT_SOCKET_UNIT_CONTENT)
    mod.CERT_FILE.write_text("fake-cert")
    mod.CONF_FILE.write_text(mod._STUNNEL_CONF_TEMPLATE)

    monkeypatch.setattr(mod, "is_port_listening", lambda port, host="127.0.0.1", timeout=1.5: True)
    monkeypatch.setattr(mod, "detect_stunnel_service_name", lambda: "stunnel4")


# --- is_compliant() ---------------------------------------------------------

def test_is_compliant_true_when_everything_configured(monkeypatch, tmp_path):
    _make_compliant(monkeypatch, tmp_path)
    compliant, reason = mod.is_compliant()
    assert compliant is True
    assert reason == "compliant"


def test_is_compliant_false_when_socket_not_rebound(monkeypatch, tmp_path):
    _wire_paths(monkeypatch, tmp_path)
    # AGENT_SOCKET_UNIT does not exist at all
    compliant, reason = mod.is_compliant()
    assert compliant is False
    assert "socket" in reason


def test_is_compliant_false_when_local_agent_port_not_reachable(monkeypatch, tmp_path):
    _make_compliant(monkeypatch, tmp_path)
    monkeypatch.setattr(mod, "is_port_listening", lambda port, host="127.0.0.1", timeout=1.5: port != 6555)
    compliant, reason = mod.is_compliant()
    assert compliant is False
    assert "6555" in reason


def test_is_compliant_false_when_cert_missing(monkeypatch, tmp_path):
    _make_compliant(monkeypatch, tmp_path)
    mod.CERT_FILE.unlink()
    compliant, reason = mod.is_compliant()
    assert compliant is False
    assert "certificate" in reason


def test_is_compliant_false_when_stunnel_conf_wrong(monkeypatch, tmp_path):
    _make_compliant(monkeypatch, tmp_path)
    mod.CONF_FILE.write_text("garbage config")
    compliant, reason = mod.is_compliant()
    assert compliant is False
    assert "stunnel.conf" in reason


def test_is_compliant_false_when_stunnel_not_installed(monkeypatch, tmp_path):
    _make_compliant(monkeypatch, tmp_path)
    monkeypatch.setattr(mod, "detect_stunnel_service_name", lambda: None)
    compliant, reason = mod.is_compliant()
    assert compliant is False
    assert "not installed" in reason


def test_is_compliant_false_when_tls_port_not_reachable(monkeypatch, tmp_path):
    _make_compliant(monkeypatch, tmp_path)
    monkeypatch.setattr(mod, "is_port_listening", lambda port, host="127.0.0.1", timeout=1.5: port != 6556)
    compliant, reason = mod.is_compliant()
    assert compliant is False
    assert "6556" in reason


# --- main(): fast path -------------------------------------------------------

def test_main_fast_path_ok_never_calls_remediate(monkeypatch, tmp_path, capsys):
    _make_compliant(monkeypatch, tmp_path)

    def _boom():
        raise AssertionError("remediate() must not be called when already compliant")

    monkeypatch.setattr(mod, "remediate", _boom)

    rc = mod.main()

    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("0 Agent.TLS.Stunnel - OK")


# --- main(): remediation path -------------------------------------------------

def test_main_remediates_and_reports_ok(monkeypatch, tmp_path, capsys):
    _wire_paths(monkeypatch, tmp_path)
    # First call: not compliant. After "remediate" flips state, compliant.
    calls = {"n": 0}

    def fake_is_compliant():
        calls["n"] += 1
        if calls["n"] == 1:
            return False, "agent socket not rebound to 127.0.0.1"
        return True, "compliant"

    monkeypatch.setattr(mod, "is_compliant", fake_is_compliant)
    monkeypatch.setattr(mod, "remediate", lambda: None)

    rc = mod.main()

    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("0 Agent.TLS.Stunnel - OK")
    assert "just configured" in out


def test_main_reports_critical_when_remediation_raises_error(monkeypatch, tmp_path, capsys):
    _wire_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(mod, "is_compliant", lambda: (False, "agent socket not rebound to 127.0.0.1"))
    monkeypatch.setattr(mod, "remediate", lambda: "stunnel package installation failed")

    rc = mod.main()

    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("2 Agent.TLS.Stunnel - CRITICAL")
    assert "stunnel package installation failed" in out


def test_main_reports_critical_when_still_not_compliant_after_remediation(monkeypatch, tmp_path, capsys):
    _wire_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(mod, "is_compliant", lambda: (False, "stunnel.conf missing or misconfigured"))
    monkeypatch.setattr(mod, "remediate", lambda: None)

    rc = mod.main()

    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("2 Agent.TLS.Stunnel - CRITICAL")
    assert "still not compliant" in out


# --- detect_stunnel_service_name() / detect_package_manager() ---------------

def test_detect_stunnel_service_name_none_when_stunnel_not_found(monkeypatch):
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)
    assert mod.detect_stunnel_service_name() is None


def test_detect_stunnel_service_name_prefers_distro_unit(monkeypatch):
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/stunnel" if name == "stunnel" else None)

    def fake_run(cmd, timeout=15):
        if cmd[:2] == ["systemctl", "list-unit-files"] and "stunnel4.service" in cmd:
            return 0, "stunnel4.service enabled", ""
        return 1, "", ""

    monkeypatch.setattr(mod, "run_command", fake_run)
    assert mod.detect_stunnel_service_name() == "stunnel4"


def test_detect_package_manager_returns_first_available(monkeypatch):
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/dnf" if name == "dnf" else None)
    assert mod.detect_package_manager() == "dnf"


def test_detect_package_manager_none_when_nothing_available(monkeypatch):
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)
    assert mod.detect_package_manager() is None


# --- is_port_listening() ------------------------------------------------------
# Real TCP probes against a throwaway localhost listener - this is the exact
# regression this check guards against: systemd reporting a socket unit as
# "active (listening)" while it has actually lost its listening fd (real bug
# hit while validating this script against box-lab00).

def test_is_port_listening_true_for_a_real_open_port():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert mod.is_port_listening(port) is True
    finally:
        srv.close()


def test_is_port_listening_false_for_a_closed_port():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.close()  # port is now closed again
    assert mod.is_port_listening(port, timeout=0.3) is False


# --- remediate() orchestration ------------------------------------------------

def test_remediate_returns_error_when_no_package_manager(monkeypatch):
    monkeypatch.setattr(mod, "detect_stunnel_service_name", lambda: None)
    monkeypatch.setattr(mod, "detect_package_manager", lambda: None)

    error = mod.remediate()

    assert error == "no supported package manager (apt-get/dnf/yum) found"


def test_remediate_returns_error_when_install_fails(monkeypatch):
    monkeypatch.setattr(mod, "detect_stunnel_service_name", lambda: None)
    monkeypatch.setattr(mod, "detect_package_manager", lambda: "apt-get")
    monkeypatch.setattr(mod, "install_stunnel", lambda pkg_mgr: False)

    error = mod.remediate()

    assert error == "stunnel package installation failed"


def test_remediate_happy_path_calls_all_steps(monkeypatch):
    monkeypatch.setattr(mod, "detect_stunnel_service_name", lambda: "stunnel4")
    calls = []
    monkeypatch.setattr(mod, "configure_agent_socket", lambda: calls.append("socket"))
    monkeypatch.setattr(mod, "generate_certificate", lambda: calls.append("cert"))
    monkeypatch.setattr(mod, "configure_stunnel", lambda svc: calls.append(f"stunnel:{svc}"))

    error = mod.remediate()

    assert error is None
    assert calls == ["socket", "cert", "stunnel:stunnel4"]
