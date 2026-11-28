"""Synthetic data generation, scenarios, fault injection, fail-safe controller and episode runner."""
import hashlib
from datetime import datetime, timedelta

import pytest

from twin.controllers import Decision, Observation, ScheduleController
from twin.runner import run_episode
from twin.safety import GuardedController, InputGuard, blocking
from twin.scenarios import SCENARIOS, ScenarioBuilding, SensorPath
from twin.spec import build_spec
from twin.validation import validate_records

START = datetime(2026, 3, 2)


def test_every_listed_scenario_exists():
    need = {"normal", "high_occupancy", "low_occupancy", "hot_weather", "cool_weather", "sudden_occupancy",
            "hvac_failure", "hvac_reduced", "sensor_dropout", "network_outage", "unusual_demand",
            "conflicting_objectives"}
    assert need <= set(SCENARIOS)


def test_runner_records_validate_and_are_deterministic():
    a = run_episode("schedule", "normal", seed=4, start=START, days=0.25, warmup_days=0.1, record_every=10)
    b = run_episode("schedule", "normal", seed=4, start=START, days=0.25, warmup_days=0.1, record_every=10)
    assert validate_records(a.records) == []
    h = lambda rs: hashlib.sha256(repr(rs).encode()).hexdigest()
    assert h(a.records) == h(b.records)
    assert abs(a.metrics["consistency_room_sum_minus_total_kwh"]) < 1e-6
    assert all(r["provenance"] == "synthetic" for r in a.records)


def test_validation_catches_impossible_state():
    a = run_episode("schedule", "normal", seed=4, start=START, days=0.05, warmup_days=0.05, record_every=5)
    bad = [dict(r) for r in a.records]
    bad[3]["t_air_c"] = 80.0
    bad[4]["occupants"] = 999
    probs = validate_records(bad)
    assert any("out of range" in p for p in probs) and any("occupants" in p for p in probs)


def test_occupancy_scaling_changes_head_counts():
    specs = build_spec()
    hi = ScenarioBuilding(specs, 2, START + timedelta(hours=10), "high_occupancy")
    lo = ScenarioBuilding(specs, 2, START + timedelta(hours=10), "low_occupancy")
    n_hi = n_lo = 0
    for _ in range(60):
        hi.advance(60)
        lo.advance(60)
        n_hi += sum(hi.occupants.values())
        n_lo += sum(lo.occupants.values())
    assert n_hi > n_lo
    for rid in hi.ids:
        assert hi.occupants[rid] <= hi.specs[rid].max_occupancy


def test_hvac_failure_window_sets_capacity():
    b = ScenarioBuilding(build_spec(), 3, START, "hvac_failure")
    rooms = b.fault_rooms["hvac_fault_0"]
    assert len(rooms) == 4
    b.advance((24 + 10) * 3600)                       # day 1, 10:00 is inside 09:00-15:00
    assert all(b.capacity_factor(r) == 0.0 for r in rooms)
    others = [r for r in b.ids if r not in rooms]
    assert all(b.capacity_factor(r) == 1.0 for r in others)


def test_sensor_dropout_and_network_outage():
    specs = build_spec()
    b = ScenarioBuilding(specs, 1, START + timedelta(hours=9, minutes=50), "network_outage")
    path = SensorPath("network_outage", b.ids, 1, b.time)
    _, age, out = path.deliver(b.readings, b.time)
    assert not out
    for _ in range(20):                                # into the 10:00-10:45 outage
        b.advance(60)
        b.read_sensors(60)
        _, age, out = path.deliver(b.readings, b.time)
    assert out and age >= 600
    b2 = ScenarioBuilding(specs, 1, START, "sensor_dropout")
    p2 = SensorPath("sensor_dropout", b2.ids, 1, b2.time)
    missing = 0
    for _ in range(50):
        b2.advance(60)
        b2.read_sensors(60)
        rd, _, _ = p2.deliver(b2.readings, b2.time)
        missing += sum(v is None for r in rd.values() for k, v in r.items() if k in ("temperature", "humidity", "light"))
    assert missing > 0


def test_input_guard_holds_then_flags_missing_stale_stuck():
    g = InputGuard(hold_s=180, stale_s=300, stuck_s=1800)
    t = START
    vals, p = g.check("r", {"temperature": 25.0, "humidity": 60.0, "light": 100.0, "co2": 600.0}, t)
    assert not blocking(p)
    vals, p = g.check("r", {"temperature": None, "humidity": 60.0, "light": 100.0, "co2": 600.0}, t + timedelta(minutes=2))
    assert vals["temperature"] == 25.0 and "temperature held" in p and not blocking(p)
    vals, p = g.check("r", {"temperature": None, "humidity": 60.0, "light": 100.0, "co2": 600.0}, t + timedelta(minutes=5))
    assert vals["temperature"] is None and "temperature missing" in blocking(p)
    _, p = g.check("r", {"temperature": 99.0, "humidity": 60.0, "light": 100.0}, t + timedelta(minutes=6))
    assert any("implausible" in x for x in p)
    _, p = g.check("r", {"temperature": 25.0, "humidity": 60.0, "light": 100.0}, t, age_s=400)
    assert any(x.startswith("stale") for x in blocking(p))
    g2 = InputGuard()
    for k in range(32):
        _, p = g2.check("s", {"temperature": 24.5, "humidity": 60.0, "light": 1.0}, t + timedelta(minutes=k))
    assert "temperature stuck" in p


class _Broken:
    name = "broken"

    def decide(self, obs):
        raise RuntimeError("model file corrupted")


class _Invalid:
    name = "invalid"

    def decide(self, obs):
        return Decision("ON", "TURBO", 0.9, "OCCUPIED", "bad", setpoint_c=float("nan"))


def _obs():
    return Observation("f2_office_b2", "office", START + timedelta(hours=10), 25.0, 60.0, 300.0, 600.0, 0.012, 30.0)


def test_guarded_controller_falls_back_and_says_why():
    sched = ScheduleController()
    g = GuardedController(_Broken(), sched)
    d = g.decide(_obs())
    assert d.reason.startswith("FAIL-SAFE (F2") and g.counts["F2"] == 1
    g = GuardedController(_Invalid(), sched)
    d = g.decide(_obs())
    assert d.reason.startswith("FAIL-SAFE (F3") and d.hvac_action in ("ECO", "LOW", "NORMAL")
    g = GuardedController(sched, sched)
    d = g.decide(_obs(), ["temperature missing"])
    assert "F1" in d.reason


@pytest.mark.slow
def test_fault_scenarios_run_with_sensor_driven_controller():
    r = run_episode("mo", "sensor_dropout", seed=5, start=START, days=0.5, warmup_days=0.2)
    assert r.metrics["failsafe_F2"] == 0 and r.metrics["failsafe_F3"] == 0
    assert r.metrics["failsafe_F1"] > 0                # the stuck sensors are caught
    r = run_episode("mo", "network_outage", seed=5, start=START + timedelta(hours=9), days=0.25, warmup_days=0.1)
    assert r.metrics["failsafe_F1"] > 0
