"""The virtual board (raspberry_pi/virtual_board.py) behaves like the firmware on the wire, its data is never
taken for the real board, and Room 101's controller applies the vacancy rule."""
import os
import re
import tempfile
from datetime import datetime, timedelta

import pytest

from raspberry_pi.virtual_board import TwinSource, UciSource, VirtualBoard, load_uci

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INO = os.path.join(ROOT, "firmware", "esp32_smart_building", "esp32_smart_building.ino")


def firmware_fields():
    src = open(INO, encoding="utf-8").read()
    return set(re.findall(r'doc\["([a-zA-Z0-9_]+)"\]', src)) | {"sensor_health"}, \
        set(re.findall(r'health\["([a-zA-Z0-9_]+)"\]', src))


def test_payload_has_exactly_the_firmware_fields_plus_its_label():
    fields, health = firmware_fields()
    board = VirtualBoard(UciSource("2015-02-11T15:00", 1.0), seed=3)
    p = board.reading()
    assert set(p) == fields | {"data_source"}
    assert set(p["sensor_health"]) == health
    assert p["source"] == "virtual_board" and p["source"] != "sensor_node" and p["co2_source"] == "scd41_ndir"


def test_uci_replay_uses_the_recorded_values():
    rows = {r["time"]: r for r in load_uci()}
    assert len(rows) > 20000
    board = VirtualBoard(UciSource("2015-02-11T15:00", 1.0), seed=3)
    for _ in range(20):
        p = board.reading()
        r = rows[board.last_env["time"]]
        assert abs(p["temperature"] - r["temperature"]) < 0.2 and abs(p["humidity"] - r["humidity"]) < 1.0
        assert abs(p["co2"] - r["co2"]) < 40
        assert p["lux"] == pytest.approx(r["lux"], rel=0.05, abs=1.0)       # LED off: room light only


def test_reply_applied_like_the_firmware_and_fail_safe():
    board = VirtualBoard(UciSource("2015-02-11T15:00", 1.0), seed=3)
    board.apply_reply({"fan_speed": 255, "light_level": 102, "servo_angle": 90})
    p = board.reading()
    assert (p["actuator_fan_speed"], p["actuator_light_level"], p["actuator_servo_angle"]) == (255, 102, 90)
    board.apply_reply({"fan_speed": 999, "light_level": -5})                  # bounded like the firmware
    assert board.act["fan"] == 255 and board.act["led"] == 0
    board.fail_safe()                                                         # edge brain unreachable
    assert board.act["fan"] == 0 and board.act["led"] == 0 and board.act["servo"] == 90


def test_dropped_sensor_is_omitted_and_reported_not_detected():
    board = VirtualBoard(UciSource("2015-02-11T15:00", 1.0), seed=3, drop=["scd41", "ina226"])
    p = board.reading()
    assert "scd41_temp" not in p and p["co2_source"] == "none" and "measured_power_mW" not in p
    assert p["sensor_health"]["scd41"] is False and p["sensor_health"]["ina226"] is False


def test_room_model_responds_to_the_ac_command():
    def run(fan):
        src = TwinSource(seed=5, start="2026-03-02T07:00", minutes_per_post=1.0)
        b = VirtualBoard(src, seed=5)
        b.apply_reply({"fan_speed": fan, "light_level": 0, "servo_angle": 0})
        for _ in range(60):
            b.reading()
        return b.last_env["t_air_true"]
    assert run(255) < run(0) - 1.0                                            # AC at 24 C cools the room


def test_edge_brain_labels_virtual_board_and_stores_synthetic():
    import raspberry_pi.edge_brain as eb
    from raspberry_pi.edge_brain import EdgeBrain, HARDWARE_ROOM_ID
    brain = EdgeBrain(speed_factor=360, warmup=False, store_path=os.path.join(tempfile.mkdtemp(), "e.sqlite3"))
    eb.brain = brain
    c = eb.app.test_client()
    board = VirtualBoard(UciSource("2015-02-11T15:00", 1.0), seed=3)
    for _ in range(5):
        r = c.post("/api/hardware/sensor-data", json=board.reading())
        assert r.status_code == 200
        board.apply_reply(r.get_json())
    st = c.get("/api/hardware/status").get_json()["rooms"][0]
    assert st["sender"] == "virtual_board" and st["sender_detail"] == "uci_replay" and st["real_board"] is False
    room = next(x for x in brain.get_current_state()["rooms"] if x["room_id"] == HARDWARE_ROOM_ID)
    assert room["provenance"]["sensors"] == "synthetic"
    assert brain.store.summary()["provenance"]["readings"] == {"synthetic": 5}


def test_vacancy_rule_turns_lights_and_ac_off_despite_high_co2():
    from twin.hardware_room import HardwareRoomController
    from twin.spec import build_spec
    spec = next(r for r in build_spec() if r.room_id == "f2_office_a")
    ctrl = HardwareRoomController(spec)
    t0 = datetime(2026, 3, 2, 18, 0)
    res = ctrl.step(t0, 29.0, 60.0, 5.0, 1200.0, 0.015, True)                # dark, warm, someone moves
    assert res["control"]["light_action"] != "OFF" and not res["ai"]["vacant"]
    for k in range(1, 400):                                                   # they leave; CO2 stays high
        res = ctrl.step(t0 + timedelta(seconds=3 * k), 29.0, 60.0, 5.0, 1200.0, 0.015, False)
    assert res["ai"]["vacant"] and res["control"]["light_action"] == "OFF" and res["control"]["hvac_action"] == "ECO"
    assert res["ai"]["predicted_occupancy"] == 0 and "vacancy rule" in res["control"]["reason"]
    # without presence sensors (presence None) the rule does not apply: CO2 is the only evidence
    ctrl2 = HardwareRoomController(spec)
    res2 = ctrl2.step(t0, 29.0, 60.0, 5.0, 1200.0, 0.015, None)
    assert res2["ai"]["vacant"] is False
