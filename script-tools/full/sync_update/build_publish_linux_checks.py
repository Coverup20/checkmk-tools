#!/usr/bin/env python3
"""build_publish_linux_checks.py - Publish Linux local checks as a release

Collects the check_*.py files of every Linux category, copies them into an
output directory under a unique asset name, computes their sha256 and writes
a manifest.json that describes category, deployed name, asset name, hash and
size of every check. With --publish the assets and the manifest are uploaded
to a GitHub release whose tag starts with linuxchecks-.

Linux runs the Python source directly, so no build step is needed: the asset
is the script itself. The downloader on the host (sync_linuxchecks.py) reads
the manifest and installs the checks of its own categories without cloning
the repository.

Version: 1.0.0"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

VERSION = "1.0.0"

TAG_PREFIX = "linuxchecks-"
MANIFEST_ASSET = "manifest.json"
DEFAULT_REPO = "Coverup20/checkmk-tools"
CATEGORY_PREFIX = "script-check-"
KNOWN_CATEGORIES = [
    "ns7",
    "ns8",
    "nsec8",
    "proxmox",
    "ubuntu",
    "tmate-server",
]


class BuildError(Exception):
    """Fatal error that stops the run with exit code 1."""


def info(message):
    print(f"[INFO] {message}", flush=True)


def sha256_file(path):
    """Lowercase hex sha256 of a file."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checkout_root(script_path):
    """Repository root: <root>/script-tools/full/sync_update/<script>."""
    return Path(script_path).resolve().parents[3]


def source_files(category_dir):
    """Check scripts of a category, same rule used by the deploy tooling."""
    full_dir = Path(category_dir) / "full"
    if not full_dir.is_dir():
        return []
    return sorted(path for path in full_dir.glob("check*.py") if path.is_file())


def build(root, categories, out_dir, tag):
    """Copy the sources with unique asset names and return the manifest."""
    root = Path(root)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    checks = []
    for category in categories:
        category_dir = root / (CATEGORY_PREFIX + category)
        if not category_dir.is_dir():
            info(f"{category}: category directory not found, skipped")
            continue
        for source in source_files(category_dir):
            asset_name = f"{category}--{source.name}"
            asset_path = out_dir / asset_name
            shutil.copyfile(source, asset_path)
            checks.append({
                "category": category,
                "name": source.stem,
                "source": source.name,
                "asset": asset_name,
                "sha256": sha256_file(asset_path),
                "size": asset_path.stat().st_size,
            })
            info(f"{category}: {source.stem}")

    if not checks:
        raise BuildError("no check found in the selected categories")

    manifest = {
        "tag": tag,
        "version": tag[len(TAG_PREFIX):] if tag.startswith(TAG_PREFIX) else tag,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "generator": f"build_publish_linux_checks.py {VERSION}",
        "categories": sorted({check["category"] for check in checks}),
        "checks": checks,
    }
    manifest_path = out_dir / MANIFEST_ASSET
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest, manifest_path


def publish(manifest, manifest_path, out_dir, tag, repo, draft):
    """Create or update the GitHub release with gh; tokens stay in gh's store."""
    gh = shutil.which("gh")
    if not gh:
        raise BuildError("GitHub CLI not found: install it and run gh auth login")
    auth = subprocess.run([gh, "auth", "status"], capture_output=True, text=True)
    if auth.returncode != 0:
        raise BuildError("GitHub CLI not authenticated: run gh auth login")

    assets = [str(Path(out_dir) / check["asset"]) for check in manifest["checks"]]
    assets.append(str(manifest_path))

    existing = subprocess.run(
        [gh, "release", "view", tag, "--repo", repo],
        capture_output=True, text=True)
    if existing.returncode == 0:
        info(f"release {tag} exists, uploading assets")
        result = subprocess.run(
            [gh, "release", "upload", tag] + assets
            + ["--repo", repo, "--clobber"],
            capture_output=True, text=True)
        if result.returncode != 0:
            raise BuildError(f"gh release upload failed: {result.stderr.strip()}")
        return

    notes = [f"Linux local checks {tag}", ""]
    notes += [f"- {check['category']}/{check['name']} sha256 {check['sha256']}"
              for check in manifest["checks"]]
    command = [gh, "release", "create", tag] + assets + [
        "--repo", repo,
        "--title", f"Linux local checks {tag}",
        "--notes", "\n".join(notes),
    ]
    if draft:
        command.append("--draft")
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise BuildError(f"gh release create failed: {result.stderr.strip()}")


