#!/usr/bin/env python3
"""
sync-checks.py - Download leggero degli script check da GitHub.

Sostituisce git clone/pull: scarica solo i 13 file .py necessari
da script-check-nsec8/full/ senza installare git o clonare il repository.

Logica:
  1. Ottieni SHA dell'ultimo commit di main (1 chiamata API)
  2. Confronta con SHA salvato localmente
  3. Se diverso: scarica file listing + file modificati
  4. Salva nuovo SHA

Version: 1.0.0
"""

import json
import sys
import urllib.request
from pathlib import Path

VERSION = "1.2.0"

REPO = "Coverup20/checkmk-tools"
BRANCH = "main"
CHECKS_PATH = "script-check-nsec8/full"
SELF_PATH = "script-tools/full/upgrade_maintenance/sync-checks.py"

CHECKS_DIR = Path("/opt/checkmk-checks")
LOCAL_DIR = Path("/usr/lib/check_mk_agent/local")
SHA_CACHE = Path("/opt/checkmk-backups/last-sync-sha.txt")
API_BASE = f"https://api.github.com/repos/{REPO}"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}"
TIMEOUT = 20


def _get_json(url: str) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": f"nsec8-sync/{VERSION}"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read())


def main() -> int:
    # 0. Self-update: scarica se stessa da GitHub e si sostituisce se cambiata
    self_path = Path(__file__).resolve()
    try:
        url = f"{RAW_BASE}/{SELF_PATH}"
        req = urllib.request.Request(url, headers={"User-Agent": f"nsec8-sync/{VERSION}"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            new_content = r.read()
        current_content = self_path.read_bytes()
        if new_content != current_content:
            import tempfile, os
            tmp = tempfile.NamedTemporaryFile(delete=False, dir=str(self_path.parent), suffix=".tmp")
            tmp.write(new_content)
            tmp.close()
            os.replace(tmp.name, str(self_path))
            self_path.chmod(0o755)
            print(f"[sync-checks] Self-update completato — riavvio")
            os.execv(str(self_path), [str(self_path)])  # riavvia con nuova versione
    except Exception as exc:
        print(f"[sync-checks] Self-update fallito (continuo con versione attuale): {exc}", file=sys.stderr)

    # 1. Ottieni SHA HEAD del branch main (1 API call)
    try:
        ref = _get_json(f"{API_BASE}/git/ref/heads/{BRANCH}")
        remote_sha: str = ref["object"]["sha"]
    except Exception as exc:
        print(f"[sync-checks] ERRORE: impossibile ottenere SHA remoto: {exc}", file=sys.stderr)
        return 1

    # 2. Confronta con SHA locale
    try:
        local_sha = SHA_CACHE.read_text().strip()
    except FileNotFoundError:
        local_sha = ""

    if remote_sha == local_sha:
        return 0  # Già aggiornato, uscita silenziosa

    # 3. Ottieni lista file da GitHub API
    try:
        files = _get_json(f"{API_BASE}/contents/{CHECKS_PATH}?ref={BRANCH}")
    except Exception as exc:
        print(f"[sync-checks] ERRORE: impossibile ottenere lista file: {exc}", file=sys.stderr)
        return 1

    # 4. Scarica file .py in /opt/checkmk-checks/
    CHECKS_DIR.mkdir(parents=True, exist_ok=True)
    count = 0
    for entry in files:
        name = entry.get("name", "")
        if not name.endswith(".py") or name.startswith("."):
            continue
        url = f"{RAW_BASE}/{CHECKS_PATH}/{name}"
        dest = CHECKS_DIR / name
        try:
            urllib.request.urlretrieve(url, str(dest))
            dest.chmod(0o755)
            count += 1
        except Exception as exc:
            print(f"[sync-checks] ERRORE: download {name}: {exc}", file=sys.stderr)

    # 5. Deploy in local checks dir (senza estensione .py)
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    deployed = 0
    for src in CHECKS_DIR.glob("*.py"):
        dest = LOCAL_DIR / src.stem  # es: check_uptime.py → check_uptime
        try:
            import shutil
            shutil.copy2(str(src), str(dest))
            dest.chmod(0o755)
            deployed += 1
        except Exception as exc:
            print(f"[sync-checks] ERRORE deploy {src.name}: {exc}", file=sys.stderr)

    # 6. Salva nuovo SHA
    SHA_CACHE.parent.mkdir(parents=True, exist_ok=True)
    SHA_CACHE.write_text(remote_sha + "\n")
    print(f"[sync-checks] {count} file aggiornati, {deployed} deployati (sha: {remote_sha[:8]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
