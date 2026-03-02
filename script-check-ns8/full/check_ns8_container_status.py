#!/usr/bin/env python3
"""
check_ns8_container_status.py - Stato container NS8 per CheckMK

Version: 1.3.0
"""

import subprocess
import sys
import time
from typing import List, Tuple

VERSION = "1.3.0"
SERVICE = "NS8 Container Status"
SCRIPT_TIMEOUT_SECONDS = 10
COMMAND_TIMEOUT_SECONDS = 4
_SCRIPT_START = time.monotonic()


def run_command(cmd: List[str], timeout: int = 30) -> Tuple[int, str, str]:
    try:
        remaining = SCRIPT_TIMEOUT_SECONDS - (time.monotonic() - _SCRIPT_START)
        if remaining <= 0:
            return 124, "", "timeout"

        effective_timeout = min(timeout, COMMAND_TIMEOUT_SECONDS, max(1, int(remaining)))
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=effective_timeout,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return 1, "", "timeout"
    except FileNotFoundError:
        return 127, "", "command not found"
    except Exception as exc:
        return 1, "", str(exc)


def get_instances() -> List[str]:
    code, out, _ = run_command(["runagent", "-l"])
    if code != 0 or not out:
        return []

    result = []
    for line in out.splitlines():
        name = line.strip()
        if not name or name in ("cluster", "node"):
            continue
        result.append(name)
    return result


def get_containers(instance: str) -> List[Tuple[str, str]]:
    code, out, _ = run_command(
        [
            "runagent",
            "-m",
            instance,
            "podman",
            "ps",
            "-a",
            "--format",
            "{{.Names}}|{{.Status}}",
        ]
    )
    if code != 0 or not out:
        return []

    rows: List[Tuple[str, str]] = []
    for line in out.splitlines():
        if "|" not in line:
            continue
        name, status = line.split("|", 1)
        rows.append((name.strip(), status.strip()))
    return rows


def is_running(status: str) -> bool:
    return status.startswith("Up")


def main() -> int:
    if run_command(["which", "runagent"])[0] != 0:
        print(f"3 {SERVICE} - UNKNOWN: runagent non trovato")
        return 0

    instances = get_instances()
    if not instances:
        print(f"3 {SERVICE} - UNKNOWN: nessuna istanza NS8 trovata")
        return 0

    critical_problems: List[str] = []
    warning_notes: List[str] = []
    checked = 0
    timed_out = False

    for instance in instances:
        if (time.monotonic() - _SCRIPT_START) >= SCRIPT_TIMEOUT_SECONDS:
            timed_out = True
            break

        containers = get_containers(instance)
        if not containers:
            warning_notes.append(f"{instance}:no-containers-or-inactive")
            continue

        for container_name, container_status in containers:
            checked += 1
            if not is_running(container_status):
                critical_problems.append(f"{instance}:{container_name}({container_status})")

    partial = " (partial scan)" if timed_out else ""

    if checked == 0:
        detail = ", ".join(warning_notes[:8]) if warning_notes else "nessun dato"
        print(f"1 {SERVICE} - WARNING: nessun container rilevato{partial} | {detail}")
        return 0

    if critical_problems:
        detail = ", ".join(critical_problems[:10])
        if len(critical_problems) > 10:
            detail = f"{detail}, ... (+{len(critical_problems) - 10} altri)"
        print(f"2 {SERVICE} - CRIT: problematici={len(critical_problems)}/{checked}{partial} | {detail}")
    elif warning_notes:
        detail = ", ".join(warning_notes[:10])
        if len(warning_notes) > 10:
            detail = f"{detail}, ... (+{len(warning_notes) - 10} altri)"
        print(f"1 {SERVICE} - WARNING: running={checked}, note={len(warning_notes)}{partial} | {detail}")
    else:
        print(f"0 {SERVICE} - OK: tutti i container sono running ({checked}/{checked}){partial}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
