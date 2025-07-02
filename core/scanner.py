import socket

def scan_ports(url: str):
    host = url.replace("http://", "").replace("https://", "").split("/")[0]
    open_ports = []
    for port in [80, 443, 8080, 8443]:
        try:
            sock = socket.create_connection((host, port), timeout=2)
            open_ports.append({"type": "port", "port": port, "status": "open"})
            sock.close()
        except:
            continue
    return open_ports
