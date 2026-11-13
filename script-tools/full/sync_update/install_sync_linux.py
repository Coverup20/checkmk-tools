#!/usr/bin/env python3
"""install_sync_linux.py - Install the GitHub-release local check sync

Copies sync_linuxchecks.py into a system directory and schedules it: a
systemd timer when systemd is available, otherwise a cron entry (OpenWrt and
images without systemd). The downloader needs no repository clone, so the
host only keeps the small script plus its staging directory.

The installer is idempotent: running it again updates the script and the
schedule in place. --uninstall removes the schedule and the script but leaves
the checks already deployed in the agent local directory untouched.

Version: 1.0.0"""

import argparse
import os
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path

VERSION = "1.0.0"

SERVICE_NAME = "cmk-local-checks-sync.service"
TIMER_NAME = "cmk-local-checks-sync.timer"
UNIT_DIR = "/etc/systemd/system"
CRON_MARKER = "sync_linuxchecks"
DEFAULT_INSTALL_DIR = "/usr/local/bin"
DEFAULT_LOG = "/var/log/cmk-local-checks-sync.log"
DEFAULT_STAGING = "/var/lib/cmk-sync"
DEFAULT_TARGET = "/usr/lib/check_mk_agent/local"
DEFAULT_EXCLUDE_FILE = "/etc/checkmk-python-full-sync.exclude"
OPENWRT_CRONTAB = "/etc/crontabs/root"

SERVICE_TEMPLATE = """\
[Unit]
Description=CheckMK local checks sync from a GitHub release
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart={command}
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cmk-local-checks-sync"""

TIMER_TEMPLATE = """\
[Unit]
Description=CheckMK local checks sync - every {interval} seconds

[Timer]
OnBootSec=1min
OnUnitActiveSec={interval}s
Persistent=true

[Install]
WantedBy=timers.target"""


class InstallError(Exception):
    """Fatal error that stops the run with exit code 1."""


def info(message):
    print(f"[INFO] {message}", flush=True)


def run(command, check=False):
    """Run a command as a list and return the CompletedProcess."""
    return subprocess.run(command, capture_output=True, text=True, check=check)


def is_openwrt():
    return Path("/etc/openwrt_release").is_file()


def has_systemd():
    return Path("/run/systemd/system").is_dir() and bool(
        shutil.which("systemctl"))


def require_root(dry_run):
    if dry_run:
        return
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        raise InstallError("this installer must run as root")


def build_command(install_dir, args):
    """The exact command line the schedule runs."""
    script = Path(install_dir) / "sync_linuxchecks.py"
    parts = [
        "/usr/bin/env", "python3", str(script),
        "--repo", args.repo,
        "--categories", args.categories,
        "--target", args.target,
        "--staging", args.staging,
        "--exclude-file", args.exclude_file,
    ]
    return " ".join(shlex.quote(part) for part in parts)


def merge_cron(text, marker, line):
    """Remove every line carrying the marker and append the new one."""
    kept = [row for row in text.splitlines() if marker not in row]
    kept.append(line)
    return "\n".join(kept) + "\n"


def remove_cron(text, marker):
    """Drop every line carrying the marker."""
    kept = [row for row in text.splitlines() if marker not in row]
    return "\n".join(kept) + "\n" if kept else ""


def crontab_read():
    """Current crontab text, or empty when none is installed."""
    if is_openwrt():
        path = Path(OPENWRT_CRONTAB)
        return path.read_text() if path.is_file() else ""
    result = run(["crontab", "-l"])
    return result.stdout if result.returncode == 0 else ""


def crontab_write(text):
    """Replace the crontab with the given text."""
    if is_openwrt():
        path = Path(OPENWRT_CRONTAB)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return
    result = subprocess.run(["crontab", "-"], input=text, text=True,
                            capture_output=True)
    if result.returncode != 0:
        raise InstallError(f"crontab update failed: {result.stderr.strip()}")


def install_systemd(command, interval, dry_run):
    service = SERVICE_TEMPLATE.format(command=command)
    timer = TIMER_TEMPLATE.format(interval=interval)
    if dry_run:
        info(f"would write {UNIT_DIR}/{SERVICE_NAME} and {TIMER_NAME}")
        return
    Path(UNIT_DIR, SERVICE_NAME).write_text(service + "\n")
    Path(UNIT_DIR, TIMER_NAME).write_text(timer + "\n")
    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", "--now", TIMER_NAME], check=True)
    info(f"systemd timer {TIMER_NAME} active, every {interval}s")
    info(f"journal: journalctl -u {SERVICE_NAME} -f")


