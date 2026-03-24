#!/usr/bin/env python3
"""
check-proxmox_snapshots_status.py - CheckMK Local Check for Proxmox Snapshots

Monitor snapshot count and age for QEMU VMs (WARN 14 days, CRIT 30 days).

Proxmox VE

Version: 1.1.0
"""

import subprocess
import sys
import re
import time

VERSION = "1.1.0"
PVE_TIMEOUT = 8
PER_VM_SNAPSHOT_TIMEOUT = 2
TOTAL_BUDGET_SECONDS = 20
WARN_DAYS = 14
CRIT_DAYS = 30


def sanitize_name(name):
    """Sanitize VM name for CheckMK service name."""
    name = re.sub(r'[ /]', '__', name)
    name = re.sub(r'[^A-Za-z0-9_.:-]', '', name)
    return name


def run_cmd(cmd, timeout=PVE_TIMEOUT):
    """Run command with timeout."""
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=timeout
        )
        return result.returncode, result.stdout
    except subprocess.TimeoutExpired:
        return 124, ""
    except FileNotFoundError:
        return 127, ""


def get_vm_inventory():
    """Get list of (vmid, name) from qm list."""
    rc, out = run_cmd(["qm", "list"])
    if rc != 0:
        return []

    inventory = []
    for line in out.splitlines()[1:]:  # Skip header
        parts = line.split()
        if parts:
            vmid = parts[0]
            name = parts[1] if len(parts) > 1 else f"vm{vmid}"
            inventory.append((vmid, name))
    return inventory


def get_snapshot_count(vmid):
    """Get snapshot count for VM."""
    rc, out = run_cmd(["qm", "listsnapshot", vmid], timeout=PER_VM_SNAPSHOT_TIMEOUT)
    if rc != 0:
        return None
    
    count = 0
    for line in out.splitlines()[1:]:  # Skip header
        if line.strip():
            count += 1
    return count


def get_oldest_snapshot_age(vmid):
    """Get oldest snapshot age in days from /etc/pve/qemu-server/VMID.conf."""
    conf_path = f"/etc/pve/qemu-server/{vmid}.conf"
    
    try:
        with open(conf_path, 'r') as f:
            content = f.read()
    except (FileNotFoundError, PermissionError):
        return None
    
    # Find all snaptime entries
    snaptimes = []
    for line in content.splitlines():
        if line.startswith("snaptime:"):
            try:
                snaptime = int(line.split(":", 1)[1].strip())
                snaptimes.append(snaptime)
            except (ValueError, IndexError):
                continue
    
    if not snaptimes:
        return None
    
    # Get oldest snapshot
    oldest = min(snaptimes)
    now = int(time.time())
    age_sec = now - oldest
    age_days = age_sec // 86400
    
    return age_days


def main():
    started = time.monotonic()
    partial = False

    # Check qm command exists
    try:
        subprocess.run(
            ["qm", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        print("3 PVE_QEMU_Snapshots - qm command not found")
        return 0
    
    inventory = get_vm_inventory()
    if not inventory:
        print("3 PVE_QEMU_Snapshots_Summary - No VMs found")
        return 0

    vm_total = len(inventory)
    snaps_total = 0
    processed = 0

    # Per-VM checks
    for vmid, name in inventory:
        if (time.monotonic() - started) >= TOTAL_BUDGET_SECONDS:
            partial = True
            break

        safe_name = sanitize_name(name)
        svc_base = f"SNP_{safe_name}"

        snap_count = get_snapshot_count(vmid)

        if snap_count is None:
            print(f"3 {svc_base}_Count - snapshot query timeout/error")
            continue

        processed += 1
        snaps_total += snap_count

        if snap_count == 0:
            print(f"2 {svc_base}_Count count=0 CRIT - 0 snapshots")
            continue
        elif snap_count == 1:
            print(f"1 {svc_base}_Count count=1 WARN - 1 snapshot")
        else:
            print(f"0 {svc_base}_Count count={snap_count} OK - {snap_count} snapshots")
        
        # Check age
        age_days = get_oldest_snapshot_age(vmid)
        if age_days is not None:
            if age_days >= CRIT_DAYS:
                state = 2
            elif age_days >= WARN_DAYS:
                state = 1
            else:
                state = 0

            print(f"{state} {svc_base}_Age age_days={age_days};{WARN_DAYS};{CRIT_DAYS} - oldest snapshot {age_days} days")

    elapsed = time.monotonic() - started
    if partial:
        print(
            f"1 PVE_QEMU_Snapshots_Summary vms={vm_total} processed={processed} snapshots={snaps_total} runtime_seconds={elapsed:.1f} "
            f"WARN - execution budget reached, partial results"
        )
    else:
        print(
            f"0 PVE_QEMU_Snapshots_Summary vms={vm_total} processed={processed} snapshots={snaps_total} runtime_seconds={elapsed:.1f} "
            f"OK - {snaps_total} snapshots across {processed} VMs"
        )
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
