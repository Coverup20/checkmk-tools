#!/usr/bin/env python3
"""sync_linuxchecks.py - Deploy Linux local checks from a GitHub release

Reads manifest.json from a public release (tag prefix linuxchecks-), selects
the checks for the categories of this host, downloads only the ones that are
missing or changed, verifies every sha256 in a staging directory and installs
each check atomically into the CheckMK agent local directory.

On Linux the agent executes every file found in the local directory, so a
check is installed with the name the agent expects (the file stem, no .py
extension) and mode 0755. The previous version of a replaced check is kept in
<staging>/previous, and checks deployed by this tool that are no longer part
of the release are removed from the local directory unless --no-prune is
given. Checks never deployed by this tool (written by hand on the host) are
left untouched.

No GitHub account and no repository clone are needed: the assets of a public
release are plain HTTPS downloads.

Version: 1.0.0"""

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

VERSION = "1.0.0"

DEFAULT_REPO = "Coverup20/checkmk-tools"
TAG_PREFIX = "linuxchecks-"
DEFAULT_API_BASE = "https://api.github.com"
DEFAULT_TARGET = "/usr/lib/check_mk_agent/local"
DEFAULT_STAGING = "/var/lib/cmk-sync"
DEFAULT_EXCLUDE_FILE = "/etc/checkmk-python-full-sync.exclude"
MANIFEST_ASSET = "manifest.json"
USER_AGENT = "cmk-local-check-sync/" + VERSION

# Short category names used in the manifest and on the command line. The
# Windows category is served by sync_winchecks.ps1 and is never handled here.
KNOWN_CATEGORIES = [
    "ns7",
    "ns8",
    "nsec8",
    "proxmox",
    "ubuntu",
    "tmate-server",
]


class SyncError(Exception):
    """Fatal error that stops the run with exit code 1."""


# ─── Utilities ────────────────────────────────────────────────────────────────

def info(message):
    print(f"[INFO] {message}", flush=True)


def warn(message):
    print(f"[WARN] {message}", flush=True)


