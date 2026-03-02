#!/usr/bin/env python3
"""
check_ns8_container_resources.py - Risorse container NS8 per CheckMK

Version: 1.1.0
"""

import subprocess
import sys
from typing import List, Tuple

VERSION = "1.1.0"
SERVICE = "NS8 Container Resources"
CPU_WARN = 80.0
CPU_CRIT = 95.0
MEM_WARN = 80.0
MEM_CRIT = 95.0


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

    result = []
    for line in out.splitlines():
        name = line.strip()
        if not name or name in ("cluster", "node"):
            continue
        result.append(name)
    return result


def parse_percent(value: str) -> float:
    clean = value.replace("%", "").replace(",", ".").strip()
    try:
        return float(clean)
    except ValueError:
        return 0.0


def get_stats(instance: str) -> List[Tuple[str, float, float, str]]:
    code, out, _ = run_command(
        [
            "runagent",
            "-m",
            instance,
            "podman",
            "stats",
            "--no-stream",
            "--format",
            "{{.Name}}|{{.CPUPerc}}|{{.MemPerc}}|{{.MemUsage}}",
        ]
    )
    if code != 0 or not out:
        return []

    result: List[Tuple[str, float, float, str]] = []
    for line in out.splitlines():
        parts = line.split("|", 3)
        if len(parts) != 4:
            continue
        name = parts[0].strip()
        cpu = parse_percent(parts[1])
        mem = parse_percent(parts[2])
        usage = parts[3].strip()
        result.append((name, cpu, mem, usage))
    return result


def state_for(cpu: float, mem: float) -> int:
    if cpu >= CPU_CRIT or mem >= MEM_CRIT:
        return 2
    if cpu >= CPU_WARN or mem >= MEM_WARN:
        return 1
    return 0


def label_for(state: int) -> str:
    if state == 2:
        return "CRIT"
    if state == 1:
        return "WARN"
    return "OK"


def top_entries(entries: List[Tuple[str, float]], size: int = 3) -> str:
    if not entries:
        return "n/a"
    ordered = sorted(entries, key=lambda item: item[1], reverse=True)[:size]
    return ", ".join(f"{name}:{value:.1f}%" for name, value in ordered)


def main() -> int:
    if run_command(["which", "runagent"])[0] != 0:
        print(f"3 {SERVICE} - UNKNOWN: runagent non trovato")
        return 0

    instances = get_instances()
    if not instances:
        print(f"3 {SERVICE} - UNKNOWN: nessuna istanza NS8 trovata")
        return 0

    total = 0
    warn_count = 0
    crit_count = 0
    max_cpu = 0.0
    max_mem = 0.0
    cpu_items: List[Tuple[str, float]] = []
    mem_items: List[Tuple[str, float]] = []

    for instance in instances:
        stats = get_stats(instance)
        for container_name, cpu, mem, usage in stats:
            total += 1
            state = state_for(cpu, mem)
            if state == 2:
                crit_count += 1
            elif state == 1:
                warn_count += 1

            if cpu > max_cpu:
                max_cpu = cpu
            if mem > max_mem:
                max_mem = mem

            cpu_items.append((f"{instance}/{container_name}", cpu))
            mem_items.append((f"{instance}/{container_name}", mem))

    if total == 0:
        print(f"1 {SERVICE} - WARNING: nessuna metrica container disponibile")
        return 0

    overall_state = 2 if crit_count > 0 else 1 if warn_count > 0 else 0
    label = label_for(overall_state)

    top_cpu = top_entries(cpu_items)
    top_mem = top_entries(mem_items)

    print(
        f"{overall_state} {SERVICE} - {label}: total={total} warn={warn_count} crit={crit_count} top_cpu=[{top_cpu}] top_mem=[{top_mem}] | max_cpu={max_cpu:.2f};{CPU_WARN};{CPU_CRIT};0;100 max_mem={max_mem:.2f};{MEM_WARN};{MEM_CRIT};0;100"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
