"""Concurrent TCP collector: one thread per connection, NDJSON framing with a per-connection
byte buffer so partial reads / coalesced messages are handled correctly."""
import socketserver, threading
from .schema import MAX_TCP_LINE


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        proc = self.server.processor
        peer = f"{self.client_address[0]}:{self.client_address[1]}"
        buf = b""
        if proc.verbose:
            print(f"[TCP] connected {peer}", flush=True)
        try:
            while True:
                chunk = self.request.recv(4096)
                if not chunk:                       # orderly close from peer
                    break
                buf += chunk
                while b"\n" in buf:                 # extract every complete frame
                    line, buf = buf.split(b"\n", 1)
                    if line.strip():
                        proc.handle(line, "TCP", peer)
                if len(buf) > MAX_TCP_LINE:         # no newline in 64 KiB: abusive/broken peer
                    proc.count_error("TCP", "oversized", f"{peer} frame > {MAX_TCP_LINE} B, closing")
                    buf = b""
                    break
        except (ConnectionResetError, BrokenPipeError, OSError) as e:
            proc.count_error("TCP", "conn_error", f"{peer} {e}")
        finally:
            if buf.strip():                         # trailing bytes with no '\n' = truncated frame
                proc.count_error("TCP", "truncated", f"{peer} {len(buf)} B unterminated")
            if proc.verbose:
                print(f"[TCP] disconnected {peer}", flush=True)


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class TCPCollector:
    def __init__(self, processor, host="0.0.0.0", port=9000):
        self.server = _Server((host, port), _Handler)
        self.server.processor = processor
        self.port = self.server.server_address[1]
        self._t = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self._t.start(); return self

    def stop(self):
        self.server.shutdown(); self.server.server_close()
