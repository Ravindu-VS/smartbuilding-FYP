#!/usr/bin/env python3
"""
Telemetry ingestion: MQTT → validation → PostgreSQL (+ optional ML prediction per reading).

Subscribes to the topics the firmware and the edge brain already use (no topic change):
    sb/v1/room/<room>/telemetry   readings  → table telemetry   (idempotent on room_id + msg_id: QoS 1 duplicates)
    sb/v1/room/<room>/status      online/offline (retained)  → table device_events
    sb/v1/room/<room>/ack         command acknowledgements    → table device_events
Validation is the edge brain's own (raspberry_pi.mqtt_bridge.validate_telemetry), so both stores accept and
reject exactly the same messages. Readings from the real board are stored with provenance 'physical';
every other sender (simulated board, test sender, unknown) with 'simulated'.

When ML_API_URL is set every stored reading is also sent to POST /predict and the answer (probability,
model version, latency) is stored in table predictions; the ML API being down never blocks ingestion.

Resilience: the database writer runs on its own thread with a bounded queue. If PostgreSQL goes away the
readings wait in the queue (INGEST_QUEUE_MAX, oldest dropped and counted when full) and are written when
it is back. paho-mqtt reconnects by itself.

    python -m ingestion.service           # DATABASE_URL, MQTT_HOST, MQTT_PORT, MQTT_USERNAME/PASSWORD, MQTT_TLS
    GET :8090/health   GET :8090/metrics
"""
from __future__ import annotations

import json
import logging
import os
import queue
import re
import signal
import ssl
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest  # noqa: E402

from raspberry_pi.mqtt_bridge import PREFIX, validate_telemetry   # noqa: E402

log = logging.getLogger("ingestion")
ROOM_ID = re.compile(r"^[a-z0-9_]{1,32}$")
# Same rule as the edge brain (raspberry_pi.edge_brain.REAL_BOARD_SOURCES; a test keeps them equal): only the real
# board's sender ids are 'physical', anything else (simulated board, test sender, unknown) is 'simulated'.
REAL_BOARD_SOURCES = ("sensor_node", "esp32_room101")

MIGRATIONS = [
    (1, """
    CREATE TABLE IF NOT EXISTS telemetry (
        id            BIGSERIAL PRIMARY KEY,
        received_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        device_ts     TEXT,
        room_id       TEXT NOT NULL,
        msg_id        TEXT NOT NULL,
        provenance    TEXT NOT NULL CHECK (provenance IN ('physical', 'simulated')),
        temperature   DOUBLE PRECISION,
        humidity      DOUBLE PRECISION,
        pressure_hpa  DOUBLE PRECISION,
        lux           DOUBLE PRECISION,
        motion        BOOLEAN,
        mq135_raw     DOUBLE PRECISION,
        mq135_adc_mv  DOUBLE PRECISION,
        mq135_do_high BOOLEAN,
        voltage_v     DOUBLE PRECISION,
        current_ma    DOUBLE PRECISION,
        power_mw      DOUBLE PRECISION,
        fan_on        BOOLEAN,
        relay_on      BOOLEAN,
        rgb           TEXT,
        wifi_rssi_dbm DOUBLE PRECISION,
        uptime_s      DOUBLE PRECISION,
        fw_version    TEXT,
        payload       JSONB NOT NULL,
        UNIQUE (room_id, msg_id)
    );
    CREATE INDEX IF NOT EXISTS telemetry_room_time ON telemetry (room_id, received_at DESC);
    CREATE TABLE IF NOT EXISTS device_events (
        id          BIGSERIAL PRIMARY KEY,
        received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        room_id     TEXT NOT NULL,
        kind        TEXT NOT NULL,
        detail      JSONB
    );
    CREATE TABLE IF NOT EXISTS predictions (
        id            BIGSERIAL PRIMARY KEY,
        created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
        room_id       TEXT NOT NULL,
        msg_id        TEXT NOT NULL,
        model_name    TEXT,
        model_version TEXT,
        probability   DOUBLE PRECISION,
        occupied      BOOLEAN,
        latency_ms    DOUBLE PRECISION,
        UNIQUE (room_id, msg_id, model_version)
    );
    """),
]