def sha256_file(path):
    """Lowercase hex sha256 of a file."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def set_executable(path):
    """Mode 0755; no-op on Windows."""
    if os.name == "nt":
        return
    current = path.stat().st_mode
    path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def load_exclude_list(exclude_file):
    """Set of check stems to skip, one name per line (# comments allowed).

    Both the source name (check_vpn_tunnels.py) and the deployed name
    (check_vpn_tunnels) are accepted. A missing file means no exclusions.
    """
    path = Path(exclude_file)
    if not path.is_file():
        return set()

    excluded = set()
    try:
        content = path.read_text().strip()
    except OSError as error:
        warn(f"cannot read exclude file {path}: {error}")
        return set()

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = line
        if name.endswith(".py"):
            name = name[:-3]
        excluded.add(name)
    return excluded


def detect_categories():
    """Short names of the categories that apply to this host.

    Exactly one base platform (a host is never NS7 and Ubuntu at the same
    time) plus zero or more role add-ons that can coexist with any base.
    """
    categories = []

    if shutil.which("pveversion") or Path("/etc/pve").is_dir():
        categories.append("proxmox")
    elif Path("/etc/openwrt_release").is_file():
        categories.append("nsec8")
    elif Path("/etc/nethserver-release").is_file():
        categories.append("ns7")
    elif (Path("/etc/nethserver/api-server.env").is_file()
          or Path("/etc/nethserver/core.env").is_file()):
        categories.append("ns8")
    elif shutil.which("dpkg") or shutil.which("apt-get"):
        categories.append("ubuntu")

    if shutil.which("tmate-ssh-server"):
        categories.append("tmate-server")

    return categories


# ─── HTTP ─────────────────────────────────────────────────────────────────────

def http_json(url):
    """Fetch and decode a JSON document."""
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
    })
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise SyncError(f"request failed: {url} ({error})")


def http_download(url, destination):
    """Stream a URL into a file."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=120) as response, \
                open(destination, "wb") as handle:
            shutil.copyfileobj(response, handle, length=65536)
    except (urllib.error.URLError, OSError) as error:
        raise SyncError(f"download failed: {url} ({error})")


def fetch_release(repo, tag, api_base):
    """Release object for an explicit tag, or the newest linuxchecks-* one."""
    base = api_base.rstrip("/") + "/repos/" + repo + "/releases"
    if tag:
        url = base + "/tags/" + urllib.parse.quote(tag, safe="")
        return http_json(url)

    releases = http_json(base + "?per_page=100")
    if isinstance(releases, dict):
        releases = [releases]
    for release in releases:
        if release.get("draft") or release.get("prerelease"):
            continue
        if str(release.get("tag_name", "")).startswith(TAG_PREFIX):
            return release
    raise SyncError(f"no {TAG_PREFIX}* release found in {repo}")


def release_asset_url(release, asset_name):
    """browser_download_url of an asset, or None when it is not there."""
    for asset in release.get("assets") or []:
        if asset.get("name") == asset_name:
            return asset.get("browser_download_url")
    return None


# ─── Manifest ─────────────────────────────────────────────────────────────────

def load_manifest(release, staging, tag, dry_run):
    """Download manifest.json of the release and return the checks list."""
    url = release_asset_url(release, MANIFEST_ASSET)
    if not url:
        raise SyncError(f"manifest.json is missing from release {tag}")

    if dry_run:
        staged = Path(tempfile.gettempdir()) / "cmk-linuxchecks-manifest.json"
    else:
        staged = Path(staging) / "manifest.json"
        staged.parent.mkdir(parents=True, exist_ok=True)
    http_download(url, staged)

    try:
        manifest = json.loads(staged.read_text())
    except (OSError, ValueError) as error:
        raise SyncError(f"invalid manifest.json: {error}")

    checks = manifest.get("checks")
    if not isinstance(checks, list):
        raise SyncError("manifest.json has no checks list")
    return checks


def select_checks(checks, categories, scripts_filter, exclude):
    """Checks of the given categories, filtered by --scripts and exclusions."""
    selected = []
    for entry in checks:
        category = entry.get("category")
        name = entry.get("name")
        if category not in categories or not name:
            continue
        if scripts_filter and name not in scripts_filter:
            continue
        if name in exclude:
            info(f"{name}: excluded by exclude list")
            continue
        selected.append(entry)
    return selected


# ─── State ────────────────────────────────────────────────────────────────────

def state_path(staging):
    return Path(staging) / "state.json"


def load_state(staging):
    """Previously deployed checks; a missing or broken file means empty state."""
    path = state_path(staging)
    if not path.is_file():
        return {"deployed": {}}
    try:
        state = json.loads(path.read_text())
    except (OSError, ValueError):
        warn(f"state file unreadable, starting from an empty state: {path}")
        return {"deployed": {}}
    if not isinstance(state.get("deployed"), dict):
        return {"deployed": {}}
    return state


def save_state(staging, tag, deployed):
    """Persist the deployed names and their hashes."""
    path = state_path(staging)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"tag": tag, "deployed": deployed}
    partial = path.with_name(path.name + ".new")
    partial.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(partial, path)


def acquire_lock(staging):
    """Exclusive non-blocking lock so two cron runs never overlap."""
    try:
        import fcntl
    except ImportError:
        return None
    handle = open(Path(staging) / ".lock", "w")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise SyncError("another sync run is in progress")
    return handle


# ─── Install ──────────────────────────────────────────────────────────────────

def atomic_install(source, destination):
    """Copy into a temp file next to the destination and rename over it.

    The rename happens inside the target directory, so it stays on the same
    filesystem and is atomic: the agent never reads a half-written check.
    """
    destination = Path(destination)
    partial = destination.with_name(
        f".{destination.name}.tmp-{os.getpid()}")
    shutil.copyfile(source, partial)
    set_executable(partial)
    os.replace(partial, destination)


