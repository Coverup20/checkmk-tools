#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Prompt Compiler
- Incolli un testo grezzo
- Auto-detect Template 1 (decisione) o Template 3 (script) oppure scegli tu
- Chiede i campi mancanti in modo minimale
- Stampa un prompt "finale" pronto da incollare in ChatGPT

Uso:
  python3 prompt_compiler.py
  python3 prompt_compiler.py --choose 3
  python3 prompt_compiler.py --auto
"""

import argparse
import re
import sys
from textwrap import dedent

TEMPLATE_1 = dedent("""\
RUOLO DELL’AI:
Agisci come sysadmin senior / SRE.
Niente spiegazioni didattiche, solo decisioni motivate.

CONTESTO TECNICO:
- Sistema operativo: {os}
- Software / versioni: {software_versions}
- Ambiente (prod / lab): {env}
- Vincoli reali (licenza, tempo, spazio, policy): {constraints}
- Cosa è GIÀ configurato e funzionante: {already_done}

PROBLEMA / ESIGENZA:
{problem}

OBIETTIVO FINALE:
{goal}

VINCOLI DI RISPOSTA (OBBLIGATORI):
- Output completo, niente parziali
- Niente alternative teoriche
- Se mancano dati → fai assunzioni e dichiarale
- Se qualcosa NON è possibile, dillo chiaramente
- Evita frasi tipo “potresti / sarebbe meglio”

FORMAT OUTPUT:
- Decisione: scelta + motivazione tecnica + trade-off
- Piano: step numerati riproducibili
""")

TEMPLATE_3 = dedent("""\
CONTESTO:
- OS + versione: {os}
- Shell: {shell}
- Utente di esecuzione: {user}
- Software coinvolti + percorsi assoluti: {software_paths}
- Ambiente (prod / lab): {env}

OBIETTIVO:
- Script UNICO
- Idempotente
- Pronto produzione

REQUISITI FUNZIONALI:
- Deve fare:
{must_do_list}

REQUISITI TECNICI:
- {tech_reqs}

VINCOLI:
- Nessun pseudo-codice
- Nessuna funzione “placeholder”
- Nessuna dipendenza non dichiarata
- Compatibile con Checkmk CRE (se rilevante)

GESTIONE ERRORI:
- Fail fast
- Messaggi espliciti
- Exit code significativi