class Metrics:
    def __init__(self):
        self.reg = CollectorRegistry()
        r = self.reg
        self.received = Counter("sb_ingest_messages", "MQTT messages received", ["kind"], registry=r)
        self.rejected = Counter("sb_ingest_rejected", "Telemetry rejected by validation", ["reason"], registry=r)
        self.stored = Counter("sb_ingest_rows_stored", "Rows written", ["table", "provenance"], registry=r)
        self.duplicates = Counter("sb_ingest_duplicates", "QoS 1 redeliveries ignored", registry=r)
        self.dropped = Counter("sb_ingest_dropped", "Readings dropped because the queue was full", registry=r)
        self.db_errors = Counter("sb_ingest_db_errors", "Database errors", registry=r)
        self.queue = Gauge("sb_ingest_queue_depth", "Readings waiting for the database", registry=r)
        self.db_up = Gauge("sb_ingest_db_up", "1 while PostgreSQL is reachable", registry=r)
        self.mqtt_up = Gauge("sb_ingest_mqtt_connected", "1 while connected to the broker", registry=r)
        self.last = Gauge("sb_ingest_last_message_timestamp_seconds", "Unix time of the last telemetry message",
                          ["room_id"], registry=r)
        self.write_s = Histogram("sb_ingest_db_write_seconds", "Time to write one batch",
                                 buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 1), registry=r)
        self.pred = Counter("sb_ingest_predictions", "ML API calls", ["result"], registry=r)
        self.room = Gauge("sb_ingest_room_value", "Last stored value per room (physical rooms only)",
                          ["room_id", "field"], registry=r)


