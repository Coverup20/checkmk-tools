#!/usr/bin/env python3
"""install-agent-nsec8-apk.py — CheckMK Agent Installer — APK Edition (BETA)

Install and configure CheckMK Agent on NethSecurity 8.8+ (APK-based).

Based on the verified NSec8 APK Migration Guide:
    script-check-nsec8/doc/nsec8-apk-migration-guide.md

Target platform:
    NethSecurity 8.8 (OpenWRT 25.12, APK package manager)
    checkmk-agent 2.5.0-r1
    ns-checkmk-utils 0.0.5-r1

Installation commands (from guide §3):
    apk update
    apk add checkmk-agent
    apk add ns-checkmk-utils

Deploy check scripts from repository full/ to /usr/lib/check_mk_agent/local/.
Scripts are copied WITHOUT the .py extension — CheckMK runs all executable
files in the local directory regardless of extension.

Usage:
  python3 install-agent-nsec8-apk.py                     # Install agent + deploy checks
  python3 install-agent-nsec8-apk.py --agent-only        # Install agent only (skip check deploy)
  python3 install-agent-nsec8-apk.py --deploy-checks     # Deploy checks only (skip agent install)
  python3 install-agent-nsec8-apk.py --uninstall         # Remove agent and checks
  python3 install-agent-nsec8-apk.py --help              # Show this help

Version: 1.0.0b1 (BETA)"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

VERSION = "1.0.0b1"

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
AGENT_BIN = "/usr/sbin/check_mk_agent"          # installed by apk
AGENT_BIN_ALT = "/usr/bin/check_mk_agent"       # alternative location
LOCAL_DIR = Path("/usr/lib/check_mk_agent/local")
PACKAGES = ["checkmk-agent", "ns-checkmk-utils"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def log(msg: str) -> None:
    print(f"  [INFO] {msg}", flush=True)


def ok(msg: str) -> None:
    print(f"  [ OK ] {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"  [WARN] {msg}", flush=True)


def die(msg: str) -> None:
    print(f"  [ERR]  {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


def run(cmd, check=True, timeout=120, capture=False):
    """Run a command, print output live unless capture=True."""
    if capture:
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=timeout
        )
    else:
        result = subprocess.run(cmd, timeout=timeout)
    if check and result.returncode != 0:
        die(f"Command failed (exit {result.returncode}): {' '.join(cmd)}")
    return result


def is_root() -> bool:
    return os.geteuid() == 0


def detect_system() -> str:
    """Verify we are on NethSecurity 8.8+ with APK available."""
    if not shutil.which("apk"):
        die("apk not found — this script requires NethSecurity 8.8+ (APK-based)")

    os_release = Path("/etc/os-release")
    if os_release.exists():
        text = os_release.read_text()
        if "NethSecurity" in text:
            for line in text.splitlines():
                if line.startswith("VERSION_ID="):
                    ver = line.split("=", 1)[1].strip().strip('"')
                    log(f"Detected NethSecurity {ver}")
                    return ver
    log("Detected NethSecurity (APK-based)")
    return "unknown"


def check_apk_package_installed(pkg: str) -> bool:
    """Check if an APK package is already installed."""
    result = subprocess.run(
        ["apk", "list", "--installed", pkg],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, timeout=30
    )
    return result.returncode == 0 and pkg in result.stdout


# ---------------------------------------------------------------------------
# Installation phases
# ---------------------------------------------------------------------------


def phase_update() -> None:
    """Phase 1: Update APK repository indexes."""
    log("Updating APK repository indexes...")
    run(["apk", "update"])
    ok("Repository indexes updated")


def phase_install_agent() -> None:
    """Phase 2: Install checkmk-agent and ns-checkmk-utils via APK."""
    for pkg in PACKAGES:
        if check_apk_package_installed(pkg):
            log(f"{pkg} already installed, skipping")
            continue
        log(f"Installing {pkg}...")
        run(["apk", "add", pkg])
        ok(f"{pkg} installed")


def phase_verify_agent() -> None:
    """Phase 3: Verify agent installation."""
    log("Verifying agent installation...")

    # Check binary
    agent_path = None
    for path in (AGENT_BIN, AGENT_BIN_ALT):
        if os.path.exists(path):
            agent_path = path
            break

    if not agent_path:
        warn("Agent binary not found at expected paths")
        return

    result = subprocess.run(
        [agent_path, "--version"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, timeout=15
    )
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            if "Version:" in line or "AgentOS:" in line:
                log(line.strip())
        ok(f"Agent binary: {agent_path}")
    else:
        warn(f"Agent binary found but --version failed: {result.stderr.strip()}")

    # Verify APK package listing
    for pkg in PACKAGES:
        r = subprocess.run(
            ["apk", "list", pkg],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, timeout=15
        )
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                if pkg in line:
                    log(line.strip())

    # Show installed local checks
    if LOCAL_DIR.is_dir():
        checks = sorted(LOCAL_DIR.iterdir())
        log(f"Local checks in {LOCAL_DIR}: {len(checks)} files")
        for c in checks:
            print(f"         {c.name}")
    else:
        warn(f"Local checks directory {LOCAL_DIR} does not exist")


def phase_deploy_checks() -> None:
    """Phase 4: Deploy check scripts from repository to agent local dir.

    Scripts are copied WITHOUT the .py extension, matching the convention
    documented in the NSec8 APK Migration Guide §3.
    """
    # Determine source directory: use full/ by default
    repo_root = Path(__file__).resolve().parent.parent.parent.parent  # up 4: beta -> full -> nsec8 -> checkmk-tools
    scripts_dir = repo_root / "script-check-nsec8" / "full"

    if not scripts_dir.is_dir():
        die(f"Source scripts directory not found: {scripts_dir}")

    # Ensure local dir exists
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)

    # Collect .py files from full/ (exclude __init__.py and .gitignore)
    py_files = sorted(scripts_dir.glob("*.py"))
    if not py_files:
        warn(f"No .py files found in {scripts_dir}")
        return

    deployed = 0
    for src in py_files:
        # Strip .py extension for target name (CheckMK convention)
        target_name = src.stem  # e.g. check_apk_packages -> check_apk_packages
        dst = LOCAL_DIR / target_name

        # Preserve executable bit from source, or set it
        shutil.copy2(str(src), str(dst))
        dst.chmod(0o755)
        deployed += 1
        log(f"Deployed: {target_name}")

    ok(f"Deployed {deployed} check scripts to {LOCAL_DIR}")


def phase_test_agent() -> None:
    """Phase 5: Quick connectivity test via socat/ncat."""
    log("Testing agent connectivity on 127.0.0.1:6556...")

    # Try nc first, then socat
    nc_cmd = shutil.which("nc") or shutil.which("ncat") or shutil.which("netcat")
    if nc_cmd:
        result = subprocess.run(
            [nc_cmd, "127.0.0.1", "6556"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=5
        )
        if result.returncode == 0 or "check_mk" in result.stdout:
            first_line = result.stdout.splitlines()[0] if result.stdout else "(empty)"
            ok(f"Agent responds: {first_line.strip()}")
        else:
            warn(f"Agent test returned exit {result.returncode}")
    else:
        # Try socat
        socat_cmd = shutil.which("socat")
        if socat_cmd:
            result = subprocess.run(
                [socat_cmd, "-", "TCP:127.0.0.1:6556"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, timeout=5
            )
            if "check_mk" in result.stdout:
                first_line = result.stdout.splitlines()[0] if result.stdout else "(empty)"
                ok(f"Agent responds (via socat): {first_line.strip()}")
            else:
                warn("Agent test via socat returned unexpected output")
        else:
            warn("Neither nc nor socat found — skip connectivity test")


# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------


def phase_uninstall() -> None:
    """Remove APK packages and deployed checks."""
    log("Uninstalling CheckMK Agent (APK)...")

    # Remove APK packages in reverse dependency order
    for pkg in reversed(PACKAGES):
        if check_apk_package_installed(pkg):
            log(f"Removing {pkg}...")
            run(["apk", "del", pkg], check=False)
            ok(f"{pkg} removed")
        else:
            log(f"{pkg} not installed, skipping")

    # Remove deployed check scripts
    if LOCAL_DIR.is_dir():
        # Only remove files that look like our deployed checks (no .py extension)
        removed = 0
        for f in LOCAL_DIR.iterdir():
            if f.is_file() and not f.name.endswith(".py") and f.name != ".gitignore":
                f.unlink()
                removed += 1
        if removed:
            log(f"Removed {removed} deployed check scripts from {LOCAL_DIR}")

    ok("Uninstall complete")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def usage() -> None:
    print(
        f"install-agent-nsec8-apk.py v{VERSION} (BETA)\n"
        f"\n"
        f"CheckMK Agent Installer — APK Edition\n"
        f"Install CheckMK Agent on NethSecurity 8.8+ using native APK packages.\n"
        f"\n"
        f"Based on: script-check-nsec8/doc/nsec8-apk-migration-guide.md\n"
        f"\n"
        f"Installation commands (from guide §3):\n"
        f"  apk update\n"
        f"  apk add checkmk-agent        (v2.5.0-r1)\n"
        f"  apk add ns-checkmk-utils     (v0.0.5-r1)\n"
        f"\n"
        f"Usage:\n"
        f"  python3 install-agent-nsec8-apk.py               Full install (agent + checks)\n"
        f"  python3 install-agent-nsec8-apk.py --agent-only   Install agent only\n"
        f"  python3 install-agent-nsec8-apk.py --deploy-checks  Deploy checks only\n"
        f"  python3 install-agent-nsec8-apk.py --uninstall    Remove agent and checks\n"
        f"  python3 install-agent-nsec8-apk.py --help         This help\n"
    )


def main() -> int:
    args = sys.argv[1:]

    if "-h" in args or "--help" in args:
        usage()
        return 0

    if not is_root():
        die("This script must be run as root")

    mode_agent_only = "--agent-only" in args
    mode_deploy_only = "--deploy-checks" in args
    mode_uninstall = "--uninstall" in args

    if mode_uninstall:
        phase_uninstall()
        return 0

    print()
    print("=" * 62)
    print("  CheckMK Agent Installer — APK Edition (BETA)")
    print(f"  v{VERSION}")
    print("  Target: NethSecurity 8.8+ (APK package manager)")
    print("=" * 62)
    print()

    detect_system()

    if not mode_deploy_only:
        print()
        print("--- Phase 1/3: Update APK repositories ---")
        phase_update()

        print()
        print("--- Phase 2/3: Install CheckMK Agent ---")
        phase_install_agent()

        print()
        print("--- Phase 3/3: Verify installation ---")
        phase_verify_agent()

    if not mode_agent_only:
        print()
        print("--- Deploy check scripts ---")
        phase_deploy_checks()

    print()
    print("--- Connectivity test ---")
    phase_test_agent()

    print()
    print("=" * 62)
    if mode_agent_only:
        print("  AGENT INSTALLATION COMPLETE")
    elif mode_deploy_only:
        print("  CHECK DEPLOY COMPLETE")
    else:
        print("  FULL INSTALLATION COMPLETE")
    print("=" * 62)
    print()
    print("Agent status:")
    print(f"  apk list checkmk-agent")
    print(f"  check_mk_agent --version")
    print(f"  ls -la {LOCAL_DIR}")
    print()
    print("Agent test:")
    print("  nc 127.0.0.1 6556 | head")
    print()
    print("Disinstallazione:")
    print(f"  python3 {sys.argv[0]} --uninstall")

    return 0


if __name__ == "__main__":
    sys.exit(main())
