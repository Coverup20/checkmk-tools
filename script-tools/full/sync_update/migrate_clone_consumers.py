#!/usr/bin/env python3
"""migrate_clone_consumers.py - Move scripts out of a deploy clone

The local-check sync no longer needs the /opt/checkmk-tools clone, but a few
scheduled jobs still execute scripts that live inside it: the weekly CheckMK
upgrade, the daily/weekly backup management and the agent autoupdate. This
tool copies those scripts to /usr/local/lib/checkmk-tools-upgrade and rewrites
the exact absolute paths in the crontab and in the systemd unit files, so the
clone can be removed afterwards.

Only the known paths listed in PAYLOADS are touched; every replaced file is
saved under /var/backups/cmk-migration/<timestamp> and --rollback restores it.
Dry run is the default: nothing changes without --apply.

Version: 1.0.0"""

import argparse
import datetime
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

VERSION = "1.0.0"

CLONE_DIR = "/opt/checkmk-tools"
DEST_DIR = "/usr/local/lib/checkmk-tools-upgrade"
BACKUP_ROOT = "/var/backups/cmk-migration"
UNIT_DIR = "/etc/systemd/system"

PAYLOADS = [
    "script-tools/full/upgrade_maintenance/upgrade-checkmk.py",
    "script-tools/full/upgrade_maintenance/upgrade_checkmk.py",
    "script-tools/full/backup_restore/checkmk_manage_job00_daily.py",
    "script-tools/full/backup_restore/checkmk_manage_job01_weekly.py",
    "script-tools/full/agent_maintenance/checkmk-agent-autoupdate-linux.py",
]


class MigrationError(Exception):
    """Fatal error that stops the run with exit code 1."""


def info(message):
    print(f"[INFO] {message}", flush=True)


def warn(message):
    print(f"[WARN] {message}", flush=True)


def run(command):
    return subprocess.run(command, capture_output=True, text=True)


def old_path(relative):
    return str(Path(CLONE_DIR) / relative)


def new_path(relative):
    return str(Path(DEST_DIR) / Path(relative).name)


def replacements():
    """Exact old path to new path map for the payloads that exist."""
    pairs = {}
    for relative in PAYLOADS:
        if Path(old_path(relative)).is_file():
            pairs[old_path(relative)] = new_path(relative)
    return pairs


def rewrite_text(text, pairs):
    """Replace exact paths; returns (new text, replacement count)."""
    count = 0
    for old, new in pairs.items():
        occurrences = text.count(old)
        if occurrences:
            text = text.replace(old, new)
            count += occurrences
    return text, count


def unit_files(unit_dir, pairs):
    """Unit files that mention at least one of the old paths."""
    found = []
    for path in sorted(Path(unit_dir).glob("*.service")):
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        if any(old in text for old in pairs):
            found.append(path)
    return found


def crontab_read(crontab_file):
    """Current crontab text, or empty when none is installed."""
    if crontab_file:
        path = Path(crontab_file)
        return path.read_text() if path.is_file() else ""
    result = run(["crontab", "-l"])
    return result.stdout if result.returncode == 0 else ""


def crontab_write(text, crontab_file):
    if crontab_file:
        Path(crontab_file).write_text(text)
        return
    result = subprocess.run(["crontab", "-"], input=text, text=True,
                            capture_output=True)
    if result.returncode != 0:
        raise MigrationError(f"crontab update failed: {result.stderr.strip()}")


def validate_python(source, name):
    """Refuse to install a payload that does not compile."""
    try:
        compile(source, name, "exec")
    except SyntaxError as error:
        raise MigrationError(f"{name} does not compile: {error}")


def backup_dir():
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path(BACKUP_ROOT) / stamp


