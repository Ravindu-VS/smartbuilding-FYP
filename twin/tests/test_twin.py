"""
Tests for the live digital twin (twin/).

    python -m pytest twin/tests -q

The physics test compares the twin's RoomPhysics with a trace computed by the
thesis code (simulation/room_physics.py and climate.py of the thesis repository,
commit 08427b4) for the thesis's 36 m2 office: with no geometry or overrides the
twin must reproduce it.
"""
import json
import os
import sys
from datetime import datetime, timedelta

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from twin.climate import ColomboClimate, ScenarioClimate                    # noqa: E402
from twin.controllers import Observation, RandomForestEstimator              # noqa: E402
from twin.hardware_room import HardwareRoomController, fan_pwm               # noqa: E402
from twin.live import LiveTwin                                               # noqa: E402
from twin.occupancy import BuildingOccupancy                                 # noqa: E402
from twin.physics import RoomPhysics                                         # noqa: E402
from twin.safety import SafetyLayer                                          # noqa: E402
from twin.spec import build_spec, schedule_profiles                          # noqa: E402
from integration.building_config import get_all_rooms                        # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------- physics
def test_physics_reproduces_thesis_code():
    ref = json.load(open(os.path.join(HERE, "thesis_physics_reference.json")))["trace"]
    clim = ColomboClimate(seed=3)
    rp = RoomPhysics(1, "office", 6.0, 6.0, 3.0, window_azimuth=180.0, initial_temperature=29.0, initial_w=0.016)
    t, dt, got = datetime(2026, 3, 2), 15.0, []
    for k in range(int(86400 / dt)):
        h = t.hour + t.minute / 60
        occ = 3 if 8 <= h < 12 or 13 <= h < 17 else (1 if 12 <= h < 13 else 0)
        c = rp.command
        c.light_level = 1.0 if 8 <= h < 17 else (0.4 if 17 <= h < 19 else 0.0)
        c.hvac_mode = "comfort" if 8 <= h < 17 else ("setback" if 17 <= h < 19 else "off")
        c.comfort_setpoint = 25.0 if 12 <= h < 13 else None
        out = clim.at(t)
        rp.step(dt, out, ColomboClimate.irradiance_on_window(out, rp.window_azimuth), occ, 30.0 if 14 <= h < 15 else 0.0)
        t += timedelta(seconds=dt)
        if k % 240 == 239:
            s = rp.state
            got.append({"t_air": s.t_air, "t_mass": s.t_mass, "t_surface": s.t_surface, "co2": s.co2_ppm, "w": s.w,
                        "e_hvac_wh": s.e_hvac_wh, "e_lighting_wh": s.e_lighting_wh, "e_plug_wh": s.e_plug_wh,
                        "daylight_lux": s.daylight_lux})
    assert len(got) == len(ref) == 24
    for g, r in zip(got, ref):
        for k, v in g.items():
            assert v == pytest.approx(r[k], rel=1e-9, abs=1e-9), (r["t"], k)


def test_scenario_climate_is_unchanged_without_disturbance():
    a, b = ColomboClimate(seed=5), ScenarioClimate(seed=5)
    for hrs in (0, 7, 12.5, 18):
        ts = datetime(2026, 3, 3) + timedelta(hours=hrs)
        assert a.at(ts) == b.at(ts)
    b.temp_offset_k, b.daylight_scale = 3.0, 0.2
    o = b.at(datetime(2026, 3, 3, 12))
    assert o.temperature == pytest.approx(a.at(datetime(2026, 3, 3, 12)).temperature + 3.0)
    assert o.ghi == pytest.approx(0.2 * a.at(datetime(2026, 3, 3, 12)).ghi)


