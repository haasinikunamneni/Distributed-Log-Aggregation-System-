"""SQLite persistence. event_id is UNIQUE so retried events are not stored twice."""
import sqlite3, threading
from typing import Optional
from .schema import LogEvent

DDL = """
CREATE TABLE IF NOT EXISTS logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL UNIQUE,
  timestamp REAL NOT NULL,      -- sender time
  recv_ts REAL NOT NULL,        -- collector receive time
  source_id TEXT NOT NULL,
  service TEXT NOT NULL,
  severity TEXT NOT NULL,
  message TEXT NOT NULL,
  protocol TEXT NOT NULL,       -- actual transport the collector saw
  seq INTEGER,
  peer TEXT,
  experiment_id TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_logs_ts ON logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_logs_src ON logs(source_id);
CREATE INDEX IF NOT EXISTS idx_logs_sev ON logs(severity);
"""


class LogStorage:
    def __init__(self, path: str = "data/logs.db"):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(DDL)

    def insert(self, ev: LogEvent, recv_ts: float, peer: str = "") -> bool:
        """Returns True if stored, False if it was a duplicate event_id."""
        with self._lock:
            cur = self._db.execute(
                "INSERT OR IGNORE INTO logs(event_id,timestamp,recv_ts,source_id,service,severity,message,protocol,seq,peer,experiment_id)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (ev.event_id, ev.timestamp, recv_ts, ev.source_id, ev.service, ev.severity,
                 ev.message, ev.protocol, ev.seq, peer, ev.experiment_id))
            self._db.commit()
            return cur.rowcount == 1

    def query(self, source: Optional[str] = None, severity: Optional[str] = None,
              protocol: Optional[str] = None, since: Optional[float] = None,
              until: Optional[float] = None, limit: int = 100):
        sql, args = "SELECT * FROM logs WHERE 1=1", []
        for col, val in (("source_id", source), ("severity", severity), ("protocol", protocol)):
            if val:
                sql += f" AND {col}=?"; args.append(val)
        if since is not None:
            sql += " AND timestamp>=?"; args.append(since)
        if until is not None:
            sql += " AND timestamp<=?"; args.append(until)
        sql += " ORDER BY id DESC LIMIT ?"; args.append(limit)
        with self._lock:
            return [dict(r) for r in self._db.execute(sql, args).fetchall()]

    def count(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM logs").fetchone()[0]

    def close(self):
        with self._lock:
            self._db.close()
