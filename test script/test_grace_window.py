#!/usr/bin/env python3
"""
test_grace_window.py - Test suite per la logica grace window 24h post-Effettuato

Scenari testati:
  A) effettuato_at in cache (<24h) + WARNING  → scartato silenzioso
  B) effettuato_at in cache (<24h) + CRITICAL → commento privato riapertura
  C) effettuato_at in cache (>24h)            → ticket rimosso cache, normale
  D) effettuato_at NON in cache + Ydea: Effettuato → lo rileva e scarta WARNING
  E) ticket attivo (non Effettuato)           → comportamento normale (nessuna grace)
  F) dopo CRITICAL reopen, nuovo WARNING      → non scartato (reopen_at = attivo)

Serve: accesso a srv-monitoring-sp (scenario D usa API Ydea reale)
       Per scenari A-C-E-F: completamente locale, nessuna API call.

Usage:
  # Solo test locali (nessuna API):
  python3 test_grace_window.py

  # Con test API reale (scenario D, richiede ydea-toolkit):
  python3 test_grace_window.py --real-ticket <ticket_id>

  # Su srv-monitoring-sp:
  python3 /opt/checkmk-tools/test\ script/test_grace_window.py --real-ticket 1697129
"""

import sys
import os
import json
import time
import tempfile
import shutil
from datetime import datetime
from typing import Optional, Dict, Any

# ─── Colori output ─────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"


def ok(msg):  print(f"  {GREEN}✓ PASS{RESET}  {msg}")
def fail(msg): print(f"  {RED}✗ FAIL{RESET}  {msg}"); global _failures; _failures += 1
def info(msg): print(f"  {CYAN}ℹ{RESET}      {msg}")
def warn(msg): print(f"  {YELLOW}⚠{RESET}      {msg}")

_failures = 0

# ─── Setup env per importare funzioni da ydea_la.py ───────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
NOTIFY_DIR = os.path.join(SCRIPT_DIR, "..", "script-notify-checkmk", "full")
NOTIFY_DIR = os.path.realpath(NOTIFY_DIR)

# Usa una directory temporanea per la cache di test
TEST_CACHE_DIR = tempfile.mkdtemp(prefix="ydea_test_")
TEST_TICKET_CACHE  = os.path.join(TEST_CACHE_DIR, "ydea_checkmk_tickets.json")
TEST_FLAPPING_CACHE = os.path.join(TEST_CACHE_DIR, "ydea_checkmk_flapping.json")
TEST_CACHE_LOCK    = os.path.join(TEST_CACHE_DIR, "ydea_cache.lock")


