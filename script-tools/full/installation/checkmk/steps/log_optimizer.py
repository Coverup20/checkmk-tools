from __future__ import annotations

import subprocess
from pathlib import Path

from lib.common import log_header, log_info, log_success, log_warn
from lib.config import InstallerConfig

_SCRIPT_REL = "script-tools/full/installation/install-checkmk-log-optimizer.sh"


def _find_script() -> Path | None:
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        candidate = parent / _SCRIPT_REL
        if candidate.exists():
            return candidate
    return None


def run(cfg: InstallerConfig) -> None:
    log_header("95-LOG-OPTIMIZER")

    script = _find_script()
    if script is None:
        log_warn(f"Script non trovato: {_SCRIPT_REL}. Skip.")
        return

    log_info("Installa logrotate per tutti i log CheckMK (Nagios, Apache, OMD, Event Console, Piggyback, Crash, Notify).")
    try:
        choice = input("Installare log optimization pack adesso? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        choice = ""

    if choice != "y":
        log_warn("Skip log optimization pack.")
        return

    log_info("Avvio installazione log optimizer...")
    result = subprocess.run(["bash", str(script)], check=False)
    if result.returncode == 0:
        log_success("Log optimization pack installato")
    else:
        log_warn(f"Script terminato con codice {result.returncode} (verificare output sopra)")
