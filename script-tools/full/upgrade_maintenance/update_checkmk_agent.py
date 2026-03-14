#!/usr/bin/env python3
"""
update_checkmk_agent.py - Aggiornamento automatico CheckMK Agent

Controlla se l'agent locale è allineato alla versione del server CheckMK.
Se il server è più nuovo → scarica e installa il nuovo agent dal server stesso.
Se il server non è ancora aggiornato → skip (versione disponibile == versione locale).

Questo garantisce che l'agent non venga mai aggiornato prima del server.

Usage:
    # Auto-rileva server da installazione OMD locale
    python3 update_checkmk_agent.py

    # Specifica server manualmente (override o host senza OMD locale)
    python3 update_checkmk_agent.py --server-url https://monitor.nethlab.it/monitoring
    python3 update_checkmk_agent.py --server-url https://monitor.nethlab.it/monitoring --dry-run
    python3 update_checkmk_agent.py --server-url https://monitor.nethlab.it/monitoring --force

Version: 0.3.0
"""

import argparse
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Tuple

VERSION = "0.3.0"

# ─── OS Detection ─────────────────────────────────────────────────────────────

def detect_pkg_type() -> str:
    """
    Rileva il tipo di pacchetto richiesto per questo OS.

    Returns:
        'deb', 'rpm', o 'openwrt'
    """
    if Path("/etc/openwrt_release").exists():
        return "openwrt"
    if shutil.which("dpkg"):
        return "deb"
    if shutil.which("rpm"):
        return "rpm"
    print("[ERROR] OS non supportato (nessun dpkg/rpm/openwrt rilevato)", file=sys.stderr)
    sys.exit(1)


# ─── Versione Agent Locale ────────────────────────────────────────────────────

