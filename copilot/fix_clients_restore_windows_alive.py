#!/usr/bin/env python3
"""
fix_clients_restore_windows_alive.py

Fix completo per i client Windows senza agent CheckMK:

1. Rimuove il blocco host_check_commands dalla regola GLOBALE (rules.mk)
   che usa check_host_status (porta 6556 = CMK agent, sbagliato per client)

2. Ripristina in clients/rules.mk:
   - host_check_commands → check_windows_alive (ARP/nmap, originale 14 marzo)
   - Host Connectivity service → check_windows_alive (originale 14 marzo)

3. cmk -U + cmk -R

Motivazione: check_host_status --type generic testa porta 6556 (CMK agent).
I client Windows non hanno agent → penalità enorme → tutti CRIT.
check_windows_alive usa solo ARP nmap: se il client è acceso sulla LAN → OK.
"""

import os
import re
import subprocess
import datetime
import shutil

WATO_BASE = "/omd/sites/monitoring/etc/check_mk/conf.d/wato"
GLOBAL_RULES = f"{WATO_BASE}/rules.mk"
CLIENTS_RULES = f"{WATO_BASE}/clients/rules.mk"

def backup(path):
    ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    bak = path + f".backup_{ts}"
    shutil.copy2(path, bak)
    os.system(f"chown monitoring:monitoring '{bak}'")
    os.system(f"chmod 660 '{bak}'")
    print(f"  Backup: {bak}")
    return bak

def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()

def remove_host_check_commands_block(content, label=""):
    """Rimuove il blocco globals().setdefault('host_check_commands'...) + host_check_commands = [...] + host_check_commands"""
    if "host_check_commands" not in content:
        print(f"  {label}: host_check_commands non presente - nulla da fare")
        return content, False

    lines = content.split("\n")
    result_lines = []
    skip = False
    removed = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        # Inizio blocco
        if not skip and "globals().setdefault('host_check_commands'" in line:
            skip = True
            removed += 1
            i += 1
            continue
        if not skip and re.match(r'^host_check_commands\s*=\s*\[', line):
            skip = True
            removed += 1
            i += 1
            continue
        if skip:
            removed += 1
            # Fine blocco: "] + host_check_commands"
            if re.search(r'\]\s*\+\s*host_check_commands', line):
                skip = False
                # Salta riga vuota successiva se presente
                if i + 1 < len(lines) and lines[i + 1].strip() == "":
                    i += 2
                    removed += 1
                    continue
            i += 1
            continue
        result_lines.append(line)
        i += 1

    new_content = "\n".join(result_lines)
    if "host_check_commands" in new_content:
        print(f"  WARN: host_check_commands ancora presente dopo rimozione!")
        return content, False

    print(f"  {label}: rimosso blocco host_check_commands ({removed} righe)")
    return new_content, True