# ---------------------------------------------------------------- building model
def test_spec_matches_building_config():
    specs = build_spec()
    cfg = {r["room_id"]: r for r in get_all_rooms()}
    assert len(specs) == len(cfg) == 26
    assert [r.room_id for r in specs if r.data_source == "hardware"] == ["f2_office_a"]
    for r in specs:
        assert r.area > 0 and r.volume > 0
        assert r.max_occupancy == cfg[r.room_id]["max_occupancy"]
        if r.room_type == "server":
            assert r.window_area == 0.0 and r.equipment_cooled
        opts = r.controller_overrides["ac_options"]
        assert ("ECO", None) in opts and min(sp for m, sp in opts if m == "NORMAL") == r.design_setpoint
        assert r.controller_overrides["energy_norm"] == pytest.approx(36.0 / r.area)
    # rooms on one floor do not overlap and lie inside the footprint
    for f in {r.floor_id for r in specs}:
        rooms = [r for r in specs if r.floor_id == f]
        for i, a in enumerate(rooms):
            assert a.x >= 0 and a.z >= 0 and a.x + a.w <= 30.0 + 1e-6 and a.z + a.d <= 20.0 + 1e-6
            for b in rooms[i + 1:]:
                overlap = min(a.x + a.w, b.x + b.w) - max(a.x, b.x) > 1e-6 and \
                    min(a.z + a.d, b.z + b.d) - max(a.z, b.z) > 1e-6
                assert not overlap, (a.room_id, b.room_id)


def test_occupancy_is_reproducible_and_forcible():
    prof = schedule_profiles()
    a, b = BuildingOccupancy(11, prof), BuildingOccupancy(11, prof)
    ts = [datetime(2026, 3, 2, 6) + timedelta(minutes=17 * i) for i in range(60)]
    for rid, rt in (("f2_office_b2", "office"), ("f1_gym", "gym"), ("f0_cafe", "shop")):
        assert [a.count(rid, rt, t, 10) for t in ts] == [b.count(rid, rt, t, 10) for t in ts]
    a.force("f1_gym", 7, ts[0], 30)
    assert a.count("f1_gym", "gym", ts[0] + timedelta(minutes=10), 20) == 7
    assert a.count("f1_gym", "gym", ts[0] + timedelta(minutes=40), 20) == b.count("f1_gym", "gym",
                                                                                  ts[0] + timedelta(minutes=40), 20)


# ---------------------------------------------------------------- safety
def test_safety_rules():
    s = SafetyLayer({"srv": True, "o": False})
    v = s.validate("o", "ON", "NORMAL", 18.0, 0.9, 25.0, 600.0)
    assert v.setpoint == 22.0 and not v.accepted
    v = s.validate("srv", "OFF", "ECO", None, 0.0, 26.0, None)
    assert (v.hvac, v.setpoint) == ("NORMAL", 24.0)
    v = s.validate("o", "OFF", "ECO", None, 0.8, 33.0, None)
    assert (v.hvac, v.setpoint) == ("NORMAL", 26.0)
    assert s.validate("o", "ON", "NORMAL", 24.0, 0.9, 25.0, 1200.0).vent_boost is True
    assert s.validate("o", "ON", "NORMAL", 24.0, 0.9, 25.0, 900.0).vent_boost is True     # hysteresis
    assert s.validate("o", "ON", "NORMAL", 24.0, 0.9, 25.0, 700.0).vent_boost is False
    v = s.validate("o", "DIM", "LOW", None, 0.3, 25.0, 500.0)
    assert v.accepted and v.notes == []


# ---------------------------------------------------------------- estimators
def test_random_forest_fast_path_equals_pipeline():
    rf = RandomForestEstimator()
    assert rf._fast_setup() is True
    obs = [Observation("r%d" % i, "office", datetime(2026, 3, 2, 9), 22 + i, 50 + i, 100 * i,
                       450 + 40 * i if i % 3 else None, 0.006 + 0.0005 * i, None) for i in range(12)]
    fast = rf.probabilities(obs)
    rf._fast = None
    rf._fast_checked = True
    slow = rf.probabilities(obs)
    assert fast == pytest.approx(slow, abs=1e-12)


# ---------------------------------------------------------------- live twin
@pytest.fixture(scope="module")
def twin():
    t = LiveTwin(seed=3, warmup=False)
    for _ in range(180):
        t.control_step()
    return t


def test_both_buildings_see_the_same_weather_and_people(twin):
    assert twin.ctrl.time == twin.base.time
    assert twin.ctrl.occupants == twin.base.occupants
    assert twin.ctrl.outdoor == twin.base.outdoor


def test_same_seed_same_result():
    a, b = LiveTwin(seed=9, warmup=False), LiveTwin(seed=9, warmup=False)
    for _ in range(90):
        a.control_step()
        b.control_step()
    assert a.ctrl.energy_wh == b.ctrl.energy_wh and a.base.energy_wh == b.base.energy_wh
    assert [r["control"] for r in a.room_states()] == [r["control"] for r in b.room_states()]


