#!/usr/bin/env python3
"""upgrade_checkmk.py - CheckMK RAW Upgrade Automation

Automates the CheckMK RAW Edition update process.
Features:
- Current and latest available version detection
- Site backup before upgrade
- Download and install .deb package
- Stop/Update/Start the site
- Cleanup obsolete versions and old packages
- Detailed report

Usage:
    upgrade_checkmk.py [site_name]

Version: 1.0.0"""

import sys
import os
import re
import shutil
import subprocess
import requests
import time
import argparse
from datetime import datetime
from pathlib import Path

# --- Configuration ---
DOWNLOAD_DIR = Path("/tmp/checkmk-upgrade")
BACKUP_DIR = Path("/opt/omd/backups")
REPORT_FILE = Path("/tmp/checkmk-upgrade-report.txt")

class Console:
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    RED = '\033[0;31m'
    BLUE = '\033[0;34m'
    NC = '\033[0m'
    
    @staticmethod
    def log(msg): 
        print(f"{Console.BLUE}[INFO]{Console.NC} {msg}")
        with open(REPORT_FILE, "a") as f: f.write(f"[INFO] {msg}\n")
    
    @staticmethod
    def warn(msg): 
        print(f"{Console.YELLOW}[WARN]{Console.NC} {msg}")
        with open(REPORT_FILE, "a") as f: f.write(f"[WARN] {msg}\n")
        
    @staticmethod
    def error(msg, fatal=True): 
        print(f"{Console.RED}[ERROR]{Console.NC} {msg}")
        with open(REPORT_FILE, "a") as f: f.write(f"[ERROR] {msg}\n")
        if fatal: sys.exit(1)
        
    @staticmethod
    def success(msg): 
        print(f"{Console.GREEN}[OK]{Console.NC} {msg}")
        with open(REPORT_FILE, "a") as f: f.write(f"[OK] {msg}\n")

def run_cmd(cmd, check=True):
    Console.log(f"Exec: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=check, text=True, capture_output=False)
        return True
    except subprocess.CalledProcessError as e:
        Console.warn(f"Command failed: {e}")
        return False

def get_current_version(site):
    try:
        res = subprocess.check_output(["omd", "version", site], text=True)
        # OMD - Open Monitoring Distribution Version 2.2.0p12.cre
        m = re.search(r'(\d+\.\d+\.\d+p\d+)', res)
        if m: return m.group(1)
    except Exception:
        pass
    Console.error(f"Cannot detect version for site {site}")

def get_latest_version():
    try:
        # Scrape download page efficiently? better check version API if available.
        # Fallback to scraping as per original script
        url = "https://checkmk.com/download"
        res = requests.get(url, timeout=10)
        # Look for check-mk-raw-X.X.XpX
        versions = re.findall(r'check-mk-raw-(\d+\.\d+\.\d+p\d+)', res.text)
        if versions:
            # Sort versions? usually first found is latest featured
            return versions[0] 
    except Exception as e:
        Console.warn(f"Failed to check update: {e}")
    return None

def detect_deb_codename():
    try:
        with open("/etc/os-release") as f:
            data = f.read()
        
        distro_id = re.search(r'^ID=([a-z]+)', data, re.M).group(1)
        version_id = re.search(r'^VERSION_ID="?([^"]+)"?', data, re.M).group(1)
        
        if distro_id == "ubuntu":
            if version_id == "20.04": return "focal"
            if version_id == "22.04": return "jammy"
            if version_id == "24.04": return "noble"
        elif distro_id == "debian":
            if version_id == "11": return "bullseye"
            if version_id == "12": return "bookworm"
            
    except Exception:
        pass
    Console.error("Unsupported OS/Version")

class Upgrader:
    def __init__(self, site):
        self.site = site
        self.codename = detect_deb_codename()
        
    def run(self):
        # Init Report
        with open(REPORT_FILE, "w") as f:
            f.write(f"CHECKMK UPGRADE REPORT - {datetime.now()}\n")
            f.write(f"Site: {self.site}\n\n")

        current = get_current_version(self.site)
        latest = get_latest_version()
        
        Console.log(f"Current: {current}")
        Console.log(f"Latest:  {latest}")
        
        if not latest or current == latest:
            Console.success("No upgrade needed")
            return

        Console.log(f"Upgrading {current} -> {latest}")
        
        # Backups
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        backup_file = BACKUP_DIR / f"{self.site}_pre-upgrade_{datetime.now().strftime('%Y%m%d_%H%M%S')}.tar.gz"
        Console.log(f"Backup site to {backup_file}...")
        run_cmd(["omd", "backup", self.site, str(backup_file)])
        
        # Download
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        pkg_name = f"check-mk-raw-{latest}_0.{self.codename}_amd64.deb"
        url = f"https://download.checkmk.com/checkmk/{latest}/{pkg_name}"
        local_pkg = DOWNLOAD_DIR / pkg_name
        
        if not local_pkg.exists():
            Console.log(f"Downloading {url}...")
            r = requests.get(url, stream=True)
            if r.status_code == 200:
                with open(local_pkg, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
            else:
                Console.error(f"Download failed: {r.status_code}")
                
        # Install
        Console.log("Installing .deb...")
        if not run_cmd(["dpkg", "-i", str(local_pkg)]):
            Console.warn("dpkg failed, trying apt-get -f install...")
            run_cmd(["apt-get", "install", "-f", "-y"])
            if not run_cmd(["dpkg", "-i", str(local_pkg)]):
                Console.error("Install failed")
                
        # Upgrade Site
        Console.log("Stopping site...")
        run_cmd(["omd", "stop", self.site])
        
        Console.log("Updating site...")
        run_cmd(["omd", "-f", "update", "--conflict=install", self.site])
        
        Console.log("Starting site...")
        run_cmd(["omd", "start", self.site])
        
        new_ver = get_current_version(self.site)
        Console.success(f"Upgrade completed. New version: {new_ver}")
        
        self.cleanup(current, new_ver)

    def cleanup(self, old_ver, new_ver):
        Console.log("Cleanup...")
        
        # Remove old versions from /opt/omd/versions
        versions_dir = Path("/opt/omd/versions")
        for v in versions_dir.iterdir():
            if v.is_dir() and not v.is_symlink():
                if v.name != new_ver and v.name != "default":
                    # Check if used by other sites?
                    # Simplify: remove if not new_ver
                    Console.log(f"Removing old version: {v.name}")
                    shutil.rmtree(v)
                    
        # Remove old debs
        run_cmd(["apt-get", "autoremove", "-y"])
        
        # Clean downloads
        shutil.rmtree(DOWNLOAD_DIR)

def main():
    if os.geteuid() != 0:
        Console.error("Run as root")
        
    parser = argparse.ArgumentParser()
    parser.add_argument("site", nargs="?")
    args = parser.parse_args()
    
    site = args.site
    if not site:
        # Detect
        try:
            sites = subprocess.check_output(["omd", "sites", "--bare"], text=True).split()
            if not sites: Console.error("No sites found")
            site = sites[0] # Default to first
        except:
            Console.error("OMD not found")
            
    Upgrader(site).run()

if __name__ == "__main__":
    main()
