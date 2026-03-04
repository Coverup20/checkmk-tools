#!/usr/bin/env python3
"""Patch /usr/local/sbin/checkmk_cloud_backup_push_run.sh - fix remote retention sort bug."""
import sys
from pathlib import Path

WRAPPER = Path("/usr/local/sbin/checkmk_cloud_backup_push_run.sh")

OLD = "    mapfile -t sorted_backups < <(printf '%s\\n' \"${all_remote_backups[@]}\" | sort -r)"
NEW = """    mapfile -t sorted_backups < <(
      printf '%s\\n' "${all_remote_backups[@]}" | \\
        sed 's/.*\\([0-9]\\{4\\}-[0-9]\\{2\\}-[0-9]\\{2\\}-[0-9]\\{2\\}h[0-9]\\{2\\}\\).*/\\1 &/' | \\
        sort -r | \\
        cut -d' ' -f2-
    )"""

if not WRAPPER.exists():
    print(f"ERROR: {WRAPPER} not found", file=sys.stderr)
    sys.exit(1)

content = WRAPPER.read_text()

if OLD not in content:
    if "sorted_backups" in content and "sort -r" not in content:
        print("Already patched.")
        sys.exit(0)
    print(f"ERROR: pattern not found in {WRAPPER}", file=sys.stderr)
    sys.exit(1)

WRAPPER.write_text(content.replace(OLD, NEW, 1))
print(f"Patched OK: {WRAPPER}")
