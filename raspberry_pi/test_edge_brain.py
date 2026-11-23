"""
Tests for the edge brain: board link status, no invented values, one decision for
Office A from the thesis AI, the twin's control API and change-driven streaming.

    python -m pytest raspberry_pi/test_edge_brain.py -q
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import raspberry_pi.edge_brain as eb
from raspberry_pi.edge_brain import EdgeBrain, HARDWARE_ROOM_ID

# test brains must not write the real MQ-135 calibration in output/
import tempfile                                                    # noqa: E402
eb.MQ135_CALIBRATION_FILE = os.path.join(tempfile.mkdtemp(prefix="mq135-test-"), "mq135_calibration.json")

BOARD_READING = {
    "room_id": HARDWARE_ROOM_ID, "source": "sensor_node",
    "temperature": 27.4, "humidity": 66.0, "pressure_hpa": 1009.0,
    "co2": 812.0, "co2_source": "scd41_ndir", "lux": 140.0,
    "motion_detected": True, "presence": True, "presence_source": "pir",
    "actuator_fan_speed": 0, "actuator_light_level": 0, "actuator_servo_angle": 0,
    "mq135_raw": 2101, "mq135_adc_mv": 1718, "mq135_do_high": False,
    "fan_on": False, "relay_on": False, "actuator_rgb": "OFF",
    "measured_voltage_v": 12.0, "ina219_shunt_voltage_mV": 18.0,
    "measured_current_mA": 180.0, "measured_power_mW": 2160.0,
    "sensor_health": {"bme280": True, "bh1750": True, "scd41": True},
}


def new_brain():
    return EdgeBrain(speed_factor=360, warmup=False)


@pytest.fixture(scope="module")
def brain():
    return new_brain()


def _room(state, room_id=HARDWARE_ROOM_ID):
    return next(r for r in state["rooms"] if r["room_id"] == room_id)


def test_26_rooms_and_one_hardware_room(brain):
    brain.tick(1.0)
    state = brain.get_current_state()
    assert state["api_version"] == eb.API_VERSION
    assert [r["room_id"] for r in state["rooms"]] == eb.ROOM_IDS
    assert [r["room_id"] for r in state["rooms"] if r["source"] == "hardware"] == [HARDWARE_ROOM_ID]
    assert sum(r["source"] == "simulated" for r in state["rooms"]) == 25
    for k in ("clock", "floors", "comparison", "timeline", "scenarios", "alerts"):
        assert k in state


def test_no_board_means_not_connected_and_no_values():
    b = new_brain()
    b.tick(1.0)
    state = b.get_current_state()
    room = _room(state)
    assert room["hardware"]["connected"] is False
    assert room["hardware"]["state"] == "never_connected"
    assert all(v is None for v in room["sensors"].values())
    assert room["ai"] is None and room["control"] is None and room["energy"] is None
    assert state["system"]["rooms_with_data"] == 25
    assert state["hardware"]["connected"] is False


def test_board_reading_is_shown_exactly_and_decision_matches_reply():
    b = new_brain()
    b.tick(1.0)
    reply = b.inject_hardware_data(dict(BOARD_READING))
    room = _room(b.get_current_state())
    assert room["hardware"]["connected"] is True
    assert room["hardware"]["sender"] == "esp32_board" and room["hardware"]["real_board"] is True
    s = room["sensors"]
    assert (s["Temperature"], s["Humidity"], s["Light"], s["CO2"]) == (27.4, 66.0, 140.0, 812.0)
    for k in ("hvac_action", "light_action", "control_mode", "fan_speed", "light_level", "servo_angle"):
        assert room["control"][k] == reply[k]
    assert room["ai"]["occupancy_probability"] == reply["occupancy_probability"]
    assert room["ai"]["method"] == "fusion_pir_co2" and room["control"]["controller"] == "mo"
    assert room["energy"]["measured_power_watts"] == 2.16
    assert room["sensors"]["MQ135_raw"] == 2101 and room["sensors"]["MQ135_adc_mV"] == 1718
    assert room["device_state"]["relay_on"] is False and room["device_state"]["rgb"] == "OFF"
    assert room["power_measurement"]["voltage_v"] == 12.0
    assert room["power_measurement"]["shunt_voltage_mV"] == 18.0
    assert room["power_measurement"]["current_mA"] == 180.0
    b.tick(1.0)
    assert _room(b.get_current_state())["control"] == room["control"]
    ev = [e for e in b.twin.get_timeline(room_id=HARDWARE_ROOM_ID) if e["kind"] == "decision"]
    assert ev and ev[-1]["source"] == "hardware" and ev[-1]["why"]


def test_current_firmware_source_is_reported_as_real_board():
    b = new_brain()
    b.tick(1.0)
    b.inject_hardware_data(dict(BOARD_READING, source="esp32_room101"))
    status = b.hardware_status()
    assert status["sender"] == "esp32_board"
    assert status["real_board"] is True


def test_mq2_estimate_is_never_used_as_co2():
    b = new_brain()
    b.inject_hardware_data(dict(BOARD_READING, co2=650.0, co2_source="mq2_estimate"))
    room = _room(b.get_current_state())
    # the board's MQ-2 figure is rejected; the edge's own labelled MQ-135 estimate is used instead
    assert "not an NDIR" in room["sensors"]["CO2_rejected"]
    assert room["sensors"]["CO2"] != 650.0
    assert room["sensors"]["CO2_source"] == "mq135_estimate"


def test_mq135_estimate_is_labelled_and_ndir_wins():
    b = new_brain()
    b.inject_hardware_data(dict(BOARD_READING, co2=None, co2_source=None, uptime_s=4000))
    est = _room(b.get_current_state())["sensors"]
    assert est["CO2_source"] == "mq135_estimate" and est["CO2_estimate_state"] in ("provisional", "calibrated")
    b.inject_hardware_data(dict(BOARD_READING))          # an NDIR reading is preferred whenever present
    ndir = _room(b.get_current_state())["sensors"]
    assert ndir["CO2"] == 812.0 and ndir["CO2_source"] == "scd41_ndir"


def test_real_esp32_source_is_stored_as_measured():
    assert eb.reading_provenance("esp32_room101") == "room101_measured"
    assert eb.reading_provenance("test_sender") == "synthetic"


def test_missing_fields_stay_missing():
    b = new_brain()
    b.inject_hardware_data({"source": "sensor_node", "lux": 50.0, "motion_detected": False})
    room = _room(b.get_current_state())
    s = room["sensors"]
    assert s["Temperature"] is None and s["Humidity"] is None and s["CO2"] is None
    assert s["Light"] == 50.0
    assert "missing" in room["control"]["reason"]


def test_board_timeout_marks_room_not_connected():
    b = new_brain()
    b.inject_hardware_data(dict(BOARD_READING))
    assert _room(b.get_current_state())["hardware"]["connected"] is True
    b.links[HARDWARE_ROOM_ID].last_rx_mono -= eb.HW_TIMEOUT_S + 1
    b._state_cache = None
    room = _room(b.get_current_state())
    assert room["hardware"]["connected"] is False and room["hardware"]["state"] == "lost"
    assert room["hardware"]["last_seen"] is not None
    assert all(v is None for v in room["sensors"].values()) and room["control"] is None


def test_test_sender_is_not_reported_as_the_real_board():
    b = new_brain()
    b.inject_hardware_data(dict(BOARD_READING, source="test_sender"))
    hw = _room(b.get_current_state())["hardware"]
    assert hw["connected"] is True and hw["sender"] == "test_sender" and hw["real_board"] is False


def test_led_calibration_measures_the_led():
    b = new_brain()
    b.inject_hardware_data(dict(BOARD_READING))
    b.start_led_calibration()
    r1 = b.inject_hardware_data(dict(BOARD_READING, lux=60.0, actuator_light_level=255))
    assert r1["light_level"] == 0                                    # LED off first
    r2 = b.inject_hardware_data(dict(BOARD_READING, lux=60.0, actuator_light_level=0))
    assert r2["light_level"] == 255                                  # then full
    b.inject_hardware_data(dict(BOARD_READING, lux=310.0, actuator_light_level=255))
    assert b.links[HARDWARE_ROOM_ID].ctrl.led_lux_full == pytest.approx(250.0)
    if os.path.exists(eb.CALIBRATION_FILE):
        os.remove(eb.CALIBRATION_FILE)


def test_ai_switch_drives_simulation_and_board():
    b = new_brain()
    b.tick(1.0)
    b.inject_hardware_data(dict(BOARD_READING))
    time.sleep(0.05)
    r_on = b.inject_hardware_data(dict(BOARD_READING))
    assert _room(b.get_current_state())["control"]["mode"] == "ai"
    b.set_ai(False)
    state = b.get_current_state()
    assert state["ai_enabled"] is False and state["meter"]["mode"] == "conventional"
    r_off = b.inject_hardware_data(dict(BOARD_READING))
    room = _room(b.get_current_state())
    assert room["control"]["mode"] == "conventional" and room["control"]["controller"] == "schedule"
    assert r_on["room_id"] == r_off["room_id"] == HARDWARE_ROOM_ID
    segs = room["meter"]["segments"]
    assert [s["mode"] for s in segs] == ["ai", "conventional"]
    assert segs[0]["measured"] is True and segs[0]["wh"] > 0          # measured INA226 energy while AI was on
    b.set_ai(True)
    assert b.get_current_state()["meter"]["mode"] == "ai"
    ev = [e for e in b.twin.timeline if e.get("kind") == "switch"]
    assert len(ev) >= 2


def test_stream_is_notified_by_a_board_reading():
    b = new_brain()
    seq0 = b.seq
    got = {}

    def waiter():
        t0 = time.monotonic()
        got["seq"] = b.wait_for_change(seq0, timeout=5)
        got["dt"] = time.monotonic() - t0

    th = threading.Thread(target=waiter)
    th.start()
    time.sleep(0.05)
    b.inject_hardware_data(dict(BOARD_READING))
    th.join(5)
    assert got["seq"] != seq0 and got["dt"] < 1.0


def test_api():
    eb.brain = new_brain()
    eb.brain.tick(1.0)
    c = eb.app.test_client()
    assert c.post("/api/hardware/sensor-data", json=dict(BOARD_READING, room_id="f9_nowhere")).status_code == 400
    assert c.post("/api/hardware/sensor-data", data="not json", content_type="application/json").status_code == 400
    r = c.post("/api/hardware/sensor-data", json=dict(BOARD_READING))
    assert r.status_code == 200 and set(r.get_json()) >= {"fan_speed", "light_level", "servo_angle", "hvac_action"}
    assert len(r.data) < 300                      # the firmware parses the reply into 384 bytes
    cfg = c.get("/api/building/config").get_json()
    assert len(cfg["rooms"]) == 26 and cfg["hardware_room_id"] == HARDWARE_ROOM_ID
    assert {x["id"] for x in cfg["controllers"]} == {"mo", "threshold_rf", "ppo"}
    assert all(x["available"] for x in cfg["controllers"] if x["id"] != "ppo")   # ppo only once approved
    assert c.post("/api/simulation/control", json={"action": "pause"}).get_json()["clock"]["running"] is False
    assert c.post("/api/simulation/control", json={"action": "resume"}).get_json()["clock"]["running"] is True
    assert c.post("/api/simulation/control", json={"action": "speed", "speed": 120}).get_json()["clock"]["speed"] == 120
    assert c.post("/api/simulation/control", json={"action": "teleport"}).status_code == 400
    r = c.post("/api/scenario", json={"kind": "occupancy", "room_id": "f2_meeting_b", "value": 6, "minutes": 20})
    assert r.status_code == 200 and r.get_json()["scenario"]["room_id"] == "f2_meeting_b"
    assert c.post("/api/scenario", json={"kind": "occupancy", "room_id": HARDWARE_ROOM_ID, "value": 6}).status_code == 400
    assert c.post("/api/scenario", json={"action": "clear"}).status_code == 200
    assert c.post("/api/simulation/controller", json={"controller": "threshold_rf"}).get_json()["controller"] == "threshold_rf"
    assert c.post("/api/simulation/controller", json={"controller": "magic"}).status_code == 400
    assert c.post("/api/ai", json={"enabled": "yes"}).status_code == 400
    assert c.post("/api/ai", json={"enabled": False}).get_json()["ai_enabled"] is False
    assert c.get("/api/ai").get_json()["ai_enabled"] is False
    m = c.get("/api/meter").get_json()
    assert m["mode"] == "conventional" and m["real_rooms"][0]["room_id"] == HARDWARE_ROOM_ID
    assert c.post("/api/ai", json={"enabled": True}).get_json()["ai_enabled"] is True
    assert isinstance(c.get("/api/timeline?limit=5").get_json(), list)
    assert c.get("/api/rooms/history?room_id=f9_nowhere").status_code == 404
    a = c.get("/api/analytics").get_json()
    assert "comparison" in a and "series" in a
    h = c.get("/health").get_json()
    assert h["hardware"]["connected"] is True and h["api_version"] == eb.API_VERSION


def test_system_summary_has_no_hardcoded_flags(brain):
    brain.tick(1.0)
    sysd = brain.get_current_state()["system"]
    for k in ("api_online", "simulation_connected", "simulation_paused", "percentage_saved"):
        assert k not in sysd
    assert sysd["simulation_running"] is True and sysd["data_stale"] is False
    assert sysd["sim_power_watts"] > 0 and sysd["ai_enabled"] is True


def test_api_responses_are_strict_json():
    """NaN / infinity would make the browser reject the whole response (found by the browser flows on
    /api/models: an undefined drift PSI). Every endpoint sends them as null."""
    import json as _json
    import math as _math
    from raspberry_pi.edge_brain import _json_safe
    assert _json_safe({"a": float("nan"), "b": [1.0, float("inf")], "c": {"d": -float("inf"), "e": 2}}) == \
        {"a": None, "b": [1.0, None], "c": {"d": None, "e": 2}}
    eb.brain = new_brain()
    eb.brain.tick(1.0)
    c = eb.app.test_client()
    for path in ("/api/models", "/api/rooms/current-state", "/api/analytics", "/api/system/summary", "/health"):
        r = c.get(path)
        assert r.status_code == 200, path
        _json.loads(r.get_data(as_text=True), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(f"{path}: {x}")))
    from ml.drift import DriftMonitor
    m = DriftMonitor(["flag"], {"flag": {"deciles": [0, 0, 0, 1, 1], "min": 0, "max": 1, "mean": 0.4, "missing_share": 0}},
                     min_rows=1)
    m.add([1.0])
    rep = m.report()
    assert rep["features"]["flag"]["psi"] is None and "not defined" in rep["features"]["flag"]["psi_note"]
    assert not any(isinstance(v, float) and not _math.isfinite(v) for v in rep["features"]["flag"].values())


def test_board_indicators_follow_the_decision_and_warnings():
    ind = eb.board_indicators({"hvac_action": "NORMAL", "setpoint_c": 24, "mode": "ai"}, 26.0, 600.0, {"bme280": True}, 24)
    assert ind == {"ac_led": "MAX", "status_led": "AI", "warnings": []}
    ind = eb.board_indicators({"hvac_action": "NORMAL", "setpoint_c": 25, "mode": "conventional"}, 26.0, None, None, 24)
    assert (ind["ac_led"], ind["status_led"]) == ("COOL", "RULE")
    ind = eb.board_indicators({"hvac_action": "ECO", "mode": "manual"}, 26.0, None, {}, 24)
    assert (ind["ac_led"], ind["status_led"]) == ("ECO", "MANUAL")
    ind = eb.board_indicators({"hvac_action": "LOW", "mode": "ai"}, 31.0, None, {"bh1750": False}, 24)
    assert ind["ac_led"] == "LOW" and ind["status_led"] == "WARNING" and len(ind["warnings"]) == 2
    assert eb.board_indicators({"hvac_action": "ECO", "mode": "ai", "calibrating": True}, 25, None, None, 24)["status_led"] == "TEST"


def test_reply_carries_indicator_states_for_the_board():
    b = new_brain()
    b.tick(1.0)
    reply = b.inject_hardware_data(dict(BOARD_READING, actuator_ac_led="COOL", actuator_status_led="AI"))
    assert reply["ac_led"] in eb.AC_LED_STATES and reply["status_led"] in eb.STATUS_LED_STATES
    room = _room(b.get_current_state())
    assert room["control"]["indicators"]["ac_led"] == reply["ac_led"]
    assert room["device_state"]["ac_led"] == "COOL" and room["device_state"]["status_led"] == "AI"


def test_dashboard_is_served_from_the_edge_brain(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<html>twin</html>")
    (tmp_path / "_next").mkdir()
    (tmp_path / "_next" / "app.js").write_text("console.log(1)")
    monkeypatch.setattr(eb, "DASHBOARD_DIR", str(tmp_path))
    c = eb.app.test_client()
    assert b"twin" in c.get("/").data
    assert c.get("/_next/app.js").status_code == 200
    assert c.get("/missing.js").status_code == 404
    assert c.get("/health").status_code == 200          # API routes still win


def test_relay_board_fan_is_verified_on_off_not_by_level(tmp_path):
    """The final board switches the fan with a relay: a LOW (level 100) command reported back as ON is applied."""
    import raspberry_pi.edge_brain as eb
    brain = eb.EdgeBrain(speed_factor=360, warmup=False, store_path=str(tmp_path / "e.sqlite3"))
    link = brain._link_for(eb.HARDWARE_ROOM_ID)
    base = {"room_id": eb.HARDWARE_ROOM_ID, "source": "esp32_room101", "temperature": 29.0, "humidity": 60.0,
            "lux": 50.0, "motion_detected": True, "presence": True, "actuator_light_level": 0}
    brain.inject_hardware_data(dict(base, fan_on=False, actuator_fan_speed=0))
    link.last_command = {"fan": 100, "led": 0}
    brain.inject_hardware_data(dict(base, fan_on=True, actuator_fan_speed=255))
    room = next(x for x in brain.get_current_state()["rooms"] if x["room_id"] == eb.HARDWARE_ROOM_ID)
    assert room["control"]["previous_command_verified"] is True
    link.last_command = {"fan": 100, "led": 0}
    brain.inject_hardware_data(dict(base, fan_on=False, actuator_fan_speed=0))
    room = next(x for x in brain.get_current_state()["rooms"] if x["room_id"] == eb.HARDWARE_ROOM_ID)
    assert room["control"]["previous_command_verified"] is False
