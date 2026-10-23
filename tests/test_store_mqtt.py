"""SQLite store (migrations, provenance, dedupe, restart) and the MQTT bridge with a local broker."""
import json
import logging
import os
import time

import pytest

from raspberry_pi.mqtt_bridge import MqttBridge, build_command, topic, validate_telemetry
from raspberry_pi.store import MIGRATIONS, Store
from tests.conftest import wait_for

ROOM = "f2_office_a"


def test_migrations_apply_once_and_survive_restart(tmp_path):
    p = str(tmp_path / "e.sqlite3")
    s = Store(p)
    assert s.applied == [m[0] for m in MIGRATIONS] and s.schema_version() == MIGRATIONS[-1][0]
    assert s.add_reading("2026-10-23T10:00:00", ROOM, "room101_measured", {"temperature_c": 27.0}, msg_id="m1")
    assert not s.add_reading("2026-10-23T10:00:00", ROOM, "room101_measured", {"temperature_c": 27.0}, msg_id="m1")
    s.close()
    s2 = Store(p)
    assert s2.applied == [] and s2.summary()["tables"]["readings"] == 1
    with pytest.raises(ValueError):
        s2.add_reading("t", ROOM, "prediction", {})       # a prediction is never stored as a reading


def test_history_and_commands(tmp_path):
    s = Store(str(tmp_path / "e.sqlite3"))
    s.add_snapshots([{"ts": f"2026-10-23T10:0{i}:00", "room_id": "f0_lobby", "provenance": "synthetic",
                      "temperature_c": 25 + i} for i in range(5)])
    rows = s.history("f0_lobby", since="2026-10-23T10:02:00")
    assert [r["temperature_c"] for r in rows] == [27, 28, 29]
    s.add_command("t", ROOM, "c1", "mqtt", {"x": 1})
    assert s.ack_command("c1", "applied") and not s.ack_command("c1", "applied")
    assert s.summary()["commands"] == {"applied": 1}


def test_validate_telemetry():
    good = {"schema": "sb.telemetry/1", "room_id": ROOM, "msg_id": "a1", "temperature": 27.2, "humidity": 60,
            "co2": 700, "lux": 120, "presence": True, "source": "mqtt_device_sim"}
    clean, probs = validate_telemetry(ROOM, good, {ROOM})
    assert clean["temperature"] == 27.2 and clean["presence"] is True and probs == []
    clean, probs = validate_telemetry(ROOM, dict(good, temperature=999, humidity="wet"), {ROOM})
    assert "temperature" not in clean and "humidity" not in clean and len(probs) == 2
    assert validate_telemetry(ROOM, dict(good, room_id="f0_lobby"), {ROOM})[0] is None   # topic mismatch
    assert validate_telemetry("f9", dict(good, room_id="f9"), {ROOM})[0] is None          # unknown room
    assert validate_telemetry(ROOM, {k: v for k, v in good.items() if k != "msg_id"}, {ROOM})[0] is None
    assert validate_telemetry(ROOM, [1, 2], {ROOM})[0] is None
    assert validate_telemetry(ROOM, dict(good, schema="other/9"), {ROOM})[0] is None


def _device(host, port, on_cmd):
    import paho.mqtt.client as mqtt
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="test-device")
    c.on_message = lambda cl, u, m: on_cmd(cl, json.loads(m.payload))
    c.connect(host, port)
    c.subscribe(topic(ROOM, "command"), qos=1)
    c.loop_start()
    time.sleep(0.3)
    return c


def test_bridge_end_to_end_with_broker(mqtt_broker, tmp_path, monkeypatch, caplog):
    host, port = mqtt_broker
    monkeypatch.setenv("MQTT_USERNAME", "")
    monkeypatch.setenv("MQTT_PASSWORD", "s3cret-should-not-appear")
    store = Store(str(tmp_path / "e.sqlite3"))
    ingested = []

    def ingest(p):
        ingested.append(p)
        return {"hvac_action": "NORMAL", "light_action": "ON", "fan_speed": 255, "light_level": 255,
                "servo_angle": 0, "occupancy_probability": 0.9}

    caplog.set_level(logging.DEBUG)
    bridge = MqttBridge(ingest, [ROOM], store=store, host=host, port=port, client_id="edge-test")
    bridge.start()
    assert wait_for(lambda: bridge.connected)
    cmds = []

    def on_cmd(cl, cmd):
        cmds.append(cmd)
        cl.publish(topic(ROOM, "ack"), json.dumps({"schema": "sb.ack/1", "msg_id": cmd["msg_id"], "status": "applied",
                                                   "applied": {"fan": cmd["fan_speed"]}}), qos=1)

    dev = _device(host, port, on_cmd)
    msg = {"schema": "sb.telemetry/1", "room_id": ROOM, "msg_id": "t-1", "temperature": 27.0, "humidity": 60.0,
           "source": "mqtt_device_sim"}
    dev.publish(topic(ROOM, "telemetry"), json.dumps(msg), qos=1)
    dev.publish(topic(ROOM, "telemetry"), json.dumps(msg), qos=1)                 # duplicate
    dev.publish(topic(ROOM, "telemetry"), "not json", qos=1)                      # invalid
    dev.publish(topic(ROOM, "telemetry"), json.dumps(dict(msg, msg_id="t-2", temperature=999.0)), qos=1)
    assert wait_for(lambda: bridge.stats["acks"] >= 2 and bridge.stats["rejected"] >= 1)
    st = bridge.status()
    assert st["stats"]["accepted"] == 2 and st["stats"]["duplicates"] == 1 and st["stats"]["field_problems"] == 1
    assert ingested[0]["transport"] == "mqtt" and "temperature" not in ingested[1]
    assert cmds[0]["in_reply_to"] == "t-1" and cmds[0]["schema"] == "sb.command/1"
    assert store.summary()["commands"].get("applied") == 2
    assert "s3cret-should-not-appear" not in caplog.text and "s3cret" not in json.dumps(st)
    dev.loop_stop(); dev.disconnect()
    bridge.stop()


