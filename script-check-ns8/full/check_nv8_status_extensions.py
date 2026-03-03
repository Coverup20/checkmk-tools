#!/usr/bin/env python3
"""
check_nv8_status_extensions.py - CheckMK Local Check per stato registrazione interni NethVoice NS8

Monitora la registrazione PJSIP degli interni (endpoint) su tutti i moduli NethVoice
installati su NethServer 8 (NS8).

Usa runagent + podman exec per eseguire `asterisk -rx "pjsip show endpoints"` nel
container FreePBX/Asterisk di ogni modulo NethVoice trovato.

Output CheckMK:
  - Una riga per interno NON registrato (per drilldown granulare in CheckMK)
  - Una riga di sommario NV8.Status.Extensions con conteggi totali

Stati endpoint PJSIP:
  Not in use   → registrato, nessuna chiamata attiva   (OK)
  In use       → registrato, chiamata in corso         (OK)
  Ringing      → registrato, squillo                   (OK)
  Busy         → registrato, occupato                  (OK)
  On Hold      → registrato, in attesa                 (OK)
  Unavailable  → NON registrato (nessun contatto)      (WARN/CRIT)
  Invalid      → errore configurazione                 (WARN)
  Unknown      → stato sconosciuto                     (WARN)

Soglie (configurabili):
  WARN  se >WARN_PCT% degli interni non registrati  (default: 10%)
  CRIT  se >CRIT_PCT% degli interni non registrati  (default: 30%)

Deployment (NS8 host):
  cd /opt/checkmk-tools && git pull
  cp script-check-ns8/full/check_nv8_status_extensions.py /usr/lib/check_mk_agent/local/check_nv8_status_extensions
  chmod +x /usr/lib/check_mk_agent/local/check_nv8_status_extensions

Version: 1.0.0
"""

import re
import subprocess
import sys
import time
from typing import Dict, List, Optional, Tuple

VERSION = "1.0.0"
SERVICE_PREFIX   = "NV8.Status.Extension"
SERVICE_SUMMARY  = "NV8.Status.Extensions"

SCRIPT_TIMEOUT = 25       # secondi totali budget
WARN_PCT       = 10       # % interni non registrati → WARNING
CRIT_PCT       = 30       # % interni non registrati → CRITICAL

_START = time.monotonic()

# Endpoint states che indicano registrazione attiva
REGISTERED_STATES = {
    "not in use",
    "in use",
    "ringing",
    "ring",
    "busy",
    "on hold",
}

