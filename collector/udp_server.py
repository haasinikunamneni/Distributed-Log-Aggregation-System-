"""UDP collector. One datagram = one JSON log event. No connection, ack, ordering or retransmission.
The receive thread only timestamps the datagram and puts it on a BOUNDED queue; a worker thread does
validation + SQLite. If the queue is full (DB slower than the network) the datagram is dropped and counted
as 'UDP.queue_overflow' - the receiver never blocks."""
import queue, socket, threading, time


class UDPCollector:
    def __init__(self, processor, host="0.0.0.0", port=9001, queue_size=20000, label="UDP"):
        self.processor, self.label = processor, label
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
        self.sock.bind((host, port)); self.sock.settimeout(0.2)
        self.port = self.sock.getsockname()[1]
        self.q = queue.Queue(maxsize=queue_size)
        self._stop = threading.Event()
        self._rx = threading.Thread(target=self._recv_loop, daemon=True)
        self._wk = threading.Thread(target=self._work_loop, daemon=True)

    def _recv_loop(self):
        while not self._stop.is_set():
            try:
                data, addr = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                self.q.put_nowait((data, f"{addr[0]}:{addr[1]}", time.time()))
            except queue.Full:
                self.processor.count_error("UDP", "queue_overflow", "bounded queue full, datagram dropped")

    def _work_loop(self):
        while not (self._stop.is_set() and self.q.empty()):
            try:
                data, peer, ts = self.q.get(timeout=0.2)
            except queue.Empty:
                continue
            self.processor.handle(data, "UDP", peer, ts)

    def start(self):
        self._rx.start(); self._wk.start(); return self

    def stop(self):
        deadline = time.time() + 5          # let the worker drain what was already received
        while not self.q.empty() and time.time() < deadline:
            time.sleep(0.05)
        self._stop.set(); self._rx.join(timeout=2); self._wk.join(timeout=2); self.sock.close()
