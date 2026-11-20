"""TCP log client: NDJSON over a persistent connection, reconnects on failure."""
import argparse, socket, time
from collector.schema import LogEvent
from clients.log_generator import generate_events, paced


class TCPLogClient:
    def __init__(self, host, port, retries=5, backoff=0.5):
        self.addr, self.retries, self.backoff, self.sock = (host, port), retries, backoff, None

    def connect(self):
        last = None
        for i in range(self.retries):
            try:
                self.sock = socket.create_connection(self.addr, timeout=5)
                self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                return
            except OSError as e:
                last = e; time.sleep(self.backoff * (i + 1))
        raise ConnectionError(f"cannot connect to {self.addr}: {last}")

    def send(self, ev: LogEvent):
        data = ev.to_bytes() + b"\n"
        for attempt in range(2):            # one transparent reconnect; same event_id => collector dedups
            try:
                if self.sock is None:
                    self.connect()
                self.sock.sendall(data); return
            except OSError:
                self.close()
                if attempt == 1:
                    raise

    def close(self):
        if self.sock:
            try: self.sock.close()
            except OSError: pass
        self.sock = None


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1"); ap.add_argument("--port", type=int, default=9000)
    ap.add_argument("--source", default="client1"); ap.add_argument("--service", default="app")
    ap.add_argument("--count", type=int, default=100); ap.add_argument("--rate", type=float, default=50)
    ap.add_argument("--size", type=int, default=120)
    a = ap.parse_args()
    c = TCPLogClient(a.host, a.port); c.connect(); t0 = time.time(); n = 0
    for ev in paced(generate_events(a.source, a.service, "TCP", a.count, a.size), a.rate):
        c.send(ev); n += 1
    c.close(); print(f"{a.source}: sent {n} TCP events in {time.time()-t0:.2f}s")
