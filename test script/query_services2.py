import socket

sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect('/omd/sites/monitoring/tmp/run/live')
query = b'GET services\nFilter: host_filename ~ rete_192_168_32_0_23\nColumns: host_name description state plugin_output check_command\nOutputFormat: csv\nSeparator: 59\nLimit: 10\n\n'
sock.sendall(query)
sock.shutdown(socket.SHUT_WR)
data = b''
while True:
    chunk = sock.recv(4096)
    if not chunk:
        break
    data += chunk
sock.close()
lines = data.decode().strip().split('\n')
print(f'Total services (sample 10): {len(lines)}')
for l in lines:
    print(l)
