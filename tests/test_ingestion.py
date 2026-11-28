"""
Ingestion service: MQTT → validation → PostgreSQL, outage recovery, and predictions from the ML API.

Integration tests need a PostgreSQL database (TEST_DATABASE_URL, e.g.
postgresql://sbtest:...@127.0.0.1:5432/sbtest) and use a real broker when TEST_MQTT_HOST is set, otherwise
an in-process amqtt broker.

    TEST_DATABASE_URL=... python -m pytest tests/test_ingestion.py -q
"""
import asyncio
import json
import os
import socket
import threading
import time

import pytest

from ingestion.service import REAL_BOARD_SOURCES, Ingestor, to_row

DSN = os.environ.get("TEST_DATABASE_URL")
ROOM = "f2_office_a"


def board(msg_id, **kw):
    p = {"schema": "sb.telemetry/1", "room_id": ROOM, "msg_id": msg_id, "source": "esp32_room101",
         "device_id": "room101-esp32", "temperature": 24.1, "humidity": 61.0, "pressure_hpa": 1008.0, "lux": 220.0,
         "motion_detected": True, "measured_voltage_v": 12.0, "measured_current_mA": 90.4,
         "measured_power_mW": 1084.8, "fan_on": True, "relay_on": True, "mq135_raw": 1000, "mq135_adc_mv": 806,
         "wifi_rssi_dbm": -58, "uptime_s": 3600, "fw_version": "room101-2026.11.25"}
    p.update(kw)
    return p


def wait_for(cond, timeout=20.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if cond():
                return True
        except Exception:                 # e.g. the table is not created yet
            pass
        time.sleep(0.1)
    return False


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ------------------------------------------------------------------ unit
def test_provenance_rule_matches_the_edge_brain():
    from raspberry_pi.edge_brain import REAL_BOARD_SOURCES as EDGE
    assert tuple(REAL_BOARD_SOURCES) == tuple(EDGE)


def test_only_the_real_board_is_physical():
    assert to_row(board("a"))["provenance"] == "physical"
    assert to_row(board("b", source="virtual_board"))["provenance"] == "simulated"
    assert to_row(board("c", source="something_new"))["provenance"] == "simulated"
    row = to_row(board("d"))
    assert row["voltage_v"] == 12.0 and row["current_ma"] == 90.4 and row["power_mw"] == 1084.8
    assert json.loads(row["payload"])["msg_id"] == "d"


def test_validation_rejects_like_the_edge_brain():
    ing = Ingestor("postgresql://unused", rooms="*")
    ing.on_message(f"sb/v1/room/{ROOM}/telemetry", b"not json")
    ing.on_message(f"sb/v1/room/{ROOM}/telemetry", json.dumps(board("x", room_id="other_room")).encode())
    ing.on_message(f"sb/v1/room/{ROOM}/telemetry", json.dumps({k: v for k, v in board("y").items()
                                                               if k != "msg_id"}).encode())
    assert ing.q.qsize() == 0
    ing.on_message(f"sb/v1/room/{ROOM}/telemetry", json.dumps(board("ok", temperature=999)).encode())
    kind, clean = ing.q.get_nowait()
    assert kind == "telemetry" and "temperature" not in clean      # out-of-range field dropped, reading kept
    text = __import__("prometheus_client").generate_latest(ing.m.reg).decode()
    assert "sb_ingest_rejected_total" in text


def test_queue_drops_the_oldest_when_full():
    ing = Ingestor("postgresql://unused", queue_max=3)
    for i in range(5):
        ing.on_message(f"sb/v1/room/{ROOM}/telemetry", json.dumps(board(f"m{i}")).encode())
    assert [ing.q.get_nowait()[1]["msg_id"] for _ in range(3)] == ["m2", "m3", "m4"]
    assert ing.m.dropped._value.get() == 2


# ------------------------------------------------------------------ integration
needs_db = pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL not set")


@pytest.fixture(scope="module")
def broker():
    host = os.environ.get("TEST_MQTT_HOST")
    if host:
        yield host, int(os.environ.get("TEST_MQTT_PORT", "1883"))
        return
    amqtt_broker = pytest.importorskip("amqtt.broker")
    port = free_port()
    cfg = {"listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{port}"}}, "sys_interval": 0,
           "auth": {"allow-anonymous": True, "plugins": ["auth_anonymous"]}, "topic-check": {"enabled": False}}
    loop = asyncio.new_event_loop()
    b = amqtt_broker.Broker(cfg, loop=loop)
    threading.Thread(target=lambda: (asyncio.set_event_loop(loop), loop.run_until_complete(b.start()),
                                     loop.run_forever()), daemon=True).start()
    time.sleep(1.5)
    yield "127.0.0.1", port
    asyncio.run_coroutine_threadsafe(b.shutdown(), loop).result(timeout=10)


@pytest.fixture()
def db():
    import psycopg
    conn = psycopg.connect(DSN, autocommit=True)
    conn.execute("DROP TABLE IF EXISTS telemetry, device_events, predictions, schema_migrations")
    yield conn
    conn.close()


