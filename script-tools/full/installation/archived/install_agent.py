#!/usr/bin/env python3
"""
install_agent.py - CheckMK Agent Installer

Installazione interattiva Checkmk Agent + FRPC.
Supporta:
- Debian/Ubuntu (.deb)
- RHEL/CentOS/Rocky (.rpm)
- OpenWrt (se Python3 presente)
- Configurazione socket systemd TCP 6556
- Installazione/Configurazione FRPC

Usage:
    install_agent.py [options]

Options:
    --uninstall         Rimuovi agente e configurazioni
    --uninstall-frpc    Rimuovi solo FRPC
    --non-interactive   Modalità non interattiva (richiede env vars)

Env Vars:
    CHECKMK_BASE_URL    URL base download agenti
    FRP_VERSION         Versione FRPC (es. 0.64.0)

Version: 1.0.0
"""

import sys
import os
import shutil
import subprocess
import urllib.request
import re
import tarfile
import tempfile
import platform
from pathlib import Path

# --- Configurazione ---
DEFAULT_URL = "https://monitoring.nethlab.it/monitoring/check_mk/agents"
DEFAULT_FRP_VER = "0.64.0"

class Console:
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    RED = '\033[0;31m'
    NC = '\033[0m'
    
    @staticmethod
    def log(msg): print(f"[INFO] {msg}")
    @staticmethod
    def warn(msg): print(f"{Console.YELLOW}[WARN] {msg}{Console.NC}")
    @staticmethod
    def error(msg, fatal=True): 
        print(f"{Console.RED}[ERROR] {msg}{Console.NC}")
        if fatal: sys.exit(1)
        
    @staticmethod
    def confirm(msg, default=False):
        yn = "Y/n" if default else "y/N"
        res = input(f"{msg} [{yn}]: ").strip().lower()
        if not res: return default
        return res in ['y', 'yes']

    @staticmethod
    def input_val(msg, default=None):
        if default:
            res = input(f"{msg} [{default}]: ").strip()
            return res if res else default
        res = input(f"{msg}: ").strip()
        while not res:
             print("Valore obbligatorio")
             res = input(f"{msg}: ").strip()
        return res

def run_cmd(cmd, check=True, cwd=None):
    try:
        subprocess.run(cmd, check=check, cwd=cwd)
        return True
    except subprocess.CalledProcessError:
        return False

def http_get(url):
    try:
        with urllib.request.urlopen(url) as response:
            return response.read().decode('utf-8')
    except Exception as e:
        Console.error(f"HTTP GET failed {url}: {e}", fatal=False)
        return None

def download_file(url, dest):
    try:
        with urllib.request.urlopen(url) as response, open(dest, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)
        return True
    except Exception as e:
        Console.error(f"Download failed {url}: {e}", fatal=False)
        return False

