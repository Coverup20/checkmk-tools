#!/usr/bin/env python3
"""Query livestatus per dettagli Check_MK Discovery WARN sui switch."""
import socket

SOCKET_PATH = "/omd/sites/monitoring/tmp/run/live"
HOSTS = ["SW-AreaProgettazione1", "SW-AreaGare", "SW-CEDPianoPrimo1", "SW-AreaStrutture"]

def query(q):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(SOCKET_PATH)
    s.sendall(q.encode())
    s.shutdown(socket.SHUT_WR)
    data = b""
    while True:
        chunk = s.recv(4096)
        if not chunk:
            break
        data += chunk
    s.close()
    return data.decode("utf-8", errors="replace")

# Discovery WARN details
q = (
    "GET services\n"
    "Filter: description = Check_MK Discovery\n"
    "Filter: state > 0\n"
    "Columns: host_name state plugin_output long_plugin_output\n"
    "OutputFormat: csv\n\n"
)

print("=== Check_MK Discovery WARN ===")
result = query(q)
for line in result.strip().split("\n"):
    if not line:
        continue
    parts = line.split(";", 3)
    host = parts[0] if len(parts) > 0 else ""
    state_map = {"0": "OK", "1": "WARN", "2": "CRIT", "3": "UNKN"}
    state = state_map.get(parts[1], parts[1]) if len(parts) > 1 else ""
    output = parts[2] if len(parts) > 2 else ""
    long_out = parts[3] if len(parts) > 3 else ""
    print(f"\n[{state}] {host}")
    print(f"  Summary: {output}")
    if long_out:
        print(f"  Detail:  {long_out[:500]}")