def publisher(host, port):
    import paho.mqtt.client as mqtt
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"test-pub-{time.time_ns()}")
    c.connect(host, port)
    c.loop_start()
    return c


def count(conn, sql, *args):
    return conn.execute(sql, args).fetchone()[0]


@needs_db
def test_mqtt_to_postgres_end_to_end(broker, db):
    host, port = broker
    ing = Ingestor(DSN, mqtt_host=host, mqtt_port=port, client_id=f"ing-{time.time_ns()}")
    ing.start()
    try:
        assert wait_for(lambda: ing.health()["status"] == "ok")
        pub = publisher(host, port)
        topic = f"sb/v1/room/{ROOM}/telemetry"
        for i in range(3):
            pub.publish(topic, json.dumps(board(f"r{i}", temperature=24.0 + i)), qos=1).wait_for_publish()
        pub.publish(topic, json.dumps(board("r1")), qos=1).wait_for_publish()                 # QoS 1 redelivery
        pub.publish(topic, json.dumps(board("s1", source="virtual_board")), qos=1).wait_for_publish()
        pub.publish(topic, b"{broken", qos=1).wait_for_publish()
        pub.publish(f"sb/v1/room/{ROOM}/status", json.dumps({"state": "online"}), qos=1).wait_for_publish()
        assert wait_for(lambda: count(db, "SELECT count(*) FROM telemetry") == 4
                        and count(db, "SELECT count(*) FROM device_events") == 1)
        assert count(db, "SELECT count(*) FROM telemetry WHERE provenance='physical'") == 3
        assert count(db, "SELECT count(*) FROM telemetry WHERE provenance='simulated'") == 1
        assert db.execute("SELECT temperature, power_mw, fan_on FROM telemetry WHERE msg_id='r2'").fetchone() \
            == (26.0, 1084.8, True)
        assert ing.m.duplicates._value.get() == 1
        assert count(db, "SELECT max(version) FROM schema_migrations") == 1
        pub.loop_stop()
        pub.disconnect()
    finally:
        ing.stop()


@needs_db
def test_database_outage_keeps_readings_and_writes_them_later(broker, db):
    host, port = broker
    ing = Ingestor("postgresql://nobody:nothing@127.0.0.1:1/none", mqtt_host=host, mqtt_port=port,
                   client_id=f"ing-{time.time_ns()}")
    ing.start()
    try:
        assert wait_for(lambda: ing.health()["mqtt_connected"])
        pub = publisher(host, port)
        for i in range(5):
            pub.publish(f"sb/v1/room/{ROOM}/telemetry", json.dumps(board(f"o{i}")), qos=1).wait_for_publish()
        assert wait_for(lambda: ing.q.qsize() >= 4)
        h = ing.health()
        assert h["status"] == "degraded" and not h["db_up"]
        ing.dsn = DSN                                                     # the database comes back
        assert wait_for(lambda: count(db, "SELECT count(*) FROM telemetry") == 5, timeout=40)
        assert ing.health()["db_up"] and ing.q.qsize() == 0
        pub.loop_stop()
        pub.disconnect()
    finally:
        ing.stop()


@needs_db
def test_predictions_from_the_ml_api_are_stored(broker, db, tmp_path, monkeypatch):
    pytest.importorskip("mlflow")
    uvicorn = pytest.importorskip("uvicorn")
    import mlflow
    from mlops.train import train
    uri = "sqlite:///" + str(tmp_path / "mlflow.db")
    train(tracking_uri=uri)
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)
    monkeypatch.setenv("MODEL_POLL_SECONDS", "0")
    mlflow.set_tracking_uri(uri)
    import mlops.serving.app as A
    monkeypatch.setattr(A, "holder", A.ModelHolder())
    api_port = free_port()
    server = uvicorn.Server(uvicorn.Config(A.app, host="127.0.0.1", port=api_port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    assert wait_for(lambda: server.started and A.holder.loaded, timeout=60)

    host, port = broker
    ing = Ingestor(DSN, mqtt_host=host, mqtt_port=port, ml_api_url=f"http://127.0.0.1:{api_port}",
                   client_id=f"ing-{time.time_ns()}")
    ing.start()
    try:
        assert wait_for(lambda: ing.health()["status"] == "ok")
        pub = publisher(host, port)
        for i in range(3):
            pub.publish(f"sb/v1/room/{ROOM}/telemetry", json.dumps(board(f"p{i}", lux=300.0 + i)),
                        qos=1).wait_for_publish()
        assert wait_for(lambda: count(db, "SELECT count(*) FROM predictions") == 3, timeout=30)
        row = db.execute("SELECT model_name, model_version, probability, occupied FROM predictions "
                         "ORDER BY id LIMIT 1").fetchone()
        assert row[0] == "room-occupancy" and row[1] == "1" and 0 <= row[2] <= 1 and isinstance(row[3], bool)
        pub.loop_stop()
        pub.disconnect()
    finally:
        ing.stop()
        server.should_exit = True
