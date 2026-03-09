import socket

hosts = ['192.168.32.144', '192.168.32.141', '192.168.32.220', '192.168.32.218', '192.168.32.60']
ports = [6556, 445, 135, 3389]

for host in hosts:
    results = []
    for port in ports:
        s = socket.socket()
        s.settimeout(2)
        r = s.connect_ex((host, port))
        s.close()
        status = 'OPEN' if r == 0 else 'CLOSED'
        results.append(f'{port}:{status}')
    print(f'{host} - {" | ".join(results)}')