def self_test():
    """Offline test: build a fake checkout and inspect the manifest."""
    failures = []

    def expect(condition, label):
        if condition:
            print(f"  [PASS] {label}")
        else:
            print(f"  [FAIL] {label}")
            failures.append(label)

    root = Path(tempfile.mkdtemp(prefix="cmk-linuxchecks-build-test-"))
    try:
        for category, files in {
            "script-check-ubuntu": ["check_alpha.py", "helper.py"],
            "script-check-ns8": ["check_beta.py"],
            "script-check-windows": ["check_windows.py"],
        }.items():
            full = root / category / "full"
            full.mkdir(parents=True)
            for name in files:
                (full / name).write_text(f"#!/usr/bin/env python3\n# {name}\n")

        out_dir = root / "out"
        manifest, manifest_path = build(root, KNOWN_CATEGORIES, out_dir,
                                        "linuxchecks-selftest")

        names = sorted(check["name"] for check in manifest["checks"])
        expect(names == ["check_alpha", "check_beta"],
               "only check*.py of the selected categories are included")
        expect(manifest["categories"] == ["ns8", "ubuntu"],
               "manifest lists the categories")
        expect((out_dir / "ubuntu--check_alpha.py").is_file(),
               "asset name carries the category prefix")
        expect(manifest_path.is_file(), "manifest.json written")

        entry = next(c for c in manifest["checks"] if c["name"] == "check_alpha")
        expect(entry["sha256"]
               == sha256_file(out_dir / "ubuntu--check_alpha.py"),
               "manifest sha256 matches the asset")
        expect(json.loads(manifest_path.read_text())["checks"], "manifest is JSON")

        empty = root / "empty"
        empty.mkdir()
        try:
            build(empty, ["ubuntu"], root / "out2", "linuxchecks-empty")
            expect(False, "empty build must fail")
        except BuildError:
            expect(True, "empty build fails")
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


def parse_args():
    parser = argparse.ArgumentParser(
        description=f"build_publish_linux_checks v{VERSION} - Publish Linux "
                    "local checks as a GitHub release",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  # Build the release assets and the manifest in a temporary directory
  build_publish_linux_checks.py

  # Build from another checkout and publish a draft release
  build_publish_linux_checks.py --repo-dir /path/to/checkout --publish --draft

  # Republish the assets of an existing tag
  build_publish_linux_checks.py --tag linuxchecks-2026.11.13 --publish""",
    )
    parser.add_argument("--repo-dir", default=None,
                        help="checkout root (default: the checkout of this script)")
    parser.add_argument("--out-dir", default=None,
                        help="output directory (default: <temp>/linuxchecks-build/<tag>)")
    parser.add_argument("--tag", default="",
                        help=f"release tag (default: {TAG_PREFIX}YYYY.MM.DD)")
    parser.add_argument("--categories", default=",".join(KNOWN_CATEGORIES),
                        help="comma-separated categories to include")
    parser.add_argument("--repo", default=DEFAULT_REPO,
                        help=f"GitHub repository (default: {DEFAULT_REPO})")
    parser.add_argument("--publish", action="store_true",
                        help="create or update the GitHub release")
    parser.add_argument("--draft", action="store_true",
                        help="create the release as a draft")
    parser.add_argument("--self-test", action="store_true",
                        help="run the offline self test")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {VERSION}")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.self_test:
        return self_test()

    tag = args.tag or TAG_PREFIX + datetime.now().strftime("%Y.%m.%d")
    root = Path(args.repo_dir) if args.repo_dir else checkout_root(__file__)
    if not root.is_dir():
        print(f"[ERROR] checkout not found: {root}", file=sys.stderr)
        return 1

    categories = [c.strip() for c in args.categories.split(",") if c.strip()]
    unknown = [c for c in categories if c not in KNOWN_CATEGORIES]
    if unknown:
        print(f"[ERROR] unknown category: {', '.join(unknown)}", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir) if args.out_dir else (
        Path(tempfile.gettempdir()) / "linuxchecks-build" / tag)

    try:
        manifest, manifest_path = build(root, categories, out_dir, tag)
    except BuildError as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1

    for check in manifest["checks"]:
        print(f"  {check['category']:<14}{check['name']:<40}"
              f"{check['size']:>8}  {check['sha256'][:16]}")
    info(f"manifest: {manifest_path}")

    if args.publish:
        try:
            publish(manifest, manifest_path, out_dir, tag, args.repo, args.draft)
        except BuildError as error:
            print(f"[ERROR] {error}", file=sys.stderr)
            return 1
        info(f"published release {tag} on {args.repo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
