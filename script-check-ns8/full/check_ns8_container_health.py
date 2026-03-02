#!/usr/bin/env python3
"""
check_ns8_container_health.py - CheckMK Local Check per stato container NS8

Monitora i container delle istanze NS8 (runagent + podman):
- conta container totali/running/problematici
- segnala in CRITICAL i container non running

Version: 1.0.0
"""

import subprocess
import sys
from typing import List, Tuple

VERSION = "1.0.0"
SERVICE = "NS8.Containers"


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
        return 1, "", "Command timeout"
    except FileNotFoundError:
        return 127, "", "Command not found"
    except Exception as exc:
        return 1, "", str(exc)


def get_instances() -> List[str]:
    code, out, _ = run_command(["runagent", "-l"])
    if code != 0 or not out:
        return []

    instances = []
    for line in out.splitlines():
        name = line.strip()
        if not name:
            continue
        if name in ("cluster", "node"):
            continue
        instances.append(name)
    return instances


def get_instance_containers(instance: str) -> List[Tuple[str, str]]:
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

    containers = []
    for line in out.splitlines():
        if "|" not in line:
            continue
        name, status = line.split("|", 1)
        containers.append((name.strip(), status.strip()))
    return containers


def status_is_running(status: str) -> bool:
    return status.startswith("Up")


def main() -> int:
    if run_command(["which", "runagent"])[0] != 0:
        print("3 {} - UNKNOWN: runagent non trovato".format(SERVICE))
        return 0

    instances = get_instances()
    if not instances:
        print("3 {} - UNKNOWN: nessuna istanza NS8 trovata".format(SERVICE))
        return 0

    total = 0
    running = 0
    problems: List[str] = []

    for instance in instances:
        containers = get_instance_containers(instance)
        if not containers:
            problems.append("{}:no-containers".format(instance))
            continue

        for container_name, container_status in containers:
            total += 1
            if status_is_running(container_status):
                running += 1
            else:
                problems.append("{}:{}({})".format(instance, container_name, container_status))

    problem_count = len(problems)

    if problem_count > 0:
        detail = ", ".join(problems[:8])
        if problem_count > 8:
            detail = "{}, ... (+{} altri)".format(detail, problem_count - 8)
        print(
            "2 {} - CRIT: total={} running={} problem={} | {}".format(
                SERVICE, total, running, problem_count, detail
            )
        )
    else:
        print("0 {} - OK: total={} running={} problem=0".format(SERVICE, total, running))

    return 0


if __name__ == "__main__":
    sys.exit(main())
