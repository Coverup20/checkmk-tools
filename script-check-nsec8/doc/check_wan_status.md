# check_wan_status.sh

## Description
Monitoring script for CheckMK that checks the status of WAN interfaces on NSecFirewall8 (OpenWrt).

## Features
- Automatically detect all configured WAN interfaces (wan, wan6, wwan, vwan)
- Check UP/DOWN status via `ubus`
- Test real connectivity by pinging the gateway
- Fallback to public DNS (8.8.8.8, 1.1.1.1) if gateway unavailable
- CheckMK format output with perfdata

## States
- **OK (0)**: All WANs are UP and reachable
- **WARNING (1)**: WAN UP but no connectivity or unknown status
- **CRITICAL (2)**: At least one WAN is DOWN

## Output CheckMK
### wan_status section
```
0 WAN_Status status=OK wan=OK - wan: UP (gateway 192.168.1.1 reachable)
```

### wan_metrics section
```
0 WAN_Metrics - Total=1 Up=1 Down=0 Degraded=0 | total=1 up=1 down=0 degraded=0
```

## Performance Data
- `total`: Total number of WAN interfaces
- `up`: Number of UP and functioning interfaces
- `down`: Number of DOWN interfaces
- `degraded`: Number of UP interfaces but without connectivity

## Requirements
- OpenWrt with `ubus`
- `ping` command available
- `jsonfilter` command for JSON parsing

## Installation
```bash
# Copy to CheckMK agent directory
cp check_wan_status.sh /usr/lib/check_mk_agent/local/rcheck_wan_status.sh
chmod +x /usr/lib/check_mk_agent/local/rcheck_wan_status.sh
```

## Manual testing
```bash
bash /opt/checkmk-tools/script-check-nsec8/full/check_wan_status.sh
```

## Notes
- The script uses `ubus call network.interface.<name> status` to get the status
- Connectivity test with 2 second timeout and 2 retries
- Multiple WAN interfaces supported (failover, load balancing)