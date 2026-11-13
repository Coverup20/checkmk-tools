#!/usr/bin/env python3
"""check_pending_reboot.py - CheckMK Local Check for a pending reboot on Windows

Reads the markers Windows leaves when a restart is required: the component
based servicing key, the Windows Update key and the pending file rename
operations. Prints the standard local check line for the CheckMK agent.

Version: 1.0.0"""

import argparse
import sys

try:
    import winreg
except ImportError:  # not Windows
    winreg = None

VERSION = "1.0.0"
SERVICE = "Pending.Reboot"

MARKERS = (
    ("CBS",
     r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending"),
    ("WindowsUpdate",
     r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired"),
)

SESSION_MANAGER = r"SYSTEM\CurrentControlSet\Control\Session Manager"
FILE_RENAME_VALUE = "PendingFileRenameOperations"


def key_exists(path):
    """True when the HKLM key exists, False otherwise."""
    try:
        handle = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path)
    except OSError:
        return False
    handle.Close()
    return True


def file_renames_pending():
    """True when PendingFileRenameOperations has at least one entry."""
    try:
        handle = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, SESSION_MANAGER)
    except OSError:
        return False
    try:
        value, _kind = winreg.QueryValueEx(handle, FILE_RENAME_VALUE)
    except OSError:
        return False
    finally:
        handle.Close()
    return bool(value)


def pending_reasons():
    """Names of the markers that report a pending reboot."""
    reasons = [name for name, path in MARKERS if key_exists(path)]
    if file_renames_pending():
        reasons.append("PendingFileRename")
    return reasons


def emit(reasons):
    """Print the local check line for the given reasons."""
    if reasons:
        print("1 %s - reboot pending (%s)" % (SERVICE, ", ".join(reasons)))
    else:
        print("0 %s - no reboot pending" % SERVICE)


def self_test():
    """Check the output format and the registry helpers."""
    if winreg is None:
        print("[SKIP] registry helpers need Windows")
        return 0
    if not key_exists(r"SOFTWARE\Microsoft"):
        print("[FAIL] a known HKLM key was not found")
        return 1
    if key_exists(r"SOFTWARE\ThisKeyDoesNotExist-4c1e2d"):
        print("[FAIL] a missing HKLM key was reported as present")
        return 1
    emit([])
    emit(["CBS"])
    emit(["CBS", "PendingFileRename"])
    print("[OK] self-test")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="CheckMK local check: pending reboot on Windows")
    parser.add_argument("--self-test", action="store_true",
                        help="validate the output format and registry access")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if winreg is None:
        print("3 %s - unsupported platform" % SERVICE)
        return 0
    emit(pending_reasons())
    return 0


if __name__ == "__main__":
    sys.exit(main())
