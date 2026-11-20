"""Mininet topology (run with sudo, Linux only).
   h1,h2,h3 (10.0.0.1-3) -- s1 ==[bottleneck s1-eth4 <-> s2-eth1]== s2 -- hc (collector, 10.0.0.100)
Port numbers are fixed so the controller knows the bottleneck: s1 port 4."""
from functools import partial
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.link import Link

COLLECTOR_IP = "10.0.0.100"


def build(controller_ip="127.0.0.1", controller_port=6653, datapath="user"):
    """datapath='user' works everywhere (userspace OVS). On a normal Ubuntu VM 'kernel' is faster."""
    net = Mininet(controller=None, link=Link, autoSetMacs=True,
                  switch=partial(OVSSwitch, protocols="OpenFlow13", datapath=datapath))
    net.addController("c0", controller=RemoteController, ip=controller_ip, port=controller_port)
    s1, s2 = net.addSwitch("s1", dpid="1"), net.addSwitch("s2", dpid="2")
    for i in (1, 2, 3):
        h = net.addHost(f"h{i}", ip=f"10.0.0.{i}/24")
        net.addLink(h, s1, port2=i)
    net.addLink(s1, s2, port1=4, port2=1)                 # bottleneck link
    hc = net.addHost("hc", ip=f"{COLLECTOR_IP}/24")
    net.addLink(hc, s2, port2=2)
    return net


def disable_offload(net):
    """Userspace OVS (and veth) can emit packets with a partial/offloaded checksum that the receiving host then
    discards. Turning TX offload off on every host interface makes UDP checksums real."""
    for h in net.hosts:
        for intf in h.intfNames():
            h.cmd(f"ethtool -K {intf} tx off rx off gso off gro off tso off")


if __name__ == "__main__":
    from mininet.cli import CLI
    from mininet.log import setLogLevel
    setLogLevel("info")
    n = build(); n.start(); disable_offload(n); CLI(n); n.stop()
