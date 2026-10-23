"""
Plausibility and consistency checks for simulator output (synthetic data).

validate_records(rows) checks one generated table and returns a list of problems
(an empty list means every check passed).  Checks:
  ranges       air temperature 10-50 C, RH 0-100 %, CO2 >= 380 ppm (outdoor is 420),
               illuminance >= 0, powers >= 0, occupants 0..capacity (integers)
  equipment    AC electric power is 0 when the AC is off and the boost fan is off;
               lighting power is the room's installed power x the commanded level;
               power = AC + lighting + plug
  time         timestamps strictly increase per room with a constant interval
  inertia      air temperature changes by less than 1.5 K per minute of interval
               (a step change would mean a numerical problem, not physics)
  energy       cumulative energy never decreases
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from typing import Dict, Iterable, List

from twin.building import LIGHT_LEVELS
from twin.spec import build_spec

MAX_RATE_K_PER_MIN = 1.5


def validate_records(rows: Iterable[Dict], max_problems: int = 50) -> List[str]:
    specs = {r.room_id: r for r in build_spec()}
    problems: List[str] = []
    by_room: Dict[str, List[Dict]] = defaultdict(list)

    def bad(msg: str) -> None:
        if len(problems) < max_problems:
            problems.append(msg)

    for r in rows:
        by_room[r["room_id"]].append(r)
        rid, ts = r["room_id"], r["timestamp"]
        rs = specs.get(rid)
        if rs is None:
            bad(f"{ts} unknown room {rid}")
            continue
        if not 10.0 <= r["t_air_c"] <= 50.0:
            bad(f"{ts} {rid} air temperature {r['t_air_c']} C out of range")
        if not 0.0 <= r["rh_pct"] <= 100.0:
            bad(f"{ts} {rid} RH {r['rh_pct']} % out of range")
        if r["co2_ppm"] < 380.0:
            bad(f"{ts} {rid} CO2 {r['co2_ppm']} ppm below outdoor level")
        if r["lux"] < 0:
            bad(f"{ts} {rid} negative illuminance")
        for k in ("hvac_w", "lighting_w", "plug_w", "power_w"):
            if r[k] < -1e-9:
                bad(f"{ts} {rid} negative {k}")
        occ = r["occupants"]
        if not isinstance(occ, int) or occ < 0 or occ > rs.max_occupancy:
            bad(f"{ts} {rid} occupants {occ} outside 0..{rs.max_occupancy}")
        if r["hvac_cmd"] in ("ECO", "OFF") and not r["vent_boost"] and r["hvac_w"] > 1e-6:
            bad(f"{ts} {rid} AC off but AC power {r['hvac_w']} W")
        expect_light = rs.physics_params["lighting_w"] * LIGHT_LEVELS[r["light_cmd"]]
        if abs(r["lighting_w"] - expect_light) > 0.01 + 1e-6 * expect_light:
            bad(f"{ts} {rid} lighting {r['lighting_w']} W != {expect_light:.3f} W for {r['light_cmd']}")
        if abs(r["power_w"] - (r["hvac_w"] + r["lighting_w"] + r["plug_w"])) > 0.01:
            bad(f"{ts} {rid} power != AC + lighting + plug")
    for rid, lst in by_room.items():
        times = [datetime.fromisoformat(r["timestamp"]) for r in lst]
        steps = {(b - a).total_seconds() for a, b in zip(times, times[1:])}
        if any(s <= 0 for s in steps):
            bad(f"{rid}: timestamps not strictly increasing")
        if len(steps) > 1:
            bad(f"{rid}: irregular interval {sorted(steps)[:5]}")
        dt_min = (min(steps) / 60.0) if steps else 1.0
        for a, b in zip(lst, lst[1:]):
            if abs(b["t_air_c"] - a["t_air_c"]) > MAX_RATE_K_PER_MIN * dt_min:
                bad(f"{b['timestamp']} {rid}: air temperature jumped {a['t_air_c']} -> {b['t_air_c']}")
            if b["energy_wh_cum"] + 1e-6 < a["energy_wh_cum"]:
                bad(f"{b['timestamp']} {rid}: cumulative energy decreased")
    return problems
