#!/usr/bin/env python3
"""
check_nethvoice_trunks.py - CheckMK Local Check per stato trunk NethVoice

Monitora la registrazione dei trunk PJSIP su NethVoice NS8.
Usa runagent + podman exec per eseguire `asterisk -rx "pjsip show registrations"`
all'interno del container Asterisk del modulo NethVoice.

Output CheckMK:
  - Una riga per trunk (servizio dedicato per granularità in caso di problemi)
  - Una riga di sommario complessivo (NethVoice_Trunks)

Stati PJSIP riconosciuti:
  Registered     → OK (0)
  Not Registered → WARNING (1)  es: trunk IP-based non registranti
  Trying         → WARNING (1)  registrazione in corso
  No Auth        → CRITICAL (2) errore autenticazione
  Rejected       → CRITICAL (2) rifiutato dal provider
  Failed         → CRITICAL (2) fallimento generico
  Stopped        → CRITICAL (2) registrazione fermata
  Unregistered   → CRITICAL (2) deregistrato

Deployment:
  cp check_nethvoice_trunks.py /usr/lib/check_mk_agent/local/
  chmod +x /usr/lib/check_mk_agent/local/check_nethvoice_trunks.py

Version: 1.0.0
"""

import subprocess
import sys
import re
import time
from typing import Dict, List, Optional, Tuple

VERSION = "1.0.0"
SERVICE_PREFIX = "NethVoice_Trunk"
SERVICE_SUMMARY = "NethVoice_Trunks"

SCRIPT_TIMEOUT = 20  # secondi totali a disposizione dello script
_START = time.monotonic()

# PJSIP registration states → stato CheckMK (0=OK, 1=WARN, 2=CRIT, 3=UNKNOWN)
STATE_MAP: Dict[str, int] = {
    "Registered":     0,  # registrato correttamente
    "Not Registered": 1,  # non registrato (potrebbe essere intenzionale per trunk IP-based)
    "Trying":         1,  # tentativo di registrazione in corso
    "No Auth":        2,  # credenziali errate
    "Rejected":       2,  # rifiutato dal provider SIP
    "Failed":         2,  # errore generico
    "Stopped":        2,  # registrazione fermata
    "Unregistered":   2,  # deregistrato manualmente
}

