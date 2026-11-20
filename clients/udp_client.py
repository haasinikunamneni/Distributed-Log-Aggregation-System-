"""UDP log client. Classification for the SDN: CRITICAL events go to the critical UDP port, all others to the
ordinary port (the switch can match UDP ports; it cannot read the JSON payload).
Example: python3 -m clients.udp_client --host 10.0.0.100 --source h1 --experiment run1 --count 2000 --rate 200"""
import argparse, json, socket, time
from collections import Counter
from collector.schema import LogEvent
from clients.log_generator import generate_events, paced

CLASS = lambda sev: "critical" if sev == "CRITICAL" else "ordinary"


class UDPLogClient:
    def __init__(self, host, port, crit_port=None):
        self.host, self.port, self.crit_port = host, port, crit_port or port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, ev: LogEvent):
        port = self.crit_port if ev.severity == "CRITICAL" else self.port
        self.sock.sendto(ev.to_bytes(), (self.host, port))   # no ack: only means "handed to the OS"

    def send_raw(self, data: bytes, port=None):
        self.sock.sendto(data, (self.host, port or self.port))

    def close(self):
        self.sock.close()


def parse_weights(s):
    return {k: float(v) for k, v in (kv.split("=") for kv in s.split(","))} if s else None


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9001); ap.add_argument("--crit-port", type=int, default=9101)
    ap.add_argument("--source", default="client1"); ap.add_argument("--service", default="app")
    ap.add_argument("--experiment", default="adhoc")
    ap.add_argument("--count", type=int, default=100); ap.add_argument("--rate", type=float, default=50)
    ap.add_argument("--size", type=int, default=120)
    ap.add_argument("--weights", default="", help="e.g. DEBUG=30,INFO=40,WARNING=15,ERROR=5,CRITICAL=10")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--manifest", default="", help="write JSON of what was sent")
    a = ap.parse_args()
    c = UDPLogClient(a.host, a.port, a.crit_port); t0 = time.time(); sent = Counter()
    for ev in paced(generate_events(a.source, a.service, "UDP", a.count, a.size,
                                    parse_weights(a.weights), a.seed, a.experiment), a.rate):
        c.send(ev); sent[CLASS(ev.severity)] += 1; sent[ev.severity] += 1
    c.close()
    man = {"source": a.source, "experiment": a.experiment, "total": a.count, "sent": dict(sent),
           "duration_s": time.time() - t0}
    if a.manifest:
        json.dump(man, open(a.manifest, "w"))
    print(f"{a.source}: sent {a.count} UDP datagrams in {man['duration_s']:.2f}s {dict(sent)}")
