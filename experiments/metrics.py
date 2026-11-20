"""Compute delivery metrics from the collector DB + client manifests (all measured, nothing assumed).
delivery_ratio = received unique event_ids / sent;  loss_ratio = 1 - delivery_ratio (sequences are 0..n-1 per source,
so 'expected' is exactly what each client reports sending).  delay = collector recv_ts - client send timestamp
(same machine clock: Mininet hosts share the VM kernel clock)."""
import sqlite3, statistics


def pct(xs, q):
    if not xs: return None
    xs = sorted(xs); k = (len(xs) - 1) * q
    f = int(k); c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def summarize(db_path, manifests, duration_s):
    db = sqlite3.connect(db_path)
    rows = db.execute("select severity, recv_ts - timestamp from logs").fetchall()
    out = {}
    for cls in ("critical", "ordinary", "all"):
        sent = sum(m["sent"].get(cls, 0) for m in manifests) if cls != "all" else sum(m["total"] for m in manifests)
        sel = [d for sev, d in rows if cls == "all" or (sev == "CRITICAL") == (cls == "critical")]
        ms = [d * 1000 for d in sel]
        out[cls] = {"sent": sent, "received": len(sel), "missing": sent - len(sel),
                    "delivery_ratio": len(sel) / sent if sent else None,
                    "loss_ratio": 1 - len(sel) / sent if sent else None,
                    "delay_ms_mean": statistics.mean(ms) if ms else None,
                    "delay_ms_median": pct(ms, .5), "delay_ms_p95": pct(ms, .95),
                    "throughput_msgs_per_s": len(sel) / duration_s if duration_s else None}
    return out