def test_bridge_marks_unacknowledged_commands(mqtt_broker, tmp_path, monkeypatch):
    import raspberry_pi.mqtt_bridge as mb
    monkeypatch.setattr(mb, "ACK_TIMEOUT_S", 1.0)
    host, port = mqtt_broker
    store = Store(str(tmp_path / "e.sqlite3"))
    events = []
    bridge = MqttBridge(lambda p: {"hvac_action": "ECO", "light_action": "OFF", "fan_speed": 0, "light_level": 0,
                                   "servo_angle": 0, "occupancy_probability": 0.1},
                        [ROOM], store=store, host=host, port=port, client_id="edge-test-2",
                        on_event=lambda k, t, r: events.append(t))
    bridge.start()
    assert wait_for(lambda: bridge.connected)
    dev = _device(host, port, lambda cl, cmd: None)                              # never acknowledges
    dev.publish(topic(ROOM, "telemetry"), json.dumps({"room_id": ROOM, "msg_id": "x-1", "temperature": 26.0}), qos=1)
    assert wait_for(lambda: bridge.stats["ack_timeouts"] == 1, timeout=8)
    assert store.summary()["commands"] == {"timeout": 1}
    assert any("no acknowledgement" in e for e in events)
    dev.loop_stop(); dev.disconnect()
    bridge.stop()


def test_export_keeps_provenance_classes_apart(tmp_path):
    import subprocess, sys, csv
    db = str(tmp_path / "e.sqlite3")
    s = Store(db)
    s.add_reading("2026-10-23T10:00:00", ROOM, "room101_measured", {"temperature_c": 27.0}, msg_id="a")
    s.add_reading("2026-10-23T10:00:03", ROOM, "synthetic", {"temperature_c": 26.0}, msg_id="b")
    s.close()
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = str(tmp_path / "x.csv")
    r = subprocess.run([sys.executable, os.path.join(root, "scripts", "export_store.py"), "--db", db, "--table", "readings",
                        "--out", out], capture_output=True, text=True)
    assert r.returncode == 2                                   # mixed classes refused
    r = subprocess.run([sys.executable, os.path.join(root, "scripts", "export_store.py"), "--db", db, "--table", "readings",
                        "--provenance", "room101_measured", "--out", out], capture_output=True, text=True)
    assert r.returncode == 0
    rows = list(csv.DictReader(open(out)))
    assert len(rows) == 1 and rows[0]["provenance"] == "room101_measured"


def test_bridge_reconnects_after_broker_restart(tmp_path):
    """The broker goes away and comes back on the same port: the bridge reports the disconnect and
    reconnects by itself (paho back-off 1-30 s)."""
    import asyncio, threading
    amqtt_broker = pytest.importorskip("amqtt.broker")
    from tests.conftest import free_port
    port = free_port()
    cfg = {"listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{port}"}}, "sys_interval": 0,
           "auth": {"allow-anonymous": True, "plugins": ["auth_anonymous"]}, "topic-check": {"enabled": False}}

    def start_broker():
        loop = asyncio.new_event_loop()
        b = amqtt_broker.Broker(cfg, loop=loop)
        threading.Thread(target=lambda: (asyncio.set_event_loop(loop), loop.run_until_complete(b.start()),
                                         loop.run_forever()), daemon=True).start()
        return loop, b

    loop, b = start_broker()
    time.sleep(1.5)
    events = []
    bridge = MqttBridge(lambda p: {}, [ROOM], host="127.0.0.1", port=port, client_id="edge-reconnect",
                        on_event=lambda k, t, r: events.append(t))
    bridge.start()
    assert wait_for(lambda: bridge.connected)
    asyncio.run_coroutine_threadsafe(b.shutdown(), loop).result(timeout=10)
    assert wait_for(lambda: not bridge.connected, timeout=15)
    loop2, b2 = start_broker()
    assert wait_for(lambda: bridge.connected, timeout=40)
    assert bridge.status()["stats"]["reconnects"] >= 1
    assert any("disconnected" in e for e in events)
    bridge.stop()
    asyncio.run_coroutine_threadsafe(b2.shutdown(), loop2)
