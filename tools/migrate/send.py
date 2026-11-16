# tar 串流 → TCP：讀 stdin、邊傳邊算 sha256；結束印「sent <bytes> sha256 <hex>」到 stderr
import hashlib, socket, sys
host, port = sys.argv[1], int(sys.argv[2])
s = socket.create_connection((host, port), timeout=60)
s.settimeout(None)
h, n, inp = hashlib.sha256(), 0, sys.stdin.buffer
while True:
    b = inp.read(1 << 20)
    if not b:
        break
    h.update(b); n += len(b); s.sendall(b)
s.shutdown(socket.SHUT_WR); s.recv(1); s.close()
print(f"sent {n} sha256 {h.hexdigest()}", file=sys.stderr)