def test_metrics_and_explanations(twin):
    c = twin.comparison()
    assert c["ai"]["minutes"] == 180 and c["conventional"]["minutes"] == 180
    assert c["ai"]["total_kwh"] > 0 and c["conventional"]["total_kwh"] > 0
    eu = c["ai"]["end_use_kwh"]
    assert sum(eu.values()) == pytest.approx(c["ai"]["total_kwh"])
    assert sum(c["ai"]["floor_kwh"].values()) == pytest.approx(c["ai"]["total_kwh"])
    assert c["occupancy_fusion"]["n"] == 180 * 25
    decisions = [e for e in twin.timeline if e["kind"] == "decision"]
    assert decisions
    e = decisions[-1]
    for k in ("observed", "why", "proposed", "safety", "validated", "previous", "expected"):
        assert k in e
    assert e["expected"]["J_ac_options"] and e["expected"]["J_light_options"]
    filled = [x for x in decisions if x["outcome"] is not None]
    assert filled and all(x["outcome"]["after_min"] == 15 for x in filled)


def test_room_state_separates_truth_prediction_and_baseline(twin):
    for r in twin.room_states():
        assert r["source"] == "simulated"
        assert set(r["ground_truth"]) == {"true_occupancy", "max_occupancy"}
        assert 0.0 <= r["ai"]["occupancy_probability"] <= 1.0
        assert r["energy"]["power_w"] == pytest.approx(
            r["energy"]["hvac_w"] + r["energy"]["lighting_w"] + r["energy"]["plug_w"], abs=2)
        assert r["modes"]["ai"]["copy"] == "building" and r["modes"]["conventional"]["copy"] == "twin"
        assert r["modes"]["conventional"]["power_w"] >= 0


def test_scenario_applies_to_both_buildings_and_expires():
    t = LiveTwin(seed=4, warmup=False)
    for _ in range(240):                    # 10:00
        t.control_step()
    rid = "f2_meeting_b"
    t.add_scenario("occupancy", rid, 7, 10)
    t.add_scenario("heat_gain", rid, 2000, 10)
    t.control_step()
    assert t.ctrl.occupants[rid] == 7 == t.base.occupants[rid]
    assert t.ctrl.physics[rid].extra_gain_w == 2000 == t.base.physics[rid].extra_gain_w
    assert rid in t.watch
    for _ in range(12):
        t.control_step()
    assert not t.scenarios
    assert t.ctrl.physics[rid].extra_gain_w == 0 == t.base.physics[rid].extra_gain_w
    kinds = [e["kind"] for e in t.timeline if e.get("room_id") == rid]
    assert "scenario" in kinds
    with pytest.raises(ValueError):
        t.add_scenario("occupancy", "f2_office_a", 3, 10)     # the real room cannot be simulated
    with pytest.raises(ValueError):
        t.add_scenario("earthquake", rid, 1, 10)


def test_people_arriving_in_a_dark_empty_room_switch_lights_and_ac_on():
    t = LiveTwin(seed=4, warmup=False)
    for _ in range(14 * 60):                # Monday 20:00, after hours
        t.control_step()
    rid = "f2_office_b2"
    t.add_scenario("occupancy", rid, 0, 5)  # make sure it starts empty
    for _ in range(5):
        t.control_step()
    assert t.cmd["ctrl"][rid]["light"] == "OFF"
    t.add_scenario("occupancy", rid, 4, 30)
    for _ in range(3):
        t.control_step()
    assert t.cmd["ctrl"][rid]["light"] in ("DIM", "ON")
    assert t.cmd["ctrl"][rid]["hvac"] == "NORMAL"
    ev = [e for e in t.timeline if e.get("room_id") == rid and e["kind"] == "decision"]
    assert ev and "lights OFF ->" in ev[-1]["summary"] or any("AC" in e["summary"] for e in ev)