def install_cron(command, interval, log, dry_run):
    minutes = max(1, interval // 60)
    line = (f"*/{minutes} * * * * {command} >> "
            f"{shlex.quote(log)} 2>&1  # {CRON_MARKER}")
    if dry_run:
        info(f"would add the cron entry: {line}")
        return
    crontab_write(merge_cron(crontab_read(), CRON_MARKER, line))
    info(f"cron entry installed, every {minutes} min")
    info(f"log: tail -f {log}")


def uninstall(args, dry_run):
    removed = []
    if has_systemd():
        if dry_run:
            info(f"would disable {TIMER_NAME} and remove the unit files")
        else:
            run(["systemctl", "disable", "--now", TIMER_NAME])
            for name in (TIMER_NAME, SERVICE_NAME):
                path = Path(UNIT_DIR, name)
                if path.is_file():
                    path.unlink()
                    removed.append(str(path))
            run(["systemctl", "daemon-reload"])
    else:
        if dry_run:
            info("would remove the cron entry")
        else:
            crontab_write(remove_cron(crontab_read(), CRON_MARKER))

    script = Path(args.install_dir) / "sync_linuxchecks.py"
    if script.is_file():
        if dry_run:
            info(f"would remove {script}")
        else:
            script.unlink()
            removed.append(str(script))

    info("checks already deployed in the target directory were left in place")
    if removed:
        info("removed: " + ", ".join(removed))
    return 0


def self_test():
    """Offline test of the pure helpers."""
    failures = []

    def expect(condition, label):
        if condition:
            print(f"  [PASS] {label}")
        else:
            print(f"  [FAIL] {label}")
            failures.append(label)

    text = "# other entry\n0 3 * * * backup\n"
    line = f"*/5 * * * * /usr/bin/env python3 x.py  # {CRON_MARKER}"
    merged = merge_cron(text, CRON_MARKER, line)
    expect(merged.count(CRON_MARKER) == 1, "marker line added once")
    expect("0 3 * * * backup" in merged, "unrelated entries preserved")
    merged2 = merge_cron(merged, CRON_MARKER, line)
    expect(merged2.count(CRON_MARKER) == 1, "second install does not duplicate")
    expect(CRON_MARKER not in remove_cron(merged, CRON_MARKER),
           "remove drops the marker line")
    expect("0 3 * * * backup" in remove_cron(merged, CRON_MARKER),
           "remove keeps unrelated entries")

    args = argparse.Namespace(
        repo="owner/repo", categories="auto", target=DEFAULT_TARGET,
        staging=DEFAULT_STAGING, exclude_file=DEFAULT_EXCLUDE_FILE)
    command = build_command("/usr/local/bin", args)
    expect("--categories auto" in command, "command carries the categories")
    expect("sync_linuxchecks.py" in command, "command runs the downloader")
    expect(TIMER_TEMPLATE.format(interval=300).count("300s") == 1,
           "timer template carries the interval")

    if failures:
        print(f"[FAIL] self test: {len(failures)} failure(s)")
        return 1
    print("[PASS] self test: all checks passed")
    return 0


def parse_args():
    parser = argparse.ArgumentParser(
        description=f"install_sync_linux v{VERSION} - Install the local check "
                    "sync from a GitHub release",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  # Install and schedule the sync every 5 minutes
  install_sync_linux.py

  # Update the schedule only, with a preview
  install_sync_linux.py --interval 900 --dry-run

  # Remove the schedule and the script, keep deployed checks
  install_sync_linux.py --uninstall""",
    )
    parser.add_argument("--source", default=None,
                        help="path of sync_linuxchecks.py (default: next to this script)")
    parser.add_argument("--install-dir", default=DEFAULT_INSTALL_DIR,
                        help=f"where the downloader is copied (default: {DEFAULT_INSTALL_DIR})")
    parser.add_argument("--interval", type=int, default=300,
                        help="seconds between runs (default: 300)")
    parser.add_argument("--repo", default="Coverup20/checkmk-tools",
                        help="public GitHub repository")
    parser.add_argument("--categories", default="auto",
                        help="comma-separated categories, or auto (default: auto)")
    parser.add_argument("--target", default=DEFAULT_TARGET,
                        help=f"agent local directory (default: {DEFAULT_TARGET})")
    parser.add_argument("--staging", default=DEFAULT_STAGING,
                        help=f"staging and state directory (default: {DEFAULT_STAGING})")
    parser.add_argument("--exclude-file", default=DEFAULT_EXCLUDE_FILE,
                        help=f"exclude list (default: {DEFAULT_EXCLUDE_FILE})")
    parser.add_argument("--log", default=DEFAULT_LOG,
                        help=f"log file used by the cron entry (default: {DEFAULT_LOG})")
    parser.add_argument("--no-schedule", action="store_true",
                        help="copy the script without installing a schedule")
    parser.add_argument("--uninstall", action="store_true",
                        help="remove the schedule and the script")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would happen, change nothing")
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
        require_root(args.dry_run)
        if args.uninstall:
            return uninstall(args, args.dry_run)

        source = Path(args.source) if args.source else (
            Path(__file__).resolve().parent / "sync_linuxchecks.py")
        if not source.is_file():
            raise InstallError(f"downloader not found: {source}")
        if not shutil.which("python3"):
            raise InstallError("python3 not found in PATH")

        destination = Path(args.install_dir) / "sync_linuxchecks.py"
        if args.dry_run:
            info(f"would copy {source} to {destination}")
        else:
            Path(args.install_dir).mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            destination.chmod(destination.stat().st_mode | stat.S_IXUSR)
            info(f"installed {destination}")

        if args.no_schedule:
            return 0

        command = build_command(args.install_dir, args)
        if has_systemd():
            install_systemd(command, args.interval, args.dry_run)
        else:
            install_cron(command, args.interval, args.log, args.dry_run)
        return 0
    except InstallError as error:
        print(f"[ERROR] {error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
