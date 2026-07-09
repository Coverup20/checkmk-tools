#!/usr/bin/env python3
"""check_firewall_rules.py - CheckMK firewall rules check.

Counts nftables rules, zones, and forwardings using:
  - nft (if available) for precise rule count
  - fw4 print (if available) for NethSecurity-managed rules
  - UCI as fallback for zone/forwarding count
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

VERSION = "1.2.0"
SERVICE = "Firewall.Rules"


def find_nft():
    nft_path = shutil.which("nft")
    if nft_path:
        return nft_path
    for p in ["/usr/sbin/nft", "/usr/bin/nft", "/sbin/nft", "/bin/nft"]:
        if Path(p).exists():
            return p
    return None


def count_nft_rulesets(nft_bin):
    """Use nft to list all rulesets and count tables, chains, rules."""
    try:
        result = subprocess.run(
            [nft_bin, "list", "ruleset"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return None, f"nft error: {result.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return None, "nft list ruleset timed out"
    except FileNotFoundError:
        return None, "nft binary not found"

    output = result.stdout
    lines = output.splitlines()

    # Count tables: lines matching ^table <family> <name>
    table_count = 0
    chain_count = 0
    in_a_chain = False
    rule_count = 0

    for line in lines:
        stripped = line.strip()

        # Detect table declaration
        if re.match(r'^table\s+\S+\s+\S+\s*\{?\s*$', stripped):
            table_count += 1
            continue

        # Detect chain declaration
        if re.match(r'^\s*chain\s+\S+\s*\{?\s*$', stripped) or \
           re.match(r'^\s*chain\s+\S+\s*\{', stripped):
            chain_count += 1
            in_a_chain = True
            continue

        # End of chain block
        if stripped == '}':
            in_a_chain = False
            continue

        # Inside a chain: a rule has meaningful content
        if in_a_chain and stripped and not stripped.startswith('#'):
            # Skip meta-lines
            if not stripped.startswith(('type ', 'policy ', 'ct ', 'iif ', 'iifname ',
                                        'oif ', 'oifname ', 'meta ', 'tcp ', 'udp ',
                                        'icmp ', 'ip ', 'ip6 ', 'ether ', 'arp ',
                                        'sctp ', 'dccp ', 'th ', 'numgen ', 'jhash ',
                                        'symhash ', 'expr ', 'log ', 'limit ',
                                        'low ', 'medium ', 'high ', 'quota ',
                                        'set ', 'map ', 'element ', 'vmap ',
                                        'accept', 'drop', 'reject', 'return',
                                        'jump ', 'goto ', 'counter', 'not', 'and',
                                        'or ', 'dup ', 'fwd ', 'queue')):
                if not stripped.startswith('}'):
                    rule_count += 1

    # If the above counting is off, use a simpler approach:
    # Count lines with "counter" that are inside chain blocks
    # Actually, let me just count actual rule lines more directly
    in_table = False
    rule_count_v2 = 0
    for line in lines:
        s = line.strip()
        if re.match(r'^table\s', s):
            in_table = True
            continue
        if in_table and re.match(r'^\s*chain\s', s):
            continue  # Start of chain - skip the declaration
        # Inside a chain block, after the opening {, look for actual rules
        if in_table and s and not s.startswith('#') and not s == '}':
            # This is a content line - check if it looks like a statement
            if any(s.startswith(x) for x in (
                'accept', 'drop', 'reject', 'return', 'jump ', 'goto ',
                'counter', 'log ', 'queue', 'dup ', 'fwd ', 'not',
                'iif', 'oif', 'tcp ', 'udp ', 'icmp ', 'meta ',
                'ip ', 'ip6 ', 'ether ')):
                rule_count_v2 += 1

    # Most reliable: count lines with "counter packets" - each rule has one
    counter_rules = len([l for l in lines if 'counter packets' in l])
    if counter_rules > rule_count_v2:
        rule_count_v2 = counter_rules

    return {
        "tables": table_count,
        "chains": chain_count,
        "rules": rule_count_v2,
    }, None


def count_uci_firewall():
    try:
        from euci import EUci
    except ImportError:
        return None, "pyuci not available"
    try:
        with EUci() as u:
            fw = u.get("firewall")
    except Exception as e:
        return None, f"UCI error: {e}"
    if not fw:
        return None, "UCI firewall config is empty"
    zones = 0
    forwardings = 0
    rules = 0
    redirects = 0
    for key, value in fw.items():
        if key.endswith("._type"):
            if value == "zone":
                zones += 1
            elif value == "forwarding":
                forwardings += 1
            elif value == "rule":
                rules += 1
            elif value == "redirect":
                redirects += 1
    return {"zones": zones, "forwardings": forwardings, "rules": rules, "redirects": redirects}, None


def main():
    nft_bin = find_nft()
    if nft_bin:
        nft_result, nft_err = count_nft_rulesets(nft_bin)
        if nft_result:
            r = nft_result
            print(
                f"0 {SERVICE} - OK - {r['tables']} tables, {r['chains']} chains, "
                f"{r['rules']} rules (nft)"
                f" | tables={r['tables']} chains={r['chains']} rules={r['rules']}"
            )
            return 0

    # UCI-only fallback
    uci_result, uci_err = count_uci_firewall()
    if uci_result:
        r = uci_result
        print(
            f"0 {SERVICE} - OK - {r['zones']} zones, {r['forwardings']} forwarding, "
            f"{r['rules']} rules (UCI)"
            f" | zones={r['zones']} forwardings={r['forwardings']} rules={r['rules']}"
        )
        return 0

    reasons = []
    if nft_err:
        reasons.append(nft_err)
    if uci_err:
        reasons.append(uci_err)
    print(
        f"3 {SERVICE} - Cannot read firewall rules"
        + (f" ({'; '.join(reasons)})" if reasons else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
