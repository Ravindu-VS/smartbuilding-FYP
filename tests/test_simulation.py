"""Simulation: rooms, units, thermal behaviour, energy, constraints, determinism, invalid input, stability."""
import math
from datetime import datetime

import pytest

from twin.building import LIGHT_LEVELS, TwinBuilding
from twin.climate import ColomboClimate
from twin.physics import RoomPhysics
from twin.safety import SETPOINT_RANGE, SafetyLayer
from twin.spec import build_spec, room_number_map

START = datetime(2026, 3, 2, 0, 0)


def test_26_rooms_5_floors_one_real_room_and_numbers():
    rs = build_spec()
    assert len(rs) == 26 and len({r.room_id for r in rs}) == 26
    assert sorted({r.floor_id for r in rs}) == [0, 1, 2, 3, 4]
    real = [r for r in rs if r.data_source == "hardware"]
    assert [r.room_id for r in real] == ["f2_office_a"]
    nums = room_number_map(rs)
    assert nums["f2_office_a"] == 101
    assert sorted(nums.values()) == list(range(101, 127))
    b = TwinBuilding(rs, 1, START)
    assert len(b.ids) == 25 and "f2_office_a" not in b.ids


def test_rooms_are_not_identical():
    rs = [r for r in build_spec() if r.data_source != "hardware"]
    areas = {round(r.area, 1) for r in rs}
    types = {r.room_type for r in rs}
    caps = {round(r.physics_params["ac_cool_capacity_w"]) for r in rs}
    assert len(areas) > 5 and len(types) > 5 and len(caps) > 5


def _room(**kw):
    out = ColomboClimate(0).at(datetime(2026, 3, 2, 14))
    rp = RoomPhysics("r", "office", 6, 6, 3, 180.0, initial_temperature=30.0, initial_w=out.humidity_ratio)
    return rp, out


def test_ac_cools_towards_setpoint_and_energy_is_electric_over_cop():
    rp, out = _room()
    rp.command.hvac_mode = "comfort"
    rp.command.comfort_setpoint = 24.0
    for _ in range(4 * 60 * 2):                       # 2 h at 15 s
        rp.step(15.0, out, 300.0, 3, 0.0)
    assert 23.0 < rp.state.t_air < 25.5
    s, p = rp.state, rp.p
    if s.hvac_thermal_w < 0:                          # electric = thermal (+latent) / COP + fan, never thermal alone
        assert s.hvac_electric_w >= -s.hvac_thermal_w / p["ac_cop_cool"] + p["ac_fan_w"] - 1e-6
        assert s.hvac_electric_w < -s.hvac_thermal_w     # COP 3.2 > 1: electricity below heat removed


def test_no_ac_room_warms_with_occupants_and_cools_less():
    rp1, out = _room()
    rp2, _ = _room()
    for _ in range(240):
        rp1.step(15.0, out, 300.0, 0, 0.0)
        rp2.step(15.0, out, 300.0, 6, 0.0)
    assert rp2.state.t_air > rp1.state.t_air          # people add heat
    assert rp1.state.hvac_electric_w == 0.0


def test_capacity_factor_zero_means_no_cooling_only_fan():
    rp, out = _room()
    rp.command.hvac_mode = "comfort"
    rp.capacity_factor = 0.0
    t0 = rp.state.t_air
    for _ in range(240):
        rp.step(15.0, out, 300.0, 2, 0.0)
    assert rp.state.hvac_thermal_w == 0.0
    assert math.isclose(rp.state.hvac_electric_w, rp.p["ac_fan_w"])
    assert rp.state.t_air > t0 - 0.5


def test_time_step_stability_and_consistency():
    finals = []
    for dt in (5.0, 15.0, 30.0):
        rp, out = _room()
        rp.command.hvac_mode = "comfort"
        for _ in range(int(3600 / dt)):
            rp.step(dt, out, 300.0, 2, 0.0)
        assert all(math.isfinite(v) for v in (rp.state.t_air, rp.state.t_mass, rp.state.co2_ppm, rp.state.w))
        finals.append(rp.state.t_air)
    assert max(finals) - min(finals) < 0.3            # result does not depend much on the step


def test_lighting_power_matches_command():
    rp, out = _room()
    for lvl, frac in LIGHT_LEVELS.items():
        rp.command.light_level = frac
        rp.step(15.0, out, 0.0, 0, 0.0)
        assert math.isclose(rp.state.lighting_w, rp.p["lighting_w"] * frac)


def test_energy_by_room_floor_and_end_use_add_up():
    b = TwinBuilding(build_spec(), 3, START)
    for rid in b.ids:
        b.apply(rid, "ON", "NORMAL", 24.0)
    b.advance(6 * 3600)
    total = b.energy_wh
    assert math.isclose(sum(b.energy_by_end_use_wh().values()), total, rel_tol=1e-9)
    assert math.isclose(sum(b.energy_by_floor_wh().values()), total, rel_tol=1e-9)
    assert math.isclose(sum(b.physics[r].total_energy_wh for r in b.ids), total, rel_tol=1e-9)


def test_same_seed_same_building_different_seed_differs():
    def run(seed):
        b = TwinBuilding(build_spec(), seed, START)
        b.advance(3 * 3600)
        b.read_sensors(60)
        return [b.physics[r].state.t_air for r in b.ids], [b.occupants[r] for r in b.ids]
    a1, a2, c = run(5), run(5), run(6)
    assert a1 == a2
    assert a1 != c


def test_safety_layer_bounds_and_rules():
    s = SafetyLayer({"srv": True})
    va = s.validate("r", "ON", "NORMAL", 18.0, 0.9, 25.0, 500.0)
    assert va.setpoint == SETPOINT_RANGE[0] and not va.accepted
    va = s.validate("r", "BLINK", "TURBO", None, 0.9, 25.0, 500.0)
    assert va.light == "OFF" and va.hvac == "ECO"
    assert s.validate("srv", "OFF", "ECO", None, 0.0, 25.0, None).hvac == "NORMAL"       # R2
    va = s.validate("r", "OFF", "ECO", None, 0.9, 33.0, None)                            # R3
    assert va.hvac == "NORMAL"
    assert s.validate("r", "ON", "NORMAL", 24.0, 0.9, 25.0, 1200.0).vent_boost            # R4 on
    assert s.validate("r", "ON", "NORMAL", 24.0, 0.9, 25.0, 900.0).vent_boost             # hysteresis
    assert not s.validate("r", "ON", "NORMAL", 24.0, 0.9, 25.0, 700.0).vent_boost


def test_invalid_command_is_rejected_by_building():
    b = TwinBuilding(build_spec(), 1, START)
    with pytest.raises(KeyError):
        b.apply(b.ids[0], "SUPERBRIGHT", "NORMAL", 24.0)