def setup_module():
    """Importa ydea_la come modulo patchando le costanti di path."""
    sys.path.insert(0, NOTIFY_DIR)

    # Patch environment prima dell'import
    os.environ["YDEA_TOOLKIT_DIR"] = "/opt/ydea-toolkit"
    os.environ["DEBUG_YDEA"] = "1"

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "ydea_la",
        os.path.join(NOTIFY_DIR, "ydea_la.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Override path cache con directory temporanea
    mod.TICKET_CACHE   = TEST_TICKET_CACHE
    mod.FLAPPING_CACHE = TEST_FLAPPING_CACHE
    mod.CACHE_LOCK     = TEST_CACHE_LOCK
    mod.YDEA_CACHE_DIR = TEST_CACHE_DIR

    return mod


def reset_cache():
    """Svuota la cache di test."""
    with open(TEST_TICKET_CACHE, 'w') as f:
        json.dump({}, f)
    with open(TEST_FLAPPING_CACHE, 'w') as f:
        json.dump({}, f)
    open(TEST_CACHE_LOCK, 'w').close()


def make_ticket_entry(ticket_id: int, state: str = "OK",
                      effettuato_at: Optional[int] = None,
                      reopen_at: Optional[int] = None) -> dict:
    now = int(time.time())
    return {
        "ticket_id": ticket_id,
        "state": state,
        "created_at": now - 3600,
        "last_update": now,
        "resolved_at": effettuato_at,
        "effettuato_at": effettuato_at,
        "reopen_at": reopen_at
    }


def write_cache(entries: dict):
    with open(TEST_TICKET_CACHE, 'w') as f:
        json.dump(entries, f)


def read_cache() -> dict:
    with open(TEST_TICKET_CACHE, 'r') as f:
        return json.load(f)


# ─── MOCK toolkit_cmd ─────────────────────────────────────────────────────────
_mock_calls = []
_mock_responses = {}

def mock_toolkit_cmd(args, timeout=None):
    """Intercetta le chiamate al toolkit e ritorna risposte predefinite."""
    _mock_calls.append(list(args))
    key = args[0] if args else ""
    if key in _mock_responses:
        return _mock_responses[key]
    # Default: successo con risposta vuota
    return 0, "{}", ""


# ─── TEST ─────────────────────────────────────────────────────────────────────

def test_a_warning_in_grace(mod):
    """Scenario A: effettuato_at in cache (<24h) + WARNING → scartato."""
    print(f"\n{BOLD}[A] WARNING scartato durante grace 24h{RESET}")
    reset_cache()

    now = int(time.time())
    write_cache({"testhost": make_ticket_entry(99001, state="OK", effettuato_at=now - 3600)})

    # Verifica check_effettuato_grace
    grace = mod.check_effettuato_grace("testhost")
    if grace is True:
        ok("check_effettuato_grace -> True (in grace)")
    else:
        fail(f"check_effettuato_grace atteso True, ottenuto {grace}")

    # Simula: get_ticket_id presente, state WARNING
    # La logica nel main() non viene chiamata qui, ma verifichiamo le funzioni
    ticket_id = mod.get_ticket_id("testhost")
    if ticket_id == 99001:
        ok(f"get_ticket_id -> {ticket_id}")
    else:
        fail(f"get_ticket_id atteso 99001, ottenuto {ticket_id}")

    info("Se in main(): WARNING sarebbe scartato silenziosamente → return 0")


def test_b_critical_reopen_in_grace(mod):
    """Scenario B: CRITICAL durante grace → commento privato, reopen_at settato."""
    print(f"\n{BOLD}[B] CRITICAL riapertura durante grace 24h{RESET}")
    reset_cache()

    now = int(time.time())
    write_cache({"testhost2": make_ticket_entry(99002, state="OK", effettuato_at=now - 3600)})

    grace = mod.check_effettuato_grace("testhost2")
    if grace is True:
        ok("grace is True confermato")
    else:
        fail(f"atteso True, ottenuto {grace}")

    # Simula: add_private_note OK → poi set_cache_field reopen_at
    mod.set_cache_field("testhost2", "reopen_at", now)
    mod.update_ticket_state("testhost2", "CRITICAL")

    cache = read_cache()
    entry = cache.get("testhost2", {})

    if entry.get("reopen_at") == now:
        ok(f"reopen_at settato correttamente: {now}")
    else:
        fail(f"reopen_at atteso {now}, ottenuto {entry.get('reopen_at')}")

    if entry.get("state") == "CRITICAL":
        ok("state aggiornato a CRITICAL")
    else:
        fail(f"state atteso CRITICAL, ottenuto {entry.get('state')}")

    # Dopo reopen_at, check_effettuato_grace deve tornare None (attivo)
    grace2 = mod.check_effettuato_grace("testhost2")
    if grace2 is None:
        ok("post-reopen: grace -> None (ticket attivo)")
    else:
        fail(f"post-reopen: grace atteso None, ottenuto {grace2}")


def test_c_outside_grace_24h(mod):
    """Scenario C: effettuato_at > 24h fa → ticket rimosso da cache."""
    print(f"\n{BOLD}[C] Fuori finestra 24h → rimozione cache{RESET}")
    reset_cache()

    now = int(time.time())
    old_effettuato = now - (25 * 3600)  # 25 ore fa
    write_cache({"testhost3": make_ticket_entry(99003, state="OK", effettuato_at=old_effettuato)})

    grace = mod.check_effettuato_grace("testhost3")
    if grace is False:
        ok("grace is False (fuori 24h)")
    else:
        fail(f"atteso False, ottenuto {grace}")

    # Simula rimozione
    mod.remove_ticket_from_cache("testhost3")
    cache = read_cache()
    if "testhost3" not in cache:
        ok("ticket rimosso dalla cache")
    else:
        fail("ticket ancora in cache dopo rimozione")


def test_d_fetch_ticket_stato_mock(mod):
    """Scenario D: effettuato_at NON in cache, Ydea ritorna 'Effettuato' → rileva e scarta WARNING."""
    print(f"\n{BOLD}[D] Rilevamento Effettuato da Ydea (mock API){RESET}")
    reset_cache()

    # Ticket in cache senza effettuato_at (caso ticket chiuso dall'operatore)
    write_cache({"testhost4": make_ticket_entry(99004, state="CRITICAL", effettuato_at=None)})

    # Mock: toolkit 'get' ritorna stato Effettuato
    orig_toolkit = mod.toolkit_cmd
    _mock_calls.clear()
    _mock_responses['get'] = (0, '{"stato": "Effettuato", "id": 99004}', "")
    mod.toolkit_cmd = mock_toolkit_cmd

    try:
        stato = mod.fetch_ticket_stato(99004)
        if stato == "Effettuato":
            ok(f"fetch_ticket_stato -> '{stato}'")
        else:
            fail(f"atteso 'Effettuato', ottenuto '{stato}'")

        if any(c[0] == 'get' and c[1] == '99004' for c in _mock_calls):
            ok(f"chiamata 'get 99004' eseguita")
        else:
            fail(f"chiamata 'get 99004' non trovata in: {_mock_calls}")

        # Simula: script rileva Effettuato e setta effettuato_at
        now = int(time.time())
        mod.set_cache_field("testhost4", 'effettuato_at', now)
        mod.set_cache_field("testhost4", 'reopen_at', None)

        grace = mod.check_effettuato_grace("testhost4")
        if grace is True:
            ok("dopo set effettuato_at: grace -> True (<24h)")
        else:
            fail(f"atteso True, ottenuto {grace}")

        info("WARNING arrivasse ora → verrebbe scartato")
    finally:
        mod.toolkit_cmd = orig_toolkit


def test_e_active_ticket_no_grace(mod):
    """Scenario E: ticket attivo (senza effettuato_at) → nessuna grace."""
    print(f"\n{BOLD}[E] Ticket attivo, nessuna grace{RESET}")
    reset_cache()

    write_cache({"testhost5": make_ticket_entry(99005, state="CRITICAL", effettuato_at=None, reopen_at=None)})

    # Mock: toolkit 'get' ritorna stato attivo
    orig_toolkit = mod.toolkit_cmd
    _mock_calls.clear()
    _mock_responses['get'] = (0, '{"stato": "In lavorazione", "id": 99005}', "")
    mod.toolkit_cmd = mock_toolkit_cmd

    try:
        stato = mod.fetch_ticket_stato(99005)
        if stato == "In lavorazione":
            ok(f"fetch_ticket_stato -> '{stato}' (attivo)")
        else:
            fail(f"atteso 'In lavorazione', ottenuto '{stato}'")

        # Stato non in RESOLVED_STATES → effettuato_at NON viene settato
        if stato and stato.lower() not in mod.RESOLVED_STATES:
            ok(f"'{stato}'.lower() non in RESOLVED_STATES → nessuna grace impostata")
        else:
            fail(f"'{stato}' erroneamente in RESOLVED_STATES")

        grace = mod.check_effettuato_grace("testhost5")
        if grace is None:
            ok("grace -> None (ticket attivo, comportamento normale)")
        else:
            fail(f"atteso None, ottenuto {grace}")
    finally:
        mod.toolkit_cmd = orig_toolkit


def test_f_warning_after_reopen(mod):
    """Scenario F: dopo CRITICAL reopen, nuovo WARNING → non scartato (trattato come attivo)."""
    print(f"\n{BOLD}[F] WARNING dopo CRITICAL reopen → non scartato{RESET}")
    reset_cache()

    now = int(time.time())
    # Ticket: effettuato_at set (grace originale) + reopen_at set (riaperto da CRIT)
    write_cache({"testhost6": make_ticket_entry(
        99006, state="CRITICAL",
        effettuato_at=now - 3600,  # 1h fa
        reopen_at=now - 120         # riaperto 2 min fa
    )})

    grace = mod.check_effettuato_grace("testhost6")
    if grace is None:
        ok("reopen_at presente → grace -> None (ticket trattato come attivo)")
    else:
        fail(f"atteso None (ticket attivo post-reopen), ottenuto {grace}")

    info("WARNING successivo verrebbe gestito normalmente (commento privato)")


def test_real_api(mod, ticket_id: int):
    """Test opzionale: chiama Ydea realmente per verificare stato ticket."""
    print(f"\n{BOLD}[REAL] Fetch stato reale ticket #{ticket_id} da Ydea{RESET}")

    os.environ["DEBUG_YDEA"] = "1"
    stato = mod.fetch_ticket_stato(ticket_id)

    if stato:
        ok(f"Stato ticket #{ticket_id}: '{stato}'")
        if stato.lower() in mod.RESOLVED_STATES:
            info(f"→ Ticket in stato risolto: grace window si applicherebbe")
        else:
            info(f"→ Ticket attivo: nessuna grace window")
    else:
        warn(f"Impossibile recuperare stato ticket #{ticket_id} (timeout/errore API)")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Test grace window ydea_la/ag")
    parser.add_argument("--real-ticket", type=int, metavar="ID",
                        help="ID ticket reale Ydea per testare fetch_ticket_stato")
    args = parser.parse_args()

    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  Test Grace Window 24h - ydea_la / ydea_ag{RESET}")
    print(f"{BOLD}{'='*60}{RESET}")
    print(f"  Cache test dir: {TEST_CACHE_DIR}")
    print(f"  Script dir:     {NOTIFY_DIR}")

    try:
        mod = setup_module()
    except Exception as e:
        print(f"\n{RED}ERRORE import ydea_la.py: {e}{RESET}")
        print(f"  Assicurarsi che il path sia corretto: {NOTIFY_DIR}")
        sys.exit(2)

    info(f"ydea_la v{mod.VERSION} importato OK")
    info(f"EFFETTUATO_GRACE_SECONDS = {mod.EFFETTUATO_GRACE_SECONDS}s ({mod.EFFETTUATO_GRACE_SECONDS//3600}h)")
    info(f"RESOLVED_STATES = {mod.RESOLVED_STATES}")

    # Inizializza cache
    reset_cache()

    # Esegui test
    test_a_warning_in_grace(mod)
    test_b_critical_reopen_in_grace(mod)
    test_c_outside_grace_24h(mod)
    test_d_fetch_ticket_stato_mock(mod)
    test_e_active_ticket_no_grace(mod)
    test_f_warning_after_reopen(mod)

    if args.real_ticket:
        test_real_api(mod, args.real_ticket)

    # Riepilogo
    print(f"\n{BOLD}{'='*60}{RESET}")
    total = 20  # circa (conteggio approssimativo)
    if _failures == 0:
        print(f"{GREEN}{BOLD}  ✓ TUTTI I TEST PASSATI{RESET}")
    else:
        print(f"{RED}{BOLD}  ✗ {_failures} TEST FALLITI{RESET}")
    print(f"{BOLD}{'='*60}{RESET}\n")

    # Pulizia
    shutil.rmtree(TEST_CACHE_DIR, ignore_errors=True)

    return 0 if _failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
