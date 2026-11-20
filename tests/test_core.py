import json, socket, threading, time, pytest
from collector.schema import parse_event, ValidationError, MAX_DATAGRAM
from collector.storage import LogStorage
from collector.processor import Processor
from collector.tcp_server import TCPCollector
from collector.udp_server import UDPCollector
from clients.log_generator import generate_events
from clients.tcp_client import TCPLogClient
from clients.udp_client import UDPLogClient


def wait_for(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond(): return True
        time.sleep(0.02)
    return False


@pytest.fixture
def stack(tmp_path):
    st = LogStorage(str(tmp_path / "t.db")); p = Processor(st)
    tcp = TCPCollector(p, "127.0.0.1", 0).start(); udp = UDPCollector(p, "127.0.0.1", 0).start()
    yield st, p, tcp, udp
    tcp.stop(); udp.stop(); st.close()


def ev(**kw):
    d = dict(event_id="e1", timestamp=1.0, source_id="s", service="a", severity="INFO", message="m", protocol="TCP", seq=0)
    d.update(kw); return d


def test_parse_valid():
    assert parse_event(json.dumps(ev()).encode()).source_id == "s"

@pytest.mark.parametrize("bad", [b"not json", b"[1,2]", b"\xff\xfe", json.dumps(ev(severity="LOUD")).encode(),
                                 json.dumps(ev(seq=-1)).encode(), json.dumps(ev(timestamp="x")).encode(),
                                 json.dumps({k: v for k, v in ev().items() if k != "event_id"}).encode()])
def test_parse_invalid(bad):
    with pytest.raises(ValidationError): parse_event(bad)


def test_duplicate_event_id_not_stored(tmp_path):
    st = LogStorage(str(tmp_path / "d.db")); e = parse_event(json.dumps(ev()).encode())
    assert st.insert(e, time.time()) is True and st.insert(e, time.time()) is False and st.count() == 1

def test_query_filters(tmp_path):
    st = LogStorage(str(tmp_path / "q.db"))
    for i, sev in enumerate(["INFO", "ERROR", "ERROR"]):
        st.insert(parse_event(json.dumps(ev(event_id=f"x{i}", severity=sev, timestamp=10.0 + i)).encode()), time.time())
    assert len(st.query(severity="ERROR")) == 2
    assert len(st.query(since=11.0, until=11.5)) == 1


def test_tcp_partial_and_coalesced_reads(stack):
    st, p, tcp, _ = stack
    msgs = [json.dumps(ev(event_id=f"p{i}", seq=i)).encode() + b"\n" for i in range(3)]
    blob = b"".join(msgs)
    s = socket.create_connection(("127.0.0.1", tcp.port))
    for i in range(0, len(blob), 7):            # 7 bytes at a time: forces partial reads
        s.sendall(blob[i:i + 7]); time.sleep(0.001)
    s.sendall(blob)                              # then all three coalesced in one send (duplicates)
    s.close()
    assert wait_for(lambda: st.count() == 3)
    assert wait_for(lambda: p.snapshot().get("TCP.duplicate") == 3)

def test_tcp_malformed_does_not_kill_connection(stack):
    st, p, tcp, _ = stack
    s = socket.create_connection(("127.0.0.1", tcp.port))
    s.sendall(b"garbage\n" + json.dumps(ev(event_id="ok")).encode() + b"\n"); s.close()
    assert wait_for(lambda: st.count() == 1) and p.snapshot()["TCP.invalid"] == 1

def test_tcp_oversized_frame_closes_connection(stack):
    st, p, tcp, _ = stack
    s = socket.create_connection(("127.0.0.1", tcp.port))
    try: s.sendall(b"A" * 200_000)
    except OSError: pass
    s.close()
    assert wait_for(lambda: p.snapshot().get("TCP.oversized", 0) >= 1)

def test_tcp_concurrent_clients(stack):
    st, p, tcp, _ = stack
    def run(name):
        c = TCPLogClient("127.0.0.1", tcp.port); c.connect()
        for e in generate_events(name, protocol="TCP", count=100): c.send(e)
        c.close()
    ts = [threading.Thread(target=run, args=(f"c{i}",)) for i in range(5)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert wait_for(lambda: st.count() == 500)

def test_tcp_client_reconnects_after_collector_restart(tmp_path):
    st = LogStorage(str(tmp_path / "r.db")); p = Processor(st)
    tcp = TCPCollector(p, "127.0.0.1", 0).start(); port = tcp.port
    c = TCPLogClient("127.0.0.1", port, retries=10, backoff=0.1); c.connect()
    evs = list(generate_events("rc", protocol="TCP", count=6))
    for e in evs[:3]: c.send(e)
    assert wait_for(lambda: st.count() == 3)
    tcp.stop(); time.sleep(0.2)
    tcp2 = TCPCollector(p, "127.0.0.1", port).start()
    for e in evs[3:]:
        c.send(e); time.sleep(0.05)
    assert wait_for(lambda: st.count() >= 5)     # the in-flight message at the break may be lost
    tcp2.stop(); st.close()


def test_udp_delivery_and_gap_detection(stack):
    st, p, _, udp = stack
    c = UDPLogClient("127.0.0.1", udp.port)
    for e in generate_events("u1", protocol="UDP", count=10):
        if e.seq in (3, 4): continue             # deliberately skip two datagrams
        c.send(e)
    assert wait_for(lambda: st.count() == 8)
    assert p.loss_report("UDP")["u1"] == {"received": 8, "expected": 10, "missing": 2}

def test_udp_invalid_and_oversized(stack):
    st, p, _, udp = stack
    c = UDPLogClient("127.0.0.1", udp.port)
    c.send_raw(b"nope"); c.send_raw(b"{" + b"x" * (MAX_DATAGRAM + 10))
    assert wait_for(lambda: p.snapshot().get("UDP.invalid") == 1 and p.snapshot().get("UDP.oversized") == 1)
    assert st.count() == 0

def test_protocol_normalized_to_actual_transport(stack):
    st, p, tcp, _ = stack
    s = socket.create_connection(("127.0.0.1", tcp.port))
    s.sendall(json.dumps(ev(protocol="UDP")).encode() + b"\n"); s.close()
    assert wait_for(lambda: st.count() == 1) and st.query()[0]["protocol"] == "TCP"
