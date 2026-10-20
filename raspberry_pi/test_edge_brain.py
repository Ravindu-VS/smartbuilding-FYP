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

BOARD_READING = {
    "room_id": HARDWARE_ROOM_ID, "source": "sensor_node",
    "temperature": 27.4, "humidity": 66.0, "pressure_hpa": 1009.0,
    "co2": 812.0, "co2_source": "scd41_ndir", "lux": 140.0,
    "motion_detected": True, "presence": True, "presence_source": "pir",
    "actuator_fan_speed": 0, "actuator_light_level": 0, "actuator_servo_angle": 0,
    "measured_power_mW": 1500.0,
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
    assert room["energy"]["measured_power_watts"] == 1.5
    # A later simulation tick must not replace the board's decision
    b.tick(1.0)
    assert _room(b.get_current_state())["control"] == room["control"]
    # the decision is explained in the timeline
    ev = [e for e in b.twin.get_timeline(room_id=HARDWARE_ROOM_ID) if e["kind"] == "decision"]
    assert ev and ev[-1]["source"] == "hardware" and ev[-1]["why"]


def test_mq2_estimate_is_never_used_as_co2():
    b = new_brain()
    b.inject_hardware_data(dict(BOARD_READING, co2=650.0, co2_source="mq2_estimate"))
    room = _room(b.get_current_state())
    assert room["sensors"]["CO2"] is None and "not an NDIR" in room["sensors"]["CO2_rejected"]
    assert room["ai"]["co2_used"] is False


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
    assert {x["id"] for x in cfg["controllers"]} == {"mo", "threshold_rf"}
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
