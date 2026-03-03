#!/usr/bin/env python3
"""
install_frpc_dryrun.py - Dry-run installazione FRPC.

Version: 1.0.0
"""

import os
import shutil
import subprocess
import sys

VERSION = "1.0.0"
FRP_VERSION = "0.64.0"
FRP_URL_DEFAULT = f"https://github.com/fatedier/frp/releases/download/v{FRP_VERSION}/frp_{FRP_VERSION}_linux_amd64.tar.gz"


def detect_os_type() -> str:
    os_release = "/etc/os-release"
    if not os.path.exists(os_release):
        return "altro"

    try:
        content = open(os_release, "r", encoding="utf-8", errors="ignore").read().lower()
    except Exception:
        return "altro"

    if "rocky" in content:
        return "rockylinux"
    if "nethserver" in content:
        return "nethserver"
    if "debian" in content:
        if shutil.which("dpkg"):
            res = subprocess.run(["bash", "-lc", "dpkg -l 2>/dev/null | grep -q pve-manager"], check=False)
            return "proxmox" if res.returncode == 0 else "debian"
        return "debian"
    return "altro"


def prompt(prompt_text: str, default: str = "") -> str:
    suffix = f" [default: {default}]" if default else ""
    value = input(f"{prompt_text}{suffix}: ").strip()
    return value or default


def main() -> int:
    print(f"install_frpc_dryrun.py v{VERSION}")

    os_type = detect_os_type()
    print(f"[DRYRUN] OS rilevato: {os_type}")

    frp_url = prompt("URL pacchetto FRP", FRP_URL_DEFAULT)
    hostname = prompt("Nome host (es: rl94ns8)")
    remote_port = prompt("Porta remota da usare")

    if not hostname or not remote_port:
        print("[DRYRUN][ERR] Parametri mancanti", file=sys.stderr)
        return 1

    print(f"[DRYRUN] Download: {frp_url}")
    print(f"[DRYRUN] Estraggo in: /usr/local/src/frp_{FRP_VERSION}_linux_amd64")
    print("[DRYRUN] Installo binario: /usr/local/bin/frpc")
    print("[DRYRUN] Scrivo config: /etc/frp/frpc.toml")
    print("[DRYRUN] Scrivo unita': /etc/systemd/system/frpc.service")
    print("[DRYRUN] Avvio: systemctl enable --now frpc")

    print(
        f"""

[DRYRUN] Esempio frpc.toml (token non incluso):
[common]
server_addr = "monitor.nethlab.it"
server_port = 7000
auth.method = "token"
auth.token  = "<INSERIRE_TOKEN>"
tls.enable  = true
log.to      = "/var/log/frpc.log"
log.level   = "info"

[{hostname}]
type        = "tcp"
local_ip    = "127.0.0.1"
local_port  = 6556
remote_port = {remote_port}
"""
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
