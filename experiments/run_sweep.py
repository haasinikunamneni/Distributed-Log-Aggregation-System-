"""Vary ONE factor at a time (message size, share of critical logs, send rate) and run baseline + priority for each.
  sudo python3 -m experiments.run_sweep --factor size|critical|rate
Writes results/sweep.csv (one row per case and mode)."""
import argparse, csv, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from mininet.log import setLogLevel
from experiments.run_experiment import run_once, WEIGHTS

def mix(crit):          # critical share in percent; the other levels keep the same relative proportions
    rest = 100 - crit; base = {"DEBUG": 30, "INFO": 40, "WARNING": 15, "ERROR": 5}; tot = sum(base.values())
    w = {k: round(v * rest / tot, 2) for k, v in base.items()}; w["CRITICAL"] = crit
    return ",".join(f"{k}={v}" for k, v in w.items())

CASES = {"size": [("message size (bytes)", v) for v in (100, 200, 400)],
         "critical": [("critical share (%)", v) for v in (5, 10, 30)],
         "rate": [("rate per client (msg/s)", v) for v in (100, 200, 300)]}

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--factor", choices=CASES, required=True)
    f = ap.parse_args().factor
    setLogLevel("warning")
    out = os.path.join(ROOT, "results", "sweep.csv"); new = not os.path.exists(out)
    for label, v in CASES[f]:
        for mode in ("baseline", "priority"):
            a = argparse.Namespace(datapath="user", rate_bps=1_000_000, count=1000, rate=200, size=200, weights=WEIGHTS)
            if f == "size": a.size = v
            elif f == "rate": a.rate = v; a.count = int(v * 5)
            else: a.weights = mix(v)
            rid = f"sweep-{f}{v}-{mode}_{int(time.time())}"
            res = run_once(mode, rid, a); m = res["metrics"]
            with open(out, "a", newline="") as fh:
                w = csv.writer(fh)
                if new: w.writerow(["factor", "value", "mode", "crit_sent", "crit_delivery", "crit_delay_ms", "ord_sent", "ord_delivery", "ord_delay_ms"]); new = False
                w.writerow([f, v, mode, m["critical"]["sent"], round(m["critical"]["delivery_ratio"], 3), round(m["critical"]["delay_ms_mean"] or 0, 2),
                            m["ordinary"]["sent"], round(m["ordinary"]["delivery_ratio"], 3), round(m["ordinary"]["delay_ms_mean"] or 0, 2)])
            print(f, v, mode, "crit", round(m["critical"]["delivery_ratio"], 3), round(m["critical"]["delay_ms_mean"] or 0, 2),
                  "ord", round(m["ordinary"]["delivery_ratio"], 3), round(m["ordinary"]["delay_ms_mean"] or 0, 2), flush=True)
