"""Configurable synthetic log source (rate, size, severity mix, count)."""
import random, time, uuid
from collector.schema import LogEvent, SEVERITIES

DEFAULT_WEIGHTS = {"DEBUG": 20, "INFO": 55, "WARNING": 15, "ERROR": 8, "CRITICAL": 2}


def generate_events(source_id, service="app", protocol="TCP", count=100, size=120,
                    weights=None, seed=None, experiment_id=""):
    rnd = random.Random(seed)
    w = weights or DEFAULT_WEIGHTS
    sev = rnd.choices(SEVERITIES, weights=[w.get(s, 0) for s in SEVERITIES], k=count)
    for seq in range(count):
        base = f"{service} event {seq} from {source_id} "
        msg = (base + "x" * max(0, size - len(base)))[:max(size, 1)]
        yield LogEvent(uuid.uuid4().hex, time.time(), source_id, service, sev[seq], msg, protocol, seq, experiment_id)


def paced(events, rate):
    """Yield events at `rate` events/s (0 = as fast as possible)."""
    start, n = time.perf_counter(), 0
    for ev in events:
        if rate > 0:
            delay = start + n / rate - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
        n += 1
        ev.timestamp = time.time()          # stamp at actual send time
        yield ev
