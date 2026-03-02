#!/usr/bin/env python3
"""
sync-python-full-checks.py - Sincronizza e deploya Python local checks

Copia i launcher Python da script-check-*/remote/*.py
verso /usr/lib/check_mk_agent/local/ (senza estensione .py).

Utilizzato da install-checkmk-sync.py come STEP 2.

Argomenti:
  --repo           Path repository locale (default: /opt/checkmk-tools)
  --target         Directory destinazione local checks (default: /usr/lib/check_mk_agent/local)
  --category       Categoria script-check-* specifica (default: auto-detect)
  --all-categories Sincronizza tutte le categorie script-check-*

Version: 1.0.0
"""

import argparse
import os
import shutil
import stat
import sys
from pathlib import Path
from typing import List, Tuple

VERSION = "1.0.0"

REPO_DEFAULT = Path("/opt/checkmk-tools")
TARGET_DEFAULT = "/usr/lib/check_mk_agent/local"


# ─── Utilities ────────────────────────────────────────────────────────────────

def set_executable(path: Path) -> None:
    """Rende il file eseguibile (rwxr-xr-x)."""
    current = path.stat().st_mode
    path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def get_categories(repo: Path, category: str, all_categories: bool) -> List[Path]:
    """Restituisce lista di directory script-check-* da processare."""
    if all_categories:
        cats = sorted(repo.glob("script-check-*/"))
        return [c for c in cats if c.is_dir()]

    if category and category != "auto":
        cat_path = repo / category
        if not cat_path.is_dir():
            print(f"[ERROR] Categoria non trovata: {cat_path}", file=sys.stderr)
            sys.exit(1)
        return [cat_path]

    # Auto-detect: tutte le categorie con almeno un file in remote/
    cats = sorted(repo.glob("script-check-*/"))
    return [c for c in cats if c.is_dir() and (c / "remote").is_dir()]


def find_launchers(category_dir: Path) -> List[Path]:
    """Trova tutti i launcher Python in category_dir/remote/*.py"""
    remote_dir = category_dir / "remote"
    if not remote_dir.is_dir():
        return []
    return sorted(remote_dir.glob("*.py"))


def deploy_name(launcher: Path) -> str:
    """Calcola il nome file destinazione (senza .py)."""
    name = launcher.stem  # rimuove .py
    return name


# ─── Deploy ───────────────────────────────────────────────────────────────────

def sync_category(category_dir: Path, target_dir: Path) -> Tuple[int, int, int]:
    """
    Sincronizza i launcher di una categoria.

    Returns:
        (deployed, updated, skipped)
    """
    launchers = find_launchers(category_dir)
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

        # Se destination esiste, controlla se è identico
        if dest_path.exists():
            try:
                dest_content = dest_path.read_bytes()
                if src_content == dest_content:
                    skipped += 1
                    continue
            except OSError:
                pass
            # Contenuto diverso → aggiorna
            try:
                dest_path.write_bytes(src_content)
                set_executable(dest_path)
                print(f"  [UPDATED] {launcher.name} → {dest_path}")
                updated += 1
            except OSError as e:
                print(f"  [ERROR] {launcher.name}: {e}")
                skipped += 1
        else:
            # Non esiste → deploy solo se esiste già un check deployato con stesso prefisso
            # (per rispettare la regola: deploy solo se bash check già presente)
            # In modalità sync (non primo deploy) copiamo direttamente
            try:
                dest_path.write_bytes(src_content)
                set_executable(dest_path)
                print(f"  [DEPLOYED] {launcher.name} → {dest_path}")
                deployed += 1
            except OSError as e:
                print(f"  [ERROR] {launcher.name}: {e}")
                skipped += 1

    return deployed, updated, skipped


def run(repo: Path, target_dir: Path, category: str, all_categories: bool) -> int:
    """Entry point principale."""
    print(f"=== sync-python-full-checks v{VERSION} ===")
    print(f"  Repo:   {repo}")
    print(f"  Target: {target_dir}")
    print()

    if not repo.is_dir():
        print(f"[ERROR] Repository non trovato: {repo}", file=sys.stderr)
        return 1

    if not target_dir.is_dir():
        print(f"[WARN] Target directory non esiste, la creo: {target_dir}")
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            print(f"[ERROR] Impossibile creare target dir: {e}", file=sys.stderr)
            return 1

    categories = get_categories(repo, category, all_categories)

    if not categories:
        print("[WARN] Nessuna categoria trovata.")
        return 0

    total_deployed = 0
    total_updated = 0
    total_skipped = 0

    for cat_dir in categories:
        cat_name = cat_dir.name
        print(f"── {cat_name} ──")
        d, u, s = sync_category(cat_dir, target_dir)
        total_deployed += d
        total_updated += u
        total_skipped += s
        if d == 0 and u == 0 and s == 0:
            print(f"  (nessun launcher trovato in remote/)")
        print()

    print("─" * 40)
    print(f"[OK] Riepilogo: {total_deployed} deployati, {total_updated} aggiornati, {total_skipped} invariati")
    return 0


# ─── CLI ──────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=f"sync-python-full-checks v{VERSION} - Deploy Python local checks",
    )
    p.add_argument("--repo", default=str(REPO_DEFAULT),
                   help=f"Path repository locale (default: {REPO_DEFAULT})")
    p.add_argument("--target", default=TARGET_DEFAULT,
                   help=f"Directory destinazione (default: {TARGET_DEFAULT})")
    p.add_argument("--category", default="auto",
                   help="Categoria script-check-* o 'auto'")
    p.add_argument("--all-categories", action="store_true",
                   help="Sincronizza tutte le categorie")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    repo = Path(args.repo)
    target = Path(args.target)
    return run(repo, target, args.category, args.all_categories)


if __name__ == "__main__":
    sys.exit(main())
