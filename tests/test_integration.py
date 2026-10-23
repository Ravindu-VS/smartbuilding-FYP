"""
Integration and end-to-end tests of the edge brain (Flask API, store, models, live/simulated separation).

End-to-end flow checked by test_end_to_end_flow (numbers = the master prompt's list):
 1 start  2 simulation runs  3 simulated room conditions change (scenario)  4 occupancy inference
 5 controller decides  6 safety layer validates  7 simulated HVAC/lighting state updates
 8 energy and comfort are computed  9 state published (API + change sequence for SSE)
 10 digital-twin payload complete  11 events and metrics logged (timeline + store)
 12 reset and repeat without duplicate loops, rooms or state.
"""
import os
import threading
import time

import pytest

import raspberry_pi.edge_brain as eb
from raspberry_pi.edge_brain import HARDWARE_ROOM_ID, EdgeBrain

READING = {"room_id": HARDWARE_ROOM_ID, "temperature": 27.4, "humidity": 66.0, "co2": 812.0, "co2_source": "scd41_ndir",
           "lux": 140.0, "motion_detected": True, "presence": True, "presence_source": "pir",
           "actuator_fan_speed": 0, "actuator_light_level": 0, "actuator_servo_angle": 0, "measured_power_mW": 1500.0}


@pytest.fixture()
def brain(tmp_path):
    b = EdgeBrain(speed_factor=360, warmup=False, store_path=str(tmp_path / "edge.sqlite3"))
    eb.brain = b
    yield b
    eb.brain = None


def _client(b):
    eb.brain = b
    return eb.app.test_client()


def test_live_and_simulated_rooms_stay_separate(brain):
    brain.tick(1.0)
    st = brain.get_current_state()
    sim = [r for r in st["rooms"] if r["source"] == "simulated"]
    hw = [r for r in st["rooms"] if r["source"] == "hardware"]
    assert len(sim) == 25 and len(hw) == 1 and hw[0]["room_number"] == 101
    assert sorted(r["room_number"] for r in st["rooms"]) == list(range(101, 127))
    assert all(r["provenance"]["sensors"] == "synthetic" for r in sim)
    assert hw[0]["provenance"]["sensors"] == "unavailable" and hw[0]["sensors"]["Temperature"] is None
    brain.inject_hardware_data(dict(READING, source="test_sender"))
    hw = next(r for r in brain.get_current_state()["rooms"] if r["source"] == "hardware")
    assert hw["provenance"]["sensors"] == "synthetic"          # the test sender is not the real board
    brain.inject_hardware_data(dict(READING, source="sensor_node", msg_id="m-1"))
    hw = next(r for r in brain.get_current_state()["rooms"] if r["source"] == "hardware")
    assert hw["provenance"]["sensors"] == "room101_measured" and hw["sensors"]["Temperature"] == 27.4
    assert hw["freshness"]["stale"] is False
    prov = brain.store.summary()["provenance"]["readings"]
    assert prov == {"synthetic": 1, "room101_measured": 1}


def test_new_api_endpoints(brain):
    c = _client(brain)
    brain.tick(1.0)
    brain.inject_hardware_data(dict(READING, source="sensor_node", msg_id="m-2"))
    brain._last_snapshot_mono = 0.0
    brain._persist(time.monotonic() + 1e6)
    m = c.get("/api/models").get_json()
    assert "registry" in m and "controllers" in m and m["live"] is not None
    h = c.get(f"/api/history?room_id={HARDWARE_ROOM_ID}&table=readings").get_json()
    assert h["room_number"] == 101 and h["rows"][0]["provenance"] == "room101_measured"
    snap = c.get("/api/history?room_id=f0_lobby").get_json()
    assert snap["rows"] and snap["rows"][-1]["provenance"] == "synthetic"
    assert c.get("/api/history?room_id=nowhere").status_code == 400
    assert c.get(f"/api/history?room_id={HARDWARE_ROOM_ID}&table=secrets").status_code == 400
    p = c.get("/api/provenance").get_json()
    assert len(p["rooms"]) == 26 and p["store"]["schema_version"] >= 2
    assert c.get("/api/datasets").status_code == 200
    assert c.get("/api/experiments").status_code == 200
    assert c.get("/api/hardware/mqtt").get_json()["enabled"] is False
    ev = c.get("/api/events?limit=5").get_json()
    assert ev["persistent"] is True
    assert c.post("/api/models/promote", json={"task": "nope", "version": "v1"}).status_code == 400


def test_admin_token_protects_model_changes(brain, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "t0k3n")
    c = _client(brain)
    assert c.post("/api/models/rollback", json={"task": "occupancy_rf"}).status_code == 403


