"""Run one baseline or priority experiment on Mininet (Linux, needs sudo).
  sudo python3 -m experiments.run_experiment --mode baseline --repeat 3
  sudo python3 -m experiments.run_experiment --mode priority --repeat 3
Both modes use the same topology, bottleneck rate, load and traffic mix; only the queue policy differs."""
import argparse, json, os, subprocess, sys, time, csv
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from mininet.log import setLogLevel
from sdn.topology import build, disable_offload, COLLECTOR_IP
from sdn import queue_config
from experiments.metrics import summarize

WEIGHTS = "DEBUG=30,INFO=40,WARNING=15,ERROR=5,CRITICAL=10"


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout


def run_once(mode, run_id, a):
    out = os.path.join(ROOT, "results", run_id); os.makedirs(out, exist_ok=True)
    env = dict(os.environ, PRIORITY="1" if mode == "priority" else "0", STATS_FILE=f"{out}/flowstats.jsonl",
               PYTHONPATH=ROOT)
    sh("mn -c >/dev/null 2>&1")
    # userspace OVS sends through AF_PACKET sockets; a small send buffer would drop packets BEFORE the tc scheduler
    sh("sysctl -w net.core.wmem_default=16777216 net.core.wmem_max=16777216 >/dev/null")
    import socket
    if socket.socket().connect_ex(("127.0.0.1", 6653)) == 0:
        sys.exit("port 6653 already in use: another controller is running. Stop it first (see guide).")
    ctl = subprocess.Popen([sys.executable, "-m", "sdn.run_controller"], cwd=ROOT, env=env,
                           stdout=open(f"{out}/controller.log", "w"), stderr=subprocess.STDOUT)
    time.sleep(3)
    net = build(datapath=a.datapath); net.start(); disable_offload(net); time.sleep(3)
    try:
        ok, err = queue_config.configure(mode, a.rate_bps)
        if not ok: raise RuntimeError("queue config failed: " + err)
        loss = net.pingAll(timeout=2)                      # connectivity + installs forwarding flows
        hc = net.get("hc")
        db = f"{out}/logs.db"
        col = hc.popen(["bash", "-c", f"cd {ROOT} && exec python3 -m collector.main --quiet --db {db} "
                        f"--summary {out}/collector_summary.json"], stdout=open(f"{out}/collector.log", "w"),
                       stderr=subprocess.STDOUT)
        time.sleep(1.5)
        before = sh("tc -s class show dev s1-eth4")
        t0 = time.time(); procs = []
        for i in (1, 2, 3):
            h = net.get(f"h{i}")
            cmd = (f"cd {ROOT} && exec python3 -m clients.udp_client --host {COLLECTOR_IP} --source h{i} "
                   f"--experiment {run_id} --count {a.count} --rate {a.rate} --size {a.size} "
                   f"--weights {a.weights} --seed {i} --manifest {out}/manifest_h{i}.json")
            procs.append(h.popen(["bash", "-c", cmd], stdout=open(f"{out}/client_h{i}.log", "w"), stderr=subprocess.STDOUT))
        for p in procs: p.wait()
        time.sleep(3)                                      # let queued packets drain
        dur = time.time() - t0
        queue_stats = sh("tc -s class show dev s1-eth4")
        flows = {s: sh(f"ovs-ofctl -O OpenFlow13 dump-flows {s}") for s in ("s1", "s2")}
        ports = sh("ovs-ofctl -O OpenFlow13 dump-ports s1")
        qos = queue_config.show()  # tc qdisc/class/filter state
        col.terminate(); col.wait(timeout=10)
    finally:
        net.stop(); ctl.terminate(); ctl.wait(timeout=10); sh("mn -c >/dev/null 2>&1")
    manifests = [json.load(open(f"{out}/manifest_h{i}.json")) for i in (1, 2, 3)]
    res = {"run_id": run_id, "mode": mode, "bottleneck_bps": a.rate_bps, "clients": 3, "count_per_client": a.count,
           "rate_per_client": a.rate, "payload_size": a.size, "duration_s": dur, "ping_loss_pct": loss,
           "metrics": summarize(db, manifests, dur),
           "collector": json.load(open(f"{out}/collector_summary.json"))}
    json.dump(res, open(f"{out}/result.json", "w"), indent=1)
    open(f"{out}/ovs_flows_s1.txt", "w").write(flows["s1"]); open(f"{out}/ovs_flows_s2.txt", "w").write(flows["s2"])
    open(f"{out}/ovs_ports_s1.txt", "w").write(ports); open(f"{out}/qos.txt", "w").write(qos)
    open(f"{out}/tc_class_before.txt", "w").write(before); open(f"{out}/tc_class_after.txt", "w").write(queue_stats)
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["baseline", "priority"], required=True)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--count", type=int, default=1500)
    ap.add_argument("--rate", type=float, default=200, help="messages/s per client")
    ap.add_argument("--size", type=int, default=200, help="message field length (bytes)")
    ap.add_argument("--rate-bps", type=int, default=1_000_000, help="bottleneck bit/s")
    ap.add_argument("--datapath", default="user", choices=["user", "kernel"])
    ap.add_argument("--tag", default="")
    ap.add_argument("--weights", default=WEIGHTS, help="severity mix, e.g. DEBUG=30,INFO=40,WARNING=15,ERROR=5,CRITICAL=10")
    a = ap.parse_args()
    if os.geteuid() != 0: sys.exit("run with sudo")
    setLogLevel("warning")
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    csv_path = os.path.join(ROOT, "results", "summary.csv")
    for r in range(1, a.repeat + 1):
        rid = f"{a.mode}{a.tag}_{int(time.time())}_r{r}"
        res = run_once(a.mode, rid, a)
        m = res["metrics"]; new = not os.path.exists(csv_path)
        with open(csv_path, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["run_id", "mode", "bottleneck_bps", "class", "sent", "received", "delivery_ratio",
                            "loss_ratio", "delay_ms_mean", "delay_ms_median", "delay_ms_p95", "throughput_msgs_per_s"])
            for cls in ("critical", "ordinary", "all"):
                x = m[cls]
                w.writerow([rid, a.mode, a.rate_bps, cls, x["sent"], x["received"], x["delivery_ratio"], x["loss_ratio"],
                            x["delay_ms_mean"], x["delay_ms_median"], x["delay_ms_p95"], x["throughput_msgs_per_s"]])
        print(rid, {k: (round(v["delivery_ratio"], 3), round(v["delay_ms_mean"] or 0, 1)) for k, v in m.items()}, flush=True)
