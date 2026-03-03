#!/usr/bin/env python3
"""
rssh_nethvoice_trunks.py - Remote launcher per check_nethvoice_trunks.py

Scarica ed esegue la versione completa del check da GitHub.
Da deployare in /usr/lib/check_mk_agent/local/ (senza estensione .py).

Version: 1.0.0
"""

import urllib.request
import sys

VERSION = "1.0.0"

REPO_URL = (
    "https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/"
    "script-check-ns8/full/check_nethvoice_trunks.py"
)

try:
    with urllib.request.urlopen(REPO_URL, timeout=10) as response:
        script_code = response.read().decode("utf-8")
    exec(script_code, {"__name__": "__main__"})
except Exception as exc:
    print(f"3 NethVoice_Trunks - UNKNOWN: impossibile scaricare/eseguire lo script remoto: {exc}")
    sys.exit(0)