def apply_release(release, categories, args):
    """Download, verify and install the selected checks. Returns stats."""
    staging = Path(args.staging)
    target = Path(args.target)
    tag = release.get("tag_name", "unknown")
    exclude = load_exclude_list(args.exclude_file)

    scripts_filter = None
    if args.scripts:
        scripts_filter = {s.strip() for s in args.scripts.split(",") if s.strip()}

    info(f"release: {tag}")
    checks = load_manifest(release, staging, tag, args.dry_run)
    selected = select_checks(checks, categories, scripts_filter, exclude)
    if not selected:
        info("no check selected for this host")

    stats = {"downloaded": 0, "deployed": 0, "up_to_date": 0, "removed": 0}
    previous_dir = staging / "previous"

    for entry in selected:
        name = entry["name"]
        asset = entry.get("asset") or entry.get("source") or name
        expected_hash = str(entry.get("sha256", "")).lower()
        if not expected_hash:
            raise SyncError(f"{name}: manifest entry has no sha256")

        target_file = target / name
        staged_file = staging / asset

        if target_file.is_file() and sha256_file(target_file) == expected_hash:
            info(f"{name}: already up to date")
            stats["up_to_date"] += 1
            continue

        if staged_file.is_file() and sha256_file(staged_file) == expected_hash:
            info(f"{name}: verified copy already in staging")
        else:
            url = release_asset_url(release, asset)
            if not url:
                raise SyncError(f"asset {asset} is missing from release {tag}")
            if args.dry_run:
                info(f"{name}: would download")
                continue
            partial = staged_file.with_name(staged_file.name + ".new")
            http_download(url, partial)
            if sha256_file(partial) != expected_hash:
                partial.unlink(missing_ok=True)
                raise SyncError(f"{name}: sha256 mismatch, download discarded")
            os.replace(partial, staged_file)
            info(f"{name}: downloaded and verified")
            stats["downloaded"] += 1

        if args.dry_run:
            info(f"{name}: would install in {target}")
            continue

        target.mkdir(parents=True, exist_ok=True)
        previous_dir.mkdir(parents=True, exist_ok=True)
        if target_file.is_file():
            shutil.copy2(target_file, previous_dir / name)
            info(f"{name}: previous version kept in {previous_dir}")
        atomic_install(staged_file, target_file)
        info(f"{name}: deployed")
        stats["deployed"] += 1

    expected_names = {entry["name"] for entry in selected}
    state = load_state(staging)

    # A --scripts run handles a subset of the manifest: it must not prune the
    # checks it was not asked about, and it must not drop them from the state.
    if not args.no_prune and not scripts_filter and not args.dry_run:
        for name in sorted(set(state["deployed"]) - expected_names - exclude):
            target_file = target / name
            if target_file.is_file():
                target_file.unlink()
                info(f"{name}: removed (not part of release {tag})")
                stats["removed"] += 1

    if not args.dry_run:
        managed = dict(state["deployed"]) if scripts_filter else {}
        managed.update({entry["name"]: str(entry.get("sha256", "")).lower()
                        for entry in selected})
        for name in set(state["deployed"]) & exclude:
            managed[name] = state["deployed"][name]
        save_state(staging, tag, managed)

    info("summary: {downloaded} downloaded, {deployed} deployed, "
         "{up_to_date} up to date, {removed} removed".format(**stats))
    if args.dry_run:
        info("dry run: nothing was changed")
    return stats


def run_sync(args):
    """Entry point for a real run: select categories then apply the release."""
    categories = args.categories
    if categories == "auto":
        categories = detect_categories()
        if not categories:
            raise SyncError("auto-detect: cannot determine the category of this "
                            "host, use --categories")
        info("auto-detect: " + ",".join(categories))
    else:
        categories = [c.strip() for c in categories.split(",") if c.strip()]
        unknown = [c for c in categories if c not in KNOWN_CATEGORIES]
        if unknown:
            raise SyncError("unknown category: " + ", ".join(unknown))

    staging = Path(args.staging)
    if not args.dry_run:
        staging.mkdir(parents=True, exist_ok=True)
        acquire_lock(staging)

    release = fetch_release(args.repo, args.tag, args.api_base)
    return apply_release(release, categories, args)