class Ingestor:
    def __init__(self, dsn: str, *, mqtt_host: str = "127.0.0.1", mqtt_port: int = 1883, rooms: str = "*",
                 ml_api_url: Optional[str] = None, queue_max: int = 10000, client_id: str = "sb-ingestion"):
        self.dsn, self.mqtt_host, self.mqtt_port = dsn, mqtt_host, mqtt_port
        self.rooms = None if rooms.strip() == "*" else {r.strip() for r in rooms.split(",") if r.strip()}
        self.ml_api_url = (ml_api_url or "").rstrip("/") or None
        self.q: "queue.Queue[tuple]" = queue.Queue(maxsize=queue_max)
        self.m = Metrics()
        self.stop_event = threading.Event()
        self.client_id = client_id
        self.client = None
        self.conn = None
        self.started = time.time()
        self.last_message: Optional[float] = None

    # ------------------------------------------------------------------ database
    def connect_db(self):
        import psycopg
        self.conn = psycopg.connect(self.dsn, autocommit=False, connect_timeout=5)
        self.migrate()
        self.m.db_up.set(1)
        log.info("connected to PostgreSQL")

    def migrate(self):
        with self.conn.cursor() as cur:
            cur.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INT PRIMARY KEY, "
                        "applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
            cur.execute("SELECT coalesce(max(version), 0) FROM schema_migrations")
            done = cur.fetchone()[0]
            for version, sql in MIGRATIONS:
                if version > done:
                    cur.execute(sql)
                    cur.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
                    log.info("applied migration %d", version)
        self.conn.commit()

    def _known(self):
        rooms = self.rooms

        class Known:
            def __contains__(self, room):
                return bool(ROOM_ID.match(str(room))) and (rooms is None or room in rooms)
        return Known()

    # ------------------------------------------------------------------ MQTT
    def on_message(self, topic: str, raw: bytes) -> None:
        parts = topic.split("/")
        if len(parts) != 5 or "/".join(parts[:2]) != PREFIX or parts[2] != "room":
            return
        room, kind = parts[3], parts[4]
        self.m.received.labels(kind).inc()
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = None
        if kind == "telemetry":
            clean, problems = validate_telemetry(room, payload, self._known())
            if clean is None:
                reason = problems[0].split(" ")[0].strip(":") if problems else "invalid"
                self.m.rejected.labels(reason[:32]).inc()
                log.warning("rejected telemetry: %s", "; ".join(problems), extra={"room_id": room, "topic": topic})
                return
            self.last_message = time.time()
            self.m.last.labels(room).set(self.last_message)
            self._enqueue(("telemetry", clean))
        elif kind in ("status", "ack"):
            if not ROOM_ID.match(room):
                return
            detail = payload if isinstance(payload, dict) else {"raw": raw[:200].decode("utf-8", "replace")}
            self._enqueue(("event", {"room_id": room, "kind": kind, "detail": detail}))

    def _enqueue(self, item):
        try:
            self.q.put_nowait(item)
        except queue.Full:
            try:
                self.q.get_nowait()                      # drop the oldest, keep the newest
            except queue.Empty:
                pass
            self.m.dropped.inc()
            self.q.put_nowait(item)
        self.m.queue.set(self.q.qsize())

    def start_mqtt(self):
        import paho.mqtt.client as mqtt
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self.client_id, clean_session=False)
        user = os.environ.get("MQTT_USERNAME")
        if user:
            c.username_pw_set(user, os.environ.get("MQTT_PASSWORD"))
        if os.environ.get("MQTT_TLS", "0") == "1":
            c.tls_set(ca_certs=os.environ.get("MQTT_CA_FILE") or None, cert_reqs=ssl.CERT_REQUIRED)
        c.reconnect_delay_set(1, 30)

        def on_connect(cl, _u, _f, rc, _p=None):
            if not rc.is_failure:
                for kind in ("telemetry", "status", "ack"):
                    cl.subscribe(f"{PREFIX}/room/+/{kind}", qos=1)
                self.m.mqtt_up.set(1)
                log.info("MQTT connected to %s:%d, subscribed to %s/room/+/{telemetry,status,ack}",
                         self.mqtt_host, self.mqtt_port, PREFIX)

        def on_disconnect(_cl, _u, _f, rc, _p=None):
            self.m.mqtt_up.set(0)
            log.warning("MQTT disconnected (%s)", rc)

        c.on_connect = on_connect
        c.on_disconnect = on_disconnect
        c.on_message = lambda _cl, _u, msg: self.on_message(msg.topic, msg.payload)
        c.connect_async(self.mqtt_host, self.mqtt_port, keepalive=30)
        c.loop_start()
        self.client = c

    # ------------------------------------------------------------------ writer
    def writer(self):
        backoff = 1.0
        while not self.stop_event.is_set():
            if self.conn is None or self.conn.closed:
                try:
                    self.connect_db()
                    backoff = 1.0
                except Exception as e:
                    self.m.db_up.set(0)
                    log.warning("PostgreSQL unavailable (%s); %d readings queued", type(e).__name__, self.q.qsize())
                    self.stop_event.wait(backoff)
                    backoff = min(backoff * 2, 30.0)
                    continue
            batch = []
            try:
                batch.append(self.q.get(timeout=0.5))
                while len(batch) < 200:
                    batch.append(self.q.get_nowait())
            except queue.Empty:
                pass
            if not batch:
                continue
            t0 = time.perf_counter()
            try:
                stored = self._write(batch)
                self.conn.commit()
                self.m.write_s.observe(time.perf_counter() - t0)
            except Exception as e:
                self.m.db_errors.inc()
                self.m.db_up.set(0)
                log.warning("write failed (%s: %s); retrying the batch", type(e).__name__, e)
                try:
                    self.conn.close()
                except Exception:
                    pass
                for item in batch:                       # put the batch back in order
                    self._enqueue(item)
                continue
            self.m.queue.set(self.q.qsize())
            if self.ml_api_url:
                for row in stored:
                    self._predict(row)

    def _write(self, batch):
        stored = []
        with self.conn.cursor() as cur:
            for kind, item in batch:
                if kind == "event":
                    cur.execute("INSERT INTO device_events (room_id, kind, detail) VALUES (%s, %s, %s)",
                                (item["room_id"], item["kind"], json.dumps(item["detail"])))
                    self.m.stored.labels("device_events", "-").inc()
                    continue
                row = to_row(item)
                cur.execute("""INSERT INTO telemetry (device_ts, room_id, msg_id, provenance, temperature, humidity,
                        pressure_hpa, lux, motion, mq135_raw, mq135_adc_mv, mq135_do_high, voltage_v, current_ma,
                        power_mw, fan_on, relay_on, rgb, wifi_rssi_dbm, uptime_s, fw_version, payload)
                    VALUES (%(device_ts)s, %(room_id)s, %(msg_id)s, %(provenance)s, %(temperature)s, %(humidity)s,
                        %(pressure_hpa)s, %(lux)s, %(motion)s, %(mq135_raw)s, %(mq135_adc_mv)s, %(mq135_do_high)s,
                        %(voltage_v)s, %(current_ma)s, %(power_mw)s, %(fan_on)s, %(relay_on)s, %(rgb)s,
                        %(wifi_rssi_dbm)s, %(uptime_s)s, %(fw_version)s, %(payload)s)
                    ON CONFLICT (room_id, msg_id) DO NOTHING""", row)
                if cur.rowcount == 0:
                    self.m.duplicates.inc()
                    continue
                self.m.stored.labels("telemetry", row["provenance"]).inc()
                if row["provenance"] == "physical":
                    for f in ("temperature", "humidity", "lux", "power_mw", "current_ma", "voltage_v"):
                        if row[f] is not None:
                            self.m.room.labels(row["room_id"], f).set(row[f])
                    if row["fan_on"] is not None:
                        self.m.room.labels(row["room_id"], "fan_on").set(1 if row["fan_on"] else 0)
                stored.append(row)
        return stored

    def _predict(self, row: Dict):
        if row["temperature"] is None or row["humidity"] is None or row["lux"] is None:
            return
        body = {"temperature": row["temperature"], "humidity": row["humidity"], "lux": row["lux"],
                "room_id": row["room_id"], "timestamp": datetime.now(timezone.utc).isoformat()}
        if row["motion"] is not None:
            body["motion"] = int(row["motion"])
        try:
            req = urllib.request.Request(self.ml_api_url + "/predict", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=2) as r:
                p = json.loads(r.read())
            with self.conn.cursor() as cur:
                cur.execute("""INSERT INTO predictions (room_id, msg_id, model_name, model_version, probability,
                               occupied, latency_ms) VALUES (%s, %s, %s, %s, %s, %s, %s)
                               ON CONFLICT DO NOTHING""",
                            (row["room_id"], row["msg_id"], p["model"]["name"], p["model"]["version"],
                             p["occupancy_probability"], p["occupied"], p["latency_ms"]))
            self.conn.commit()
            self.m.pred.labels("ok").inc()
            self.m.stored.labels("predictions", row["provenance"]).inc()
        except Exception as e:
            self.m.pred.labels("failed").inc()
            log.debug("prediction failed: %s", e)
            try:
                self.conn.rollback()
            except Exception:
                pass

    # ------------------------------------------------------------------ lifecycle
    def health(self) -> Dict:
        db = bool(self.m.db_up._value.get())
        mq = bool(self.m.mqtt_up._value.get())
        return {"status": "ok" if db and mq else "degraded", "service": "ingestion", "db_up": db,
                "mqtt_connected": mq, "queue_depth": self.q.qsize(),
                "last_message_age_s": None if self.last_message is None else round(time.time() - self.last_message, 1),
                "uptime_s": round(time.time() - self.started, 1)}

    def start(self):
        threading.Thread(target=self.writer, name="db-writer", daemon=True).start()
        self.start_mqtt()

    def stop(self):
        self.stop_event.set()
        if self.client is not None:
            self.client.loop_stop()
            self.client.disconnect()
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass


