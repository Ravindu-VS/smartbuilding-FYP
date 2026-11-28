"""
Structured JSON logs shared by every service (edge brain, ingestion, ML API, trainer).

One JSON object per line on stdout, so `docker compose logs`, journald and any log shipper can parse it:

    {"ts": "2026-11-28T10:15:02.113Z", "level": "INFO", "service": "ingestion", "logger": "ingest",
     "msg": "stored reading", "room_id": "f2_office_a", "msg_id": "a1b2"}

Context fields (room_id, device_id, msg_id, request_id, model_version, ...) are passed with
`logger.info("...", extra={"room_id": ...})`. Values whose key looks like a secret are never written.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone

CONTEXT_KEYS = ("room_id", "device_id", "msg_id", "request_id", "model_version", "endpoint", "status",
                "duration_ms", "topic", "event")
SECRET_HINTS = ("password", "passwd", "secret", "token", "api_key", "apikey", "authorization")


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str):
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        out = {"ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds")
               .replace("+00:00", "Z"),
               "level": record.levelname, "service": self.service, "logger": record.name,
               "msg": record.getMessage()}
        for k in CONTEXT_KEYS:
            v = getattr(record, k, None)
            if v is not None:
                out[k] = v
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(redact(out), default=str, ensure_ascii=False)


def redact(d: dict) -> dict:
    return {k: ("***" if any(h in k.lower() for h in SECRET_HINTS) else v) for k, v in d.items()}


def setup(service: str, level: str | None = None, fmt: str | None = None, stream=None) -> None:
    """Configure the root logger. fmt 'json' (default for containers) or 'text'; LOG_FORMAT/LOG_LEVEL override.
    CLIs that print a result on stdout pass stream=sys.stderr."""
    fmt = (fmt or os.environ.get("LOG_FORMAT", "json")).lower()
    level = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()
    handler = logging.StreamHandler(stream or sys.stdout)
    if fmt == "json":
        handler.setFormatter(JsonFormatter(service))
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%H:%M:%S"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for noisy in ("werkzeug", "urllib3", "alembic", "httpx"):
        logging.getLogger(noisy).setLevel(max(logging.WARNING, root.level))
