"""Bottleneck scheduling on the egress port s1-eth4 (Linux tc HTB). Run as root.
  baseline : one class, rate = bottleneck rate (identical bottleneck, no priority)
  priority : critical class (HTB prio 0, rate 70%, may borrow up to 100%) and ordinary class (prio 1, rate 30%);
             a tc filter sends packets with DSCP 46 (marked by the OpenFlow rule) to the critical class.
Classification = OpenFlow rule (UDP port -> DSCP).  Forwarding = output action.  Scheduling = THIS file (tc).
Alternative on a kernel-datapath OVS: CLASSIFY=queue + ovs_queue_config() below (OVS QoS queues)."""
import subprocess
LIMIT = 100   # packets per class queue (bounded buffer so drops happen inside the scheduler)

def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)

def clear(port="s1-eth4"):
    sh(f"tc qdisc del dev {port} root 2>/dev/null; ovs-vsctl clear port {port} qos 2>/dev/null")

def configure(mode, rate_bps, port="s1-eth4"):
    clear(port)
    B = int(rate_bps)
    cmds = [f"tc qdisc add dev {port} root handle 1: htb default 12",
            f"tc class add dev {port} parent 1: classid 1:10 htb rate {B}bit ceil {B}bit"]
    if mode == "baseline":
        cmds += [f"tc class add dev {port} parent 1:10 classid 1:12 htb rate {B}bit ceil {B}bit prio 1",
                 f"tc qdisc add dev {port} parent 1:12 handle 112: pfifo limit {LIMIT}"]
    else:
        cmds += [f"tc class add dev {port} parent 1:10 classid 1:11 htb rate {int(B*0.7)}bit ceil {B}bit prio 0",
                 f"tc class add dev {port} parent 1:10 classid 1:12 htb rate {int(B*0.3)}bit ceil {B}bit prio 1",
                 f"tc qdisc add dev {port} parent 1:11 handle 111: pfifo limit {LIMIT}",
                 f"tc qdisc add dev {port} parent 1:12 handle 112: pfifo limit {LIMIT}",
                 f"tc filter add dev {port} parent 1: protocol ip prio 1 u32 match ip dsfield 0xb8 0xfc flowid 1:11"]
    for c in cmds:
        r = sh(c)
        if r.returncode != 0:
            return False, f"{c}: {r.stderr.strip()}"
    return True, ""

def show(port="s1-eth4"):
    return sh(f"tc -s qdisc show dev {port}; tc qdisc show dev {port}; tc -s class show dev {port}; tc filter show dev {port}").stdout

def ovs_queue_config(mode, rate_bps, port="s1-eth4"):
    """Kernel-datapath alternative: OVS QoS queues (works only if set_queue reaches the kernel qdisc)."""
    B = int(rate_bps)
    q = (f"-- --id=@q0 create queue other-config:min-rate={int(B*0.1)} other-config:max-rate={B} other-config:priority=2 "
         f"-- --id=@q1 create queue other-config:min-rate={int(B*0.7)} other-config:max-rate={B} other-config:priority=1")
    r = sh(f"ovs-vsctl -- set port {port} qos=@qos -- --id=@qos create qos type=linux-htb "
           f"other-config:max-rate={B} queues:0=@q0 queues:1=@q1 {q}")
    return r.returncode == 0, r.stderr.strip()
