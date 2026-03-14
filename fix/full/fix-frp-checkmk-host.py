#!/usr/bin/env python3
"""
fix-frp-checkmk-host.py - Configura host CheckMK che usa FRP proxy

Verifica e mostra le istruzioni per configurare un host CheckMK
con tunnel FRP (connessione tramite localhost:PORT invece di IP:6556).

Version: 1.0.0
"""

import argparse
import shutil
import subprocess
import sys

VERSION = "1.0.0"


def run_capture(cmd: list) -> str:
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    return result.stdout or ""


def check_frp_port(port: int) -> bool:
    for tool in ("netstat", "ss"):
        if not shutil.which(tool):
            continue
        out = run_capture([tool, "-tlnp"])
        if f":{port}" in out:
            print(out)
            return True
    return False


def test_frp_connection(port: int) -> None:
    import socket
    try:
        with socket.create_connection(("localhost", port), timeout=3) as s:
            s.sendall(b"<<<check_mk>>>\n")
            data = s.recv(256)
            if data:
                print(data[:256].decode("utf-8", errors="replace"))
                print("\n[OK] FRP funziona correttamente!")
            else:
                print("[WARN] Connessione OK ma nessun dato ricevuto")
    except (ConnectionRefusedError, TimeoutError, OSError) as exc:
        print(f"[WARN] Connessione fallita: {exc}")


def print_gui_instructions(host: str, frp_port: int) -> None:
    print(f"""
=== ISTRUZIONI PER LA GUI DI CHECKMK ===

1. Vai su: Setup → Hosts → Hosts
2. Cerca e clicca su: {host}
3. Nella sezione 'Monitoring agents':
   - API integrations and monitoring agents: CheckMK agent
   - CheckMK agent connection mode: Direct connection

4. Espandi 'Connection Settings' e configura:
   ┌─────────────────────────────────────────┐
   │ Host name:  127.0.0.1                   │
   │ Port:       {frp_port:<5}                       │
   │                                         │
   │ [ ] Use encryption                      │
   │ [ ] Disable TLS certificate validation  │
   └─────────────────────────────────────────┘

5. Salva e vai su 'Activate changes'
""")


def print_rest_api_alternative(host: str, site: str) -> None:
    print(f"""
=== ALTERNATIVA: Configurazione tramite REST API ===

curl -X PUT \\
  "http://localhost/{site}/check_mk/api/1.0/objects/host_config/{host}" \\
  -H "Authorization: Bearer USER PASSWORD" \\
  -H "Content-Type: application/json" \\
  -d '{{
    "attributes": {{
      "ipaddress": "127.0.0.1"
    }},
    "update_attributes": {{
      "ipaddress": "127.0.0.1"
    }}
  }}'
""")


def print_post_config_test(host: str, site: str) -> None:
    print(f"""
=== TEST DOPO LA CONFIGURAZIONE ===

Dopo aver salvato:

  su - {site} -c 'cmk -d {host}'
  # → Deve mostrare output dell'agent

  su - {site} -c 'cmk -IIv {host}'
  # → Service discovery
""")


def main() -> int:
    p = argparse.ArgumentParser(
        description=f"fix-frp-checkmk-host.py v{VERSION} - Configura host CheckMK con FRP proxy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esempi:
  python3 fix-frp-checkmk-host.py
  python3 fix-frp-checkmk-host.py --host MioHost --port 20001
  python3 fix-frp-checkmk-host.py --host WS2022AD --site monitoring
        """,
    )
    p.add_argument("--host", default="WS2022AD", help="Nome host CheckMK (default: WS2022AD)")
    p.add_argument("--port", type=int, default=6045, help="Porta FRP remota (default: 6045)")
    p.add_argument("--site", default="monitoring", help="Nome site OMD (default: monitoring)")
    p.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = p.parse_args()

    print(f"=== Configurazione Host CheckMK con FRP Proxy ===")
    print(f"")
    print(f"Host: {args.host}")
    print(f"Proxy FRP: localhost:{args.port}")
    print(f"")

    # 1. Configurazione attuale
    print("1. Configurazione attuale dell'host...")
    print()
    if shutil.which("su"):
        out = run_capture(["su", "-", args.site, "-c", f"cmk -d {args.host}"])
        for line in out.splitlines()[:20]:
            print(f"   {line}")
    else:
        print("   [INFO] Comando 'su' non disponibile su questo sistema")
    print()

    # 2. Istruzioni GUI
    print_gui_instructions(args.host, args.port)

    # 3. REST API alternativa
    print_rest_api_alternative(args.host, args.site)

    # 4. Test post-configurazione
    print_post_config_test(args.host, args.site)

    # 5. Verifica FRP in ascolto
    print(f"=== VERIFICA FRP PROXY ===")
    print()
    print(f"Verifico che FRP sia in ascolto sulla porta {args.port}...")
    if not check_frp_port(args.port):
        print(f"[WARN] Nessun processo in ascolto su :{args.port}")
    print()

    # 6. Test diretto alla porta FRP
    print(f"Test connessione diretta a localhost:{args.port}...")
    test_frp_connection(args.port)
    print()
    print("Se vedi output dall'agent, FRP funziona correttamente!")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
