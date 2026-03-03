#!/usr/bin/env python3
"""
install-agent-interactive.py

Python entrypoint that delegates to install-agent-interactive.sh.
Version: 1.0.0
"""

import os
import subprocess
import sys
from pathlib import Path

VERSION = "1.0.0"


def usage() -> None:
    print(
        "Usage:\n"
        "  install-agent-interactive.py [args]\n\n"
        "Delegates to install-agent-interactive.sh for full interactive installation workflow."
    )


def main() -> int:
    if any(arg in {"-h", "--help"} for arg in sys.argv[1:]):
        usage()
        return 0

    script = Path(__file__).with_name("install-agent-interactive.sh")
    if not script.exists():
        print(f"ERROR: missing target script: {script}", file=sys.stderr)
        return 1

    result = subprocess.run(["bash", str(script), *sys.argv[1:]], env=os.environ.copy())
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
