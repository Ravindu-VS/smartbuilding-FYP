"""
Persistent store for the edge brain (SQLite, schema migrations).

Every row carries its provenance (data_source classes in data/manifest.json):
  room101_measured   readings from the real room's board (HTTP or MQTT)
  synthetic          simulated rooms (the twin)
  prediction         model outputs (occupancy probabilities, temperature forecasts, shadow models)
  derived            values computed from others
A model prediction is never written as a measurement.

Migrations are applied in order at start-up and recorded in schema_migrations; applying them
again is a no-op, so restarting the service never duplicates tables or rows, and historical
data is never dropped.  WAL journal mode lets the API read while the control loop writes.
Duplicate board messages (same room and msg_id) are ignored by a unique index.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

PROVENANCE = ("room101_measured", "synthetic", "prediction", "derived", "public_real")

MIGRATIONS: List[tuple] = [
    (1, "readings, decisions, events, predictions, commands", """
        CREATE TABLE readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL, room_id TEXT NOT NULL, room_number INTEGER,
            provenance TEXT NOT NULL CHECK (provenance IN ('room101_measured','synthetic','derived')),
            source TEXT, msg_id TEXT,
            temperature_c REAL, humidity_pct REAL, lux REAL, co2_ppm REAL, co2_source TEXT,
            presence INTEGER, pir INTEGER, power_w REAL,
            flags TEXT, received_utc TEXT NOT NULL);
        CREATE UNIQUE INDEX readings_msg ON readings(room_id, msg_id) WHERE msg_id IS NOT NULL;
        CREATE INDEX readings_room_ts ON readings(room_id, ts);
        CREATE TABLE decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL, room_id TEXT NOT NULL, provenance TEXT NOT NULL,
            controller TEXT, model_version TEXT, mode TEXT, p_occupied REAL,
            proposed TEXT, applied TEXT, safety_notes TEXT, failsafe TEXT, verified INTEGER);
        CREATE INDEX decisions_room_ts ON decisions(room_id, ts);
        CREATE TABLE events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL, kind TEXT NOT NULL, room_id TEXT, text TEXT, data TEXT);
        CREATE INDEX events_ts ON events(ts);
        CREATE TABLE predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL, room_id TEXT, task TEXT NOT NULL, model_version TEXT, role TEXT,
            value REAL, truth REAL, provenance TEXT NOT NULL DEFAULT 'prediction' CHECK (provenance = 'prediction'));
        CREATE INDEX predictions_task_ts ON predictions(task, ts);
        CREATE TABLE commands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL, room_id TEXT NOT NULL, msg_id TEXT NOT NULL UNIQUE, transport TEXT,
            payload TEXT, status TEXT NOT NULL, ack_ts TEXT, detail TEXT);
    """),
    (2, "room_snapshots: periodic state of every room (simulated and real) for history", """
        CREATE TABLE room_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL, room_id TEXT NOT NULL, room_number INTEGER, provenance TEXT NOT NULL,
            mode TEXT, temperature_c REAL, humidity_pct REAL, co2_ppm REAL, lux REAL, occupants INTEGER,
            p_occupied REAL, power_w REAL, energy_wh REAL, hvac TEXT, setpoint_c REAL, light TEXT);
        CREATE INDEX room_snapshots_room_ts ON room_snapshots(room_id, ts);
    """),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Store:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=10.0)
        self.db.row_factory = sqlite3.Row
        if path != ":memory:":
            self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.applied = self.migrate()

    # ------------------------------------------------------------------ schema
    def migrate(self) -> List[int]:
        with self.lock:
            self.db.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, "
                            "applied_utc TEXT NOT NULL, description TEXT)")
            done = {r[0] for r in self.db.execute("SELECT version FROM schema_migrations")}
            applied = []
            for version, desc, sql in MIGRATIONS:
                if version in done:
                    continue
                with self.db:                                  # one transaction per migration
                    self.db.executescript("BEGIN;" + sql + ";")  # executescript commits; wrapped for clarity
                    self.db.execute("INSERT INTO schema_migrations VALUES (?,?,?)", (version, utc_now(), desc))
                applied.append(version)
            self.db.commit()
            return applied

    def schema_version(self) -> int:
        r = self.db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        return int(r[0] or 0)

    # ------------------------------------------------------------------ writes
    def add_reading(self, ts: str, room_id: str, provenance: str, values: Dict[str, Any], *, room_number=None,
                    source: Optional[str] = None, msg_id: Optional[str] = None, flags: Optional[Dict] = None) -> bool:
        """Insert one reading; returns False when (room, msg_id) was already stored (duplicate)."""
        if provenance not in ("room101_measured", "synthetic", "derived"):
            raise ValueError(f"a reading cannot have provenance {provenance!r}")
        with self.lock:
            cur = self.db.execute(
                "INSERT OR IGNORE INTO readings (ts, room_id, room_number, provenance, source, msg_id, temperature_c, "
                "humidity_pct, lux, co2_ppm, co2_source, presence, pir, power_w, flags, received_utc) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ts, room_id, room_number, provenance, source, msg_id, values.get("temperature_c"),
                 values.get("humidity_pct"), values.get("lux"), values.get("co2_ppm"), values.get("co2_source"),
                 _int(values.get("presence")), _int(values.get("pir")), values.get("power_w"),
                 json.dumps(flags) if flags else None, utc_now()))
            self.db.commit()
            return cur.rowcount == 1

    def add_decision(self, ts: str, room_id: str, provenance: str, *, controller: str, mode: str,
                     p_occupied: Optional[float], proposed: Dict, applied: Dict, safety_notes: Sequence[str] = (),
                     failsafe: Optional[str] = None, model_version: Optional[str] = None,
                     verified: Optional[bool] = None) -> None:
        with self.lock:
            self.db.execute(
                "INSERT INTO decisions (ts, room_id, provenance, controller, model_version, mode, p_occupied, proposed, "
                "applied, safety_notes, failsafe, verified) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (ts, room_id, provenance, controller, model_version, mode, p_occupied, json.dumps(proposed),
                 json.dumps(applied), json.dumps(list(safety_notes)), failsafe, _int(verified)))
            self.db.commit()

    def add_event(self, kind: str, text: str, room_id: Optional[str] = None, data: Optional[Dict] = None,
                  ts: Optional[str] = None) -> None:
        with self.lock:
            self.db.execute("INSERT INTO events (ts, kind, room_id, text, data) VALUES (?,?,?,?,?)",
                            (ts or utc_now(), kind, room_id, text, json.dumps(data, default=str) if data else None))
            self.db.commit()

    def add_predictions(self, rows: Iterable[tuple]) -> None:
        """rows: (ts, room_id, task, model_version, role, value, truth)"""
        with self.lock:
            self.db.executemany("INSERT INTO predictions (ts, room_id, task, model_version, role, value, truth) "
                                "VALUES (?,?,?,?,?,?,?)", list(rows))
            self.db.commit()

    def add_snapshots(self, rows: Iterable[Dict]) -> None:
        cols = ("ts", "room_id", "room_number", "provenance", "mode", "temperature_c", "humidity_pct", "co2_ppm",
                "lux", "occupants", "p_occupied", "power_w", "energy_wh", "hvac", "setpoint_c", "light")
        with self.lock:
            self.db.executemany(f"INSERT INTO room_snapshots ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                [tuple(r.get(c) for c in cols) for r in rows])
            self.db.commit()

    def add_command(self, ts: str, room_id: str, msg_id: str, transport: str, payload: Dict) -> None:
        with self.lock:
            self.db.execute("INSERT OR IGNORE INTO commands (ts, room_id, msg_id, transport, payload, status) "
                            "VALUES (?,?,?,?,?, 'sent')", (ts, room_id, msg_id, transport, json.dumps(payload)))
            self.db.commit()

    def ack_command(self, msg_id: str, status: str, detail: Optional[str] = None) -> bool:
        with self.lock:
            cur = self.db.execute("UPDATE commands SET status=?, ack_ts=?, detail=? WHERE msg_id=? AND status='sent'",
                                  (status, utc_now(), detail, msg_id))
            self.db.commit()
            return cur.rowcount == 1

    # ------------------------------------------------------------------ reads
    def history(self, room_id: str, since: Optional[str] = None, until: Optional[str] = None, limit: int = 1000,
                table: str = "room_snapshots") -> List[Dict]:
        if table not in ("room_snapshots", "readings", "decisions", "predictions"):
            raise ValueError("unknown table")
        q, args = f"SELECT * FROM {table} WHERE room_id = ?", [room_id]
        if since:
            q += " AND ts >= ?"
            args.append(since)
        if until:
            q += " AND ts <= ?"
            args.append(until)
        q += " ORDER BY ts DESC, id DESC LIMIT ?"
        args.append(int(min(max(limit, 1), 20000)))
        with self.lock:
            rows = [dict(r) for r in self.db.execute(q, args)]
        return rows[::-1]

    def events(self, limit: int = 100, kind: Optional[str] = None) -> List[Dict]:
        q, args = "SELECT * FROM events", []
        if kind:
            q += " WHERE kind = ?"
            args.append(kind)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(int(min(max(limit, 1), 5000)))
        with self.lock:
            return [dict(r) for r in self.db.execute(q, args)]

    def summary(self) -> Dict:
        with self.lock:
            out = {"path": self.path, "schema_version": self.schema_version(), "tables": {}}
            for t in ("readings", "decisions", "events", "predictions", "commands", "room_snapshots"):
                out["tables"][t] = int(self.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
            out["provenance"] = {
                "readings": {r[0]: r[1] for r in self.db.execute("SELECT provenance, COUNT(*) FROM readings GROUP BY provenance")},
                "room_snapshots": {r[0]: r[1] for r in self.db.execute(
                    "SELECT provenance, COUNT(*) FROM room_snapshots GROUP BY provenance")},
                "predictions": {r[0]: r[1] for r in self.db.execute("SELECT role, COUNT(*) FROM predictions GROUP BY role")},
            }
            out["commands"] = {r[0]: r[1] for r in self.db.execute("SELECT status, COUNT(*) FROM commands GROUP BY status")}
        return out

    def close(self) -> None:
        with self.lock:
            self.db.close()


def _int(v) -> Optional[int]:
    if v is None:
        return None
    return int(bool(v))
