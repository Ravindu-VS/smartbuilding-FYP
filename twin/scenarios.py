"""
Operating scenarios and fault injection for the simulated building.

A scenario changes the conditions the building runs under, never the physics:
  * occupancy_scale        multiplies every room's head count (stochastic rounding,
                           deterministic per seed, room and minute; capped at the
                           room's capacity).  Forced occupancy is not scaled.
  * temp_offset_k          added to the synthetic Colombo outdoor temperature.
  * daylight_scale         multiplies solar irradiance and daylight (1 = clear model).
  * hvac_capacity          AC capacity factor for every room (1 = rated, 0 = failed).
  * hvac_faults            AC failures of chosen rooms for a time window.
  * extra_demand           unusual electrical load in chosen rooms (W, electricity and heat).
  * sudden_occupancy       unscheduled full-capacity occupancy of chosen rooms.
  * sensor_dropout_p       probability that one sensor value is missing in a reading.
  * stuck_temperature      rooms whose temperature sensor freezes at its first value.
  * network_outages        daily windows in which no new readings reach the controller.

Rooms are chosen from the seed, so a scenario with the same seed always hits the same
rooms.  The physical building (ScenarioBuilding) and the sensor/network path
(SensorPath) are separate: physics only sees occupancy, weather, AC capacity and
loads; faults in readings only change what the controller is told.
"""
from __future__ import annotations

import math
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from twin.building import TwinBuilding
from twin.spec import RoomSpec

# fields that can drop out (PIR "seconds since motion" is None when nothing was ever
# detected, so a PIR dropout could not be told apart from an empty room; it is not dropped)
SENSOR_FIELDS = ("temperature", "humidity", "light", "co2")


@dataclass(frozen=True)
class ScenarioSpec:
    name: str
    description: str
    occupancy_scale: float = 1.0
    temp_offset_k: float = 0.0
    daylight_scale: float = 1.0
    hvac_capacity: float = 1.0
    # (number of rooms, day index from the start, start hour, duration h, capacity factor)
    hvac_faults: Tuple[Tuple[int, int, float, float, float], ...] = ()
    # (number of rooms, start hour, end hour, extra W) every weekday
    extra_demand: Tuple[Tuple[int, float, float, float], ...] = ()
    # (number of rooms, events per room per day, duration minutes)
    sudden_occupancy: Tuple[int, float, float] = (0, 0.0, 0.0)
    sensor_dropout_p: float = 0.0
    stuck_temperature: int = 0
    # (start hour, duration minutes) every day
    network_outages: Tuple[Tuple[float, float], ...] = ()


SCENARIOS: Dict[str, ScenarioSpec] = {s.name: s for s in [
    ScenarioSpec("normal", "Synthetic Colombo weather, normal schedules, no faults"),
    ScenarioSpec("high_occupancy", "Every room 1.5 x its usual head count (capped at capacity)",
                 occupancy_scale=1.5),
    ScenarioSpec("low_occupancy", "Every room 0.4 x its usual head count", occupancy_scale=0.4),
    ScenarioSpec("hot_weather", "Outdoor air 3 K hotter than the synthetic normal (heat wave)", temp_offset_k=3.0),
    ScenarioSpec("cool_weather", "Monsoon-like: 2.5 K cooler and heavily overcast (40 % daylight)",
                 temp_offset_k=-2.5, daylight_scale=0.4),
    ScenarioSpec("sudden_occupancy", "Six rooms get unscheduled full-capacity occupancy (2 events/day, 60 min)",
                 sudden_occupancy=(6, 2.0, 60.0)),
    ScenarioSpec("hvac_failure", "AC of 4 rooms fails 09:00-15:00 on days 1 and 3; all others at rated capacity",
                 hvac_faults=((4, 1, 9.0, 6.0, 0.0), (4, 3, 9.0, 6.0, 0.0))),
    ScenarioSpec("hvac_reduced", "Every AC at 60 % of rated capacity (dirty coils / low refrigerant)",
                 hvac_capacity=0.6),
    ScenarioSpec("sensor_dropout", "10 % of sensor values missing; 2 rooms' temperature sensors stuck",
                 sensor_dropout_p=0.10, stuck_temperature=2),
    ScenarioSpec("network_outage", "No readings reach the controller 10:00-10:45 and 15:00-15:30 every day",
                 network_outages=((10.0, 45.0), (15.0, 30.0))),
    ScenarioSpec("unusual_demand", "Four rooms draw an extra 1.5 kW 10:00-16:00 on weekdays",
                 extra_demand=((4, 10.0, 16.0, 1500.0),)),
    ScenarioSpec("conflicting_objectives", "Heat wave (+3 K), 1.3 x occupancy and AC at 80 %: comfort costs energy",
                 occupancy_scale=1.3, temp_offset_k=3.0, hvac_capacity=0.8),
]}


