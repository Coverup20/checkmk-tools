"""Tests for check_stunnel_agent_tls_ns7.py (NethServer 7 (RHEL7) variant).

Covers: compliance detection (each missing piece reported distinctly),
the idempotent fast-path (compliant hosts must never call remediate()),
the remediation path (success, remediation failure, and "still not
compliant after remediation" cases), and two real regressions found while
rolling this out live: a systemd socket-rebind bug (real-socket test, not
mocked) and the RHEL-family stunnel.service incompatibility that this
per-OS split exists to avoid.
"""

import socket

import check_stunnel_agent_tls_ns7 as mod


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
    monkeypatch.setattr(mod, "is_stunnel_installed", lambda: True)


# --- is_compliant() ---------------------------------------------------------

def test_is_compliant_true_when_everything_configured(monkeypatch, tmp_path):
    _make_compliant(monkeypatch, tmp_path)
    compliant, reason = mod.is_compliant()
    assert compliant is True
    assert reason == "compliant"


def test_is_compliant_false_when_socket_not_rebound(monkeypatch, tmp_path):
    _wire_paths(monkeypatch, tmp_path)
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
    monkeypatch.setattr(mod, "is_stunnel_installed", lambda: False)
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
    srv.close()
    assert mod.is_port_listening(port, timeout=0.3) is False


# --- stunnel_service_name() / install_stunnel() -----------------------------

def test_stunnel_service_name_is_always_the_dedicated_unit():
    # Regression: must NEVER be "stunnel" (the distro-native unit name) -
    # on NethServer 7/RHEL that unit hardcodes /etc/stunnel/stunnel.conf as the
    # only config file it will load and fails outright ("Invalid
    # configuration file name") against any other filename, which is
    # exactly what happened live on rl94ns8/rl94ns81.
    assert mod.stunnel_service_name() == "stunnel-checkmk"


def test_install_stunnel_disables_native_unit(monkeypatch):
    calls = []
    monkeypatch.setattr(mod, "run_command", lambda cmd, timeout=15: (calls.append(cmd), (0, "", ""))[1])

    ok = mod.install_stunnel()

    assert ok is True
    assert ["yum", "install", "-y", "stunnel"] in calls
    assert ["systemctl", "stop", "stunnel"] in calls
    assert ["systemctl", "disable", "stunnel"] in calls


# --- remediate() orchestration ------------------------------------------------

def test_remediate_returns_error_when_yum_missing(monkeypatch):
    monkeypatch.setattr(mod, "is_stunnel_installed", lambda: False)
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)

    error = mod.remediate()

    assert error == "yum not found (not a NethServer 7 system?)"


def test_remediate_returns_error_when_install_fails(monkeypatch):
    monkeypatch.setattr(mod, "is_stunnel_installed", lambda: False)
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/yum" if name == "yum" else None)
    monkeypatch.setattr(mod, "install_stunnel", lambda: False)

    error = mod.remediate()

    assert error == "stunnel package installation failed"


def test_remediate_happy_path_calls_all_steps(monkeypatch):
    monkeypatch.setattr(mod, "is_stunnel_installed", lambda: True)
    calls = []
    monkeypatch.setattr(mod, "configure_agent_socket", lambda: calls.append("socket"))
    monkeypatch.setattr(mod, "generate_certificate", lambda: calls.append("cert"))
    monkeypatch.setattr(mod, "configure_stunnel", lambda: calls.append("stunnel"))

    error = mod.remediate()

    assert error is None
    assert calls == ["socket", "cert", "stunnel"]
