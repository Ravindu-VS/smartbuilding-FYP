"""
TwinBuilding: the simulated rooms of the building, advanced on simulated time.

Owns the outdoor climate, the occupants, the sensors and one 5R1C RoomPhysics per
simulated room, plus heat flow through the partitions between neighbouring rooms
on the same floor.  Floor slabs are treated as adiabatic (rooms above/below are
assumed to be at similar temperatures).  Physics is integrated with a fixed
step (physics_dt, 15 s); the clock speed of the live system never changes the
step, only how many steps run per real second.

Two TwinBuilding objects built with the same seed and start see identical
weather, occupants and sensor noise, which is what makes the controller-vs-
baseline comparison fair.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from twin.climate import ScenarioClimate, humidity_ratio, relative_humidity
from twin.comfort import ThermalComfortCalculator
from twin.occupancy import BuildingOccupancy
from twin.physics import RoomPhysics
from twin.sensors import AdvancedSensorModels
from twin.spec import CLO, TYPE_PARAMS, RoomSpec, schedule_profiles

LIGHT_LEVELS = {"OFF": 0.0, "DIM": 0.4, "ON": 1.0}
HVAC_MAP = {"NORMAL": "comfort", "LOW": "setback", "ECO": "off", "OFF": "off"}
AIR_SPEED = 0.1


class TwinBuilding:
    def __init__(self, specs: List[RoomSpec], seed: int, start: datetime, physics_dt: float = 15.0):
        self.seed = int(seed)
        self.start = start
        self.time = start
        self.elapsed = 0.0
        self.physics_dt = float(physics_dt)
        self.specs: Dict[str, RoomSpec] = {r.room_id: r for r in specs if r.data_source != "hardware"}
        self.ids: List[str] = list(self.specs)
        self.climate = ScenarioClimate(seed=self.seed)
        self.occupancy = BuildingOccupancy(self.seed, schedule_profiles())
        self.sensors = AdvancedSensorModels(seed=self.seed)
        out0 = self.climate.at(start)
        self.outdoor = out0
        self.physics: Dict[str, RoomPhysics] = {}
        for rid, rs in self.specs.items():
            self.physics[rid] = RoomPhysics(
                rid, rs.room_type, rs.w, rs.d, rs.height, window_azimuth=rs.window_azimuth,
                params=rs.physics_params, initial_temperature=out0.temperature + 1.0,
                initial_w=out0.humidity_ratio,
                geometry={"wall_area": rs.wall_area, "window_area": rs.window_area, "roof_area": rs.roof_area})
        seen, self.pairs = set(), []
        for rid, rs in self.specs.items():
            for nb, area in rs.neighbours:
                if nb in self.specs and (nb, rid) not in seen:
                    seen.add((rid, nb))
                    self.pairs.append((rid, nb, area))
        self.occupants: Dict[str, int] = {rid: 0 for rid in self.ids}
        self.readings: Dict[str, Dict] = {}
        self.read_sensors(0.0)

    # ------------------------------------------------------------------ #
    def apply(self, rid: str, light: str, hvac: str, setpoint: Optional[float], vent_boost: bool = False) -> None:
        c = self.physics[rid].command
        c.light_level = LIGHT_LEVELS[light]
        c.hvac_mode = HVAC_MAP[hvac]
        c.comfort_setpoint = setpoint if c.hvac_mode == "comfort" else None
        c.vent_boost = bool(vent_boost)

    def advance(self, seconds: float) -> None:
        remaining = float(seconds)
        while remaining > 1e-9:
            h = min(self.physics_dt, remaining)
            self._substep(h)
            remaining -= h

    def _substep(self, h: float) -> None:
        t = self.time
        out = self.climate.at(t)
        self.outdoor = out
        for rid, rs in self.specs.items():
            self.occupants[rid] = self.occupancy.count(rid, rs.room_type, t, rs.max_occupancy)
        flows = {rid: 0.0 for rid in self.ids}
        for a, b, area in self.pairs:
            pa, pb = self.physics[a], self.physics[b]
            q = pa.p["u_internal"] * area * (pb.state.t_air - pa.state.t_air)
            flows[a] += q
            flows[b] -= q
        for rid, rp in self.physics.items():
            irr = self.climate.irradiance_on_window(out, rp.window_azimuth)
            rp.step(h, out, irr, self.occupants[rid], flows[rid])
            self.sensors.pir_step(rid, self.occupants[rid], h, self.elapsed)
        self.elapsed += h
        self.time = self.start + timedelta(seconds=self.elapsed)

    def read_sensors(self, dt: float) -> Dict[str, Dict]:
        """Sensor readings after dt seconds (advances the sensor lag state)."""
        d = max(dt, 1e-6)
        for rid, rp in self.physics.items():
            s = rp.state
            rh = relative_humidity(s.t_air, s.w)
            since = self.sensors.seconds_since_motion(rid, self.elapsed)
            t = self.sensors.temperature(rid, s.t_air, d)
            h = self.sensors.humidity(rid, rh, d)
            self.readings[rid] = {
                "temperature": t, "humidity": h,
                "light": self.sensors.light(s.daylight_lux + s.electric_lux),
                "co2": self.sensors.co2(rid, s.co2_ppm, d),
                "humidity_ratio": humidity_ratio(t, h),
                "pir_seconds": None if since == float("inf") else since,
            }
        return self.readings

    # ------------------------------------------------------------------ #
    def truth(self, rid: str) -> Dict:
        """True physical state of a room (for evaluation and the dashboard's model view)."""
        rp = self.physics[rid]
        s = rp.state
        rs = self.specs[rid]
        rh = relative_humidity(s.t_air, s.w)
        met = TYPE_PARAMS.get(rs.room_type, TYPE_PARAMS["office"])["met"]
        try:
            pmv = ThermalComfortCalculator.pmv_iso7730(s.t_air, s.t_surface, AIR_SPEED, rh, met, CLO)
        except ValueError:
            pmv = float("nan")
        return {
            "t_air": s.t_air, "t_surface": s.t_surface, "t_mass": s.t_mass, "t_operative": rp.operative_temperature,
            "rh": rh, "co2": s.co2_ppm, "daylight_lux": s.daylight_lux, "electric_lux": s.electric_lux,
            "pmv": max(-3.0, min(3.0, pmv)) if math.isfinite(pmv) else None,
            "occupants": self.occupants[rid],
            "hvac_w": s.hvac_electric_w + s.vent_w, "lighting_w": s.lighting_w, "plug_w": s.plug_w,
            "power_w": rp.total_power_w,
            "e_hvac_wh": s.e_hvac_wh, "e_lighting_wh": s.e_lighting_wh, "e_plug_wh": s.e_plug_wh,
            "energy_wh": rp.total_energy_wh,
            "hvac_mode": rp.command.hvac_mode, "setpoint": rp.setpoint(), "light_level": rp.command.light_level,
            "vent_boost": rp.command.vent_boost,
            "cooling_fraction": min(1.0, -s.hvac_thermal_w / rp.p["ac_cool_capacity_w"]) if s.hvac_thermal_w < 0 else 0.0,
        }

    @property
    def power_w(self) -> float:
        return sum(rp.total_power_w for rp in self.physics.values())

    @property
    def energy_wh(self) -> float:
        return sum(rp.total_energy_wh for rp in self.physics.values())

    def energy_by_end_use_wh(self) -> Dict[str, float]:
        e = {"hvac": 0.0, "lighting": 0.0, "plug": 0.0}
        for rp in self.physics.values():
            e["hvac"] += rp.state.e_hvac_wh
            e["lighting"] += rp.state.e_lighting_wh
            e["plug"] += rp.state.e_plug_wh
        return e

    def energy_by_floor_wh(self) -> Dict[int, float]:
        out: Dict[int, float] = {}
        for rid, rp in self.physics.items():
            f = self.specs[rid].floor_id
            out[f] = out.get(f, 0.0) + rp.total_energy_wh
        return out
