from __future__ import annotations

import time
from pathlib import Path

from lib.common import command_exists, log_header, log_info, log_success, log_warn, run as run_cmd
from lib.config import InstallerConfig

_WAIT_POLL_SEC = 5       # intervallo polling
_WAIT_TIMEOUT_SEC = 180  # massimo 3 minuti


def _find_repo_root() -> Path | None:
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / "script-tools" / "full").exists():
            return parent
    return None


def _find_local_agent_deb() -> Path | None:
    candidates: list[Path] = []
    for pattern in [
        Path("/omd/versions/default/share/check_mk/agents").glob("check-mk-agent_*_all.deb"),
        Path("/omd/versions").glob("*/share/check_mk/agents/check-mk-agent_*_all.deb"),
    ]:
        candidates.extend([p for p in pattern if p.is_file()])
    if not candidates:
        return None
    return sorted(candidates)[-1]


def _try_install_agent_via_interactive_script(cfg: InstallerConfig, repo_root: Path | None) -> bool:
    if repo_root is None:
        return False

    installer = repo_root / "script-tools" / "full" / "installation" / "install-agent-interactive.sh"
    if not installer.exists():
        return False
    if not command_exists("bash"):
        return False

    site = (cfg.site_name or "monitoring").strip()
    base_urls = [
        f"http://127.0.0.1:5000/{site}/check_mk/agents",
        f"http://localhost/{site}/check_mk/agents",
    ]

    for base_url in base_urls:
        log_info(f"Trying agent install via install-agent-interactive.sh (CHECKMK_BASE_URL={base_url})")
        cmd = [
            "bash",
            "-lc",
            # Auto-answer prompts:
            # 1) Do you proceed with the installation? [y/N] -> y
            # 2) Do you also want to install FRPC? [y/N] -> N
            f"set -euo pipefail; export CHECKMK_BASE_URL={base_url}; printf 's\\nN\\n' | bash {installer}",
        ]
        run_cmd(cmd, check=False)

        if Path("/usr/lib/check_mk_agent/local").exists():
            return True

    return False


def _ensure_agent_and_local_dir(cfg: InstallerConfig, repo_root: Path | None) -> bool:
    local_dir = Path("/usr/lib/check_mk_agent/local")
    if local_dir.exists():
        return True

    if _try_install_agent_via_interactive_script(cfg, repo_root):
        return True

    deb = _find_local_agent_deb()
    if deb is None:
        return False

    log_info(f"CheckMK Agent not detected (missing {local_dir}). Installing from: {deb}")
    run_cmd(["dpkg", "-i", str(deb)], check=False)
    run_cmd(["apt-get", "-f", "-y", "install"], check=False)
    return local_dir.exists()


def _wait_for_local_dir(timeout: int = _WAIT_TIMEOUT_SEC) -> bool:
    """Wait polling until /usr/lib/check_mk_agent/local appears (created by the CheckMK agent)."""
    local_dir = Path("/usr/lib/check_mk_agent/local")
    if local_dir.exists():
        return True

    log_info(f"/usr/lib/check_mk_agent/local non trovata. Attendo installazione agent CheckMK (max {timeout}s)...")
    elapsed = 0
    while elapsed < timeout:
        time.sleep(_WAIT_POLL_SEC)
        elapsed += _WAIT_POLL_SEC
        if local_dir.exists():
            log_success(f"  /usr/lib/check_mk_agent/local trovata dopo {elapsed}s")
            return True
        log_info(f"  ... attendo ({elapsed}/{timeout}s)")

    log_warn(f"Timeout: /usr/lib/check_mk_agent/local non trovata dopo {timeout}s.")
    return False


def run_step(cfg: InstallerConfig) -> None:
    log_header("60-DEPLOY-LOCAL-CHECKS")

    if not cfg.deploy_local_checks:
        log_info("DEPLOY_LOCAL_CHECKS=false: skipping")
        return

    repo_root = _find_repo_root()

    # First try agent installation, then wait for polling
    if not Path("/usr/lib/check_mk_agent/local").exists():
        _ensure_agent_and_local_dir(cfg, repo_root)

    if not _wait_for_local_dir():
        log_warn("Impossibile trovare /usr/lib/check_mk_agent/local. Skip deploy check.")
        log_warn("Hint: installa CheckMK agent, poi ri-esegui: ./installer.py deploy-checks")
        return

    if repo_root is None:
        log_warn("Repository root non trovato (script-tools/full mancante). Skip deploy check.")
        return

    script_path = repo_root / "script-tools" / "full" / "deploy" / "auto-deploy-checks.py"
    if not script_path.exists():
        log_warn(f"auto-deploy-checks.py non trovato in: {script_path}. Skip.")
        return

    log_info("Deploy check locali CheckMK in /usr/lib/check_mk_agent/local ...")
    run_cmd(["python3", str(script_path), "--install-all", "--yes"])
    log_success("Check locali deployati")


def run(cfg: InstallerConfig) -> None:
    run_step(cfg)