def list_checks(args):
    """Print the checks available in the release for the selected categories."""
    categories = args.categories
    if categories == "auto":
        categories = detect_categories()
    else:
        categories = [c.strip() for c in categories.split(",") if c.strip()]
    release = fetch_release(args.repo, args.tag, args.api_base)
    checks = load_manifest(release, args.staging, release.get("tag_name", ""),
                           True)
    selected = [e for e in checks if e.get("category") in categories]
    if not selected:
        info("no check available for the selected categories")
        return 0
    print(f"{'CATEGORY':<14}{'NAME':<40}SHA256")
    for entry in selected:
        print(f"{entry.get('category', ''):<14}{entry.get('name', ''):<40}"
              f"{entry.get('sha256', '')[:16]}")
    return 0


# ─── Self test ────────────────────────────────────────────────────────────────

def self_test():
    """Offline end-to-end test with file:// asset URLs in a temporary tree."""
    failures = []

    def expect(condition, label):
        if condition:
            print(f"  [PASS] {label}")
        else:
            print(f"  [FAIL] {label}")
            failures.append(label)

    root = Path(tempfile.mkdtemp(prefix="cmk-linuxchecks-selftest-"))
    try:
        assets = root / "assets"
        assets.mkdir()
        staging = root / "staging"
        target = root / "local"
        exclude_file = root / "exclude.txt"
        exclude_file.write_text("# comment\ncheck_second.py\n")

        sources = {
            "check_first.py": "#!/usr/bin/env python3\nprint('0 First - ok')\n",
            "check_second.py": "#!/usr/bin/env python3\nprint('0 Second - ok')\n",
        }
        entries = []
        for source_name, content in sources.items():
            asset_name = "ubuntu--" + source_name
            asset_path = assets / asset_name
            asset_path.write_text(content)
            entries.append({
                "category": "ubuntu",
                "name": source_name[:-3],
                "source": source_name,
                "asset": asset_name,
                "sha256": sha256_file(asset_path),
                "size": asset_path.stat().st_size,
            })

        release = {
            "tag_name": "linuxchecks-selftest",
            "assets": [{
                "name": MANIFEST_ASSET,
                "browser_download_url": (root / MANIFEST_ASSET).as_uri(),
            }] + [{
                "name": entry["asset"],
                "browser_download_url": (assets / entry["asset"]).as_uri(),
            } for entry in entries],
        }
        (root / MANIFEST_ASSET).write_text(json.dumps({"checks": entries}))

        args = argparse.Namespace(
            staging=str(staging), target=str(target), dry_run=False,
            no_prune=False, scripts=None, exclude_file=str(exclude_file),
        )

        print("deploy")
        stats = apply_release(release, ["ubuntu"], args)
        expect(stats["deployed"] == 1, "first check deployed")
        expect((target / "check_first").is_file(), "deployed name has no extension")
        expect((target / "check_first").read_text() == sources["check_first.py"],
               "deployed content matches the asset")
        if os.name != "nt":
            expect((target / "check_first").stat().st_mode & stat.S_IXUSR != 0,
                   "deployed file is executable")
        expect(not (target / "check_second").exists(),
               "excluded check is not deployed")
        expect((staging / "state.json").is_file(), "state file written")

        print("idempotency")
        stats = apply_release(release, ["ubuntu"], args)
        expect(stats["up_to_date"] == 1, "second run is up to date")

        print("recovery from a corrupted file")
        (target / "check_first").write_text("corrupted\n")
        stats = apply_release(release, ["ubuntu"], args)
        expect(stats["deployed"] == 1, "corrupted file replaced")
        expect(sha256_file(target / "check_first")
               == entries[0]["sha256"], "content restored")
        expect((staging / "previous" / "check_first").is_file(),
               "previous version kept")

        print("prune of a managed file that left the release")
        state = load_state(staging)
        state["deployed"]["check_gone"] = "0" * 64
        save_state(staging, "linuxchecks-selftest", state["deployed"])
        (target / "check_gone").write_text("old\n")
        stats = apply_release(release, ["ubuntu"], args)
        expect(stats["removed"] == 1, "orphan removed")
        expect(not (target / "check_gone").exists(), "orphan file is gone")

        print("manual file is never pruned")
        (target / "check_manual").write_text("hand written\n")
        apply_release(release, ["ubuntu"], args)
        expect((target / "check_manual").is_file(),
               "file not in state survives")

        print("a --scripts run never prunes the rest")
        (target / "check_other").write_text("managed elsewhere\n")
        state = load_state(staging)
        state["deployed"]["check_other"] = "0" * 64
        save_state(staging, "linuxchecks-selftest", state["deployed"])
        partial = argparse.Namespace(
            staging=str(staging), target=str(target), dry_run=False,
            no_prune=False, scripts="check_first",
            exclude_file=str(exclude_file),
        )
        stats = apply_release(release, ["ubuntu"], partial)
        expect(stats["removed"] == 0, "no prune during a --scripts run")
        expect((target / "check_other").is_file(), "other check preserved")
        expect("check_other" in load_state(staging)["deployed"],
               "state keeps the checks outside the subset")

        print("dry run changes nothing")
        (target / "check_first").unlink()
        args.dry_run = True
        stats = apply_release(release, ["ubuntu"], args)
        expect(stats["deployed"] == 0, "dry run deploys nothing")
        expect(not (target / "check_first").exists(), "dry run leaves target alone")
    except Exception as error:  # pragma: no cover - self test guard
        print(f"  [FAIL] unexpected exception: {error}")
        failures.append("exception")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    if failures:
        print(f"[FAIL] self test: {len(failures)} failure(s)")
        return 1
    print("[PASS] self test: all checks passed")
    return 0


