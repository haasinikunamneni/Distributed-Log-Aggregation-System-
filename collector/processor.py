"""Ingestion pipeline shared by TCP and UDP: validate -> normalize -> store -> count.
Also tracks per-source sequence numbers to estimate loss."""
import threading, time
from collections import defaultdict
from .schema import parse_event, ValidationError, MAX_DATAGRAM
from .storage import LogStorage


class Processor:
    def __init__(self, storage: LogStorage, verbose: bool = False):
        self.storage, self.verbose = storage, verbose
        self._lock = threading.Lock()
        self.stats = defaultdict(int)       # keys like "TCP.stored", "UDP.invalid"
        self._seqs = defaultdict(set)       # (protocol, source) -> set of seqs seen

    def handle(self, raw: bytes, protocol: str, peer: str = "", recv_ts: float = None) -> str:
        """Returns 'stored' | 'duplicate' | 'invalid' | 'oversized'."""
        if protocol == "UDP" and len(raw) > MAX_DATAGRAM:
            return self._count(protocol, "oversized", f"{peer} oversized datagram ({len(raw)} B)")
        try:
            ev = parse_event(raw)
        except ValidationError as e:
            return self._count(protocol, "invalid", f"{peer} rejected: {e}")
        ev.protocol = protocol              # normalize: trust the transport we actually saw
        stored = self.storage.insert(ev, recv_ts if recv_ts is not None else time.time(), peer)
        if ev.seq is not None:
            with self._lock:
                self._seqs[(protocol, ev.source_id)].add(ev.seq)
        return self._count(protocol, "stored" if stored else "duplicate",
                           f"{peer} {ev.source_id} {ev.severity} seq={ev.seq}")

    def count_error(self, protocol: str, kind: str, note: str = ""):
        self._count(protocol, kind, note)

    def _count(self, protocol, kind, note):
        with self._lock:
            self.stats[f"{protocol}.{kind}"] += 1
        if self.verbose:
            print(f"[{protocol}] {kind}: {note}", flush=True)
        return kind

    def loss_report(self, protocol: str = "UDP"):
        """Per source: expected = max-min+1 (sequence range), received unique, estimated missing.
        Limitation: trailing losses after the last received seq are invisible."""
        out = {}
        with self._lock:
            for (proto, src), seqs in self._seqs.items():
                if proto != protocol or not seqs:
                    continue
                expected = max(seqs) - min(seqs) + 1
                out[src] = {"received": len(seqs), "expected": expected, "missing": expected - len(seqs)}
        return out

    def snapshot(self):
        with self._lock:
            return dict(self.stats)