def to_row(c: Dict) -> Dict:
    simulated = c.get("source") not in REAL_BOARD_SOURCES
    return {"device_ts": c.get("device_ts"), "room_id": c["room_id"], "msg_id": c["msg_id"],
            "provenance": "simulated" if simulated else "physical",
            "temperature": c.get("temperature"), "humidity": c.get("humidity"), "pressure_hpa": c.get("pressure_hpa"),
            "lux": c.get("lux"), "motion": c.get("motion_detected"), "mq135_raw": c.get("mq135_raw"),
            "mq135_adc_mv": c.get("mq135_adc_mv"), "mq135_do_high": c.get("mq135_do_high"),
            "voltage_v": c.get("measured_voltage_v"), "current_ma": c.get("measured_current_mA"),
            "power_mw": c.get("measured_power_mW"), "fan_on": c.get("fan_on"), "relay_on": c.get("relay_on"),
            "rgb": c.get("actuator_rgb"), "wifi_rssi_dbm": c.get("wifi_rssi_dbm"), "uptime_s": c.get("uptime_s"),
            "fw_version": c.get("fw_version") or c.get("firmware"), "payload": json.dumps(c)}


def serve_http(ing: Ingestor, port: int) -> ThreadingHTTPServer:
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/metrics"):
                body, ctype, code = generate_latest(ing.m.reg), CONTENT_TYPE_LATEST, 200
            elif self.path.startswith("/health"):
                h = ing.health()
                body, ctype = json.dumps(h).encode(), "application/json"
                code = 200 if h["status"] == "ok" else 503
            else:
                body, ctype, code = b"not found\n", "text/plain", 404
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("0.0.0.0", port), H)
    threading.Thread(target=srv.serve_forever, name="http", daemon=True).start()
    return srv


def main() -> int:
    from sbops.logs import setup
    setup("ingestion")
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        log.error("DATABASE_URL is not set")
        return 2
    ing = Ingestor(dsn, mqtt_host=os.environ.get("MQTT_HOST", "127.0.0.1"),
                   mqtt_port=int(os.environ.get("MQTT_PORT", "1883")), rooms=os.environ.get("INGEST_ROOMS", "*"),
                   ml_api_url=os.environ.get("ML_API_URL"), queue_max=int(os.environ.get("INGEST_QUEUE_MAX", "10000")))
    srv = serve_http(ing, int(os.environ.get("INGEST_HTTP_PORT", "8090")))
    ing.start()
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    stop.wait()
    log.info("shutting down")
    ing.stop()
    srv.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
