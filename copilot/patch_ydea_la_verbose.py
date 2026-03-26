#!/usr/bin/env python3
"""
patch_ydea_la_verbose.py - Rende i titoli/descrizioni ticket Ydea più verbosi.

Modifiche applicate a ydea_la:
  1. detect_alert_type: aggiunge rilevamento SNMP_ERROR
  2. get_alert_label: aggiunge label "SNMP Error"
  3. Titolo ticket: include IP + estratto output (visibile in Telegram)
  4. generate_smart_description: aggiunge blocco diagnostica suggerita

Uso (su srv-monitoring-sp come root):
  python3 patch_ydea_la_verbose.py

Version: 1.0.0
"""

import os
import sys
import shutil
from datetime import datetime

NOTIFY_SCRIPT = "/omd/sites/monitoring/local/share/check_mk/notifications/ydea_la"


def backup(path):
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    bak = f"{path}.backup_{ts}"
    shutil.copy2(path, bak)
    os.system(f"chown monitoring:monitoring {bak} && chmod 640 {bak}")
    print(f"[BACKUP] {bak}")
    return bak


def patch(content: str) -> str:
    changes = 0

    # -------------------------------------------------------------------------
    # 1. detect_alert_type: SNMP_ERROR prima del check timeout generico
    # -------------------------------------------------------------------------
    OLD_1 = "    # Timeout\n    if 'timeout' in output_lower or 'timed out' in output_lower or 'no route' in\n output_lower:"
    NEW_1 = "    # SNMP error (priorità rispetto a generic timeout)\n    if 'snmp' in output_lower and ('timeout' in output_lower or 'error' in output_lower or 'exit-code' in output_lower):\n        return \"SNMP_ERROR\"\n\n    # Timeout\n    if 'timeout' in output_lower or 'timed out' in output_lower or 'no route' in\n output_lower:"
    if OLD_1 in content:
        content = content.replace(OLD_1, NEW_1, 1)
        changes += 1
        print("[OK] 1. detect_alert_type: aggiunto SNMP_ERROR")
    else:
        # Prova versione alternativa (senza line wrap)
        OLD_1b = "    # Timeout\n    if 'timeout' in output_lower or 'timed out' in output_lower or 'no route' in output_lower:"
        NEW_1b = "    # SNMP error (priorità rispetto a generic timeout)\n    if 'snmp' in output_lower and ('timeout' in output_lower or 'error' in output_lower or 'exit-code' in output_lower):\n        return \"SNMP_ERROR\"\n\n    # Timeout\n    if 'timeout' in output_lower or 'timed out' in output_lower or 'no route' in output_lower:"
        if OLD_1b in content:
            content = content.replace(OLD_1b, NEW_1b, 1)
            changes += 1
            print("[OK] 1b. detect_alert_type: aggiunto SNMP_ERROR (alt format)")
        else:
            print("[WARN] 1. detect_alert_type: pattern non trovato, skip")

    # -------------------------------------------------------------------------
    # 2. get_alert_label: aggiungere SNMP_ERROR label
    # -------------------------------------------------------------------------
    OLD_2 = '        "UNKNOWN": "Alert"\n    }'
    NEW_2 = '        "UNKNOWN": "Alert",\n        "SNMP_ERROR": "SNMP Error",\n    }'
    if OLD_2 in content:
        content = content.replace(OLD_2, NEW_2, 1)
        changes += 1
        print("[OK] 2. get_alert_label: aggiunto SNMP_ERROR")
    else:
        print("[WARN] 2. get_alert_label: pattern non trovato, skip")

    # -------------------------------------------------------------------------
    # 3. generate_smart_description: aggiungere titolo SNMP + diagnostica
    # -------------------------------------------------------------------------
    OLD_3 = '        "HOST_OFFLINE_REFUSED": "*** ALERT - CONNESSIONE RIFIUTATA ***",        \n        "HOST_OFFLINE_NETWORK": "*** ALERT - NETWORK UNREACHABLE ***",\n        "HOST_OFFLINE_TIMEOUT": "*** ALERT - HOST TIMEOUT ***",\n        "HOST_NODATA":          "*** ALERT - DATI DI MONITORAGGIO MANCANTI ***",\n    }'
    NEW_3 = '        "HOST_OFFLINE_REFUSED": "*** ALERT - CONNESSIONE RIFIUTATA ***",        \n        "HOST_OFFLINE_NETWORK": "*** ALERT - NETWORK UNREACHABLE ***",\n        "HOST_OFFLINE_TIMEOUT": "*** ALERT - HOST TIMEOUT ***",\n        "HOST_NODATA":          "*** ALERT - DATI DI MONITORAGGIO MANCANTI ***",\n        "SNMP_ERROR":           "*** ALERT - SNMP ERROR ***",\n    }'
    if OLD_3 in content:
        content = content.replace(OLD_3, NEW_3, 1)
        changes += 1
        print("[OK] 3. generate_smart_description: aggiunto SNMP_ERROR title line")
    else:
        # Prova senza trailing spaces
        OLD_3b = '        "HOST_OFFLINE_REFUSED": "*** ALERT - CONNESSIONE RIFIUTATA ***",\n        "HOST_OFFLINE_NETWORK": "*** ALERT - NETWORK UNREACHABLE ***",\n        "HOST_OFFLINE_TIMEOUT": "*** ALERT - HOST TIMEOUT ***",\n        "HOST_NODATA":          "*** ALERT - DATI DI MONITORAGGIO MANCANTI ***",\n    }'
        NEW_3b = '        "HOST_OFFLINE_REFUSED": "*** ALERT - CONNESSIONE RIFIUTATA ***",\n        "HOST_OFFLINE_NETWORK": "*** ALERT - NETWORK UNREACHABLE ***",\n        "HOST_OFFLINE_TIMEOUT": "*** ALERT - HOST TIMEOUT ***",\n        "HOST_NODATA":          "*** ALERT - DATI DI MONITORAGGIO MANCANTI ***",\n        "SNMP_ERROR":           "*** ALERT - SNMP ERROR ***",\n    }'
        if OLD_3b in content:
            content = content.replace(OLD_3b, NEW_3b, 1)
            changes += 1
            print("[OK] 3b. generate_smart_description: aggiunto SNMP_ERROR (alt)")
        else:
            print("[WARN] 3. generate_smart_description titles: pattern non trovato, skip")

    # -------------------------------------------------------------------------
    # 4. generate_smart_description: aggiungere diagnostica dopo output_block
    # -------------------------------------------------------------------------
    OLD_4 = '    return f"""{title_line}\n\nHost: {hostname} ({ip})\nServizio: {service}\nStato: {state}\n{output_block}\n\n[CMK HOST={hostname} IP={ip}]"""'
    NEW_4 = '''    # Diagnostica suggerita per tipo di alert
    DIAG = {
        "SNMP_ERROR":           f"• Ping: ping {ip}\\n• Porta UDP 161 aperta? (snmpwalk -v2c -c public {ip} .1.3.6.1.2.1.1.1.0)\\n• Verificare community string SNMP",
        "HOST_OFFLINE_TIMEOUT": f"• Ping: ping {ip}\\n• Verificare routing/firewall verso {ip}",
        "HOST_OFFLINE_REFUSED": f"• Ping: ping {ip}\\n• Servizio in ascolto sulla porta? (netstat / ss)\\n• Verificare firewall locale",
        "HOST_OFFLINE_NETWORK": f"• Route verso {ip}: ip route get {ip}\\n• Verificare gateway/VLAN",
        "HOST_NODATA":          f"• Eseguire: cmk --check {hostname}\\n• Verificare agent su porta 6556\\n• Controllare piggyback data",
    }
    diag_block = ""
    if alert_type in DIAG:
        diag_block = f"\\n--- DIAGNOSTICA ---\\n{DIAG[alert_type]}"

    return f"""{title_line}

Host: {hostname} ({ip})
Servizio: {service}
Stato: {state}
{output_block}{diag_block}

[CMK HOST={hostname} IP={ip}]"""'''
    if OLD_4 in content:
        content = content.replace(OLD_4, NEW_4, 1)
        changes += 1
        print("[OK] 4. generate_smart_description: aggiunta diagnostica")
    else:
        print("[WARN] 4. generate_smart_description return: pattern non trovato, skip")

    # -------------------------------------------------------------------------
    # 5a. Titolo ticket: PRIMO blocco creazione (nuovo ticket CRIT/DOWN)
    # -------------------------------------------------------------------------
    # Il pattern è ripetuto due volte (creazione normale + dopo 404)
    TITLE_OLD = ('        title = f"[{state} - {alert_label}] {hostname}"\n'
                 '        if what == "SERVICE":\n'
                 '            title += f" - {service}"\n')
    TITLE_NEW = ('        _out = re.sub(r\'^\\\\[(?:snmp|agent|piggyback)\\\\]\\\\s*\', \'\', output or \'\').strip()\n'
                 '        _short = (_out[:58] + "\\u2026") if len(_out) > 58 else _out\n'
                 '        _svc = service if what == "SERVICE" else "HOST"\n'
                 '        title = f"[{state} - {alert_label}] {hostname} ({real_ip}) - {_svc}"\n'
                 '        if _short and _short.lower() not in ("n/a", ""):\n'
                 '            title += f": {_short}"\n')
    count_old = content.count(TITLE_OLD)
    if count_old >= 1:
        content = content.replace(TITLE_OLD, TITLE_NEW)
        changes += count_old
        print(f"[OK] 5. Titolo ticket: sostituito {count_old} occorrenza/e (IP + output)")
    else:
        print("[WARN] 5. Titolo ticket: pattern non trovato, skip")

    print(f"\nTotale modifiche applicate: {changes}")
    return content


