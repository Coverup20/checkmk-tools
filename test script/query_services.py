import socket

sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect('/omd/sites/monitoring/tmp/run/live')
query = b'GET services\nFilter: host_name = WKS-11settembre.ad.studiopaci.info\nColumns: description state plugin_output\nOutputFormat: csv\nSeparator: 59\n\n'
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
print(f'Services for WKS-11settembre: {len(lines)}')
for l in lines[:20]:
    print(l)
