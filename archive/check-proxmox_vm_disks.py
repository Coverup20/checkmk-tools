#!/usr/bin/env python3
"""
check-proxmox_vm_disks.py - CheckMK Local Check for Proxmox VM Disks

Monitor disk configuration for VMs and containers.

Proxmox VE

Version: 1.0.3
"""

import subprocess
import sys
import re
import time

VERSION = "1.0.3"
PVE_TIMEOUT = 6
PER_VM_CONFIG_TIMEOUT = 0.7
PER_CT_CONFIG_TIMEOUT = 0.7
TOTAL_BUDGET_SECONDS = 12


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


def sanitize_name(name):
    """Sanitize name for CheckMK service."""
    return re.sub(r'[^A-Za-z0-9_-]', '', name.upper().replace(' ', '_'))


def parse_size_to_gb(size_str):
    """Convert size string (123G, 4096M, etc.) to GB."""
    if not size_str:
        return 0
    
    match = re.match(r'^(\d+)([GMK])?$', size_str)
    if not match:
        return 0
    
    value, unit = match.groups()
    value = int(value)
    
    if unit == 'G':
        return value
    elif unit == 'M':
        return value // 1024
    elif unit == 'K':
        return value // 1048576
    else:
        return value


def main():
    started = time.monotonic()
    partial = False

    # Check qm and pct commands exist (use 'list' as validation)
    rc_qm, _ = run_cmd(["/usr/sbin/qm", "list"], timeout=5)
    rc_pct, _ = run_cmd(["/usr/sbin/pct", "list"], timeout=5)
    
    if rc_qm != 0 and rc_pct != 0:
        print("3 PVE_VM_Disks - qm/pct commands failed")
        return 0
    
    # Check VMs
    if rc_qm == 0:
        rc, out = run_cmd(["/usr/sbin/qm", "list"])
        if rc == 0:
            for line in out.splitlines()[1:]:  # Skip header
                if (time.monotonic() - started) >= TOTAL_BUDGET_SECONDS:
                    partial = True
                    break

                parts = line.split()
                if len(parts) < 2:
                    continue
                
                vmid, name = parts[0], parts[1]
                
                # Get VM config
                rc_cfg, cfg = run_cmd(["/usr/sbin/qm", "config", vmid], timeout=PER_VM_CONFIG_TIMEOUT)
                if rc_cfg != 0:
                    continue
                
                # Find disk lines (scsi0:, ide0:, sata0:, virtio0:)
                disk_lines = []
                for cfg_line in cfg.splitlines():
                    if re.match(r'^(scsi|ide|sata|virtio)\d+:', cfg_line):
                        disk_lines.append(cfg_line)
                
                if not disk_lines:
                    continue
                
                disk_count = len(disk_lines)
                total_size_gb = 0
                
                for disk_line in disk_lines:
                    # Extract size=123G
                    size_match = re.search(r'size=(\d+[GMK]?)', disk_line)
                    if size_match:
                        size_str = size_match.group(1)
                        total_size_gb += parse_size_to_gb(size_str)
                
                safe_name = sanitize_name(name)
                svc = f"DSK_{safe_name}"
                metrics = f"disks={disk_count} size_gb={total_size_gb}"
                msg = f"{disk_count} disks, Total: {total_size_gb}GB"
                print(f"0 {svc} {metrics} - {msg}")
    
    # Check LXC
    if rc_pct == 0:
        rc, out = run_cmd(["/usr/sbin/pct", "list"])
        if rc == 0:
            for line in out.splitlines()[1:]:  # Skip header
                if (time.monotonic() - started) >= TOTAL_BUDGET_SECONDS:
                    partial = True
                    break

                parts = line.split()
                if len(parts) < 2:
                    continue
                
                ctid, name = parts[0], parts[1]
                
                # Get CT config
                rc_cfg, cfg = run_cmd(["/usr/sbin/pct", "config", ctid], timeout=PER_CT_CONFIG_TIMEOUT)
                if rc_cfg != 0:
                    continue
                
                # Find rootfs line
                rootfs_line = ""
                for cfg_line in cfg.splitlines():
                    if cfg_line.startswith("rootfs:"):
                        rootfs_line = cfg_line
                        break
                
                if not rootfs_line:
                    continue
                
                # Extract size
                size_match = re.search(r'size=(\d+[GMK]?)', rootfs_line)
                if not size_match:
                    continue
                
                size_str = size_match.group(1)
                size_gb = parse_size_to_gb(size_str)
                
                safe_name = sanitize_name(name)
                svc = f"DSK_CT_{ctid}_{safe_name}"
                metrics = f"size_gb={size_gb}"
                msg = f"RootFS: {size_gb}GB"
                print(f"0 {svc} {metrics} - {msg}")

    if partial:
        elapsed = time.monotonic() - started
        print(f"1 PVE_VM_Disks_Runtime runtime_seconds={elapsed:.1f} WARN - execution budget reached, partial results")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