def main():
    if not os.path.exists(NOTIFY_SCRIPT):
        print(f"ERRORE: {NOTIFY_SCRIPT} non trovato")
        sys.exit(1)

    with open(NOTIFY_SCRIPT, 'r') as f:
        original = f.read()

    bak = backup(NOTIFY_SCRIPT)

    patched = patch(original)

    if patched == original:
        print("\nNessuna modifica applicata - file invariato")
        sys.exit(0)

    # Valida sintassi Python
    import py_compile, tempfile
    tmp = tempfile.mktemp(suffix='.py')
    with open(tmp, 'w') as f:
        f.write(patched)
    try:
        py_compile.compile(tmp, doraise=True)
        print("[OK] Sintassi Python valida")
    except py_compile.PyCompileError as e:
        print(f"ERRORE sintassi: {e}")
        print("File NON modificato, backup disponibile in:", bak)
        os.unlink(tmp)
        sys.exit(1)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

    with open(NOTIFY_SCRIPT, 'w') as f:
        f.write(patched)
    os.system(f"chown monitoring:monitoring {NOTIFY_SCRIPT} && chmod 755 {NOTIFY_SCRIPT}")
    print(f"\n[OK] {NOTIFY_SCRIPT} aggiornato con successo")


if __name__ == "__main__":
    main()
