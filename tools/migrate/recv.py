# TCP → stdout：只收指定網段（例 192.168.2.）來源的一條連線、邊收邊算 sha256；結束印「received <bytes> sha256 <hex>」到 stderr
import hashlib, socket, sys
port, allowed = int(sys.argv[1]), sys.argv[2]
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("0.0.0.0", port)); srv.listen(1)
print(f"listening on {port}", file=sys.stderr, flush=True)
while True:
    c, addr = srv.accept()
    if addr[0].startswith(allowed):
        break
    c.close()
h, n, out = hashlib.sha256(), 0, sys.stdout.buffer
while True:
    b = c.recv(1 << 20)
    if not b:
        break
    h.update(b); n += len(b); out.write(b)
out.flush(); c.close()
print(f"received {n} from {addr[0]} sha256 {h.hexdigest()}", file=sys.stderr)
