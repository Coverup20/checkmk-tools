#!/usr/bin/env python3
"""check_ns8_container_inventory.py - NS8 container inventory for CheckMK

Version: 1.0.0"""

import subprocess
import sys
from typing import List, Tuple

VERSION = "1.0.0"
SERVICE = "NS8.Container.Inventory"


def run_command(cmd: List[str], timeout: int = 30) -> Tuple[int, str, str]:
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=timeout,
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

    instances = []
    for line in out.splitlines():
        name = line.strip()
        if not name or name in ("cluster", "node"):
            continue
        instances.append(name)
    return instances


def get_container_list(instance: str) -> List[Tuple[str, str]]:
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

    containers: List[Tuple[str, str]] = []
    for line in out.splitlines():
        if "|" not in line:
            continue
        name, status = line.split("|", 1)
        containers.append((name.strip(), status.strip()))
    return containers


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

    total = 0
    running = 0
    stopped = 0
    names: List[str] = []

    for instance in instances:
        for container_name, container_status in get_container_list(instance):
            total += 1
            names.append(f"{instance}:{container_name}")
            if is_running(container_status):
                running += 1
            else:
                stopped += 1

    if total == 0:
        print(f"1 {SERVICE} - WARNING: nessun container trovato")
        return 0

    preview = ", ".join(names[:8])
    if len(names) > 8:
        preview = f"{preview}, ... (+{len(names) - 8} altri)"

    state = 0 if stopped == 0 else 1
    state_label = "OK" if state == 0 else "WARNING"

    print(
        f"{state} {SERVICE} - {state_label}: total={total} running={running} stopped={stopped} | total={total} running={running} stopped={stopped}; {preview}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