def get_scenario(name_or_spec) -> ScenarioSpec:
    if isinstance(name_or_spec, ScenarioSpec):
        return name_or_spec
    if name_or_spec not in SCENARIOS:
        raise ValueError(f"unknown scenario {name_or_spec!r}; choose from {sorted(SCENARIOS)}")
    return SCENARIOS[name_or_spec]


def _pick(ids: Sequence[str], n: int, seed: int, salt: int) -> List[str]:
    if n <= 0:
        return []
    rng = np.random.default_rng([seed, salt, 991])
    return [ids[i] for i in sorted(rng.choice(len(ids), size=min(n, len(ids)), replace=False))]


def _unit_hash(*parts) -> float:
    """Deterministic number in [0, 1) from the parts (independent of query order)."""
    return (zlib.crc32(("|".join(map(str, parts))).encode()) & 0xFFFFFFFF) / 2 ** 32


class _ScaledOccupancy:
    """Wraps BuildingOccupancy: scales unforced head counts."""

    def __init__(self, base, scale: float, seed: int):
        self.base, self.scale, self.seed = base, float(scale), int(seed)

    def count(self, room_id, room_type: str, ts: datetime, max_occ: int) -> int:
        n = self.base.count(room_id, room_type, ts, max_occ)
        if self.scale == 1.0 or self.base.forced_until(room_id, ts) is not None:
            return n
        x = n * self.scale
        lo = math.floor(x)
        u = _unit_hash(self.seed, room_id, ts.toordinal(), ts.hour, ts.minute)
        return int(min(max_occ, lo + (1 if u < x - lo else 0)))

    def __getattr__(self, name):          # force / unforce / clear_forced / forced_until
        return getattr(self.base, name)