OUTPUT ATTESO:
- Script completo, incollabile, senza spiegazioni extra
""")

DEFAULT_TECH_REQS = "Bash, set -euo pipefail, logging chiaro, controlli di precondizione, idempotenza"
DEFAULT_SHELL = "bash"
DEFAULT_USER = "root"
DEFAULT_ENV = "prod"


def ask(prompt: str, default: str | None = None) -> str:
    if default:
        p = f"{prompt} [{default}]: "
    else:
        p = f"{prompt}: "
    ans = input(p).strip()
    return ans if ans else (default or "")


def multiline_input(title: str) -> str:
    print(f"\n{title} (termina con una riga contenente solo 'EOF'):")
    lines = []
    while True:
        line = input()
        if line.strip() == "EOF":
            break
        lines.append(line)
    return "\n".join(lines).strip()


def detect_template(free_text: str) -> int:
    """
    Heuristics:
    - Template 3 (script) if mentions script/bash/systemd/unit/crontab/command/etc
    - Template 1 (decision) if mentions scelta/architettura/valutare/opzioni/pro&contro/etc
    """
    t = free_text.lower()

    script_hits = [
        "script", "bash", "python", "systemd", "unit", "service", "timer", "crontab",
        "comando", "cmd", "log", "exit code", "idempotente", "deploy", "automation",
        "rclone", "backup", "restore"
    ]
    decision_hits = [
        "architettura", "design", "scelta", "valutare", "opzioni", "pro e contro",
        "trade-off", "strategia", "approccio", "migliore", "limiti", "roadmap"
    ]

    s = sum(1 for k in script_hits if k in t)
    d = sum(1 for k in decision_hits if k in t)

    # Se c'è "script" esplicito, spingi su 3
    if "script" in t or "bash" in t or "systemd" in t:
        return 3
    if d > s:
        return 1
    return 3  # default: nel tuo caso è quasi sempre script


def extract_must_do_list(free_text: str) -> list[str]:
    """
    Prova a estrarre punti numerati o bullet dal testo grezzo.
    """
    lines = [ln.strip() for ln in free_text.splitlines() if ln.strip()]
    items = []
    for ln in lines:
        if re.match(r"^(\d+[\.\)]|\-|\*|\•)\s+", ln):
            items.append(re.sub(r"^(\d+[\.\)]|\-|\*|\•)\s+", "", ln).strip())
    # fallback: se niente, ritorna vuoto
    return items


def format_must_do(items: list[str]) -> str:
    if not items:
        return "  1. (da definire)\n  2. (da definire)\n  3. (da definire)"
    out = []
    for i, it in enumerate(items, 1):
        out.append(f"  {i}. {it}")
    return "\n".join(out)


def compile_template_3(free_text: str) -> str:
    print("\n== COMPILAZIONE TEMPLATE 3 (SCRIPT) ==")

    os_ = ask("OS + versione", "")
    if not os_:
        os_ = ask("OS + versione (obbligatorio)", "Ubuntu 22.04")

    env = ask("Ambiente (prod/lab)", DEFAULT_ENV) or DEFAULT_ENV
    shell = ask("Shell", DEFAULT_SHELL) or DEFAULT_SHELL
    user = ask("Utente di esecuzione", DEFAULT_USER) or DEFAULT_USER

    software_paths = ask("Software + percorsi assoluti (es: checkmk site path, rclone path)", "")
    if not software_paths:
        software_paths = ask("Software + percorsi assoluti (obbligatorio)", "/opt/omd/sites/<site>, rclone: /usr/bin/rclone")

    # requisiti funzionali
    extracted = extract_must_do_list(free_text)
    if extracted:
        print("\nHo trovato possibili requisiti funzionali nel testo:")
        for i, it in enumerate(extracted, 1):
            print(f"  {i}. {it}")
        use = ask("Li uso così? (y/n)", "y").lower()
        if use != "y":
            extracted = []
    if not extracted:
        raw = multiline_input("Inserisci requisiti funzionali (uno per riga o elenco numerato)")
        extracted = extract_must_do_list(raw) or [ln.strip("-*• ").strip() for ln in raw.splitlines() if ln.strip()]

    tech_reqs = ask("Requisiti tecnici", DEFAULT_TECH_REQS) or DEFAULT_TECH_REQS

    must_do_list = format_must_do(extracted)

    return TEMPLATE_3.format(
        os=os_,
        shell=shell,
        user=user,
        software_paths=software_paths,
        env=env,
        must_do_list=must_do_list,
        tech_reqs=tech_reqs,
    )


def compile_template_1(free_text: str) -> str:
    print("\n== COMPILAZIONE TEMPLATE 1 (DECISIONE/ARCHITETTURA) ==")

    os_ = ask("Sistema operativo", "Ubuntu 22.04")
    software_versions = ask("Software/versioni principali", "Checkmk CRE, rclone")
    env = ask("Ambiente (prod/lab)", DEFAULT_ENV) or DEFAULT_ENV
    constraints = ask("Vincoli reali (costi/licenze/spazio/policy)", "")
    already_done = ask("Cosa è già fatto e funzionante", "")

    if not free_text.strip():
        problem = multiline_input("Descrivi PROBLEMA/ESIGENZA")
    else:
        problem = free_text.strip()

    goal = ask("Obiettivo finale (decisione attesa, cosa vuoi ottenere)", "")

    if not constraints:
        constraints = "N/A"
    if not already_done:
        already_done = "N/A"
    if not goal:
        goal = "Definire una scelta operativa con trade-off e step riproducibili"

    return TEMPLATE_1.format(
        os=os_,
        software_versions=software_versions,
        env=env,
        constraints=constraints,
        already_done=already_done,
        problem=problem,
        goal=goal,
    )


def main():
    parser = argparse.ArgumentParser(description="Prompt template compiler")
    parser.add_argument("--auto", action="store_true", help="Auto-detect template (default)")
    parser.add_argument("--choose", choices=["1", "3"], help="Force template 1 or 3")
    args = parser.parse_args()

    print("Incolla il testo grezzo (termina con una riga 'EOF'):")
    free_text = multiline_input("TESTO GREZZO")

    if args.choose:
        template = int(args.choose)
    else:
        template = detect_template(free_text) if (args.auto or True) else 3

    if template == 1:
        final_prompt = compile_template_1(free_text)
    else:
        final_prompt = compile_template_3(free_text)

    print("\n" + "=" * 80)
    print("PROMPT FINALE (copia/incolla in ChatGPT):")
    print("=" * 80 + "\n")
    print(final_prompt.strip() + "\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrotto.")
        sys.exit(1)
