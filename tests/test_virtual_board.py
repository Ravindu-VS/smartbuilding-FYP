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
    """The fields of the firmware's buildTelemetry() (the telemetry message), and of its sensor_health."""
    src = open(INO, encoding="utf-8").read()
    body = src[src.index("size_t buildTelemetry("):]
    body = body[:body.index("\n}\n")]
    return set(re.findall(r'doc\["([a-zA-Z0-9_]+)"\]', body)) | {"sensor_health"}, \
        set(re.findall(r'health\["([a-zA-Z0-9_]+)"\]', body))


def test_uci_replay_uses_the_recorded_values():
    from raspberry_pi.co2_estimator import Mq135Co2Estimator, correction_factor
    rows = {r["time"]: r for r in load_uci()}
    assert len(rows) > 20000
    board = VirtualBoard(UciSource("2015-02-11T15:00", 1.0), seed=3)
    # the Pi's estimator, told this virtual sensor's R0, gives back the recorded CO2 from the ADC millivolts
    est = Mq135Co2Estimator(os.path.join(tempfile.mkdtemp(), "c.json"), divider=VirtualBoard.MQ_DIVIDER,
                            warmup_s=0)
    est.r0, est.r0_source = VirtualBoard.MQ_R0_KOHM, "manual"
    for _ in range(20):
        p = board.reading()
        r = rows[board.last_env["time"]]
        assert abs(p["temperature"] - r["temperature"]) < 0.2 and abs(p["humidity"] - r["humidity"]) < 1.0
        assert p["lux"] == pytest.approx(r["lux"], rel=0.05, abs=1.0)       # light off: room light only
        rs_c = est.resistance(p["mq135_adc_mv"]) / correction_factor(p["temperature"], p["humidity"])
        assert est.ppm(rs_c) == pytest.approx(r["co2"], rel=0.06)


def test_payload_has_exactly_the_firmware_fields_plus_its_label():
    fields, health = firmware_fields()
    board = VirtualBoard(UciSource("2015-02-11T15:00", 1.0), seed=3)
    p = board.reading()
    assert set(p) == fields | {"data_source"}
    assert set(p["sensor_health"]) == health
    assert p["source"] == "virtual_board" and p["schema"] == "sb.telemetry/1" and "co2" not in p


def test_reply_applied_like_the_firmware_and_fail_safe():
    board = VirtualBoard(UciSource("2015-02-11T15:00", 1.0), seed=3)
    board.apply_reply({"fan_speed": 100, "light_level": 102, "ac_led": "LOW", "status_led": "AI"})
    p = board.reading()
    assert p["fan_on"] and p["relay_on"] and p["actuator_fan_speed"] == 255          # relay: any level is ON
    assert (p["actuator_light_level"], p["actuator_rgb"]) == (102, "CUSTOM")
    assert (p["actuator_ac_led"], p["actuator_status_led"]) == ("LOW", "AI")
    assert p["measured_current_mA"] > 100 and p["measured_power_mW"] > 1000           # the fan draws current
    board.apply_reply({"fan_speed": 0, "light_level": 255})
    p = board.reading()
    assert not p["fan_on"] and abs(p["measured_current_mA"]) < 2 and p["actuator_rgb"] == "WHITE"
    board.apply_reply({"fan_speed": 999, "light_level": -5})                  # bounded like the firmware
    assert board.act["fan"] == 255 and board.act["led"] == 0
    board.fail_safe()                                                         # edge brain unreachable
    assert board.act["fan"] == 0 and board.act["led"] == 0
    assert (board.act["ac_led"], board.act["status_led"]) == ("OFF", "LOST")


def test_dropped_sensor_is_omitted_and_reported_not_detected():
    board = VirtualBoard(UciSource("2015-02-11T15:00", 1.0), seed=3, drop=["ina219", "bme280"])
    p = board.reading()
    assert "measured_power_mW" not in p and "temperature" not in p and "lux" in p
    assert p["sensor_health"]["ina219"] is False and p["sensor_health"]["bme280"] is False
    with pytest.raises(ValueError):
        VirtualBoard(UciSource("2015-02-11T15:00", 1.0), drop=["scd41"])     # not on the final board


def test_bench_v1_profile_keeps_the_earlier_sensor_set_for_experiment_11():
    board = VirtualBoard(UciSource("2015-02-11T15:00", 1.0), seed=3, profile="bench_v1", drop=["scd41"])
    p = board.reading()
    assert p["co2_source"] == "none" and "mmwave_presence" in p and p["sensor_health"]["scd41"] is False
    board = VirtualBoard(UciSource("2015-02-11T15:00", 1.0), seed=3, profile="bench_v1")
    board.apply_reply({"fan_speed": 150, "light_level": 102, "servo_angle": 90})
    p = board.reading()
    assert (p["actuator_fan_speed"], p["actuator_servo_angle"], p["co2_source"]) == (150, 90, "scd41_ndir")


def test_edge_brain_estimates_co2_from_the_virtual_mq135():
    import raspberry_pi.edge_brain as eb
    from raspberry_pi.edge_brain import EdgeBrain
    tmp = tempfile.mkdtemp()
    old = eb.MQ135_CALIBRATION_FILE
    eb.MQ135_CALIBRATION_FILE = os.path.join(tmp, "mq.json")
    try:
        brain = EdgeBrain(speed_factor=360, warmup=False, store_path=os.path.join(tmp, "e.sqlite3"))
        eb.brain = brain
        c = eb.app.test_client()
        board = VirtualBoard(UciSource("2015-02-11T15:00", 1.0), seed=3)       # just booted: warming up
        r = c.post("/api/hardware/sensor-data", json=board.reading())
        assert r.status_code == 200
        assert c.get("/api/hardware/co2").get_json()["last"]["state"] == "warming_up"
        board = VirtualBoard(UciSource("2015-02-11T15:00", 1.0), seed=3, uptime0_s=3600)   # warm
        for _ in range(10):
            r = c.post("/api/hardware/sensor-data", json=board.reading())
            board.apply_reply(r.get_json())
        last = c.get("/api/hardware/co2").get_json()["last"]
        assert last["state"] == "provisional" and last["co2_ppm"] > 350
        assert board.act["status_led"] in ("AI", "RULE", "WARNING", "TEST", "MANUAL")
    finally:
        eb.MQ135_CALIBRATION_FILE = old


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