def apply(dry_run, crontab_file, unit_dir):
    pairs = replacements()
    if not pairs:
        raise MigrationError(f"no payload found under {CLONE_DIR}")
    missing = [relative for relative in PAYLOADS
               if not Path(old_path(relative)).is_file()]
    for relative in missing:
        warn(f"not present on this host, skipped: {relative}")

    dest = Path(DEST_DIR)
    backup = backup_dir()
    plan = {
        "copied": [],
        "crontab_replacements": 0,
        "units": [],
        "backup": str(backup),
    }

    if dry_run:
        for relative in PAYLOADS:
            if Path(old_path(relative)).is_file():
                info(f"would copy {old_path(relative)} -> {new_path(relative)}")
        text, count = rewrite_text(crontab_read(crontab_file), pairs)
        plan["crontab_replacements"] = count
        info(f"crontab: {count} path replacement(s)")
        for path in unit_files(unit_dir, pairs):
            info(f"would rewrite {path}")
            plan["units"].append(str(path))
        info("dry run: nothing was changed")
        return plan

    dest.mkdir(parents=True, exist_ok=True)
    backup.mkdir(parents=True, exist_ok=True)

    for relative in PAYLOADS:
        source = Path(old_path(relative))
        if not source.is_file():
            continue
        target = Path(new_path(relative))
        validate_python(source.read_text(errors="replace"), source.name)
        shutil.copyfile(source, target)
        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP
                     | stat.S_IXOTH)
        plan["copied"].append(str(target))
        info(f"copied {source} -> {target}")

    original_cron = crontab_read(crontab_file)
    (backup / "crontab.txt").write_text(original_cron)
    new_cron, count = rewrite_text(original_cron, pairs)
    if count:
        crontab_write(new_cron, crontab_file)
    plan["crontab_replacements"] = count
    info(f"crontab: {count} path replacement(s)")

    for path in unit_files(unit_dir, pairs):
        shutil.copy2(path, backup / path.name)
        text, count = rewrite_text(path.read_text(), pairs)
        path.write_text(text)
        plan["units"].append(str(path))
        info(f"rewrote {path} ({count} replacement(s))")

    if plan["units"] and not unit_dir_override(unit_dir):
        run(["systemctl", "daemon-reload"])
        info("systemd daemon reloaded")

    (backup / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    info(f"backup: {backup}")
    return plan


def unit_dir_override(unit_dir):
    """True when the unit directory is not the real one (test or container)."""
    return str(unit_dir) != UNIT_DIR


def rollback(backup, unit_dir):
    backup = Path(backup)
    if not backup.is_dir():
        raise MigrationError(f"backup directory not found: {backup}")

    for path in backup.glob("*.service"):
        shutil.copy2(path, Path(unit_dir) / path.name)
        info(f"restored {Path(unit_dir) / path.name}")
    if not unit_dir_override(unit_dir):
        run(["systemctl", "daemon-reload"])

    cron_backup = backup / "crontab.txt"
    if cron_backup.is_file():
        warn("restore the crontab by hand from " + str(cron_backup)
             + " (the tool never rewrites a crontab it cannot show you)")
    info("rollback complete; copied scripts in the destination are left in place")
    return 0


def self_test():
    """Offline test of copy, rewrite and rollback in a temporary tree."""
    global CLONE_DIR, DEST_DIR, BACKUP_ROOT
    failures = []

    def expect(condition, label):
        print(("  [PASS] " if condition else "  [FAIL] ") + label)
        if not condition:
            failures.append(label)

    root = Path(tempfile.mkdtemp(prefix="cmk-migrate-test-"))
    original = (CLONE_DIR, DEST_DIR, BACKUP_ROOT)
    try:
        CLONE_DIR = str(root / "clone")
        DEST_DIR = str(root / "dest")
        BACKUP_ROOT = str(root / "backups")
        unit_dir = root / "units"
        unit_dir.mkdir()
        cron_file = root / "crontab"

        for relative in PAYLOADS[:2]:
            path = root / "clone" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("#!/usr/bin/env python3\nprint('ok')\n")

        unit = unit_dir / "checkmk-python-full-sync.service"
        unit.write_text(
            "[Service]\nExecStart=/usr/bin/python3 "
            f"{old_path(PAYLOADS[0])}\n")
        cron_file.write_text(
            f"0 2 * * 0 python3 {old_path(PAYLOADS[1])} --email x\n"
            "0 3 * * * unrelated\n")

        plan = apply(True, str(cron_file), unit_dir)
        expect(plan["crontab_replacements"] == 1,
               "dry run reports the cron replacement")
        expect(cron_file.read_text().count(old_path(PAYLOADS[1])) == 1,
               "dry run does not change the crontab")
        expect(not (root / "dest").exists(), "dry run copies nothing")

        plan = apply(False, str(cron_file), unit_dir)
        expect(len(plan["copied"]) == 2, "both payloads copied")
        expect((root / "dest" / "upgrade-checkmk.py").is_file(),
               "destination keeps the file name")
        expect(cron_file.read_text().count("/opt/checkmk-tools") == 0,
               "crontab path rewritten")
        expect(new_path(PAYLOADS[1]) in cron_file.read_text(),
               "crontab points to the new path")
        expect("unrelated" in cron_file.read_text(),
               "unrelated cron entries kept")
        expect(old_path(PAYLOADS[0]) not in unit.read_text(),
               "unit rewritten")
        expect(new_path(PAYLOADS[0]) in unit.read_text(),
               "unit points to the new path")
        expect((Path(plan["backup"]) / "crontab.txt").is_file(),
               "crontab backup created")
        expect((Path(plan["backup"]) / unit.name).is_file(),
               "unit backup created")

        unit.write_text("[Service]\nExecStart=/bin/true\n")
        rollback(plan["backup"], unit_dir)
        expect(old_path(PAYLOADS[0]) in unit.read_text(),
               "unit restored by rollback")
        expect("unrelated" in cron_file.read_text(),
               "rollback never writes the crontab")
    except Exception as error:  # pragma: no cover - self test guard
        print(f"  [FAIL] unexpected exception: {error}")
        failures.append("exception")
    finally:
        CLONE_DIR, DEST_DIR, BACKUP_ROOT = original
        shutil.rmtree(root, ignore_errors=True)

    if failures:
        print(f"[FAIL] self test: {len(failures)} failure(s)")
        return 1
    print("[PASS] self test: all checks passed")
    return 0


def parse_args():
    parser = argparse.ArgumentParser(
        description=f"migrate_clone_consumers v{VERSION} - Move the scheduled "
                    "scripts out of the deploy clone",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  # Show what would change
  migrate_clone_consumers.py

  # Apply the migration (root)
  migrate_clone_consumers.py --apply

  # Restore crontab and units from a backup
  migrate_clone_consumers.py --rollback /var/backups/cmk-migration/20261113-120000""",
    )
    parser.add_argument("--apply", action="store_true",
                        help="write the changes (default is a dry run)")
    parser.add_argument("--rollback", default=None,
                        help="restore units from a backup directory")
    parser.add_argument("--unit-dir", default=UNIT_DIR,
                        help=f"systemd unit directory (default: {UNIT_DIR})")
    parser.add_argument("--crontab-file", default=None,
                        help="read and write this file instead of the crontab")
    parser.add_argument("--self-test", action="store_true",
                        help="run the offline self test")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {VERSION}")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.self_test:
        return self_test()
    try:
        if args.rollback:
            return rollback(args.rollback, args.unit_dir)
        if args.apply and not args.crontab_file:
            if hasattr(os, "geteuid") and os.geteuid() != 0:
                raise MigrationError("--apply must run as root")
        apply(not args.apply, args.crontab_file, args.unit_dir)
        return 0
    except MigrationError as error:
        print(f"[ERROR] {error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