def main():
    print("=" * 65)
    print("fix_clients_restore_windows_alive.py")
    print("=" * 65)

    # ── 1. REGOLA GLOBALE: rimuovi host_check_commands da rules.mk ──
    print(f"\n[1] Rimozione host_check_commands da regola globale ({GLOBAL_RULES})")
    with open(GLOBAL_RULES, "r") as f:
        global_content = f.read()

    backup(GLOBAL_RULES)
    new_global, changed = remove_host_check_commands_block(global_content, "rules.mk")
    if changed:
        with open(GLOBAL_RULES, "w") as f:
            f.write(new_global)
        os.system(f"chown monitoring:monitoring '{GLOBAL_RULES}'")
        os.system(f"chmod 660 '{GLOBAL_RULES}'")
        print(f"  rules.mk aggiornato")
    else:
        print(f"  rules.mk: nessuna modifica necessaria")

    # ── 2. CLIENTS/rules.mk: ripristina check_windows_alive ──
    print(f"\n[2] Ripristino clients/rules.mk ({CLIENTS_RULES})")
    with open(CLIENTS_RULES, "r") as f:
        clients_content = f.read()

    backup(CLIENTS_RULES)

    # 2a. Fix Host Connectivity service: check_host_status → check_windows_alive
    if "check_host_status" in clients_content:
        old_svc = "'command_line': 'check_host_status -H $HOSTADDRESS$ --type generic'"
        new_svc = "'command_line': 'check_windows_alive -H $HOSTADDRESS$'"
        clients_content = clients_content.replace(old_svc, new_svc)
        # Aggiorna anche la descrizione se presente
        clients_content = clients_content.replace(
            "'description': 'ARP check via nmap - sostituisce PING inutile'",
            "'description': 'ARP check via nmap (check_windows_alive) - sostituisce PING inutile'"
        )
        if "check_windows_alive" in clients_content and "check_host_status" not in clients_content:
            print(f"  Host Connectivity service: ripristinato check_windows_alive ✓")
        else:
            print(f"  WARN: sostituizione parziale, verificare manualmente")
    else:
        print(f"  Host Connectivity service: già usa check_windows_alive - nulla da fare")

    # 2b. Aggiungi host_check_commands per clients (se non presente)
    if "host_check_commands" not in clients_content:
        host_check_block = """
globals().setdefault('host_check_commands', [])

host_check_commands = [
{'id': '6fbea873-8f11-4a8d-b3cc-254d203ccca9', 'value': ('custom', 'check_windows_alive -H $HOSTADDRESS$'), 'condition': {'host_folder': '/%s/' % FOLDER_PATH}, 'options': {'disabled': False, 'description': 'Windows workstations ARP check via nmap'}},
] + host_check_commands

"""
        # Inserisce prima di ignored_services (o in fondo)
        if "ignored_services" in clients_content:
            clients_content = clients_content.replace(
                "globals().setdefault('ignored_services', [])",
                host_check_block + "globals().setdefault('ignored_services', [])"
            )
        else:
            clients_content = clients_content.rstrip() + "\n" + host_check_block

        print(f"  host_check_commands: aggiunto con check_windows_alive ✓")
    else:
        # Già presente, assicurati che usi check_windows_alive
        if "check_windows_alive" in clients_content:
            print(f"  host_check_commands: già presente con check_windows_alive ✓")
        else:
            print(f"  WARN: host_check_commands presente ma non usa check_windows_alive")

    # Scrivi clients/rules.mk aggiornato
    with open(CLIENTS_RULES, "w") as f:
        f.write(clients_content)
    os.system(f"chown monitoring:monitoring '{CLIENTS_RULES}'")
    os.system(f"chmod 660 '{CLIENTS_RULES}'")
    print(f"  clients/rules.mk scritto")

    # ── 3. Mostra stato finale ──
    print(f"\n[3] Verifica stato finale:")
    print(f"  rules.mk - host_check_commands: {'ASSENTE ✓' if 'host_check_commands' not in new_global else 'PRESENTE (errore!)'}")
    with open(CLIENTS_RULES) as f:
        cc = f.read()
    print(f"  clients/rules.mk - check_windows_alive: {'OK ✓' if 'check_windows_alive' in cc else 'ASSENTE (errore!)'}")
    print(f"  clients/rules.mk - check_host_status: {'ASSENTE ✓' if 'check_host_status' not in cc else 'ANCORA PRESENTE (controllare)'}")

    # ── 4. cmk -U + cmk -R ──
    print(f"\n[4] cmk -U (update config)...")
    rc, out, err = run("su - monitoring -c 'cmk -U 2>&1'")
    print(f"  RC={rc}" + (f" - {out[:200]}" if out else ""))
    if rc != 0 and err:
        print(f"  ERR: {err[:200]}")

    print(f"\n[5] cmk -R (reload core)...")
    rc, out, err = run("su - monitoring -c 'cmk -R 2>&1'")
    print(f"  RC={rc}" + (f" - {out[:200]}" if out else ""))

    print("\n" + "=" * 65)
    print("COMPLETATO")
    print("  - Regola globale check_host_status: RIMOSSA")
    print("  - clients host_check_commands: check_windows_alive (ARP)")
    print("  - Host Connectivity service: check_windows_alive (ARP)")
    print("  Attendi 2-5 minuti per i re-check dei client.")
    print("=" * 65)
    return 0

if __name__ == "__main__":
    exit(main())
