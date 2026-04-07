# check_uptime.sh

## Description
Monitor system uptime and load average on NSecFirewall8, normalizing load by number of CPUs.

## Features
- Read uptime from `/proc/uptime` and convert to days/hours/minutes
- Read load average (1min, 5min, 15min) from `/proc/loadavg`
- Count available CPUs with `nproc`
- Normalize load per CPU (load / cpu_count)
- Threshold: WARNING if load/cpu > 0.8, CRITICAL if > 1.5

## States
- **OK (0)**: Normalized load < 0.8 per CPU
- **WARNING (1)**: Normalized load >= 0.8 per CPU
- **CRITICAL (2)**: Normalized load >= 1.5 per CPU

## Output CheckMK
```
0 Firewall_Uptime - Uptime: 15d 8h 42m, Load: 0.35 0.42 0.38 (4 CPU) - OK | uptime_seconds=1331520 load1=0.35 load5=0.42 load15=0.38 cpu_count=4
```

## Performance Data
- `uptime_seconds`: Total uptime in seconds
- `load1`: Load average 1 minute
- `load5`: Load average 5 minutes
- `load15`: Load average 15 minutes
- `cpu_count`: Number of CPUs/cores

## Requirements
- `/proc/uptime` and `/proc/loadavg` files
- `nproc` command to count CPU

## Installation
```bash
cp check_uptime.sh /usr/lib/check_mk_agent/local/rcheck_uptime.sh
chmod +x /usr/lib/check_mk_agent/local/rcheck_uptime.sh
```

## Manual testing
```bash
bash /opt/checkmk-tools/script-check-nsec8/full/check_uptime.sh
```

## Load Average Interpretation
- **< 0.7 per CPU**: System quiet
- **0.7-1.0 per CPU**: System loaded but manageable
- **1.0-1.5 per CPU**: Highly loaded system, be careful
- **> 1.5 per CPU**: System overloaded, queued processes

## Notes
- Normalized Load helps compare systems with different CPUs
- High load on firewall may indicate:
  - Lots of traffic to process
  - Inefficient firewall rules
  - Attack in progress
  - Heavy background processes
- Very long uptime may require reboots for kernel updates