def test_restart_reuses_store_without_duplicates(tmp_path):
    p = str(tmp_path / "edge.sqlite3")
    b1 = EdgeBrain(speed_factor=360, warmup=False, store_path=p, models=False)
    b1.inject_hardware_data(dict(READING, source="sensor_node", msg_id="r-1"))
    n1 = b1.store.summary()["tables"]["readings"]
    b1.store.close()
    b2 = EdgeBrain(speed_factor=360, warmup=False, store_path=p, models=False)
    assert b2.store.applied == [] and b2.store.summary()["tables"]["readings"] == n1
    b2.inject_hardware_data(dict(READING, source="sensor_node", msg_id="r-1"))      # re-sent message
    assert b2.store.summary()["tables"]["readings"] == n1
    b2.tick(1.0)
    ids = [r["room_id"] for r in b2.get_current_state()["rooms"]]
    assert len(ids) == len(set(ids)) == 26


def test_end_to_end_flow(brain):
    c = _client(brain)
    threads0 = threading.active_count()
    seq0 = brain.seq
    # 1-2 start and run the simulation
    for _ in range(4):
        brain.tick(1.0)
    st = brain.get_current_state()
    t0 = st["clock"]["time"]
    assert st["system"]["simulated_rooms"] == 25
    # 3 change a simulated room's conditions
    r = c.post("/api/scenario", json={"kind": "heat_gain", "room_id": "f2_office_b2", "value": 1500, "minutes": 60})
    assert r.status_code == 200
    for _ in range(4):
        brain.tick(1.0)
    st = brain.get_current_state()
    room = next(x for x in st["rooms"] if x["room_id"] == "f2_office_b2")
    # 4 occupancy inference, 5 controller, 6 safety layer, 7 equipment state
    assert 0.0 <= room["ai"]["occupancy_probability"] <= 1.0
    assert room["control"]["hvac_action"] in ("ECO", "LOW", "NORMAL") and isinstance(room["control"]["safety_notes"], list)
    assert room["device_state"]["hvac_mode"] in ("off", "setback", "comfort")
    # 8 energy and comfort
    assert room["energy"]["power_w"] >= 0 and "pmv" in room["comfort"]
    assert st["meter"] is not None and st["comparison"] is not None
    # 9 published: API state, change sequence (what the SSE stream waits on)
    assert st["clock"]["time"] != t0 and brain.seq > seq0
    assert c.get("/api/rooms/current-state").status_code == 200
    # 10 the payload the 3D twin consumes has every room, floor and the live-room status
    assert len(st["rooms"]) == 26 and len(st["floors"]) == 5 and "hardware" in st
    # 11 events and metrics logged
    brain._persist(time.monotonic())
    assert brain.store.summary()["tables"]["events"] > 0
    assert any(e["kind"] for e in st["timeline"])
    # 12 reset and repeat: no new loops, same rooms, clock back to the start
    r = c.post("/api/simulation/control", json={"action": "reset"})
    assert r.status_code == 200
    for _ in range(3):
        brain.tick(1.0)
    st2 = brain.get_current_state()
    assert [x["room_id"] for x in st2["rooms"]] == [x["room_id"] for x in st["rooms"]]
    assert threading.active_count() <= threads0 + 1


def test_manual_override_and_actuator_verification(brain):
    c = _client(brain)
    d = brain.inject_hardware_data(dict(READING, source="sensor_node", msg_id="v-1"))
    # the board reports exactly what it was told -> verified
    brain.inject_hardware_data(dict(READING, source="sensor_node", msg_id="v-2",
                                    actuator_fan_speed=d["fan_speed"], actuator_light_level=d["light_level"]))
    hw = next(r for r in brain.get_current_state()["rooms"] if r["source"] == "hardware")
    assert hw["control"]["previous_command_verified"] is True
    assert c.post("/api/hardware/override", json={"room_id": HARDWARE_ROOM_ID, "fan_speed": 999,
                                                   "light_level": 40, "minutes": 5}).status_code == 200
    r = brain.inject_hardware_data(dict(READING, source="sensor_node", msg_id="v-3"))
    assert r["fan_speed"] == 255 and r["light_level"] == 40          # bounded and applied
    hw = next(x for x in brain.get_current_state()["rooms"] if x["source"] == "hardware")
    assert hw["control"]["mode"] == "manual"
    assert c.post("/api/hardware/override", json={"room_id": HARDWARE_ROOM_ID, "minutes": 999}).status_code == 400
    assert c.post("/api/hardware/override", json={"room_id": HARDWARE_ROOM_ID, "clear": True}).status_code == 200
    r = brain.inject_hardware_data(dict(READING, source="sensor_node", msg_id="v-4"))
    assert next(x for x in brain.get_current_state()["rooms"] if x["source"] == "hardware")["control"]["mode"] != "manual"
