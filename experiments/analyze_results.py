"""Aggregate results/summary.csv and plot baseline vs priority (matplotlib). Run: python3 -m experiments.analyze_results"""
import csv, os, statistics, collections
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
rows = list(csv.DictReader(open(os.path.join(ROOT, "results", "summary.csv"))))
rows = [r for r in rows if "test" not in r["run_id"].split("_")[0]]          # ignore smoke-test runs
g = collections.defaultdict(list)
for r in rows:
    g[(r["mode"], r["class"])].append(r)

def stat(mode, cls, key):
    xs = [float(r[key]) for r in g[(mode, cls)] if r[key] not in ("", "None")]
    return (statistics.mean(xs), statistics.pstdev(xs) if len(xs) > 1 else 0.0, len(xs)) if xs else (0, 0, 0)

os.makedirs(os.path.join(ROOT, "results", "plots"), exist_ok=True)
lines = ["| class | metric | baseline (mean +/- sd) | priority (mean +/- sd) | runs |", "|---|---|---|---|---|"]
for cls in ("critical", "ordinary"):
    for key in ("delivery_ratio", "loss_ratio", "delay_ms_mean", "delay_ms_median", "delay_ms_p95"):
        b, p = stat("baseline", cls, key), stat("priority", cls, key)
        lines.append(f"| {cls} | {key} | {b[0]:.3f} +/- {b[1]:.3f} | {p[0]:.3f} +/- {p[1]:.3f} | {b[2]}/{p[2]} |")
open(os.path.join(ROOT, "results", "analysis.md"), "w").write("\n".join(lines) + "\n")
print("\n".join(lines))

for key, title, fname in (("delivery_ratio", "Delivery ratio (received/sent)", "delivery_ratio.png"),
                          ("delay_ms_mean", "Mean delivery delay (ms)", "delay_mean.png"),
                          ("delay_ms_p95", "95th percentile delay (ms)", "delay_p95.png")):
    fig, ax = plt.subplots(figsize=(5.5, 3.6))
    for i, mode in enumerate(("baseline", "priority")):
        vals = [stat(mode, c, key) for c in ("critical", "ordinary")]
        ax.bar([x + i * 0.38 for x in (0, 1)], [v[0] for v in vals], 0.36, yerr=[v[1] for v in vals], label=mode, capsize=3)
    ax.set_xticks([0.19, 1.19]); ax.set_xticklabels(["critical", "ordinary"]); ax.set_title(title); ax.legend()
    fig.tight_layout(); fig.savefig(os.path.join(ROOT, "results", "plots", fname), dpi=140); plt.close(fig)
print("plots in results/plots/")
