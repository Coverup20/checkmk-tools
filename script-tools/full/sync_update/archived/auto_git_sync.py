#!/usr/bin/env python3
"""
auto_git_sync.py - Automatic Git Repository Sync

Mantiene sincronizzato un repository git locale con il remote.
Esegue fetch, reset hard e clean periodico.
Preserva file di configurazione (.env).

Usage:
    auto_git_sync.py [updates_interval_seconds]

Env Vars:
    SYNC_INTERVAL   Intervallo in secondi (default: 60)
    REPO_URL        URL repository (default: https://github.com/Coverup20/checkmk-tools.git)
    TARGET_DIR      Directory repository (auto-detect)

Version: 1.0.0
"""

import sys
import os
import time
import subprocess
import shutil
from pathlib import Path
from typing import List, Optional

# --- Configurazione ---
DEFAULT_REPO_URL = "https://github.com/Coverup20/checkmk-tools.git"
DEFAULT_INTERVAL = 60
LOG_FILE = "/var/log/auto-git-sync.log"

# --- Utils ---
def log(msg: str, level: str = "INFO"):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] {level}: {msg}"
    print(formatted)
    try:
        # Fallback log file if /var/log not writable
        log_path = Path(LOG_FILE)
        if not os.access(log_path.parent, os.W_OK):
            log_path = Path.home() / "auto-git-sync.log"
        
        with open(log_path, "a") as f:
            f.write(formatted + "\n")
    except Exception:
        pass

def run_cmd(cmd: List[str], cwd: Optional[Path] = None, timeout: int = 60) -> bool:
    try:
        subprocess.run(
            cmd, 
            cwd=cwd, 
            check=True, 
            timeout=timeout,
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.PIPE
        )
        return True
    except subprocess.CalledProcessError as e:
        log(f"Comando fallito {' '.join(cmd)}: {e.stderr.decode().strip()}", "ERROR")
        return False
    except subprocess.TimeoutExpired:
        log(f"Timeout comando {' '.join(cmd)}", "ERROR")
        return False

# --- Core Logic ---
class GitSyncer:
    def __init__(self, interval: int):
        self.interval = interval
        self.repo_url = os.environ.get("REPO_URL", DEFAULT_REPO_URL)
        self.target_dir = self.detect_target_dir()
        
    def detect_target_dir(self) -> Path:
        env_dir = os.environ.get("TARGET_DIR")
        if env_dir:
            return Path(env_dir)
            
        candidates = [
            Path("/opt/checkmk-tools"),
            Path("/root/checkmk-tools"),
            Path.home() / "checkmk-tools"
        ]
        
        for p in candidates:
            if (p / ".git").exists():
                return p
        
        return Path("/opt/checkmk-tools")

    def clone_if_needed(self) -> bool:
        if (self.target_dir / ".git").exists():
            return True
            
        log(f"Cloning repo into {self.target_dir}...", "INFO")
        try:
            if self.target_dir.exists():
                shutil.rmtree(self.target_dir)
            self.target_dir.parent.mkdir(parents=True, exist_ok=True)
            return run_cmd(["git", "clone", self.repo_url, str(self.target_dir)], timeout=180)
        except Exception as e:
            log(f"Clone error: {e}", "ERROR")
            return False

    def is_valid_repo(self) -> bool:
        return run_cmd(["git", "rev-parse", "--is-inside-work-tree"], cwd=self.target_dir)

    def sync(self) -> bool:
        if not self.is_valid_repo():
            log("Repository invalido/corrotto. Re-cloning...", "WARN")
            shutil.rmtree(self.target_dir, ignore_errors=True)
            if not self.clone_if_needed():
                return False

        # Fetch
        if not run_cmd(["git", "fetch", "origin"], cwd=self.target_dir, timeout=120):
            return False

        # Determine remote HEAD
        try:
            res = subprocess.run(
                ["git", "symbolic-ref", "-q", "refs/remotes/origin/HEAD"],
                cwd=self.target_dir, capture_output=True, text=True
            )
            remote_head = res.stdout.strip().replace("refs/remotes/", "") if res.returncode == 0 else "origin/main"
        except Exception:
            remote_head = "origin/main"

        # Checkout/Reset
        # Create local branch tracking remote if needed
        local_branch = remote_head.replace("origin/", "")
        
        # force checkout
        run_cmd(["git", "checkout", "-B", local_branch, remote_head], cwd=self.target_dir)
        
        # hard reset
        if not run_cmd(["git", "reset", "--hard", remote_head], cwd=self.target_dir):
            return False
            
        # Clean (preserve config)
        # git clean -fdx -e .env ...
        cmd_clean = ["git", "clean", "-fdx", 
                     "-e", ".env", "-e", ".env.*",
                     "-e", "install/checkmk-installer/.env",
                     "-e", "install/checkmk-installer/.env.*"]
        
        run_cmd(cmd_clean, cwd=self.target_dir)
        
        # Chmod +x *.sh and *.py
        for ext in ["*.sh", "*.py"]:
            subprocess.run(
                f"find . -type f -name '{ext}' -exec chmod +x {{}} +", 
                cwd=self.target_dir, shell=True
            )

        return True

    def run(self):
        log(f"Starting auto-git-sync. Dir: {self.target_dir}, Interval: {self.interval}s")
        
        if not self.clone_if_needed():
            log("Initial clone failed. Retrying in loop...", "ERROR")

        while True:
            start_time = time.time()
            if self.sync():
                log("Sync OK", "INFO")
            else:
                log("Sync Failed", "ERROR")
                
            elapsed = time.time() - start_time
            sleep_time = max(0, self.interval - elapsed)
            time.sleep(sleep_time)

def main():
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("SYNC_INTERVAL", DEFAULT_INTERVAL))
    
    # Check git
    if not shutil.which("git"):
        log("Git not found", "ERROR")
        sys.exit(1)
        
    syncer = GitSyncer(interval)
    try:
        syncer.run()
    except KeyboardInterrupt:
        log("Stopping...", "INFO")

if __name__ == "__main__":
    main()