# Regex per riga Endpoint nell'output di `pjsip show endpoints`
# Formato: "  Endpoint:  <name/cid>  <state>  <N of M>"
# Esempio: "  Endpoint:  100                  Not in use    0 of inf"
#          "  Endpoint:  200/200              Unavailable   0 of inf"
ENDPOINT_RE = re.compile(
    r"^\s+Endpoint:\s+(\S+)\s+(.*?)\s+\d+\s+of\s+",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def elapsed() -> float:
    return time.monotonic() - _START


def run_command(cmd: List[str], timeout: int = 8) -> Tuple[int, str, str]:
    """Esegue un comando rispettando il budget temporale globale."""
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
    """Converte il nome di un interno in service name CheckMK formato dot."""
    # Rimuove suffisso /CID (es: "200/200" → "200")
    name = name.split("/")[0]
    name = re.sub(r"[^a-zA-Z0-9]", ".", name)
    name = re.sub(r"\.{2,}", ".", name)
    return name.strip(".") or "ext"


# ---------------------------------------------------------------------------
# Discovery moduli e container
# ---------------------------------------------------------------------------

def get_modules() -> List[str]:
    code, out, _ = run_command(["runagent", "-l"])
    if code != 0 or not out:
        return []
    return [
        line.strip()
        for line in out.splitlines()
        if line.strip() and line.strip() not in ("cluster", "node")
    ]


def get_containers(module: str) -> List[str]:
    """Ritorna i nomi dei container in running nel modulo."""
    code, out, _ = run_command(
        ["runagent", "-m", module, "podman", "ps", "--format", "{{.Names}}"]
    )
    if code != 0 or not out:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def find_nethvoice_containers() -> List[Tuple[str, str]]:
    """
    Trova tutti i container FreePBX/Asterisk nei moduli NethVoice.
    Ritorna lista di (module_name, container_name).
    """
    results = []
    for module in get_modules():
        if elapsed() >= SCRIPT_TIMEOUT - 5:
            break
        if not any(kw in module.lower() for kw in ("nethvoice", "asterisk", "freepbx", "pbx")):
            continue
        for cname in get_containers(module):
            if "freepbx" in cname.lower() or "asterisk" in cname.lower():
                results.append((module, cname))
    return results


# ---------------------------------------------------------------------------
# Query Asterisk CLI
# ---------------------------------------------------------------------------

def run_asterisk_cmd(module: str, container: str, asterisk_cmd: str) -> Optional[str]:
    """Esegue un comando Asterisk CLI. Ritorna stdout o None su errore grave."""
    code, out, _ = run_command(
        ["runagent", "-m", module, "podman", "exec",
         container, "asterisk", "-rx", asterisk_cmd],
        timeout=10,
    )
    if code in (124, 127):
        return None
    return out


# ---------------------------------------------------------------------------
# Parsing di `pjsip show endpoints`
# ---------------------------------------------------------------------------

def parse_endpoints(output: str) -> List[Dict[str, str]]:
    """
    Analizza l'output di `pjsip show endpoints`.
    Restituisce lista di dict con:
      name       - nome endpoint (senza CID)
      state      - stato raw (lowercase)
      registered - True se registrato con contatto attivo
    """
    endpoints = []
    for line in output.splitlines():
        m = ENDPOINT_RE.match(line)
        if not m:
            continue

        raw_name  = m.group(1).strip()
        raw_state = m.group(2).strip()
        state_lc  = raw_state.lower()

        # Salta endpoint che sembrano trunk (contengono "trunk", "reg-", oppure
        # contengono "/" con parte sip: che indica AOR trunk)
        base_name = raw_name.split("/")[0]
        if any(kw in base_name.lower() for kw in ("trunk", "reg-", "reg_", "sip:")):
            continue

        # Salta entry non-endpoint (header, separatori, conteggi)
        if not re.match(r"^[a-zA-Z0-9]", base_name):
            continue

        registered = state_lc in REGISTERED_STATES

        endpoints.append({
            "name":       base_name,
            "raw_name":   raw_name,
            "state":      raw_state,
            "registered": registered,
        })

    return endpoints


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    # Prerequisiti
    rc, _, _ = run_command(["which", "runagent"])
    if rc != 0:
        print(f"3 {SERVICE_SUMMARY} - UNKNOWN: runagent non trovato, questo script richiede NS8")
        return 0

    containers = find_nethvoice_containers()
    if not containers:
        print(f"2 {SERVICE_SUMMARY} - CRITICAL: nessun modulo NethVoice trovato su questo host NS8")
        return 0

    all_endpoints: List[Dict[str, str]] = []
    modules_checked: List[str] = []

    for module, container in containers:
        if elapsed() >= SCRIPT_TIMEOUT - 3:
            break

        output = run_asterisk_cmd(module, container, "pjsip show endpoints")
        if not output or not output.strip():
            continue

        eps = parse_endpoints(output)
        for ep in eps:
            ep["module"] = module
        all_endpoints.extend(eps)
        modules_checked.append(module)

    if not all_endpoints:
        print(
            f"1 {SERVICE_SUMMARY} - WARNING: nessun interno PJSIP trovato "
            f"| modules={','.join(modules_checked) or 'none'}"
        )
        return 0

    total      = len(all_endpoints)
    registered = [e for e in all_endpoints if e["registered"]]
    unreg      = [e for e in all_endpoints if not e["registered"]]
    reg_count  = len(registered)
    unreg_count = len(unreg)
    unreg_pct  = (unreg_count / total * 100) if total > 0 else 0.0

    # Riga per ogni interno NON registrato (visibile come servizio separato in CheckMK)
    for ep in unreg:
        svc = f"{SERVICE_PREFIX}.{sanitize_name(ep['name'])}"
        print(
            f"2 {svc} - Unregistered | "
            f"name={ep['name']} state={ep['state']} module={ep['module']}"
        )

    # Determina stato sommario
    if unreg_count == 0:
        overall = 0
        msg = f"OK: tutti {total} interni registrati"
    elif unreg_pct >= CRIT_PCT:
        overall = 2
        msg = f"CRITICAL: {reg_count}/{total} registrati, {unreg_count} non registrati ({unreg_pct:.0f}%)"
    elif unreg_pct >= WARN_PCT:
        overall = 1
        msg = f"WARNING: {reg_count}/{total} registrati, {unreg_count} non registrati ({unreg_pct:.0f}%)"
    else:
        overall = 0
        msg = f"OK: {reg_count}/{total} registrati, {unreg_count} non registrati ({unreg_pct:.0f}%)"

    # Aggiungi lista interni non registrati se pochi (max 10 in riga)
    if 0 < unreg_count <= 10:
        names = ", ".join(e["name"] for e in unreg)
        msg += f" [{names}]"

    perf = f"registered={reg_count};;;0;{total} unregistered={unreg_count};;;0;{total} total={total}"
    modules_str = ",".join(modules_checked)
    print(f"{overall} {SERVICE_SUMMARY} - {msg} | {perf} modules={modules_str}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