def get_local_agent_version(pkg_type: str) -> Optional[str]:
    """
    Legge la versione dell'agent CheckMK installato localmente.

    Returns:
        Stringa versione es. '2.4.0p23' oppure None se non installato.
    """
    if pkg_type == "deb":
        try:
            out = subprocess.check_output(
                ["dpkg-query", "-W", "-f=${Version}", "check-mk-agent"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
            # formato: 2.4.0p23-1 → strip suffisso debian
            return out.split("-")[0] if out else None
        except subprocess.CalledProcessError:
            return None

    if pkg_type == "rpm":
        try:
            out = subprocess.check_output(
                ["rpm", "-q", "--queryformat", "%{VERSION}", "check-mk-agent"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
            return out if out and "not installed" not in out else None
        except subprocess.CalledProcessError:
            return None

    if pkg_type == "openwrt":
        # Su OpenWrt l'agent è un binario standalone, non un pacchetto gestito
        # Prova a leggere la versione dall'output dell'agent
        try:
            out = subprocess.check_output(
                ["/usr/bin/check_mk_agent", "--version"],
                stderr=subprocess.STDOUT,
                text=True,
                timeout=5,
            )
            m = re.search(r"(\d+\.\d+\.\d+(?:p\d+)?)", out)
            return m.group(1) if m else None
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return None

    return None

# ─── Auto-detection Server URL ───────────────────────────────────────────────────────────

def detect_local_server_url() -> Optional[str]:
    """
    Auto-rileva URL del server CheckMK dall'installazione OMD locale.

    Legge hostname della macchina e il primo sito trovato in /omd/sites/.
    Restituisce 'https://{hostname}/{site}' oppure None se OMD non è installato.
    """
    # Metodo 1: directory /omd/sites/ (presente su qualsiasi installazione OMD)
    omd_sites_dir = Path("/omd/sites")
    if omd_sites_dir.exists():
        sites = sorted(d.name for d in omd_sites_dir.iterdir() if d.is_dir())
        if sites:
            hostname = socket.getfqdn()
            site = sites[0]
            return f"https://{hostname}/{site}"

    # Metodo 2: comando omd (se in PATH)
    try:
        result = subprocess.run(
            ["omd", "sites", "--bare"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            sites = [s.strip() for s in result.stdout.splitlines() if s.strip()]
            if sites:
                hostname = socket.getfqdn()
                return f"https://{hostname}/{sites[0]}"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return None


def parse_server_url(server_url: str) -> Tuple[str, str]:
    """
    Estrae hostname e site name dall'URL del server.

    Args:
        server_url: es. 'https://monitor.nethlab.it/monitoring'

    Returns:
        Tupla (hostname, site) es. ('monitor.nethlab.it', 'monitoring')
    """
    parsed = urllib.parse.urlparse(server_url)
    hostname = parsed.netloc
    site = parsed.path.strip('/').split('/')[0] if parsed.path.strip('/') else ''
    return hostname, site

# ─── Versione Agent sul Server ────────────────────────────────────────────────

def get_server_agent_version(server_url: str, pkg_type: str) -> Optional[str]:
    """
    Interroga il server CheckMK per ottenere la versione dell'agent disponibile.

    Usa l'endpoint REST API /api/1.0/version per leggere la versione del server,
    che coincide con la versione dell'agent distribuito.

    Args:
        server_url: URL base del sito CheckMK (es. https://monitor.nethlab.it/monitoring)
        pkg_type:   Tipo pacchetto (per costruire URL download)

    Returns:
        Stringa versione es. '2.4.0p23' oppure None se non raggiungibile.
    """
    # Prova prima via REST API (non richiede autenticazione per /version)
    api_url = f"{server_url.rstrip('/')}/check_mk/api/1.0/version"
    try:
        req = urllib.request.Request(api_url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            import json
            data = json.loads(resp.read().decode())
            # Campo: {"site": "...", "group": "...", "edition": "cre", "version": "2.4.0p23"}
            ver = data.get("version", "")
            if ver:
                return ver
    except Exception:
        pass

    # Fallback: leggi il filename del pacchetto dalla pagina degli agenti
    # Il nome file contiene la versione: check-mk-agent_2.4.0p23-1_all.deb
    agents_url = f"{server_url.rstrip('/')}/check_mk/agents/"
    ext = {"deb": ".deb", "rpm": ".rpm", "openwrt": ".deb"}.get(pkg_type, ".deb")
    try:
        with urllib.request.urlopen(agents_url, timeout=10) as resp:
            html = resp.read().decode(errors="replace")
        # Cerca nomi file tipo check-mk-agent_2.4.0p23-1_all.deb
        pattern = r'check-mk-agent[_-](\d+\.\d+\.\d+p\d+)'
        m = re.search(pattern, html)
        if m:
            return m.group(1)
    except Exception:
        pass

    return None


# ─── Download Agent ───────────────────────────────────────────────────────────

def build_download_url(server_url: str, server_ver: str, pkg_type: str) -> Tuple[str, str]:
    """
    Costruisce URL di download e filename del pacchetto agent in modo dinamico,
    a partire dalla versione già ottenuta tramite REST API.

    Non esegue nessuna chiamata HTTP: URL e filename sono deterministici.

    Args:
        server_url: URL base sito CheckMK
        server_ver: Versione agent sul server (es. '2.4.0p23')
        pkg_type:   Tipo pacchetto ('deb', 'rpm', 'openwrt')

    Returns:
        Tupla (url_completo, filename)
    """
    agents_base = f"{server_url.rstrip('/')}/check_mk/agents/"
    if pkg_type in ("deb", "openwrt"):
        filename = f"check-mk-agent_{server_ver}-1_all.deb"
    elif pkg_type == "rpm":
        filename = f"check-mk-agent-{server_ver}-1.noarch.rpm"
    else:
        raise ValueError(f"Tipo pacchetto non supportato: {pkg_type}")
    return f"{agents_base}{filename}", filename


def download_agent(server_url: str, server_ver: str, pkg_type: str, dest_dir: Path) -> Optional[Path]:
    """
    Scarica il pacchetto agent dal server CheckMK.

    L'URL viene costruito dinamicamente dalla versione già nota (nessuno scraping HTML).

    Args:
        server_url: URL base sito CheckMK
        server_ver: Versione agent sul server (già ottenuta via REST API)
        pkg_type:   Tipo pacchetto
        dest_dir:   Directory temporanea dove salvare il file

    Returns:
        Path al file scaricato oppure None in caso di errore.
    """
    url, filename = build_download_url(server_url, server_ver, pkg_type)
    dest = dest_dir / filename

    print(f"[INFO] Download: {url}")
    try:
        urllib.request.urlretrieve(url, str(dest))
        print(f"[OK]   Scaricato: {dest}")
        return dest
    except Exception as e:
        print(f"[ERROR] Download fallito: {e}", file=sys.stderr)
        return None


# ─── Installazione Agent ──────────────────────────────────────────────────────

def install_agent_deb(pkg_path: Path) -> bool:
    """Installa pacchetto .deb e corregge dipendenze."""
    print(f"[INFO] Installazione {pkg_path.name}...")
    ret = subprocess.run(["dpkg", "-i", str(pkg_path)]).returncode
    if ret != 0:
        # fix dipendenze rotte
        subprocess.run(["apt-get", "install", "-f", "-y"])
    # Disabilita cmk-agent-ctl-daemon (causa conflitto porta 6556)
    subprocess.run(["systemctl", "stop", "cmk-agent-ctl-daemon.service"],
                   stderr=subprocess.DEVNULL)
    subprocess.run(["systemctl", "disable", "cmk-agent-ctl-daemon.service"],
                   stderr=subprocess.DEVNULL)
    subprocess.run(["systemctl", "reset-failed", "cmk-agent-ctl-daemon.service"],
                   stderr=subprocess.DEVNULL)
    return ret == 0


def install_agent_rpm(pkg_path: Path) -> bool:
    """Installa pacchetto .rpm."""
    print(f"[INFO] Installazione {pkg_path.name}...")
    ret = subprocess.run(["rpm", "-Uvh", "--replacepkgs", str(pkg_path)]).returncode
    return ret == 0


def install_agent_openwrt(pkg_path: Path) -> bool:
    """
    Installa agent su OpenWrt estraendo il binario dal .deb manualmente
    (ar + tar, nessun dpkg disponibile).
    """
    print(f"[INFO] Estrazione binario da {pkg_path.name} (OpenWrt)...")
    tmpdir = Path(tempfile.mkdtemp())
    try:
        subprocess.run(["ar", "x", str(pkg_path)], cwd=str(tmpdir), check=True)
        data_tars = list(tmpdir.glob("data.tar.*"))
        if not data_tars:
            print("[ERROR] data.tar.* non trovato nel .deb", file=sys.stderr)
            return False
        subprocess.run(["tar", "-xf", str(data_tars[0]), "-C", str(tmpdir)], check=True)
        for candidate in (tmpdir / "usr/bin/check_mk_agent",
                          tmpdir / "usr/bin/check-mk-agent"):
            if candidate.exists():
                subprocess.run(["install", "-m", "0755", str(candidate),
                                "/usr/bin/check_mk_agent"], check=True)
                print("[OK] check_mk_agent aggiornato")
                return True
        print("[ERROR] Binario agent non trovato nel .deb", file=sys.stderr)
        return False
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Estrazione fallita: {e}", file=sys.stderr)
        return False
    finally:
        shutil.rmtree(str(tmpdir), ignore_errors=True)


# ─── Comparazione Versioni ────────────────────────────────────────────────────

def parse_version(ver: str) -> Tuple[int, int, int, int]:
    """
    Converte stringa versione CheckMK in tupla comparabile.
    Es: '2.4.0p23' → (2, 4, 0, 23)
        '2.4.0'    → (2, 4, 0, 0)
    """
    m = re.match(r"(\d+)\.(\d+)\.(\d+)(?:p(\d+))?", ver.strip())
    if not m:
        return (0, 0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4) or 0))


# ─── Main ─────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=f"update_checkmk_agent.py v{VERSION} - Aggiornamento automatico agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esempi:
  # Auto-rileva server da installazione OMD locale (macchina con CheckMK server)
  python3 update_checkmk_agent.py
  python3 update_checkmk_agent.py --dry-run

  # Specifica server manualmente (host monitorati senza OMD locale)
  python3 update_checkmk_agent.py --server-url https://monitor.nethlab.it/monitoring
  python3 update_checkmk_agent.py --server-url https://monitor.nethlab.it/monitoring --dry-run
  python3 update_checkmk_agent.py --server-url https://monitor.nethlab.it/monitoring --force
        """,
    )
    p.add_argument("--server-url", required=False, default=None,
                   help="URL sito CheckMK es. https://hostname/site. "
                        "Se omesso, auto-rilevato dall'installazione OMD locale.")
    p.add_argument("--dry-run", action="store_true",
                   help="Mostra cosa farebbe senza eseguire modifiche")
    p.add_argument("--force", action="store_true",
                   help="Forza reinstallazione anche se versione già aggiornata")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    if os.geteuid() != 0:
        print("[ERROR] Richiesto root", file=sys.stderr)
        return 1

    # Risolvi server URL: da CLI oppure auto-detect da OMD locale
    server_url = args.server_url
    if not server_url:
        server_url = detect_local_server_url()
        if not server_url:
            print("[ERROR] --server-url non fornito e nessuna installazione OMD locale rilevata.",
                  file=sys.stderr)
            print("[ERROR] Fornire: --server-url https://hostname/site", file=sys.stderr)
            return 1
        print(f"[INFO] Server URL auto-rilevato: {server_url}")

    # Parsing hostname e site per output leggibile
    server_hostname, server_site = parse_server_url(server_url)

    print(f"{'='*55}")
    print(f"  update_checkmk_agent.py v{VERSION}")
    print(f"  Hostname: {server_hostname}")
    print(f"  Site:     {server_site}")
    print(f"{'='*55}")

    # 1. Detect OS
    pkg_type = detect_pkg_type()
    print(f"[INFO] Tipo pacchetto: {pkg_type}")

    # 2. Versione locale
    local_ver = get_local_agent_version(pkg_type)
    if local_ver:
        print(f"[INFO] Agent locale:   {local_ver}")
    else:
        print("[INFO] Agent locale:   non installato")

    # 3. Versione disponibile sul server
    print(f"[INFO] Query server ({server_hostname}/{server_site})...")
    server_ver = get_server_agent_version(server_url, pkg_type)
    if not server_ver:
        print("[ERROR] Impossibile ottenere versione dal server. "
              "Server non raggiungibile o non ancora aggiornato.", file=sys.stderr)
        return 1
    print(f"[INFO] Agent su server: {server_ver}")

    # 4. Confronto versioni
    local_tuple = parse_version(local_ver) if local_ver else (0, 0, 0, 0)
    server_tuple = parse_version(server_ver)

    if server_tuple < local_tuple:
        # Agent più nuovo del server → il server non è ancora aggiornato
        print(f"[WARN] Agent locale ({local_ver}) è più nuovo del server ({server_ver}).")
        print("[WARN] Il server non è ancora stato aggiornato. Skip.")
        return 0

    if server_tuple == local_tuple and not args.force:
        print(f"[OK] Agent già aggiornato alla versione {local_ver}. Niente da fare.")
        return 0

    if args.force and server_tuple == local_tuple:
        print(f"[INFO] --force: reinstallo la versione {server_ver}")
    else:
        print(f"[INFO] Aggiornamento disponibile: {local_ver or 'N/A'} → {server_ver}")

    if args.dry_run:
        print("[DRY-RUN] Nessuna modifica eseguita.")
        return 0

    # 5. Download
    tmpdir = Path(tempfile.mkdtemp(prefix="cmk-agent-update-"))
    try:
        pkg_path = download_agent(server_url, server_ver, pkg_type, tmpdir)
        if not pkg_path:
            return 1

        # 6. Installazione
        if pkg_type == "deb":
            ok = install_agent_deb(pkg_path)
        elif pkg_type == "rpm":
            ok = install_agent_rpm(pkg_path)
        elif pkg_type == "openwrt":
            ok = install_agent_openwrt(pkg_path)
        else:
            ok = False

        if ok:
            new_ver = get_local_agent_version(pkg_type)
            print(f"[OK] Aggiornamento completato → {new_ver or server_ver}")
            return 0
        else:
            print("[ERROR] Installazione fallita", file=sys.stderr)
            return 1
    finally:
        shutil.rmtree(str(tmpdir), ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
