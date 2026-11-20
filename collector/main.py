"""Run the collector. UDP on two ports: ordinary and critical (the SDN classifies on these ports).
  python3 -m collector.main --db data/logs.db --udp-port 9001 --crit-port 9101 [--tcp-port 9000]
On SIGINT/SIGTERM it writes --summary (JSON) with counters and sequence-gap estimates."""
import argparse, json, signal, threading, time
from .storage import LogStorage
from .processor import Processor
from .tcp_server import TCPCollector
from .udp_server import UDPCollector

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--udp-port", type=int, default=9001)
    ap.add_argument("--crit-port", type=int, default=9101)
    ap.add_argument("--tcp-port", type=int, default=0, help="0 = TCP disabled")
    ap.add_argument("--db", default="data/logs.db")
    ap.add_argument("--summary", default="")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    st = LogStorage(a.db); proc = Processor(st, verbose=not a.quiet)
    udps = [UDPCollector(proc, a.host, a.udp_port).start(), UDPCollector(proc, a.host, a.crit_port).start()]
    if a.tcp_port:
        TCPCollector(proc, a.host, a.tcp_port).start()
    done = threading.Event()
    for sg in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sg, lambda *_: done.set())
    print(f"collector up: UDP {a.udp_port} (ordinary) {a.crit_port} (critical) db={a.db}", flush=True)
    while not done.wait(5):
        print("stats:", proc.snapshot(), "rows:", st.count(), flush=True)
    for u in udps: u.stop()
    summary = {"counters": proc.snapshot(), "udp_loss": proc.loss_report("UDP"), "rows": st.count()}
    if a.summary:
        json.dump(summary, open(a.summary, "w"), indent=1)
    print("final:", summary, flush=True)
