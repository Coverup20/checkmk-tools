# check_firewall_traffic.sh

## Description
Monitor network traffic (RX/TX) on the WAN and LAN interfaces of the NSecFirewall8 firewall.

## Features
- Automatically detects WAN (wan, wwan) and LAN (lan, br-lan) interfaces
- Read statistics from `/sys/class/net/<device>/statistics/`
- Count bytes, packets and errors for RX and TX
- Generate alarm if errors > 100

## States
- **OK (0)**: RX/TX errors <= 100
- **WARNING (1)**: RX/TX errors > 100

## Output CheckMK
```
0 wan_traffic - RX: 123456789 bytes, TX: 987654321 bytes | rx_bytes=123456789 tx_bytes=987654321 rx_packets=12345 tx_packets=98765 rx_errors=0 tx_errors=0
0 lan_traffic - RX: 987654321 bytes, TX: 123456789 bytes | rx_bytes=987654321 tx_bytes=123456789 rx_packets=98765 tx_packets=12345 rx_errors=0 tx_errors=0
```

## Performance Data
- `rx_bytes`: Bytes received (cumulative counter)
- `tx_bytes`: Bytes transmitted (cumulative counter)
- `rx_packets`: Received packets
- `tx_packets`: Packets transmitted
- `rx_errors`: Receiving errors
- `tx_errors`: Transmission errors

## Requirements
- OpenWrt with `ubus` to map logical interfaces to physical devices
- Directory `/sys/class/net/` accessible

## Installation
```bash
cp check_firewall_traffic.sh /usr/lib/check_mk_agent/local/rcheck_firewall_traffic.sh
chmod +x /usr/lib/check_mk_agent/local/rcheck_firewall_traffic.sh
```

## Manual testing
```bash
bash /opt/checkmk-tools/script-check-nsec8/full/check_firewall_traffic.sh
```

## Notes
- The counters are cumulative since the last boot
- CheckMK automatically calculates rates (bytes/sec, packets/sec)
- Perfect for creating bandwidth graphs over time
- High errors can indicate:
  - Hardware problems (cable, network card)
  - Collisions on half-duplex
  - MTU mismatch