def test_clock_controls():
    t = LiveTwin(seed=4, warmup=False, speed=600)
    t0 = t.time
    assert t.advance_real(1.0) == 10                 # 600 s simulated = 10 control steps
    t.set_running(False)
    assert t.advance_real(1.0) == 0
    t.set_running(True)
    t.fast_forward(30)
    n = 0
    while t._ff_steps:
        n += t.advance_real(0.0)
    assert n == 30 and t.time == t0 + timedelta(minutes=40)
    t.set_controller("threshold_rf")
    t.control_step()
    assert t.ai_name == "threshold_rf" and t.comparison()["ai"]["minutes"] == 1
    with pytest.raises(ValueError):
        t.set_controller("schedule")              # conventional control is the AI-off mode, not an AI
    t.reset(seed=4)
    assert t.time == t0 and t.phase == "running"


def test_ai_switch_and_meter():
    t = LiveTwin(seed=5, warmup=False)
    for _ in range(4 * 60):                       # Monday 10:00, AI on
        t.control_step()
    assert t.mode_of("ctrl") == "ai" and t.mode_of("base") == "conventional"
    t.set_ai(False)
    assert t.mode_of("ctrl") == "conventional" and t.mode_of("base") == "ai"
    for _ in range(60):
        t.control_step()
    # conventional control at 10:00 on a weekday: offices lit and cooled whatever the occupancy
    rid = "f2_office_b2"
    assert t.cmd["ctrl"][rid]["light"] == "ON" and t.cmd["ctrl"][rid]["hvac"] == "NORMAL"
    st = next(r for r in t.room_states() if r["room_id"] == rid)
    assert st["control"]["mode"] == "conventional" and st["control"]["controller"] == "schedule"
    assert st["control"]["ai_would"] is not None
    assert st["modes"]["ai"]["copy"] == "twin" and st["modes"]["conventional"]["copy"] == "building"
    t.set_ai(True)
    for _ in range(30):
        t.control_step()
    m = t.meter(detail=True)
    modes = [s["mode"] for s in m["segments"]]
    assert modes == ["ai", "conventional", "ai"]
    assert [s["minutes"] for s in m["segments"]] == [240, 60, 30]
    assert sum(s["kwh"] for s in m["segments"]) == pytest.approx(m["total_kwh"], abs=0.02)
    # the same-period comparison covers every minute under both modes
    c = t.comparison()
    assert c["ai"]["minutes"] == c["conventional"]["minutes"] == 330
    seg_off = m["segments"][1]
    assert seg_off["ai_saving_pct"] is not None and seg_off["end"] is not None
    ev = [e for e in t.timeline if e.get("kind") == "switch"]
    assert len(ev) == 2


# ---------------------------------------------------------------- real room
def test_hardware_room_controller():
    spec = next(r for r in build_spec() if r.room_id == "f2_office_a")
    h = HardwareRoomController(spec, led_lux_full=None, outdoor_c=30)
    now = datetime(2026, 3, 2, 19, 0)
    out = h.step(now, 27.0, 65.0, 20.0, 440.0, 0.014, False)
    assert out["control"]["light_action"] == "OFF"
    out = h.step(now + timedelta(seconds=3), 27.0, 65.0, 20.0, 440.0, 0.014, True)
    assert out["control"]["light_action"] == "ON" and out["control"]["light_level"] == 255
    assert out["event"] is not None and out["event"]["source"] == "hardware"
    out = h.step(now + timedelta(seconds=6), 27.0, 65.0, 420.0, 1250.0, 0.014, True)
    assert out["control"]["vent_boost"] is True and out["control"]["servo_angle"] == 90
    out = h.step(now + timedelta(seconds=9), None, None, 20.0, None, None, True)
    assert "missing" in out["control"]["reason"]
    # AI off: conventional schedule on real time (offices 07:30-18:30 on weekdays)
    out = h.step(now + timedelta(seconds=12), 27.0, 65.0, 20.0, 440.0, 0.014, True, ai_enabled=False)
    assert out["control"]["mode"] == "conventional" and out["control"]["light_action"] == "OFF"
    assert out["control"]["ai_would"]["light_action"] == "ON"
    out = h.step(datetime(2026, 3, 3, 10, 0), 27.0, 65.0, 20.0, 440.0, 0.014, False, ai_enabled=False)
    assert (out["control"]["light_action"], out["control"]["hvac_action"], out["control"]["setpoint_c"]) == ("ON", "NORMAL", 24.0)
    assert (fan_pwm("ECO", None), fan_pwm("LOW", None), fan_pwm("NORMAL", 26), fan_pwm("NORMAL", 25),
            fan_pwm("NORMAL", 24)) == (0, 100, 150, 200, 255)
