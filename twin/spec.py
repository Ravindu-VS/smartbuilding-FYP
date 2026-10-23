"""
Building specification for the live digital twin.

Everything about a room (plan geometry, type, capacity, envelope, lighting, air
conditioning, plug loads, occupant activity, sensors, schedule hours of the
conventional baseline) is derived here from integration/building_config.py,
which is also what the 3D view draws.  One definition drives the physics, the
controllers and the renderer.

The per-type numbers below are stated ASSUMPTIONS for an illustrative mixed-use
building in Colombo (typical design values), not measurements of a real
building.  The thesis's 36 m2 office values are the reference: same specific AC
capacity (147 W/m2), lighting 8 W/m2 for offices, 400 lux at full output,
165 kJ/m2K thermal mass, single glazing, 0.5 ACH infiltration + 1 ACH fresh air
with the AC.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from integration.building_config import (BUILDING_CONFIG, BUILDING_GEOMETRY, SCHEDULE_MAP,
                                         get_all_rooms)
from twin.physics import DEFAULT_PARAMS

# Thesis reference room (36 m2): AC 5275 W, window 2.4 m2, daylight factor 0.01
THESIS_AREA_M2 = 36.0
AC_W_PER_M2 = DEFAULT_PARAMS["ac_cool_capacity_w"] / THESIS_AREA_M2        # 146.5 W/m2
AC_FAN_W_PER_W = DEFAULT_PARAMS["ac_fan_w"] / DEFAULT_PARAMS["ac_cool_capacity_w"]
THESIS_WINDOW_TO_FLOOR = DEFAULT_PARAMS["window_area"] / THESIS_AREA_M2   # 0.0667

# Per room type (assumptions):
#   lpd      installed lighting W/m2 at full output
#   plug_m2  plug/equipment base load W/m2 (always on)
#   plug_pp  extra plug load W per person present
#   sens/lat occupant sensible/latent heat W per person (activity level)
#   met      activity (met) used for PMV; clo 0.5 everywhere (tropical clothing)
#   wwr      window share of the exposed wall area
TYPE_PARAMS: Dict[str, Dict[str, float]] = {
    "office":      dict(lpd=8.0,  plug_m2=1.1,  plug_pp=120, sens=75,  lat=55,  met=1.1, wwr=0.25),
    "executive":   dict(lpd=8.0,  plug_m2=1.1,  plug_pp=120, sens=75,  lat=55,  met=1.1, wwr=0.25),
    "meeting":     dict(lpd=10.0, plug_m2=0.4,  plug_pp=25,  sens=75,  lat=55,  met=1.1, wwr=0.25),
    "kitchen":     dict(lpd=8.0,  plug_m2=4.2,  plug_pp=200, sens=80,  lat=80,  met=1.4, wwr=0.20),
    "bathroom":    dict(lpd=6.0,  plug_m2=0.3,  plug_pp=30,  sens=80,  lat=60,  met=1.2, wwr=0.10),
    "lobby":       dict(lpd=10.0, plug_m2=1.0,  plug_pp=10,  sens=90,  lat=70,  met=1.4, wwr=0.40),
    "shop":        dict(lpd=14.0, plug_m2=6.0,  plug_pp=20,  sens=90,  lat=70,  met=1.4, wwr=0.40),
    "gym":         dict(lpd=8.0,  plug_m2=2.0,  plug_pp=60,  sens=140, lat=200, met=1.6, wwr=0.30),
    "lounge":      dict(lpd=7.0,  plug_m2=1.0,  plug_pp=30,  sens=75,  lat=55,  met=1.1, wwr=0.30),
    "corridor":    dict(lpd=5.0,  plug_m2=0.2,  plug_pp=0,   sens=90,  lat=70,  met=1.6, wwr=0.10),
    "server":      dict(lpd=6.0,  plug_m2=40.0, plug_pp=50,  sens=80,  lat=60,  met=1.2, wwr=0.0),
    "residential": dict(lpd=6.0,  plug_m2=2.0,  plug_pp=80,  sens=70,  lat=50,  met=1.0, wwr=0.25),
}
CLO = 0.5

# Design cooling set-point per type: what the conventional BMS (the baseline) holds
# during operating hours and the coldest option the AI controller may choose.
# Rooms with higher activity need cooler air for the same comfort (PMV), so a
# 24 C set-point everywhere would leave them warm whatever the controller does.
DESIGN_SETPOINT: Dict[str, float] = {"gym": 22.0, "kitchen": 22.0, "shop": 23.0}
DEFAULT_SETPOINT = 24.0
# Transit spaces: people pass through rather than stay, so the steady-state PMV
# comfort index (ISO 7730 / ASHRAE 55 apply to spaces occupied for 15 min or more)
# is not used for them in the comfort KPI; their conditions are still reported.
TRANSIT_TYPES = ("corridor", "lobby", "bathroom")

# Conventional time-schedule BMS (the baseline): lights ON + AC 24 C during the
# room's operating hours, off otherwise. (start_h, end_h, weekdays_only); end < start
# means overnight. Assumed operating hours per use.
SCHEDULE_HOURS: Dict[str, Tuple[float, float, bool]] = {
    "office": (7.5, 18.5, True), "executive": (7.5, 18.5, True), "meeting": (7.5, 18.5, True),
    "kitchen": (7.5, 18.5, True), "server": (7.5, 18.5, True),
    "lobby": (7.0, 22.0, False), "corridor": (7.0, 22.0, False), "bathroom": (7.0, 22.0, False),
    "shop": (9.0, 21.0, False), "gym": (5.0, 22.0, False), "lounge": (8.0, 21.0, False),
    "residential": (17.0, 8.0, False),
}
RESIDENTIAL_HOURS = (17.0, 8.0, False)

# Rooms whose equipment must stay cooled whatever the occupancy (safety layer)
EQUIPMENT_COOLED_TYPES = ("server",)


@dataclass
class RoomSpec:
    room_id: str
    name: str
    room_type: str
    floor_id: int
    floor_name: str
    floor_type: str
    max_occupancy: int
    x: float
    z: float
    w: float
    d: float
    height: float
    data_source: str                        # "simulation" | "hardware"
    exposed: Dict[str, float]               # exposed wall length per side (S, N, W, E)
    wall_area: float                        # gross exposed wall area m2
    window_area: float
    roof_area: float
    window_azimuth: float
    physics_params: Dict[str, float]
    controller_overrides: Dict[str, float]
    schedule_hours: Tuple[float, float, bool]
    equipment_cooled: bool
    design_setpoint: float = DEFAULT_SETPOINT
    transit: bool = False
    neighbours: List[Tuple[str, float]] = field(default_factory=list)   # (room_id, shared wall m2)
    sensors: Tuple[str, ...] = ("temperature", "humidity", "light", "co2", "pir")
    room_number: int = 0                    # report label: 101 = the real room, 102-126 = simulated

    @property
    def area(self) -> float:
        return self.w * self.d

    @property
    def volume(self) -> float:
        return self.area * self.height


def _exposure(x: float, z: float, w: float, d: float, W: float, D: float) -> Dict[str, float]:
    eps = 1e-6
    return {"S": w if z <= eps else 0.0, "N": w if abs(z + d - D) <= eps else 0.0,
            "W": d if x <= eps else 0.0, "E": d if abs(x + w - W) <= eps else 0.0}


AZIMUTH = {"S": 180.0, "N": 0.0, "W": 270.0, "E": 90.0}


def build_spec() -> List[RoomSpec]:
    g = BUILDING_GEOMETRY
    W, D = g["width_m"], g["depth_m"]
    height = g["floor_height_m"] - g["slab_m"]
    top_floor = max(f["floor_id"] for f in BUILDING_CONFIG["floors"])
    floor_type = {f["floor_id"]: f.get("floor_type", "") for f in BUILDING_CONFIG["floors"]}
    rooms: List[RoomSpec] = []
    for r in get_all_rooms():
        t = r["type"]
        tp = TYPE_PARAMS.get(t, TYPE_PARAMS["office"])
        x, z, w, d = float(r["x"]), float(r["z"]), float(r["w"]), float(r["d"])
        area = w * d
        exposed = _exposure(x, z, w, d, W, D)
        exposed_len = sum(exposed.values())
        wall_area = exposed_len * height
        window_area = tp["wwr"] * wall_area
        roof_area = area if r["floor_id"] == top_floor else 0.0
        side = max(exposed, key=exposed.get) if exposed_len > 0 else "S"
        df = 0.0
        if window_area > 0:
            df = min(0.05, DEFAULT_PARAMS["daylight_factor"] * (window_area / area) / THESIS_WINDOW_TO_FLOOR)
        ac_w = AC_W_PER_M2 * area
        lighting_w = tp["lpd"] * area
        params = {
            "lighting_w": lighting_w,
            "lighting_lux": DEFAULT_PARAMS["lighting_lux"],
            "daylight_factor": df,
            "ac_cool_capacity_w": ac_w,
            "ac_fan_w": AC_FAN_W_PER_W * ac_w,
            "plug_base_w": tp["plug_m2"] * area,
            "plug_per_person_w": tp["plug_pp"],
            "occupant_sensible_w": tp["sens"],
            "occupant_latent_w": tp["lat"],
        }
        # same relation as the thesis controller's default (1700 W for the 5275 W unit)
        ac_max_electric = ac_w / DEFAULT_PARAMS["ac_cop_cool"] + params["ac_fan_w"]
        design_sp = DESIGN_SETPOINT.get(t, DEFAULT_SETPOINT)
        ac_options = [("ECO", None), ("LOW", 27.0)] + [("NORMAL", float(sp))
                                                       for sp in range(26, int(design_sp) - 1, -1)]
        overrides = {"lighting_lux_full": DEFAULT_PARAMS["lighting_lux"], "lighting_w_full": lighting_w,
                     "ac_max_electric_w": ac_max_electric, "met": tp["met"], "clo": CLO,
                     "ac_options": ac_options, "energy_norm": THESIS_AREA_M2 / area}
        ftype = floor_type.get(r["floor_id"], "")
        hours = SCHEDULE_HOURS.get(t, SCHEDULE_HOURS["office"])
        if ftype == "residential" and t in ("corridor", "bathroom", "lobby"):
            hours = RESIDENTIAL_HOURS
        rooms.append(RoomSpec(
            room_id=r["room_id"], name=r.get("name", r["room_id"]), room_type=t, floor_id=r["floor_id"],
            floor_name=r.get("floor_name", ""), floor_type=ftype, max_occupancy=int(r.get("max_occupancy", 4)),
            x=x, z=z, w=w, d=d, height=height, data_source=r.get("data_source", "simulation"),
            exposed=exposed, wall_area=wall_area, window_area=window_area, roof_area=roof_area,
            window_azimuth=AZIMUTH[side], physics_params=params, controller_overrides=overrides,
            schedule_hours=hours, equipment_cooled=t in EQUIPMENT_COOLED_TYPES,
            design_setpoint=design_sp, transit=t in TRANSIT_TYPES))
    for rs, num in zip(rooms, _numbers(rooms)):
        rs.room_number = num
    # shared partitions between rooms on the same floor
    by_floor: Dict[int, List[RoomSpec]] = {}
    for rs in rooms:
        by_floor.setdefault(rs.floor_id, []).append(rs)
    for lst in by_floor.values():
        for i, a in enumerate(lst):
            for b in lst[i + 1:]:
                shared = 0.0
                if abs(a.x + a.w - b.x) < 1e-6 or abs(b.x + b.w - a.x) < 1e-6:
                    shared = min(a.z + a.d, b.z + b.d) - max(a.z, b.z)
                elif abs(a.z + a.d - b.z) < 1e-6 or abs(b.z + b.d - a.z) < 1e-6:
                    shared = min(a.x + a.w, b.x + b.w) - max(a.x, b.x)
                if shared > 0.5:
                    a.neighbours.append((b.room_id, shared * height))
                    b.neighbours.append((a.room_id, shared * height))
    return rooms


FIRST_REAL_ROOM_NUMBER = 101
FIRST_SIMULATED_ROOM_NUMBER = 102


def _numbers(rooms: List[RoomSpec]) -> List[int]:
    """Room numbers used in the report and the dashboard (labels only; the ids stay the keys).
    The real room (data_source "hardware", Office A) is Room 101; the 25 simulated rooms
    are 102-126 in configuration order (floor 0 first).  Numbers are not floor-coded."""
    out, real, sim = [], FIRST_REAL_ROOM_NUMBER, FIRST_SIMULATED_ROOM_NUMBER
    for r in rooms:
        if r.data_source == "hardware":
            out.append(real)
            real += 1
        else:
            out.append(sim)
            sim += 1
    return out


def room_number_map(rooms: Optional[List[RoomSpec]] = None) -> Dict[str, int]:
    return {r.room_id: r.room_number for r in (rooms or build_spec())}


def schedule_profiles() -> Dict[str, List[float]]:
    return {k: v["hourly"] for k, v in SCHEDULE_MAP.items()}


def spec_for_frontend(rooms: List[RoomSpec]) -> Dict:
    """What the 3D view and dashboard need to draw and label the building."""
    g = BUILDING_GEOMETRY
    floors = []
    for f in BUILDING_CONFIG["floors"]:
        floors.append({"floor_id": f["floor_id"], "name": f["name"], "floor_type": f.get("floor_type", ""),
                       "rooms": [r.room_id for r in rooms if r.floor_id == f["floor_id"]]})
    return {
        "building": {"name": BUILDING_CONFIG.get("name", ""), "width_m": g["width_m"], "depth_m": g["depth_m"],
                     "floor_height_m": g["floor_height_m"], "slab_m": g["slab_m"], "floors": len(floors)},
        "floors": floors,
        "rooms": [{
            "room_id": r.room_id, "room_number": r.room_number, "name": r.name, "type": r.room_type,
            "floor_id": r.floor_id,
            "x": r.x, "z": r.z, "w": r.w, "d": r.d, "area_m2": r.area, "max_occupancy": r.max_occupancy,
            "data_source": r.data_source, "window_area_m2": round(r.window_area, 1),
            "lighting_w": round(r.physics_params["lighting_w"]), "ac_capacity_w": round(r.physics_params["ac_cool_capacity_w"]),
            "schedule_hours": list(r.schedule_hours), "equipment_cooled": r.equipment_cooled,
            "design_setpoint_c": r.design_setpoint, "transit": r.transit,
            "neighbours": [n for n, _ in r.neighbours],
        } for r in rooms],
    }
