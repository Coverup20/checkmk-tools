# Beta — NethSecurity 8.8 pyuci local checks

## Purpose

Python-native reimplementation of all CheckMK local checks under
`script-check-nsec8/full/`, using `pyuci` for all UCI access and Python
standard library for everything else. No subprocess, no shell, no external
commands.

Target platform: **NethSecurity 8.8** (OpenWRT 25.12, APK package manager).

## Requirements

- Python 3.13+
- `pyuci` + `euci` (Python UCI bindings)
- `libuci` (system library)

## Status per script

| Script | Status | Notes |
|---|---|---|
| `check_dhcp_leases.py` | ✅ **Ready** | pyuci for UCI, /proc/mounts, lease file resolution |
| `check_dns_resolution.py` | ✅ **Ready** | socket.getaddrinfo() replaces nslookup |
| `check_firewall_connections.py` | ✅ **Ready** | Already native (/proc), beta marker only |
| `check_firewall_rules.py` | ⚠️ **Approximate** | nftables requires 'nft' command; UCI zone/rule count as proxy |
| `check_firewall_traffic.py` | ✅ **Ready** | pyuci for interface discovery, /sys/class/net for counters |
| `check_martian_packets.py` | ✅ **Ready** | Log file only (dmesg removed — no Python equivalent) |
| `check_ovpn_host2net.py` | ✅ **Ready** | /proc scan replaces ps; status files direct read |
| `check_root_access.py` | ✅ **Ready** | utmp parse replaces who; /proc replaces ps |
| `check_uptime.py` | ✅ **Ready** | Already native (/proc), beta marker only |
| `check_vpn_tunnels.py` | ⚠️ **Partial** | OpenVPN native; WireGuard BLOCKED (netlink, no Python API) |
| `check_apk_packages.py` | ⚠️ **Limited** | APK database parse for count only; no upgrade info |
| `check_opkg_packages.py` | ❌ **Blocked** | opkg not available on NethSecurity 8.8 |
| `check_wan_status.py` | ⚠️ **Approximate** | TCP probe replaces ping; UCI + /proc/net/route for discovery |
| `check_wan_throughput.py` | ✅ **Ready** | pyuci + /proc/net/dev + sysfs; no ubus |

## Known blockers

### WireGuard (check_vpn_tunnels.py)
WireGuard peer status requires the `wg` command, which communicates over
netlink. No Python standard library or pyuci equivalent exists.

### nftables rules (check_firewall_rules.py)
nftables uses netlink for ruleset dump. The `nft` command is the only
supported interface. UCI firewall configuration provides an approximate
rule count but cannot reflect runtime nftable state.

### APK upgrades (check_apk_packages.py)
APKINDEX files (`/var/cache/apk/APKINDEX.*.tar.gz`) are binary hashed
indexes. Installed package count is available from `/lib/apk/db/installed`,
but upgrade information requires `apk list --upgradable`.

### ICMP ping (check_wan_status.py)
ICMP echo requires raw sockets (`CAP_NET_RAW`). Beta uses TCP connect()
as a limited approximation (port 80/443).

## Read-only policy

All beta scripts are strictly read-only. No UCI commit, no system
modification, no state changes.

## Naming

Beta files use the same filenames as their originals. All beta scripts
identify themselves with `[beta]` in their output summary.

## Promotion criteria

A beta script may be promoted to production when:
- All external-command blockers are resolved
- Functional equivalence is verified on target hardware
- All tests pass without subprocess usage
