#!/usr/bin/env python3
"""check_firewall_rules.py - CheckMK firewall rules check (pyuci beta).

BLOCKED: nftables ruleset inspection requires the 'nft' command (netlink
interface). No Python stdlib or pyuci equivalent exists.
iptables is also unavailable on NethSecurity 8.8 (nftables only).

This beta version reads nftables table names from UCI (firewall config)
as a best-effort approximation, but cannot count actual rules.
"""

import sys

BETA = True
VERSION = "1.1.1b1"
SERVICE = "Firewall.Rules"

try:
    from euci import EUci
    EUCI_AVAILABLE = True
except ImportError:
    EUci = None
    EUCI_AVAILABLE = False


def count_uci_firewall_zones():
    """Count firewall zones and rules from UCI as approximate metric."""
    if not EUCI_AVAILABLE:
        return 0
    try:
        with EUci() as u:
            fw = u.get("firewall")
    except Exception:
        return 0

    rules = 0
    zones = 0
    if fw:
        sections = {}
        for key in fw:
            parts = key.split(".")
            sec = parts[0]
            if sec not in sections:
                sections[sec] = {}
            if len(parts) >= 2:
                sections[sec][parts[-1]] = True

        for sec_name, fields in sections.items():
            if fields.get("_type") in ("rule", "redirect", "forwarding"):
                rules += 1
            elif fields.get("_type") == "zone":
                zones += 1

    if rules == 0 and zones == 0:
        print(f"3 {SERVICE} - Cannot read nftables rules without 'nft' command; "
              f"UCI shows no firewall zones [beta]")
        return 0

    print(
        f"0 {SERVICE} - UCI zones: {zones}, UCI rules: {rules} "
        f"(approximate, real rules require nft) [beta]"
        f" | total_rules={rules}"
    )
    return 0


def main():
    if not EUCI_AVAILABLE:
        print(f"3 {SERVICE} - pyuci not available (beta requirement) [beta]")
        return 0
    return count_uci_firewall_zones()


if __name__ == "__main__":
    sys.exit(main())
