"""OpenFlow 1.3 controller (os-ken, a maintained fork of Ryu with the same API).

Control-plane behaviour:
  1. Learning L2 switch: installs eth_dst -> output flows (connectivity).
  2. Priority policy (env PRIORITY=1): on the bottleneck egress port, UDP packets whose destination port
     is the CRITICAL port are sent to queue 1, ordinary log port to queue 0 (set_queue + output).
     Classification = flow rule (match UDP dst port). Scheduling = OVS QoS queues (sdn/queue_config.py).
  3. Statistics: every STATS_INTERVAL s requests flow, port and queue stats and appends JSON lines
     to STATS_FILE (switch-reported counters, not client or collector counters).
Config via environment: PRIORITY, CRIT_PORT, ORD_PORT, BOTTLENECK_DPID, BOTTLENECK_PORT, STATS_FILE, STATS_INTERVAL."""
import json, os, time
from os_ken.base import app_manager
from os_ken.controller import ofp_event
from os_ken.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, DEAD_DISPATCHER, set_ev_cls
from os_ken.ofproto import ofproto_v1_3
from os_ken.lib.packet import packet, ethernet, ether_types
from os_ken.lib import hub

PRIORITY = os.environ.get("PRIORITY", "0") == "1"
CRIT_PORT = int(os.environ.get("CRIT_PORT", "9101"))
ORD_PORT = int(os.environ.get("ORD_PORT", "9001"))
BN_DPID = int(os.environ.get("BOTTLENECK_DPID", "1"))
BN_PORT = int(os.environ.get("BOTTLENECK_PORT", "4"))
CLASSIFY = os.environ.get("CLASSIFY", "dscp")   # dscp: mark critical packets, tc schedules | queue: OpenFlow set_queue (needs kernel datapath)
CRIT_DSCP = 46                                   # Expedited Forwarding
STATS_FILE = os.environ.get("STATS_FILE", "data/flowstats.jsonl")
STATS_INTERVAL = float(os.environ.get("STATS_INTERVAL", "1"))


class LogSDN(app_manager.OSKenApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.mac_to_port, self.dps = {}, {}
        self.logger.info("controller start: priority=%s crit=%d ord=%d bottleneck=dpid%d:port%d",
                         PRIORITY, CRIT_PORT, ORD_PORT, BN_DPID, BN_PORT)
        hub.spawn(self._poll)

    # ---- helpers
    def add_flow(self, dp, prio, match, actions, idle=0):
        p = dp.ofproto_parser
        inst = [p.OFPInstructionActions(dp.ofproto.OFPIT_APPLY_ACTIONS, actions)]
        dp.send_msg(p.OFPFlowMod(datapath=dp, priority=prio, match=match, instructions=inst, idle_timeout=idle))

    # ---- switch lifecycle
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def on_features(self, ev):
        dp = ev.msg.datapath; p, o = dp.ofproto_parser, dp.ofproto
        self.logger.info("switch connected dpid=%d", dp.id)
        self.add_flow(dp, 0, p.OFPMatch(), [p.OFPActionOutput(o.OFPP_CONTROLLER, o.OFPCML_NO_BUFFER)])

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def on_state(self, ev):
        if ev.state == MAIN_DISPATCHER:
            self.dps[ev.datapath.id] = ev.datapath
        else:
            self.dps.pop(ev.datapath.id, None)

    # ---- learning switch + classification
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def on_packet_in(self, ev):
        msg = ev.msg; dp = msg.datapath; p, o = dp.ofproto_parser, dp.ofproto
        in_port = msg.match["in_port"]
        eth = packet.Packet(msg.data).get_protocol(ethernet.ethernet)
        if eth is None or eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return
        table = self.mac_to_port.setdefault(dp.id, {})
        table[eth.src] = in_port
        out = table.get(eth.dst, o.OFPP_FLOOD)
        if out != o.OFPP_FLOOD:
            if PRIORITY and dp.id == BN_DPID and out == BN_PORT:
                for udp_port, crit in ((CRIT_PORT, True), (ORD_PORT, False)):
                    m = p.OFPMatch(eth_dst=eth.dst, eth_type=0x0800, ip_proto=17, udp_dst=udp_port)
                    if CLASSIFY == "queue":
                        acts = [p.OFPActionSetQueue(1 if crit else 0), p.OFPActionOutput(out)]
                    else:   # classification by UDP port -> DSCP mark; scheduling is done by tc on the egress port
                        acts = ([p.OFPActionSetField(ip_dscp=CRIT_DSCP)] if crit else []) + [p.OFPActionOutput(out)]
                    self.add_flow(dp, 20, m, acts)
                self.logger.info("dpid=%d: %s classification rules for %s -> port %d", dp.id, CLASSIFY, eth.dst, out)
            self.add_flow(dp, 10, p.OFPMatch(eth_dst=eth.dst), [p.OFPActionOutput(out)])
        data = msg.data if msg.buffer_id == o.OFP_NO_BUFFER else None
        dp.send_msg(p.OFPPacketOut(datapath=dp, buffer_id=msg.buffer_id, in_port=in_port,
                                   actions=[p.OFPActionOutput(out)], data=data))

    # ---- statistics (switch-reported)
    def _poll(self):
        while True:
            hub.sleep(STATS_INTERVAL)
            for dp in list(self.dps.values()):
                p, o = dp.ofproto_parser, dp.ofproto
                dp.send_msg(p.OFPFlowStatsRequest(dp))
                dp.send_msg(p.OFPPortStatsRequest(dp, 0, o.OFPP_ANY))
                dp.send_msg(p.OFPQueueStatsRequest(dp, 0, o.OFPP_ANY, o.OFPQ_ALL))

    def _log(self, kind, dpid, rows):
        os.makedirs(os.path.dirname(STATS_FILE) or ".", exist_ok=True)
        with open(STATS_FILE, "a") as f:
            f.write(json.dumps({"t": time.time(), "kind": kind, "dpid": dpid, "rows": rows}) + "\n")

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def on_flow_stats(self, ev):
        rows = [{"priority": s.priority, "match": str(s.match), "packets": s.packet_count,
                 "bytes": s.byte_count, "duration_s": s.duration_sec} for s in ev.msg.body]
        self._log("flow", ev.msg.datapath.id, rows)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def on_port_stats(self, ev):
        rows = [{"port": s.port_no, "rx_packets": s.rx_packets, "tx_packets": s.tx_packets,
                 "rx_bytes": s.rx_bytes, "tx_bytes": s.tx_bytes, "rx_dropped": s.rx_dropped,
                 "tx_dropped": s.tx_dropped} for s in ev.msg.body]
        self._log("port", ev.msg.datapath.id, rows)

    @set_ev_cls(ofp_event.EventOFPQueueStatsReply, MAIN_DISPATCHER)
    def on_queue_stats(self, ev):
        rows = [{"port": s.port_no, "queue": s.queue_id, "tx_packets": s.tx_packets,
                 "tx_bytes": s.tx_bytes, "tx_errors": s.tx_errors} for s in ev.msg.body]
        self._log("queue", ev.msg.datapath.id, rows)
