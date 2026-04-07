import subprocess
import re
import sys
from collections import defaultdict

# Patterns to detect sensitive data in git diffs
PATTERNS = [
    # Tokens / API keys
    ("TOKEN",    re.compile(r'(?i)(token|api[_-]?key|secret|auth)["\s=:]+([A-Za-z0-9_\-]{16,})')),
    ("TOKEN",    re.compile(r'(?i)Y_KEY_[A-Za-z0-9]+')),
    ("TOKEN",    re.compile(r'(?i)(password|passwd|pwd)["\s=:]+\S{4,}')),
    # IP addresses (private + public hardcoded)
    ("IP",       re.compile(r'\b(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|45\.\d{1,3}\.\d{1,3}\.\d{1,3}|195\.\d{1,3}\.\d{1,3}\.\d{1,3})\b')),
    # Hostnames / domains interni
    ("HOST",     re.compile(r'\b[\w\-]+\.(nethlab\.it|studiopaci\.info|nethesis\.it|ad\.studiopaci\.info)\b')),
    ("HOST",     re.compile(r'\b(srv-monitoring-sp|checkmk-vps-0[12]|nsec8-stable|ns-lab00|rl94ns8|nodo-proxmox|marziodemo|box-lab00|ubntmarzio|checkmk-z1-0[01]|laboratory|redteam|fwlab)\b')),
    # Names
    ("NAME",     re.compile(r'\b(Marzio|Boldrin|marzio\.boldrin|marzio@)\b')),
    # SSH keys / certs
    ("SSHKEY",   re.compile(r'(BEGIN (RSA|EC|OPENSSH) PRIVATE KEY|ssh-rsa AAAA|ssh-ed25519 AAAA)')),
    # OMD site paths with customer name
    ("PATH",     re.compile(r'/omd/sites/\w+/|studiopaci|paci\.info')),
    # Telegram tokens (bot token format)
    ("TELEGRAM", re.compile(r'\b\d{8,12}:[A-Za-z0-9_\-]{30,}\b')),
    # UUID-like tokens in context (rule IDs etc are OK, but in .env context are not)
    ("DOTENV",   re.compile(r'(?i)^\+.*(Y_KEY|YDEA_TOKEN|BOT_TOKEN|CHAT_ID|API_KEY|SECRET|PASSWORD)\s*=\s*.+')),
]

def run_git_log():
    result = subprocess.run(
        ["git", "log", "--all", "-p", "--no-merges", "--format=COMMIT:%H %h %s"],
        capture_output=True, text=True, errors="replace",
        cwd=r"C:\Users\Marzio\Desktop\CheckMK\checkmk-tools"
    )
    return result.stdout

def scan():
    print("Reading git history... (this may take a moment)")
    log = run_git_log()
    lines = log.splitlines()

    current_commit_hash = ""
    current_commit_short = ""
    current_commit_msg = ""
    current_file = ""
    findings = defaultdict(list)  # hash -> list of (type, file, line_content)

    for line in lines:
        # New commit
        if line.startswith("COMMIT:"):
            parts = line[7:].split(" ", 2)
            current_commit_hash = parts[0] if len(parts) > 0 else ""
            current_commit_short = parts[1] if len(parts) > 1 else ""
            current_commit_msg = parts[2] if len(parts) > 2 else ""
            current_file = ""
            continue

        # File being changed
        if line.startswith("diff --git "):
            m = re.search(r'b/(.+)$', line)
            current_file = m.group(1) if m else line
            continue
        if line.startswith("+++ b/"):
            current_file = line[6:]
            continue

        # Only scan added lines (lines starting with +, not +++)
        if not line.startswith("+") or line.startswith("+++"):
            continue

        content = line[1:]  # strip leading +

        for ptype, pattern in PATTERNS:
            m = pattern.search(content)
            if m:
                matched = m.group(0)[:80]
                # Avoid duplicates per commit+file+match
                entry = (ptype, current_file, matched, content.strip()[:120])
                if entry not in findings[(current_commit_short, current_commit_msg[:60])]:
                    findings[(current_commit_short, current_commit_msg[:60])].append(entry)

    return findings

def main():
    findings = scan()

    if not findings:
        print("\nNo sensitive data found in git history.")
        return

    print(f"\n{'='*100}")
    print(f"SENSITIVE DATA SCAN RESULTS — {sum(len(v) for v in findings.values())} findings in {len(findings)} commits")
    print(f"{'='*100}\n")

    # Group by type for summary
    type_counts = defaultdict(int)

    for (short_hash, commit_msg), entries in sorted(findings.items()):
        print(f"  [{short_hash}] {commit_msg}")
        for ptype, fname, matched, context in entries:
            print(f"    [{ptype:<8}] {fname}")
            print(f"             match   : {matched}")
            print(f"             context : {context}")
            type_counts[ptype] += 1
        print()

    print(f"{'='*100}")
    print("SUMMARY BY TYPE:")
    for t, n in sorted(type_counts.items()):
        print(f"  {t:<10} : {n} findings")

main()