class ScenarioBuilding(TwinBuilding):
    """TwinBuilding under a scenario (weather offsets, occupancy scale, AC faults, extra loads)."""

    def __init__(self, specs: List[RoomSpec], seed: int, start: datetime, scenario="normal",
                 physics_dt: float = 15.0):
        super().__init__(specs, seed, start, physics_dt)
        self.scenario = get_scenario(scenario)
        sc = self.scenario
        self.climate.temp_offset_k = sc.temp_offset_k
        self.climate.daylight_scale = sc.daylight_scale
        if sc.occupancy_scale != 1.0:
            self.occupancy = _ScaledOccupancy(self.occupancy, sc.occupancy_scale, seed)
        candidates = [r for r in self.ids if not self.specs[r].equipment_cooled]
        self.fault_rooms: Dict[str, List[str]] = {}
        self._faults = []
        for k, (n, day, h0, dur, factor) in enumerate(sc.hvac_faults):
            rooms = _pick(candidates, n, seed, 10 + k)
            self.fault_rooms[f"hvac_fault_{k}"] = rooms
            t0 = datetime.combine((start + timedelta(days=day)).date(), datetime.min.time()) + timedelta(hours=h0)
            self._faults.append((rooms, t0, t0 + timedelta(hours=dur), factor))
        self._demand = []
        for k, (n, h0, h1, watts) in enumerate(sc.extra_demand):
            rooms = _pick(candidates, n, seed, 20 + k)
            self.fault_rooms[f"extra_demand_{k}"] = rooms
            self._demand.append((rooms, h0, h1, watts))
        n, per_day, minutes = sc.sudden_occupancy
        if n:
            rooms = _pick(candidates, n, seed, 30)
            self.fault_rooms["sudden_occupancy"] = rooms
            self._sudden = (rooms, per_day, minutes)
            self._planned_days = set()
        else:
            self._sudden = None
        self._apply_conditions(self.time)

    def _plan_sudden(self, day: datetime) -> None:
        rooms, per_day, minutes = self._sudden
        key = day.toordinal()
        if key in self._planned_days:
            return
        self._planned_days.add(key)
        rng = np.random.default_rng([self.seed, key, 31])
        for rid in rooms:
            for _ in range(rng.poisson(per_day)):
                start = datetime.combine(day.date(), datetime.min.time()) + timedelta(minutes=float(rng.uniform(0, 1440 - minutes)))
                self.occupancy.force(rid, self.specs[rid].max_occupancy, start, minutes)

    def _apply_conditions(self, t: datetime) -> None:
        base_cap = self.scenario.hvac_capacity
        for rid, rp in self.physics.items():
            rp.capacity_factor = base_cap
            rp.extra_plug_w = 0.0
        for rooms, t0, t1, factor in self._faults:
            if t0 <= t < t1:
                for rid in rooms:
                    self.physics[rid].capacity_factor = factor
        h = t.hour + t.minute / 60.0
        if t.weekday() < 5:
            for rooms, h0, h1, watts in self._demand:
                if h0 <= h < h1:
                    for rid in rooms:
                        self.physics[rid].extra_plug_w = watts
        if self._sudden is not None:
            self._plan_sudden(t)
            self._plan_sudden(t + timedelta(days=1))

    def _substep(self, h: float) -> None:
        self._apply_conditions(self.time)
        super()._substep(h)

    def capacity_factor(self, rid: str) -> float:
        return self.physics[rid].capacity_factor


class SensorPath:
    """
    What the controller receives from the sensors: dropouts, stuck sensors and network
    outages applied to the building's readings.  Returns, per room, the delivered
    readings (a missing value is None) and the age of the newest delivery.
    """

    def __init__(self, scenario, ids: Sequence[str], seed: int, start: datetime):
        self.scenario = get_scenario(scenario)
        self.seed = int(seed)
        self.start = start
        cands = list(ids)
        self.stuck_rooms = _pick(cands, self.scenario.stuck_temperature, seed, 40)
        self._stuck_value: Dict[str, float] = {}
        self._last: Dict[str, Dict] = {}
        self._last_time: Optional[datetime] = None
        self.step = 0

    def in_outage(self, ts: datetime) -> bool:
        h = ts.hour + ts.minute / 60.0 + ts.second / 3600.0
        return any(h0 <= h < h0 + m / 60.0 for h0, m in self.scenario.network_outages)

    def deliver(self, readings: Dict[str, Dict], ts: datetime) -> Tuple[Dict[str, Dict], float, bool]:
        """(readings as delivered, seconds since the last delivery, outage now)."""
        self.step += 1
        if self.in_outage(ts) and self._last_time is not None:
            return self._last, (ts - self._last_time).total_seconds(), True
        sc = self.scenario
        rng = np.random.default_rng([self.seed, self.step, 41]) if sc.sensor_dropout_p > 0 else None
        out: Dict[str, Dict] = {}
        for rid, rd in readings.items():
            r = dict(rd)
            if rid in self.stuck_rooms:
                r["temperature"] = self._stuck_value.setdefault(rid, rd["temperature"])
            if rng is not None:
                for f in SENSOR_FIELDS:
                    if r.get(f) is not None and rng.random() < sc.sensor_dropout_p:
                        r[f] = None
            out[rid] = r
        self._last, self._last_time = out, ts
        return out, 0.0, False