# Regex per rilevare lo stato PJSIP in fondo a ogni riga
STATUS_RE = re.compile(
    r"(Not\s+Registered|No\s+Auth|Registered|Trying|Rejected|Failed|Stopped|Unregistered)\s*$",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def elapsed() -> float:
    """Secondi trascorsi dall'avvio dello script."""
    return time.monotonic() - _START


def run_command(cmd: List[str], timeout: int = 8) -> Tuple[int, str, str]:
    """
    Esegue un comando e restituisce (exit_code, stdout, stderr).
    Rispetta il budget temporale globale SCRIPT_TIMEOUT.
    """
    try:
        remaining = max(1, int(SCRIPT_TIMEOUT - elapsed()))
        effective = min(timeout, remaining)
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=effective,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except FileNotFoundError:
        return 127, "", "command not found"
    except Exception as exc:
        return 1, "", str(exc)


def sanitize_name(name: str) -> str:
    """
    Converte il nome di un trunk in un service name valido per CheckMK.
    - Rimuove prefisso reg- / reg_
    - Sostituisce caratteri non alfanumerici con underscore
    """
    name = re.sub(r"^reg[-_]", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    return name.strip("_") or "trunk"


# ---------------------------------------------------------------------------
# Discovery del container Asterisk
# ---------------------------------------------------------------------------

def get_modules() -> List[str]:
    """Ritorna la lista di tutti i moduli NS8 (output di runagent -l)."""
    code, out, _ = run_command(["runagent", "-l"])
    if code != 0 or not out:
        return []
    return [
        line.strip()
        for line in out.splitlines()
        if line.strip() and line.strip() not in ("cluster", "node")
    ]


def get_containers(module: str) -> List[Tuple[str, str]]:
    """
    Ritorna i container del modulo come lista di (nome, status).
    Usa `podman ps` (solo container in running) per escludere container fermati.
    """
    code, out, _ = run_command(
        ["runagent", "-m", module, "podman", "ps",
         "--format", "{{.Names}}|{{.Status}}"]
    )
    if code != 0 or not out:
        return []
    result = []
    for line in out.splitlines():
        if "|" not in line:
            continue
        cname, cstatus = line.split("|", 1)
        result.append((cname.strip(), cstatus.strip()))
    return result


def find_asterisk_container() -> Optional[Tuple[str, str]]:
    """
    Cerca in tutti i moduli NS8 il container Asterisk attivo.

    Strategia:
      1. runagent -l  → lista moduli
      2. Per ogni modulo → podman ps → cerca container con "asterisk" nel nome
      3. Ritorna (module_name, container_name) alla prima occorrenza trovata

    Returns:
        (module_name, container_name) oppure None se non trovato.
    """
    for module in get_modules():
        if elapsed() >= SCRIPT_TIMEOUT:
            break
        for cname, cstatus in get_containers(module):
            if "asterisk" in cname.lower():
                return (module, cname)
    return None


# ---------------------------------------------------------------------------
# Query Asterisk
# ---------------------------------------------------------------------------

def run_asterisk_cmd(module: str, container: str, asterisk_cmd: str) -> Optional[str]:
    """
    Esegue un comando Asterisk via runagent + podman exec.

    Returns:
        Output grezzo (stdout) oppure None in caso di errore grave.
    """
    code, out, err = run_command(
        ["runagent", "-m", module, "podman", "exec",
         container, "asterisk", "-rx", asterisk_cmd],
        timeout=10,
    )
    # Asterisk CLI può uscire con code != 0 anche con output valido;
    # consideriamo errore solo timeout (124) o comando non trovato (127)
    if code in (124, 127):
        return None
    return out


# ---------------------------------------------------------------------------
# Parsing di `pjsip show registrations`
# ---------------------------------------------------------------------------

def parse_pjsip_registrations(output: str) -> List[Dict[str, str]]:
    """
    Parsa l'output di `asterisk -rx "pjsip show registrations"`.

    Formato tipico:
        <Registration/ServerURI......>  <Auth.......>  <Status>
        =========================================================
        reg-trunk1/sip:user@host       auth-t1        Registered
        reg-trunk2/sip:user@host2      auth-t2        Rejected
        2 registrations.

    Returns:
        Lista di dict con chiavi: name, server, status
    """
    trunks: List[Dict[str, str]] = []

    for line in output.splitlines():
        stripped = line.strip()

        # Salta righe vuote, separatori (===), header (<...>)
        if not stripped:
            continue
        if stripped.startswith("=") or stripped.startswith("<"):
            continue
        # Salta riga sommario "N registrations."
        if re.match(r"^\d+\s+registration", stripped, re.IGNORECASE):
            continue
        # Salta "No registrations currently exist."
        if "no registrations" in stripped.lower():
            continue

        # Cerca stato PJSIP in fondo alla riga
        m = STATUS_RE.search(stripped)
        if not m:
            continue

        status = re.sub(r"\s+", " ", m.group(1)).strip()

        # Colonna 1: la prima parte (separata da 2+ spazi)
        parts = re.split(r"\s{2,}", stripped)
        if not parts:
            continue

        reg_uri = parts[0].strip()
        reg_name = reg_uri.split("/")[0] if "/" in reg_uri else reg_uri
        server_uri = reg_uri.split("/", 1)[1] if "/" in reg_uri else ""

        trunks.append({
            "name": reg_name,
            "server": server_uri,
            "status": status,
        })

    return trunks


# ---------------------------------------------------------------------------
# CheckMK state helpers
# ---------------------------------------------------------------------------

def get_state(status: str) -> int:
    """Ritorna lo stato CheckMK per uno stato PJSIP (default: 1 WARN per sconosciuti)."""
    return STATE_MAP.get(status, 1)


STATE_LABEL = {0: "OK", 1: "WARNING", 2: "CRITICAL", 3: "UNKNOWN"}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    # --- 1. Verifica runagent disponibile (NS8) ---
    if run_command(["which", "runagent"])[0] != 0:
        print(f"3 {SERVICE_SUMMARY} - UNKNOWN: runagent non trovato, questo script richiede NS8")
        return 0

    # --- 2. Cerca container Asterisk ---
    found = find_asterisk_container()
    if found is None:
        print(
            f"2 {SERVICE_SUMMARY} - CRITICAL: container Asterisk non trovato "
            f"(NethVoice installato? container running?)"
        )
        return 0

    module, container = found

    # --- 3. Recupera registrazioni PJSIP ---
    raw = run_asterisk_cmd(module, container, "pjsip show registrations")
    if raw is None:
        print(
            f"2 {SERVICE_SUMMARY} - CRITICAL: impossibile eseguire pjsip show registrations "
            f"(module={module} container={container})"
        )
        return 0

    # --- 4. Parsa output ---
    trunks = parse_pjsip_registrations(raw)

    if not trunks:
        # Nessun trunk registrant configurato (o tutti IP-based senza registrazione)
        if "no registrations" in raw.lower():
            print(
                f"1 {SERVICE_SUMMARY} - WARNING: nessun trunk PJSIP con registrazione trovato "
                f"| module={module} container={container}"
            )
        else:
            print(
                f"3 {SERVICE_SUMMARY} - UNKNOWN: output pjsip show registrations non riconosciuto "
                f"| module={module} container={container}"
            )
        return 0

    # --- 5. Output una riga per trunk ---
    overall_state = 0
    registered_count = 0

    for trunk in trunks:
        state = get_state(trunk["status"])
        overall_state = max(overall_state, state)

        if state == 0:
            registered_count += 1

        svc_name = f"{SERVICE_PREFIX}_{sanitize_name(trunk['name'])}"

        # Server URI abbreviato: domain[:porta] senza sip:/sips:
        server = trunk["server"]
        server_clean = re.sub(r"^sips?:", "", server)          # rimuovi schema
        server_clean = server_clean.split("@")[-1]              # solo host (senza utente)
        server_clean = server_clean.split(";")[0].strip()       # rimuovi parametri SIP

        print(f"{state} {svc_name} - {trunk['status']} | server={server_clean}")

    # --- 6. Riga sommario ---
    total = len(trunks)
    not_ok = total - registered_count

    if overall_state == 0:
        summary_msg = f"OK: tutti i trunk registrati ({registered_count}/{total})"
    elif overall_state == 1:
        summary_msg = f"WARNING: {registered_count}/{total} registrati, {not_ok} con problemi"
    else:
        summary_msg = f"CRITICAL: {registered_count}/{total} registrati, {not_ok} con problemi"

    print(
        f"{overall_state} {SERVICE_SUMMARY} - {summary_msg} "
        f"| module={module} container={container}"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