class Installer:
    def __init__(self):
        self.os_type = self.detect_os()
        self.base_url = os.environ.get("CHECKMK_BASE_URL", DEFAULT_URL)
        self.frp_version = os.environ.get("FRP_VERSION", DEFAULT_FRP_VER)
        
    def detect_os(self):
        if Path("/etc/openwrt_release").exists():
            return "openwrt"
            
        try:
            with open("/etc/os-release") as f:
                data = f.read().lower()
                if "debian" in data or "ubuntu" in data: return "deb"
                if "rhel" in data or "centos" in data or "fedora" in data or "rocky" in data: return "rpm"
        except:
            pass
        return "unknown"

    def get_latest_agent(self):
        Console.log("Recupero lista agenti...")
        html = http_get(self.base_url + "/")
        if not html: return None
        
        # Parse file list
        pattern = ""
        if self.os_type == "deb":
            pattern = re.compile(r'check-mk-agent_([\d\.p]+-\d+)_all\.deb')
        elif self.os_type == "rpm":
            pattern = re.compile(r'check-mk-agent-([\d\.p]+-\d+)\.noarch\.rpm')
        else:
            return None # OpenWrt logic needs specific handling?
            
        versions = []
        for line in html.splitlines():
            m = pattern.search(line)
            if m:
                # Store full match
                versions.append(m.group(0))
                
        # Sort simple (lexicographic sort usually works for these versions)
        versions.sort()
        if not versions: return None
        return versions[-1]

    def install_agent(self):
        Console.log(f"Installazione Agente ({self.os_type})...")
        
        if self.os_type == "openwrt":
            self.install_openwrt()
            return

        filename = self.get_latest_agent()
        if not filename:
            Console.error("Impossibile trovare agente", fatal=True)
            
        url = f"{self.base_url}/{filename}"
        tmp_file = Path(f"/tmp/{filename}")
        
        Console.log(f"Download: {url}")
        if not download_file(url, tmp_file):
            Console.error("Download fallito", fatal=True)
            
        if self.os_type == "deb":
            Console.log("Installazione DEB...")
            if not run_cmd(["dpkg", "-i", str(tmp_file)]):
                Console.log("Risoluzione dipendenze...")
                run_cmd(["apt-get", "install", "-f", "-y"])
        elif self.os_type == "rpm":
            Console.log("Installazione RPM...")
            run_cmd(["rpm", "-Uvh", "--replacepkgs", str(tmp_file)])
            
        # Configure socket
        self.configure_systemd_socket()
        
        # Cleanup
        if tmp_file.exists(): os.remove(tmp_file)

    def install_openwrt(self):
        # OpenWrt steps: extract deb manually
        Console.log("Installazione OpenWrt (manual extract)...")
        # Logic from bash script: download deb, ar x, tar x data.tar.gz
        # Reuse get_latest_agent with 'deb' logic?
        # Temporarily force deb detection for finding url
        saved_type = self.os_type
        self.os_type = "deb"
        filename = self.get_latest_agent()
        self.os_type = saved_type
        
        if not filename: Console.error("Agente non trovato")
        
        url = f"{self.base_url}/{filename}"
        tmp_dir = Path(tempfile.mkdtemp())
        deb_file = tmp_dir / filename
        
        download_file(url, deb_file)
        
        # Extract ar
        run_cmd(["ar", "x", deb_file], cwd=tmp_dir)
        # Find data.tar.*
        data_tar = list(tmp_dir.glob("data.tar.*"))[0]
        run_cmd(["tar", "xf", str(data_tar)], cwd=tmp_dir)
        
        # Install bin
        bin_path = tmp_dir / "usr/bin/check_mk_agent"
        if bin_path.exists():
            shutil.copy2(bin_path, "/usr/bin/check_mk_agent")
            os.chmod("/usr/bin/check_mk_agent", 0o755)
        else:
            Console.error("Binario agente non trovato nel deb")
            
        shutil.rmtree(tmp_dir)
        self.configure_openwrt_service()

    def configure_systemd_socket(self):
        Console.log("Configurazione Systemd Socket (TCP 6556)...")
        
        # Disable agent-ctl
        run_cmd(["systemctl", "stop", "check-mk-agent.socket", "cmk-agent-ctl-daemon.service"], check=False)
        run_cmd(["systemctl", "disable", "check-mk-agent.socket", "cmk-agent-ctl-daemon.service"], check=False)
        
        socket = """[Unit]
Description=Checkmk Agent (TCP 6556 plain)
Documentation=https://docs.checkmk.com/

[Socket]
ListenStream=6556
Accept=yes

[Install]
WantedBy=sockets.target
"""
        service = """[Unit]
Description=Checkmk Agent (TCP 6556 plain) connection

[Service]
ExecStart=-/usr/bin/check_mk_agent
StandardInput=socket
"""
        with open("/etc/systemd/system/check-mk-agent-plain.socket", "w") as f: f.write(socket)
        with open("/etc/systemd/system/check-mk-agent-plain@.service", "w") as f: f.write(service)
        
        run_cmd(["systemctl", "daemon-reload"])
        run_cmd(["systemctl", "enable", "--now", "check-mk-agent-plain.socket"])
        Console.success("Agente configurato")

    def configure_openwrt_service(self):
        Console.log("Configurazione servizio Procd (socat)...")
        # Require socat
        if not shutil.which("socat"):
             Console.warn("Socat non trovato. Eseguire: opkg update && opkg install socat")
        
        init = """#!/bin/sh /etc/rc.common
START=98
STOP=10
USE_PROCD=1

PROG=/usr/bin/check_mk_agent

start_service() {
    procd_open_instance
    procd_set_param command socat TCP-LISTEN:6556,reuseaddr,fork,keepalive EXEC:$PROG
    procd_set_param respawn
    procd_set_param stdout 1
    procd_set_param stderr 1
    procd_close_instance
}

stop_service() {
    killall socat >/dev/null 2>&1 || true
}
"""
        with open("/etc/init.d/check_mk_agent", "w") as f: f.write(init)
        os.chmod("/etc/init.d/check_mk_agent", 0o755)
        run_cmd(["/etc/init.d/check_mk_agent", "enable"])
        run_cmd(["/etc/init.d/check_mk_agent", "restart"])

    def install_frpc(self):
        Console.log(f"Installazione FRPC {self.frp_version}...")
        arch = platform.machine()
        if arch == "x86_64": arch = "amd64"
        elif arch in ["aarch64", "arm64"]: arch = "arm64"
        
        url = f"https://github.com/fatedier/frp/releases/download/v{self.frp_version}/frp_{self.frp_version}_linux_{arch}.tar.gz"
        tmp_dir = Path(tempfile.mkdtemp())
        tar_path = tmp_dir / "frp.tgz"
        
        Console.log(f"Download: {url}")
        if not download_file(url, tar_path):
             Console.error("Download FRPC fallito")
             return

        # Extract
        with tarfile.open(tar_path, "r:gz") as tar:
            tar.extractall(path=tmp_dir)
            
        # Find bin
        bin_found = list(tmp_dir.rglob("frpc"))
        if not bin_found:
             Console.error("Binario frpc non trovato")
             return
             
        bin_path = bin_found[0]
        shutil.copy2(bin_path, "/usr/local/bin/frpc")
        os.chmod("/usr/local/bin/frpc", 0o755)
        shutil.rmtree(tmp_dir)
        Console.success("FRPC installato")
        
        self.configure_frpc()

    def configure_frpc(self):
        hostname = platform.node()
        
        print("\nConfigurazione FRPC:")
        host = Console.input_val("Nome host", hostname)
        server = Console.input_val("Server FRP", "monitor.nethlab.it")
        port = Console.input_val("Porta remota (es. 20001)")
        while not port.isdigit():
             port = Console.input_val("Porta remota (es. 20001)")
        token = Console.input_val("Token FRP")
        
        config_dir = Path("/etc/frp")
        config_dir.mkdir(parents=True, exist_ok=True)
        
        config = f"""[common]
server_addr = "{server}"
server_port = 7000
auth.method = "token"
auth.token  = "{token}"
tls.enable  = true
log.to      = "/var/log/frpc.log"
log.level   = "info"

[{host}]
type        = "tcp"
local_ip    = "127.0.0.1"
local_port  = 6556
remote_port = {port}
"""
        with open(config_dir / "frpc.toml", "w") as f: f.write(config)
        
        self.setup_frpc_service()
        
    def setup_frpc_service(self):
        if self.os_type == "openwrt":
            init = """#!/bin/sh /etc/rc.common
START=99
STOP=10
USE_PROCD=1

start_service() {
    procd_open_instance
    procd_set_param command /usr/local/bin/frpc -c /etc/frp/frpc.toml
    procd_set_param respawn
    procd_close_instance
}
"""
            with open("/etc/init.d/frpc", "w") as f: f.write(init)
            os.chmod("/etc/init.d/frpc", 0o755)
            run_cmd(["/etc/init.d/frpc", "enable"])
            run_cmd(["/etc/init.d/frpc", "restart"])
        else:
            service = """[Unit]
Description=FRP Client Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/frpc -c /etc/frp/frpc.toml
Restart=on-failure
RestartSec=5s
User=root

[Install]
WantedBy=multi-user.target
"""
            with open("/etc/systemd/system/frpc.service", "w") as f: f.write(service)
            run_cmd(["systemctl", "daemon-reload"])
            run_cmd(["systemctl", "enable", "--now", "frpc"])
            
        Console.success("Servizio FRPC configurato")

    def uninstall(self, agent=True, frp=True):
        if frp:
            Console.log("Disinstallazione FRPC...")
            if self.os_type == "openwrt":
                run_cmd(["/etc/init.d/frpc", "stop"], check=False)
                run_cmd(["/etc/init.d/frpc", "disable"], check=False)
                if Path("/etc/init.d/frpc").exists(): os.remove("/etc/init.d/frpc")
            else:
                run_cmd(["systemctl", "disable", "--now", "frpc"], check=False)
                if Path("/etc/systemd/system/frpc.service").exists(): os.remove("/etc/systemd/system/frpc.service")
                run_cmd(["systemctl", "daemon-reload"], check=False)
            
            if Path("/usr/local/bin/frpc").exists(): os.remove("/usr/local/bin/frpc")
            if Path("/etc/frp").exists(): shutil.rmtree("/etc/frp")
            
        if agent:
             Console.log("Disinstallazione Agente...")
             if self.os_type == "openwrt":
                 run_cmd(["/etc/init.d/check_mk_agent", "stop"], check=False)
                 if Path("/etc/init.d/check_mk_agent").exists(): os.remove("/etc/init.d/check_mk_agent")
                 if Path("/usr/bin/check_mk_agent").exists(): os.remove("/usr/bin/check_mk_agent")
             else:
                 run_cmd(["systemctl", "disable", "--now", "check-mk-agent-plain.socket"], check=False)
                 files = ["/etc/systemd/system/check-mk-agent-plain.socket", "/etc/systemd/system/check-mk-agent-plain@.service"]
                 for f in files:
                     if Path(f).exists(): os.remove(f)
                 run_cmd(["systemctl", "daemon-reload"], check=False)
                 
                 # Remove pkg
                 if self.os_type == "deb": run_cmd(["dpkg", "-r", "check-mk-agent"], check=False)
                 elif self.os_type == "rpm": run_cmd(["rpm", "-e", "check-mk-agent"], check=False)
                 
                 if Path("/usr/bin/check_mk_agent").exists(): os.remove("/usr/bin/check_mk_agent")
                 if Path("/etc/check_mk").exists(): shutil.rmtree("/etc/check_mk")

def main():
    if os.geteuid() != 0:
        Console.error("Eseguire come root")

    installer = Installer()
    
    if "--uninstall" in sys.argv:
        installer.uninstall()
        sys.exit(0)
    elif "--uninstall-frpc" in sys.argv:
        installer.uninstall(agent=False)
        sys.exit(0)
        
    Console.log(f"Sistema rilevato: {installer.os_type}")
    
    print("\nQuesta procedura installerà:")
    print("- CheckMK Agent Plain (TCP 6556)")
    if Console.confirm("Procedere?"):
        installer.install_agent()
        
        if Console.confirm("Installare FRPC (Tunnel)?"):
            installer.install_frpc()

if __name__ == "__main__":
    main()