# ─── CLI ──────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description=f"sync_linuxchecks v{VERSION} - Deploy Linux local checks "
                    "from a GitHub release",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  # Apply the newest release for the categories detected on this host
  sync_linuxchecks.py

  # Apply one category explicitly, with a preview
  sync_linuxchecks.py --categories ns8 --dry-run

  # Pin a release and keep files that are not in the manifest
  sync_linuxchecks.py --tag linuxchecks-2026.11.13 --no-prune

  # Show what a release carries for this host
  sync_linuxchecks.py --list""",
    )
    parser.add_argument("--repo", default=DEFAULT_REPO,
                        help=f"public GitHub repository (default: {DEFAULT_REPO})")
    parser.add_argument("--tag", default="",
                        help=f"release tag (default: newest {TAG_PREFIX}*)")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE,
                        help=f"GitHub API base URL (default: {DEFAULT_API_BASE})")
    parser.add_argument("--categories", default="auto",
                        help="comma-separated category list that declares the "
                             "COMPLETE set for this host (prune relies on it), "
                             "or auto (default: auto)")
    parser.add_argument("--target", default=DEFAULT_TARGET,
                        help=f"agent local directory (default: {DEFAULT_TARGET})")
    parser.add_argument("--staging", default=DEFAULT_STAGING,
                        help=f"staging and state directory (default: {DEFAULT_STAGING})")
    parser.add_argument("--exclude-file", default=DEFAULT_EXCLUDE_FILE,
                        help=f"checks to skip, one per line (default: {DEFAULT_EXCLUDE_FILE})")
    parser.add_argument("--scripts",
                        help="comma-separated deployed names to handle (subset)")
    parser.add_argument("--no-prune", action="store_true",
                        help="do not remove checks that left the release")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would happen, change nothing")
    parser.add_argument("--list", action="store_true",
                        help="list the checks of the release for this host")
    parser.add_argument("--self-test", action="store_true",
                        help="run the offline self test")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {VERSION}")
    return parser.parse_args()


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args()
    if args.self_test:
        return self_test()
    try:
        if args.list:
            return list_checks(args)
        run_sync(args)
        return 0
    except SyncError as error:
        print(f"[ERROR] {error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
