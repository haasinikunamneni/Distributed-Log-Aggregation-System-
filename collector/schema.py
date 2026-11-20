"""Shared log-event schema + validation. Wire format: one JSON object per message.
TCP framing: newline-delimited JSON (NDJSON). UDP: one JSON object per datagram."""
import json
from dataclasses import dataclass, asdict
from typing import Optional

SEVERITIES = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
PROTOCOLS = ("TCP", "UDP")
MAX_MESSAGE_LEN = 4096          # max chars in the "message" field
MAX_DATAGRAM = 8192             # UDP payloads larger than this are rejected
MAX_TCP_LINE = 65536            # TCP line longer than this without '\n' => protocol abuse


class ValidationError(ValueError):
    pass


@dataclass
class LogEvent:
    event_id: str
    timestamp: float            # sender wall-clock, epoch seconds
    source_id: str
    service: str
    severity: str
    message: str
    protocol: str
    seq: Optional[int] = None   # per-source sequence number (loss analysis)
    experiment_id: str = ""     # which experiment run produced this event

    def to_bytes(self) -> bytes:
        return json.dumps(asdict(self), separators=(",", ":")).encode("utf-8")


def parse_event(raw: bytes) -> LogEvent:
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValidationError(f"not valid UTF-8 JSON: {e}")
    if not isinstance(obj, dict):
        raise ValidationError("top-level JSON value must be an object")
    for f in ("event_id", "timestamp", "source_id", "service", "severity", "message", "protocol"):
        if f not in obj:
            raise ValidationError(f"missing field: {f}")
    for f in ("event_id", "source_id", "service", "severity", "message", "protocol"):
        if not isinstance(obj[f], str) or (f != "message" and not obj[f]):
            raise ValidationError(f"field {f} must be a non-empty string")
    ts = obj["timestamp"]
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        raise ValidationError("timestamp must be a number (epoch seconds)")
    if obj["severity"] not in SEVERITIES:
        raise ValidationError(f"bad severity: {obj['severity']}")
    if obj["protocol"] not in PROTOCOLS:
        raise ValidationError(f"bad protocol: {obj['protocol']}")
    if len(obj["message"]) > MAX_MESSAGE_LEN:
        raise ValidationError("message too long")
    seq = obj.get("seq")
    if seq is not None and (isinstance(seq, bool) or not isinstance(seq, int) or seq < 0):
        raise ValidationError("seq must be a non-negative integer")
    return LogEvent(obj["event_id"], float(ts), obj["source_id"], obj["service"],
                    obj["severity"], obj["message"], obj["protocol"], seq,
                    str(obj.get("experiment_id", "")))
