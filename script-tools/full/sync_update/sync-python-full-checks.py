#!/usr/bin/env python3
"""sync-python-full-checks.py - Synchronize and deploy Python local checks

Copy Python checks from script-check-*/full/*.py
to /usr/lib/check_mk_agent/local/ (without .py extension).

Used by install-checkmk-sync.py as STEP 2.

Topics:
  --repo Path local repository (default: /opt/checkmk-tools)
  --target Local checks target directory (default: /usr/lib/check_mk_agent/local)
  --category Specify script-check-* category (default: auto-detect)
  --all-categories Sync all categories script-check-*
  --scripts Specific script names to deploy, separated by commas
                   Ex: check_fail2ban_status,check_disk_space
  --temp-dir Deploy to temp directory instead of --target
                   (preview without real deployment)

Version: 1.2.1"""

import argparse
import os
import shutil
import stat
import sys
from pathlib import Path
from typing import List, Optional, Set, Tuple

VERSION = "1.2.1"
TEMP_DIR_DEFAULT = "/tmp/checkmk-sync-preview"

REPO_DEFAULT = Path("/opt/checkmk-tools")
TARGET_DEFAULT = "/usr/lib/check_mk_agent/local"


# ─── Utilities ────────────────────────────────────────────────────────────────

def set_executable(path: Path) -> None:
    """Makes the file executable (rwxr-xr-x)."""
    current = path.stat().st_mode
    path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def get_categories(repo: Path, category: str, all_categories: bool) -> List[Path]:
    """Returns list of script-check-* directories to process."""
    if all_categories:
        cats = sorted(repo.glob("script-check-*/"))
        return [c for c in cats if c.is_dir()]

    if category and category != "auto":
        cat_path = repo / category
        if not cat_path.is_dir():
            print(f"[ERROR] Categoria non trovata: {cat_path}", file=sys.stderr)
            sys.exit(1)
        return [cat_path]

    # Auto-detect: all categories with at least one file in full/
    cats = sorted(repo.glob("script-check-*/"))
    return [c for c in cats if c.is_dir() and (c / "full").is_dir()]


def find_launchers(category_dir: Path,
                   scripts_filter: Optional[Set[str]] = None) -> List[Path]:
    """Find check Python in category_dir/full/*.py

    If scripts_filter is specified, returns only checks
    whose stem (name without .py) is present in the set."""
    full_dir = category_dir / "full"
    if not full_dir.is_dir():
        return []
    # Only files starting with "check" → excludes daemons, utilities, etc.
    launchers = sorted(f for f in full_dir.glob("*.py") if f.stem.startswith("check"))
    if scripts_filter:
        launchers = [l for l in launchers if l.stem in scripts_filter]
    return launchers


def list_all_launchers(repo: Path) -> List[Path]:
    """Returns all checks available in the repo (all categories)."""
    result = []
    for cat in sorted(repo.glob("script-check-*/")):
        full_dir = cat / "full"
        if full_dir.is_dir():
            result.extend(sorted(full_dir.glob("*.py")))
    return result


def deploy_name(launcher: Path) -> str:
    """Calculate the destination file name (without .py)."""
    name = launcher.stem  # rimuove .py
    return name


# ─── Deploy ───────────────────────────────────────────────────────────────────

def sync_category(category_dir: Path, target_dir: Path,
                  scripts_filter: Optional[Set[str]] = None) -> Tuple[int, int, int]:
    """Sync launchers in a category.

    Args:
        category_dir: Directory script-check-*
        target_dir: Deployment target (real or temp)
        scripts_filter: If specified, deploy only scripts in the set

    Returns:
        (deployed, updated, skipped)"""
    launchers = find_launchers(category_dir, scripts_filter)
    if not launchers:
        return 0, 0, 0

    deployed = 0
    updated = 0
    skipped = 0

    for launcher in launchers:
        dest_name = deploy_name(launcher)
        dest_path = target_dir / dest_name

        # Leggi contenuto sorgente
        try:
            src_content = launcher.read_bytes()
        except OSError as e:
            print(f"  [WARN] Impossibile leggere {launcher.name}: {e}")
            skipped += 1
            continue

        # If destination exists, check if it is identical
        if dest_path.exists():
            try:
                dest_content = dest_path.read_bytes()
                if src_content == dest_content:
                    skipped += 1
                    continue
            except OSError:
                pass
            # Different content → update
            try:
                dest_path.write_bytes(src_content)
                set_executable(dest_path)
                print(f"  [UPDATED] {launcher.name} → {dest_path}")
                updated += 1
            except OSError as e:
                print(f"  [ERROR] {launcher.name}: {e}")
                skipped += 1
        else:
            # Does not exist → deploy only if a deployed check with the same prefix already exists
            # (to respect the rule: deploy only if bash check is already present)
            # In sync mode (not first deploy) we copy directly
            try:
                dest_path.write_bytes(src_content)
                set_executable(dest_path)
                print(f"  [DEPLOYED] {launcher.name} → {dest_path}")
                deployed += 1
            except OSError as e:
                print(f"  [ERROR] {launcher.name}: {e}")
                skipped += 1

    return deployed, updated, skipped


