# check_firewall_rules.sh

## Description
Monitor the number of active iptables rules per chain (INPUT, FORWARD, OUTPUT, NAT) on NSecFirewall8.

## Features
- Count rules per chain via `iptables -L`
- Count NAT rules in the nat table
- Check default policy for INPUT and FORWARD
- Alarm if no rules or few active rules

## States
- **OK (0)**: At least 5 active rules
- **WARNING (1)**: Less than 5 active rules
- **CRITICAL (2)**: No active rules

## Output CheckMK
```
0 Firewall_Rules - INPUT:25 FORWARD:40 OUTPUT:15 NAT:20 - Policy: INPUT=DROP FORWARD=DROP - OK | input=25 forward=40 output=15 nat=20 total=100
```

## Performance Data
- `input`: Number of INPUT chain rules
- `forward`: Number of FORWARD chain rules
- `output`: Number of OUTPUT chain rules
- `nat`: Number of nat table rules
- `total`: Total rules (INPUT+FORWARD+OUTPUT)

## Requirements
- `iptables` command available
- Permissions to read firewall rules

## Installation
```bash
cp check_firewall_rules.sh /usr/lib/check_mk_agent/local/rcheck_firewall_rules.sh
chmod +x /usr/lib/check_mk_agent/local/rcheck_firewall_rules.sh
```

## Manual testing
```bash
bash /opt/checkmk-tools/script-check-nsec8/full/check_firewall_rules.sh
```

## Notes
- The count includes all active rules, even OpenWrt's default ones
- Typical firewall policies:
  - INPUT: DROP (blocks incoming traffic not explicitly allowed)
  - FORWARD: DROP (block unauthorized routing)
  - OUTPUT: ACCEPT (allow outgoing traffic)
- A few rules can indicate:
  - Firewall not configured
  - Rules reset by mistake
  - Firewall service not active