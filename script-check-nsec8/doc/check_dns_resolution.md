# check_dns_resolution.sh

## Description
Test local server DNS resolution (127.0.0.1) on NSecFirewall8, checking speed and reliability.

## Features
- Test resolution of public domains (google.com, cloudflare.com, dns.google)
- Use `nslookup` towards 127.0.0.1 (local dnsmasq)
- Measure average response time in milliseconds
- Threshold: WARNING if > 500ms, CRITICAL if no response

## States
- **OK (0)**: All tests OK and time < 500ms
- **WARNING (1)**: Some tests failed or time > 500ms (but < 1000ms)
- **CRITICAL (2)**: All tests failed or time > 1000ms

## Output CheckMK
```
0 DNS_Resolution response_time=45ms;500;1000 Test: 3/3 OK, average time: 45ms - OK | successful=3 failed=0 total=3 avg_time_ms=45
```

## Performance Data
- `response_time`: Average response time with threshold
- `successful`: Number of successful tests
- `failed`: Number of failed tests
- `total`: Total number of tests
- `avg_time_ms`: Average time in milliseconds

## Requirements
- `nslookup` command available
- dnsmasq or other DNS resolver listening on 127.0.0.1:53
- Internet access to resolve public domains

## Installation
```bash
cp check_dns_resolution.sh /usr/lib/check_mk_agent/local/rcheck_dns_resolution.sh
chmod +x /usr/lib/check_mk_agent/local/rcheck_dns_resolution.sh
```

## Manual testing
```bash
bash /opt/checkmk-tools/script-check-nsec8/full/check_dns_resolution.sh
```

## Notes
- Test on public domains to verify complete chain (local → upstream)
- Slow DNS can indicate:
  - Upstream DNS overloaded or slow
  - WAN connectivity issues
  - dnsmasq overloaded (many queries)
- Failures can indicate:
  - dnsmasq not running
  - Upstream DNS unreachable
  - WAN problems