"""
Tests for the edge brain: board link status, no invented values, one decision for
Office A, model input without the room's own lights, and change-driven streaming.

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


@pytest.fixture(scope="module")
def brain():
    return EdgeBrain(speed_factor=360)


def _room(state, room_id=HARDWARE_ROOM_ID):
    return next(r for r in state["rooms"] if r["room_id"] == room_id)


def test_26_rooms_and_one_hardware_room(brain):
    brain.tick()
    state = brain.get_current_state()
    assert len(state["rooms"]) == 26
    assert [r["room_id"] for r in state["rooms"] if r["source"] == "hardware"] == [HARDWARE_ROOM_ID]
    assert sum(r["source"] == "simulated" for r in state["rooms"]) == 25


def test_no_board_means_not_connected_and_no_values():
    b = EdgeBrain(speed_factor=360)
    b.tick()
    state = b.get_current_state()
    room = _room(state)
    assert room["hardware"]["connected"] is False
    assert room["hardware"]["state"] == "never_connected"
    assert all(v is None for v in room["sensors"].values())
    assert room["ai"] is None and room["control"] is None and room["energy"] is None
    assert state["system"]["rooms_with_data"] == 25          # Office A not counted
    assert state["hardware"]["connected"] is False


def test_board_reading_is_shown_exactly_and_decision_matches_reply():
    b = EdgeBrain(speed_factor=360)
    b.tick()
    reply = b.inject_hardware_data(dict(BOARD_READING))
    room = _room(b.get_current_state())
    assert room["hardware"]["connected"] is True
    assert room["hardware"]["sender"] == "esp32_board" and room["hardware"]["real_board"] is True
    s = room["sensors"]
    assert (s["Temperature"], s["Humidity"], s["Light"], s["CO2"]) == (27.4, 66.0, 140.0, 812.0)
    for k in ("hvac_action", "light_action", "control_mode", "fan_speed", "light_level", "servo_angle"):
        assert room["control"][k] == reply[k]
    assert room["ai"]["occupancy_probability"] == reply["occupancy_probability"]
    assert room["energy"]["measured_power_watts"] == 1.5
    assert room["energy"]["estimated_power_watts"] is None
    # A later simulation tick must not replace the board's decision with another one
    b.tick()
    room2 = _room(b.get_current_state())
    assert room2["control"] == room["control"]


def test_missing_fields_stay_missing():
    b = EdgeBrain(speed_factor=360)
    b.inject_hardware_data({"source": "sensor_node", "lux": 50.0, "motion_detected": False})
    s = _room(b.get_current_state())["sensors"]
    assert s["Temperature"] is None and s["Humidity"] is None and s["CO2"] is None
    assert s["Light"] == 50.0


def test_board_timeout_marks_room_not_connected(monkeypatch):
    b = EdgeBrain(speed_factor=360)
    b.inject_hardware_data(dict(BOARD_READING))
    assert _room(b.get_current_state())["hardware"]["connected"] is True
    b._hw_last_rx_mono -= eb.HW_TIMEOUT_S + 1        # pretend the last reading is old
    room = _room(b.get_current_state())
    assert room["hardware"]["connected"] is False and room["hardware"]["state"] == "lost"
    assert room["hardware"]["last_seen"] is not None
    assert all(v is None for v in room["sensors"].values()) and room["control"] is None


def test_test_sender_is_not_reported_as_the_real_board():
    b = EdgeBrain(speed_factor=360)
    b.inject_hardware_data(dict(BOARD_READING, source="test_sender"))
    hw = _room(b.get_current_state())["hardware"]
    assert hw["connected"] is True and hw["sender"] == "test_sender" and hw["real_board"] is False


def test_model_input_excludes_the_rooms_own_lights(brain):
    sim = brain.simulator
    rid = next(iter(sim._rooms))
    sim._rooms[rid].light_on = True
    sim.step(0.5)
    st = next(s for s in sim.get_all_simulated_states() if s["room_id"] == rid)
    assert st["sensors"]["Light"] == pytest.approx(st["model_input"]["Light"] + eb.SIM_LIGHT_LUX, abs=0.2)


def test_stream_is_notified_by_a_board_reading():
    b = EdgeBrain(speed_factor=360)
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


def test_api_rejects_wrong_room_and_unsupported_actions():
    eb.brain = EdgeBrain(speed_factor=360)
    c = eb.app.test_client()
    assert c.post("/api/hardware/sensor-data", json=dict(BOARD_READING, room_id="f9_nowhere")).status_code == 400
    assert c.post("/api/hardware/sensor-data", data="not json", content_type="application/json").status_code == 400
    r = c.post("/api/hardware/sensor-data", json=dict(BOARD_READING))
    assert r.status_code == 200 and set(r.get_json()) >= {"fan_speed", "light_level", "servo_angle", "hvac_action"}
    assert len(r.data) < 300                      # the firmware parses the reply into 384 bytes
    assert c.post("/api/simulation/control", json={"action": "pause"}).status_code == 400
    assert c.post("/api/simulation/control", json={"action": "reset-energy"}).status_code == 200
    h = c.get("/health").get_json()
    assert h["hardware"]["connected"] is True and "Raspberry Pi 4B" not in h["platform"]


def test_system_summary_has_no_hardcoded_flags(brain):
    brain.tick()
    sysd = brain.get_current_state()["system"]
    for k in ("api_online", "simulation_connected", "simulation_paused", "percentage_saved"):
        assert k not in sysd
    assert sysd["simulation_running"] is True and sysd["data_stale"] is False
    acc = sysd["ai_accuracy_simulated"]
    assert acc["room_ticks"] > 0 and 0 <= acc["accuracy"] <= 1
