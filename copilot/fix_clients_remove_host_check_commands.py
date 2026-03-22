#!/usr/bin/env python3
"""
fix_clients_remove_host_check_commands.py

Rimuove il blocco host_check_commands da clients/rules.mk
Lascia attivo solo il servizio "Host Connectivity" via custom_checks.

Operazioni:
1. Backup del file con permessi monitoring:monitoring 660
2. Rimozione blocco host_check_commands (~7 righe)
3. cmk -U + cmk -R
"""

import os
import re
import subprocess
import datetime
import shutil

RULES_FILE = "/omd/sites/monitoring/etc/check_mk/conf.d/wato/clients/rules.mk"

def run(cmd, env=None):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, env=env)
    return result.returncode, result.stdout.strip(), result.stderr.strip()

def main():
    print("=" * 60)
    print("fix_clients_remove_host_check_commands.py")
    print("=" * 60)

    # 1. Leggi file originale
    if not os.path.exists(RULES_FILE):
        print(f"ERRORE: File non trovato: {RULES_FILE}")
        return 1

    with open(RULES_FILE, "r") as f:
        content = f.read()

    print(f"File letto: {RULES_FILE} ({len(content)} chars)")

    # Verifica che il blocco esista
    if "host_check_commands" not in content:
        print("INFO: Blocco host_check_commands non trovato - nulla da fare.")
        return 0

    # 2. Backup
    ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_path = RULES_FILE + f".backup_{ts}"
    shutil.copy2(RULES_FILE, backup_path)
    os.system(f"chown monitoring:monitoring '{backup_path}'")
    os.system(f"chmod 660 '{backup_path}'")
    print(f"Backup creato: {backup_path}")
    print(f"  permessi: monitoring:monitoring 660")

    # 3. Rimuovi il blocco host_check_commands
    # Il blocco è composto da:
    #   globals().setdefault('host_check_commands', [])
    #   host_check_commands = [
    #   ...
    #   ] + host_check_commands
    # Usiamo regex per trovare e rimuovere il blocco completo

    # Pattern: from setdefault('host_check_commands'...) to ] + host_check_commands (con trailing newline)
    pattern = r"globals\(\)\.setdefault\('host_check_commands',\s*\[\]\)\s*\n" \
              r"host_check_commands\s*=\s*\[.*?\]\s*\+\s*host_check_commands\s*\n?"

    new_content = re.sub(pattern, "", content, flags=re.DOTALL)

    if new_content == content:
        # Prova pattern più semplice riga per riga
        lines = content.split("\n")
        result_lines = []
        skip = False
        i = 0
        while i < len(lines):
            line = lines[i]
            if "globals().setdefault('host_check_commands'" in line:
                skip = True
            if skip:
                if line.strip().endswith("] + host_check_commands") or line.strip() == "] + host_check_commands":
                    skip = False
                    # Salta anche la riga vuota successiva se presente
                    if i + 1 < len(lines) and lines[i + 1].strip() == "":
                        i += 2
                        continue
                    i += 1
                    continue
                if "host_check_commands =" in line and "globals" not in line and not skip:
                    skip = True
                i += 1
                continue
            result_lines.append(line)
            i += 1
        new_content = "\n".join(result_lines)

    # Verifica rimozione
    if "host_check_commands" in new_content:
        print("ERRORE: Rimozione fallita - host_check_commands ancora presente!")
        # Mostra contesto per debug
        for i, line in enumerate(new_content.split("\n")):
            if "host_check_commands" in line:
                print(f"  Linea {i+1}: {line}")
        return 1

    print(f"Blocco host_check_commands rimosso")
    print(f"  Dimensione prima: {len(content)} chars")
    print(f"  Dimensione dopo:  {len(new_content)} chars")
    print(f"  Righe rimosse: {len(content.split(chr(10))) - len(new_content.split(chr(10)))}")

    # 4. Scrivi file aggiornato
    with open(RULES_FILE, "w") as f:
        f.write(new_content)

    os.system(f"chown monitoring:monitoring '{RULES_FILE}'")
    os.system(f"chmod 660 '{RULES_FILE}'")
    print(f"File aggiornato e permessi impostati: monitoring:monitoring 660")

    # 5. Verifica contenuto finale (mostra righe con check_host_status rimaste)
    print("\nRighe con check_host_status rimaste (dovrebbe esserci solo Host Connectivity):")
    for i, line in enumerate(new_content.split("\n")):
        if "check_host_status" in line:
            print(f"  L{i+1}: {line.strip()}")

    # 6. cmk -U (update config)
    print("\nEseguo: su - monitoring -c 'cmk -U'")
    rc, out, err = run("su - monitoring -c 'cmk -U 2>&1'")
    print(f"  RC={rc}")
    if out:
        print(f"  STDOUT: {out[:500]}")
    if err:
        print(f"  STDERR: {err[:200]}")

    # 7. cmk -R (reload core)
    print("\nEseguo: su - monitoring -c 'cmk -R'")
    rc, out, err = run("su - monitoring -c 'cmk -R 2>&1'")
    print(f"  RC={rc}")
    if out:
        print(f"  STDOUT: {out[:300]}")
    if err:
        print(f"  STDERR: {err[:200]}")

    print("\n" + "=" * 60)
    print("COMPLETATO - host_check_commands rimosso da clients/rules.mk")
    print("Solo 'Host Connectivity' (custom_checks) rimane attivo.")
    print("=" * 60)
    return 0

if __name__ == "__main__":
    exit(main())
