#!/usr/bin/env python3
"""check_firewall_rules.py - CheckMK local check firewall rules (Python puro).

Supporta nftables (NethSecurity 8 / OpenWrt) e iptables (sistemi legacy).
Version: 1.1.0
"""

import shutil
import subprocess
import sys

VERSION = "1.1.0"
SERVICE = "Firewall_Rules"


def run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False)
    return (result.stdout or "")


def is_nftables_system() -> bool:
    """Rileva se il sistema usa nftables (NethSecurity/OpenWrt)."""
    return (
        shutil.which("nft") is not None
        and not shutil.which("iptables")
        or _openwrt_detected()
    )


def _openwrt_detected() -> bool:
    try:
        import pathlib
        return pathlib.Path("/etc/openwrt_release").exists()
    except Exception:
        return False


def check_nftables() -> int:
    """Conta le regole nftables. Ritorna (status, text, total_rules)."""
    out = run(["nft", "list", "ruleset"])
    # Conta righe con keyword tipiche delle regole nft
    rule_lines = [l for l in out.splitlines() if l.strip().startswith(("ip ", "ip6 ", "inet ", "meta ", "iifname", "oifname", "tcp ", "udp ", "ct state", "accept", "drop", "reject", "masquerade", "dnat", "snat"))]
    total = len(rule_lines)
    # Conta catene definite
    chains = out.count("chain ")
    tables = out.count("table ")

    if total == 0 and chains == 0:
        return 2, "CRITICAL - Nessuna regola nftables attiva", 0
    elif total < 3:
        return 1, f"WARNING - Poche regole nftables ({total})", total
    else:
        return 0, f"OK - {tables} tabelle, {chains} catene, ~{total} regole", total


def count_rule_lines(output: str) -> int:
    return sum(1 for line in output.splitlines() if line.strip() and line[0].isupper())


def extract_policy(output: str) -> str:
    first = output.splitlines()[0] if output.splitlines() else ""
    token = "policy "
    if token in first:
        return first.split(token, 1)[1].split()[0]
    return "UNKNOWN"


def main() -> int:
    # NethSecurity 8 / OpenWrt: usa nftables
    if _openwrt_detected() or (shutil.which("nft") and not shutil.which("iptables")):
        if shutil.which("nft") is None:
            print(f"3 {SERVICE} - nft non trovato su sistema OpenWrt")
            return 0
        status, status_text, total = check_nftables()
        print(f"{status} {SERVICE} - {status_text} | total_rules={total}")
        return 0

    # Sistemi legacy con iptables
    if shutil.which("iptables") is None:
        print(f"3 {SERVICE} - né iptables né nft trovati")
        return 0

    out_input = run(["iptables", "-L", "INPUT", "-n"])
    out_forward = run(["iptables", "-L", "FORWARD", "-n"])
    out_output = run(["iptables", "-L", "OUTPUT", "-n"])
    out_nat = run(["iptables", "-t", "nat", "-L", "-n"])

    input_rules = count_rule_lines(out_input)
    forward_rules = count_rule_lines(out_forward)
    output_rules = count_rule_lines(out_output)
    nat_rules = count_rule_lines(out_nat)
    total_rules = input_rules + forward_rules + output_rules

    input_policy = extract_policy(out_input)
    forward_policy = extract_policy(out_forward)

    if total_rules == 0:
        status, status_text = 2, "CRITICAL - Nessuna regola attiva"
    elif total_rules < 5:
        status, status_text = 1, "WARNING - Poche regole attive"
    else:
        status, status_text = 0, "OK"

    print(
        f"{status} {SERVICE} - INPUT:{input_rules} FORWARD:{forward_rules} OUTPUT:{output_rules} NAT:{nat_rules} "
        f"- Policy: INPUT={input_policy} FORWARD={forward_policy} - {status_text} "
        f"| input={input_rules} forward={forward_rules} output={output_rules} nat={nat_rules} total={total_rules}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
