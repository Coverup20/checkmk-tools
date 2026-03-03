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

VERSION = "1.3.1"
SERVICE_PREFIX = "NethVoice.Trunk"
SERVICE_SUMMARY = "NethVoice.Trunks"

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

# Regex per rilevare lo stato PJSIP nella riga (non necessariamente a fine riga)
# es: "trunk/sip:host:5060   auth   Rejected          (exp. 28s)"
STATUS_RE = re.compile(
    r"\b(Not\s+Registered|No\s+Auth|Registered|Trying|Rejected|Failed|Stopped|Unregistered)\b",
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
    - Sostituisce caratteri non alfanumerici (incluso _ e -) con punto
    """
    name = re.sub(r"^reg[-_]", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[^a-zA-Z0-9]", ".", name)
    name = re.sub(r"\.{2,}", ".", name)  # collassa punti multipli
    return name.strip(".") or "trunk"


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


def find_nethvoice_containers() -> List[Tuple[str, str]]:
    """
    Trova TUTTI i container FreePBX/Asterisk in tutti i moduli nethvoice.
    Ritorna lista di (module_name, container_name).
    """
    results = []
    for module in get_modules():
        if elapsed() >= SCRIPT_TIMEOUT:
            break
        # Ottimizzazione: salta moduli che non sono nethvoice/asterisk/pbx
        if not any(kw in module.lower() for kw in ("nethvoice", "asterisk", "freepbx", "pbx")):
            continue
        for cname, _ in get_containers(module):
            if "freepbx" in cname.lower() or "asterisk" in cname.lower():
                results.append((module, cname))
    return results


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
    # "No objects found." è output valido (nessun trunk configurato)
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

    # --- 2. Cerca TUTTI i container FreePBX/Asterisk ---
    containers = find_nethvoice_containers()
    if not containers:
        print(
            f"2 {SERVICE_SUMMARY} - CRITICAL: container Asterisk/FreePBX non trovato "
            f"(NethVoice installato? container running?)"
        )
        return 0

    # --- 3. Raccoglie registrazioni da TUTTI i moduli nethvoice ---
    all_trunks: List[Dict[str, str]] = []
    modules_checked: List[str] = []

    for module, container in containers:
        raw = run_asterisk_cmd(module, container, "pjsip show registrations outbound")
        if raw is None:
            continue
        trunks = parse_pjsip_registrations(raw)
        for t in trunks:
            t["module"] = module  # aggiungi info modulo per debug
        all_trunks.extend(trunks)
        modules_checked.append(module)

    modules_str = ",".join(modules_checked) if modules_checked else "none"

    # --- 4. Nessun trunk trovato ---
    if not all_trunks:
        print(
            f"1 {SERVICE_SUMMARY} - WARNING: nessun trunk PJSIP outbound configurato "
            f"| modules={modules_str}"
        )
        return 0

    # --- 5. Output una riga per trunk ---
    overall_state = 0
    registered_count = 0

    for trunk in all_trunks:
        state = get_state(trunk["status"])
        overall_state = max(overall_state, state)

        if state == 0:
            registered_count += 1

        svc_name = f"{SERVICE_PREFIX}.{sanitize_name(trunk['name'])}"

        # Server URI abbreviato: domain[:porta] senza sip:/sips:
        server = trunk["server"]
        server_clean = re.sub(r"^sips?:", "", server)          # rimuovi schema
        server_clean = server_clean.split("@")[-1]              # solo host (senza utente)
        server_clean = server_clean.split(";")[0].strip()       # rimuovi parametri SIP

        mod = trunk.get("module", "")
        print(f"{state} {svc_name} - {trunk['status']} | server={server_clean} module={mod}")

    # --- 6. Riga sommario ---
    total = len(all_trunks)
    not_ok = total - registered_count

    if overall_state == 0:
        summary_msg = f"OK: tutti i trunk registrati ({registered_count}/{total})"
    elif overall_state == 1:
        summary_msg = f"WARNING: {registered_count}/{total} registrati, {not_ok} con problemi"
    else:
        summary_msg = f"CRITICAL: {registered_count}/{total} registrati, {not_ok} con problemi"

    print(
        f"{overall_state} {SERVICE_SUMMARY} - {summary_msg} "
        f"| modules={modules_str}"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