def run(repo: Path, target_dir: Path, category: str, all_categories: bool,
        scripts_filter: Optional[Set[str]] = None,
        temp_dir: Optional[Path] = None) -> int:
    """Main entry point.

    Args:
        scripts_filter: If specified, deploy only scripts in the set
        temp_dir: If specified, deploy to this dir (preview)"""
    # Destinazione effettiva
    effective_target = temp_dir if temp_dir is not None else target_dir
    is_temp = temp_dir is not None

    print(f"=== sync-python-full-checks v{VERSION} ===")
    print(f"  Repo:   {repo}")
    if is_temp:
        print(f"  Target: {effective_target}  [ANTEPRIMA - non deploy reale]")
    else:
        print(f"  Target: {effective_target}")
    if scripts_filter:
        print(f"  Script: {', '.join(sorted(scripts_filter))}")
    print()

    if not repo.is_dir():
        print(f"[ERROR] Repository non trovato: {repo}", file=sys.stderr)
        return 1

    if not effective_target.is_dir():
        print(f"[INFO] Creo directory: {effective_target}")
        try:
            effective_target.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            print(f"[ERROR] Impossibile creare target dir: {e}", file=sys.stderr)
            return 1

    # If scripts_filter specified → searches all categories ignoring --category
    if scripts_filter:
        categories = get_categories(repo, "auto", all_categories=True)
    else:
        categories = get_categories(repo, category, all_categories)

    if not categories:
        print("[WARN] Nessuna categoria trovata.")
        return 0

    total_deployed = 0
    total_updated = 0
    total_skipped = 0

    for cat_dir in categories:
        cat_name = cat_dir.name
        d, u, s = sync_category(cat_dir, effective_target, scripts_filter)
        total_deployed += d
        total_updated += u
        total_skipped += s
        if d > 0 or u > 0:
            print()  # separatore visivo tra categorie con output

    print("─" * 40)
    if is_temp:
        print(f"[OK] Anteprima in: {effective_target}")
        print(f"     Per deployare davvero: cp {effective_target}/* {target_dir}/")
    print(f"[OK] Riepilogo: {total_deployed} deployati, {total_updated} aggiornati, {total_skipped} invariati")
    return 0


# ─── CLI ──────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=f"sync-python-full-checks v{VERSION} - Deploy Python local checks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  # Deploy all categories
  sync-python-full-checks.py --all-categories

  # Deploy specific scripts only
  sync-python-full-checks.py --scripts rssh_fail2ban_status,rssh_disk_usage

  # Preview (temp dir) without real deployment
  sync-python-full-checks.py --all-categories --temp-dir /tmp/preview

  # List of available scripts
  sync-python-full-checks.py --list""",
    )
    p.add_argument("--repo", default=str(REPO_DEFAULT),
                   help=f"Path repository locale (default: {REPO_DEFAULT})")
    p.add_argument("--target", default=TARGET_DEFAULT,
                   help=f"Directory destinazione (default: {TARGET_DEFAULT})")
    p.add_argument("--category", default="auto",
                   help="Categoria script-check-* o 'auto'")
    p.add_argument("--all-categories", action="store_true",
                   help="Sincronizza tutte le categorie")
    p.add_argument("--scripts",
                   help="Script specifici da deployare (nomi separati da virgola, senza .py)")
    p.add_argument("--temp-dir", default=None,
                   help=f"Deploy in directory temp invece di --target (anteprima)")
    p.add_argument("--list", action="store_true",
                   help="Mostra tutti gli script disponibili nel repo ed esce")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    repo = Path(args.repo)
    target = Path(args.target)

    # --list: mostra script disponibili ed esce
    if args.list:
        launchers = list_all_launchers(repo)
        if not launchers:
            print("[WARN] Nessuno script trovato.")
            return 0
        print(f"Script disponibili ({len(launchers)}):\n")
        for l in launchers:
            cat = l.parent.parent.name
            print(f"  {l.stem:<45} [{cat}]")
        return 0

    scripts_filter: Optional[Set[str]] = None
    if args.scripts:
        scripts_filter = {s.strip() for s in args.scripts.split(",") if s.strip()}

    temp_dir: Optional[Path] = None
    if args.temp_dir:
        temp_dir = Path(args.temp_dir)

    return run(repo, target, args.category, args.all_categories,
               scripts_filter=scripts_filter, temp_dir=temp_dir)


if __name__ == "__main__":
    sys.exit(main())
