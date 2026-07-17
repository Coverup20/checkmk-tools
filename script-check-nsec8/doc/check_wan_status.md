# check_wan_status.py

## Description
Monitoring script for CheckMK that checks the status of WAN interfaces on NethSecurity 8.8 (OpenWrt).

## Features
- Automatically detects all WAN (`role=red`) interfaces via the `nethsec` library (`nethsec.inventory.get_networks`)
- Reports each WAN by its UCI interface name (e.g. `tim_fibra`, `vodafone_adsl` - commonly the ISP/operator name, not literally "wan"), not by the raw device name (`eth1`) - falls back to the device name only if no matching UCI section is found
- Resolves the runtime device for dynamic protocols (e.g. PPPoE) via `ubus call network.interface.<name> status` (`l3_device`), not just the UCI-configured device
- Checks UP/DOWN status via `/sys/class/net/<iface>/operstate`
- Tests real connectivity via TCP connect() to the gateway (port 80) as a ping replacement
- Falls back to public reachability checks (1.1.1.1:443, 8.8.8.8:53) if the gateway probe is inconclusive - a gateway that isn't running an HTTP server on port 80 is common and does NOT by itself mean the WAN is down
- Falls back to `/proc/net/route` default-route detection if the `nethsec`/UCI library is unavailable
- CheckMK format output with perfdata

## States
- **OK (0)**: WAN is UP and either the gateway or public internet reachability check succeeds
- **WARNING (1)**: WAN UP but neither the gateway nor public reachability check succeeds
- **CRITICAL (2)**: At least one WAN interface is DOWN

## Output CheckMK
### WAN.Status / WAN.InterfaceN
```
0 WAN.Status - tim_fibra: UP (gateway 192.168.1.1 reachable via TCP); vodafone_adsl: UP (gateway 192.168.1.1 reachable via TCP)
0 WAN.Interface0 - tim_fibra: UP (gateway 192.168.1.1 reachable via TCP)
0 WAN.Interface1 - vodafone_adsl: UP (gateway 192.168.1.1 reachable via TCP)
```

### WAN.Metrics
```
0 WAN.Metrics - Total=1 Up=1 Down=0 Degraded=0 | total=1 up=1 down=0 degraded=0
```

## Performance Data
- `total`: Total number of WAN interfaces
- `up`: Number of UP interfaces with confirmed reachability (gateway or internet)
- `down`: Number of DOWN interfaces
- `degraded`: Number of UP interfaces with no confirmed reachability

## Requirements
- Python 3 with `euci`/`nethsec` (`python3-nethsec`) for interface discovery - falls back to `/proc/net/route` if unavailable
- `ubus` for runtime device resolution (PPPoE/dynamic protocols); safely skipped if unavailable, using the UCI-configured device instead

## Installation
```bash
cp check_wan_status.py /usr/lib/check_mk_agent/local/check_wan_status
chmod +x /usr/lib/check_mk_agent/local/check_wan_status
```

## Manual testing
```bash
python3 /opt/checkmk-tools/script-check-nsec8/full/check_wan_status.py
```

## Notes
- WAN interfaces are identified by `role=red` in `nethsec.inventory.get_networks()`, not by name pattern matching
- Displayed labels come from the UCI interface section name, so a WAN named after its ISP (`tim_fibra`, `vodafone_adsl`, etc.) shows up as such, not as an opaque `eth1`/`eth2`
- A failed TCP probe on the gateway's port 80 is treated as inconclusive, not as a failure - it only affects the result if the public-internet fallback checks also fail
- Multiple WAN interfaces are supported (failover, load balancing) - verified live with 2 simultaneous WANs, each with a custom operator name
