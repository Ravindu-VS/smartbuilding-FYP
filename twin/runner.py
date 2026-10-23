"""
Episode runner: one controller drives the 25 simulated rooms through a scenario.

Used for synthetic data generation (scripts/generate_synthetic.py), controller
comparisons (rl/evaluate.py) and the experiments (experiments/run.py).  The decision
path is the live twin's: readings -> InputGuard -> controller (GuardedController,
fail-safe to the rule-based schedule) -> SafetyLayer -> actuators.  Every controller
under comparison sees the same weather, occupants and sensor noise for a given seed
(the building is rebuilt from the seed for each run).

Metrics (measured after the warm-up; only the 25 simulated rooms):
  energy_kwh            electricity of the rooms: AC (compressor + fan) + fresh-air boost
                        fan + lighting + plug loads
  hvac_kwh / lighting_kwh / plug_kwh   the same split by end use
  occupied_min          room-minutes with at least one person (true head count; transit
                        rooms such as corridors excluded, as in the live meter)
  discomfort_min        occupied room-minutes with |PMV| > 0.5 (ISO 7730 category B)
  discomfort_pmv_h      sum over occupied minutes of max(0, |PMV| - 0.5) x hours
  overheat_min          occupied room-minutes with air temperature > design set-point + 2 K
  temp_rmse_occupied_c  RMS of (air temperature - room design set-point) while occupied
  iaq_min               occupied room-minutes with true CO2 > 1000 ppm
  light_switches / hvac_changes / ac_cycles   changes of the validated commands
  failsafe_F1/F2/F3     fall-backs to the rule-based controller (see twin/safety.py)
  safety_overrides      decisions changed by safety rules R1-R3; vent_boost_min (R4)
  decision_ms_mean / decision_ms_p95   controller time per room decision on this machine
  peak_kw               highest 1-min building power of the rooms
"""
from __future__ import annotations

import math
import platform
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional

import numpy as np

from twin.controllers import (AlwaysOnController, FusionEstimator, MultiObjectiveController, Observation,
                              RandomForestEstimator, ScheduleController, ThresholdController)
from twin.safety import GuardedController, InputGuard, SafetyLayer
from twin.scenarios import ScenarioBuilding, SensorPath, get_scenario
from twin.spec import build_spec

CONTROL_DT = 60.0
DEFAULT_START = datetime(2026, 3, 2, 0, 0)        # a Monday in the hot, dry season
TUNED_WEIGHTS = {"alpha": 1.0, "beta": 3.0, "gamma": 0.1, "light_margin": 0.03}   # = twin/live.py
CONTROLLER_NAMES = ("schedule", "always_on", "threshold_rf", "mo", "ppo")
CONTROLLER_LABELS = {
    "schedule": "Conventional schedule (lights on + AC at design set-point in operating hours)",
    "always_on": "Always on (reference upper bound on energy)",
    "threshold_rf": "Original project rule: thresholds on the Random Forest occupancy probability",
    "mo": "Multi-objective optimiser (PIR+CO2 fusion, 30-min look-ahead; MPC-like)",
    "ppo": "PPO policy (rl/), behind the same guard and safety layer",
}


class _CachedEstimator:
    """Probability looked up from a per-step batch (the RF is evaluated once for all rooms)."""

    def __init__(self, inner):
        self.inner, self.cache = inner, {}
        self.name = inner.name

    def probability(self, obs: Observation) -> float:
        return self.cache[obs.room_id]


def make_controller(name: str, specs, ppo_policy: Optional[str] = None, rf=None):
    if name == "schedule":
        return ScheduleController(room_hours={r.room_id: r.schedule_hours for r in specs})
    if name == "always_on":
        return AlwaysOnController()
    if name == "mo":
        overrides = {r.room_id: dict(r.controller_overrides) for r in specs}
        return MultiObjectiveController(FusionEstimator(), room_overrides=overrides, **TUNED_WEIGHTS)
    if name == "threshold_rf":
        rf = rf or RandomForestEstimator(lighting_lux_full={
            r.room_id: r.controller_overrides["lighting_lux_full"] for r in specs})
        return ThresholdController(_CachedEstimator(rf))
    if name == "ppo":
        from rl.policy import PPOController
        return PPOController.load(ppo_policy) if ppo_policy else PPOController.load_active()
    raise ValueError(f"unknown controller {name!r}; choose from {CONTROLLER_NAMES}")


def _cmd(light="OFF", hvac="ECO", sp=None, vent=False):
    return {"light": light, "hvac": hvac, "sp": sp, "vent": vent}


@dataclass
class EpisodeResult:
    controller: str
    scenario: str
    seed: int
    start: str
    days: float
    warmup_days: float
    metrics: Dict[str, float]
    per_room: Dict[str, Dict[str, float]]
    meta: Dict
    records: Optional[List[Dict]] = None
    daily_kwh: List[float] = field(default_factory=list)


def run_episode(controller: str = "schedule", scenario="normal", seed: int = 1,
                start: datetime = DEFAULT_START, days: float = 7.0, warmup_days: float = 7.0,
                record_every: int = 0, ppo_policy: Optional[str] = None, rf=None,
                controller_obj=None, progress: Optional[Callable[[float], None]] = None) -> EpisodeResult:
    """Run one episode.  record_every > 0 keeps one row per room every that many control steps."""
    sc = get_scenario(scenario)
    specs = build_spec()
    t0 = start - timedelta(days=warmup_days)
    b = ScenarioBuilding(specs, seed, t0, sc)
    ids = b.ids
    spec = b.specs
    path = SensorPath(sc, ids, seed, t0)
    guard = InputGuard()
    safety = SafetyLayer({r.room_id: r.equipment_cooled for r in specs})
    ctrl = controller_obj or make_controller(controller, specs, ppo_policy=ppo_policy, rf=rf)
    fallback = make_controller("schedule", specs)
    guarded = GuardedController(ctrl, fallback)
    rf_batch = ctrl.estimator if isinstance(getattr(ctrl, "estimator", None), _CachedEstimator) else None
    cmd = {rid: _cmd() for rid in ids}
    for rid in ids:
        b.apply(rid, "OFF", "ECO", None)

    n_steps = int(round((warmup_days + days) * 86400 / CONTROL_DT))
    m = {k: 0.0 for k in ("hvac_kwh", "lighting_kwh", "plug_kwh", "occupied_min", "discomfort_min",
                          "discomfort_pmv_h", "overheat_min", "iaq_min", "light_switches", "hvac_changes",
                          "ac_cycles", "safety_overrides", "vent_boost_min", "peak_kw", "sq_err_occ")}
    per_room = {rid: {"energy_kwh": 0.0, "occupied_min": 0.0, "discomfort_min": 0.0, "iaq_min": 0.0}
                for rid in ids}
    dec_ms: List[float] = []
    records: List[Dict] = [] if record_every else None
    daily: Dict[str, float] = {}
    wall0 = time.perf_counter()
    e_prev = {rid: b.physics[rid].total_energy_wh for rid in ids}
    end_prev = b.energy_by_end_use_wh()
    for step in range(n_steps):
        ts = b.time
        measure = ts >= start
        delivered, age, outage = path.deliver(b.readings, ts)
        if rf_batch is not None:
            obs_rf = [Observation(rid, spec[rid].room_type, ts, rd["temperature"] if rd["temperature"] is not None else float("nan"),
                                  rd["humidity"] if rd["humidity"] is not None else float("nan"),
                                  rd["light"] if rd["light"] is not None else float("nan"), rd["co2"],
                                  rd["humidity_ratio"], rd["pir_seconds"], current_light=cmd[rid]["light"])
                      for rid, rd in delivered.items()]
            rf_batch.cache = dict(zip(ids, rf_batch.inner.probabilities(obs_rf)))
        for rid in ids:
            rd = delivered[rid]
            rs = spec[rid]
            vals, problems = guard.check(rid, {"temperature": rd["temperature"], "humidity": rd["humidity"],
                                               "light": rd["light"], "co2": rd["co2"] if "co2" in rs.sensors else None},
                                         ts, age)
            t_in = vals["temperature"]
            h_in = vals["humidity"]
            hr = rd.get("humidity_ratio")
            o = Observation(
                room_id=rid, room_type=rs.room_type, timestamp=ts,
                temperature=t_in if t_in is not None else float("nan"),
                humidity=h_in if h_in is not None else float("nan"),
                light_lux=vals["light"] if vals["light"] is not None else float("nan"),
                co2=vals["co2"], humidity_ratio=hr if hr is not None else float("nan"),
                seconds_since_motion=rd["pir_seconds"], current_light=cmd[rid]["light"],
                current_hvac=cmd[rid]["hvac"], current_setpoint=cmd[rid]["sp"],
                outdoor_temperature=b.outdoor.temperature,
                hvac_power_w=b.physics[rid].state.hvac_electric_w, true_occupants=b.occupants[rid])
            c0 = time.perf_counter()
            d = guarded.decide(o, problems)
            if measure:
                dec_ms.append((time.perf_counter() - c0) * 1000.0)
            p = d.occupancy_probability
            if p is None or not math.isfinite(p):
                p = 1.0 if d.control_mode == "OCCUPIED" else 0.0
            sp = d.setpoint_c
            if d.hvac_action == "NORMAL" and sp is None:
                sp = rs.design_setpoint
            va = safety.validate(rid, d.light_action, d.hvac_action, sp, p, t_in, vals["co2"])
            new = _cmd(va.light, va.hvac, va.setpoint, va.vent_boost)
            prev = cmd[rid]
            if measure:
                m["safety_overrides"] += not va.accepted
            if new != prev:
                if measure:
                    m["light_switches"] += new["light"] != prev["light"]
                    m["hvac_changes"] += (new["hvac"] != prev["hvac"]) or (new["sp"] != prev["sp"])
                    m["ac_cycles"] += (new["hvac"] == "ECO") != (prev["hvac"] == "ECO")
                cmd[rid] = new
                b.apply(rid, new["light"], new["hvac"], new["sp"], new["vent"])
        b.advance(CONTROL_DT)
        b.read_sensors(CONTROL_DT)
        end_now = b.energy_by_end_use_wh()
        if measure:
            for k in ("hvac", "lighting", "plug"):
                m[f"{k}_kwh"] += (end_now[k] - end_prev[k]) / 1000.0
            m["peak_kw"] = max(m["peak_kw"], b.power_w / 1000.0)
            day = ts.date().isoformat()
            for rid in ids:
                rp = b.physics[rid]
                e = rp.total_energy_wh
                per_room[rid]["energy_kwh"] += (e - e_prev[rid]) / 1000.0
                daily[day] = daily.get(day, 0.0) + (e - e_prev[rid]) / 1000.0
                m["vent_boost_min"] += cmd[rid]["vent"]
                rs = spec[rid]
                occ = b.occupants[rid]
                if occ > 0 and not rs.transit:
                    tr = b.truth(rid)
                    m["occupied_min"] += 1
                    per_room[rid]["occupied_min"] += 1
                    pmv = tr["pmv"]
                    if pmv is not None and abs(pmv) > 0.5:
                        m["discomfort_min"] += 1
                        per_room[rid]["discomfort_min"] += 1
                        m["discomfort_pmv_h"] += (abs(pmv) - 0.5) / 60.0
                    if tr["t_air"] > rs.design_setpoint + 2.0:
                        m["overheat_min"] += 1
                    m["sq_err_occ"] += (tr["t_air"] - rs.design_setpoint) ** 2
                    if tr["co2"] > 1000.0:
                        m["iaq_min"] += 1
                        per_room[rid]["iaq_min"] += 1
                e_prev[rid] = e
            if records is not None and step % record_every == 0:
                for rid in ids:
                    records.append(_record(b, rid, delivered[rid], cmd[rid], age, outage, sc.name, seed, controller))
        else:
            for rid in ids:
                e_prev[rid] = b.physics[rid].total_energy_wh
        end_prev = end_now
        if progress and step % 1440 == 0:
            progress(step / n_steps)

    energy = m["hvac_kwh"] + m["lighting_kwh"] + m["plug_kwh"]
    occ = max(1.0, m["occupied_min"])
    room_sum = sum(v["energy_kwh"] for v in per_room.values())
    metrics = {
        "energy_kwh": energy, "hvac_kwh": m["hvac_kwh"], "lighting_kwh": m["lighting_kwh"], "plug_kwh": m["plug_kwh"],
        "controllable_kwh": m["hvac_kwh"] + m["lighting_kwh"],
        "occupied_min": m["occupied_min"], "discomfort_min": m["discomfort_min"],
        "discomfort_share": m["discomfort_min"] / occ, "discomfort_pmv_h": m["discomfort_pmv_h"],
        "overheat_min": m["overheat_min"], "temp_rmse_occupied_c": math.sqrt(m["sq_err_occ"] / occ),
        "iaq_min": m["iaq_min"], "iaq_share": m["iaq_min"] / occ,
        "light_switches": m["light_switches"], "hvac_changes": m["hvac_changes"], "ac_cycles": m["ac_cycles"],
        "safety_overrides": m["safety_overrides"], "vent_boost_min": m["vent_boost_min"],
        "failsafe_F1": guarded.counts["F1"], "failsafe_F2": guarded.counts["F2"], "failsafe_F3": guarded.counts["F3"],
        "decision_ms_mean": float(np.mean(dec_ms)) if dec_ms else 0.0,
        "decision_ms_p95": float(np.percentile(dec_ms, 95)) if dec_ms else 0.0,
        "peak_kw": m["peak_kw"], "wall_s": time.perf_counter() - wall0,
        "consistency_room_sum_minus_total_kwh": room_sum - energy,
    }
    meta = {"scenario_description": sc.description, "fault_rooms": b.fault_rooms,
            "stuck_temperature_rooms": path.stuck_rooms, "controller_label": CONTROLLER_LABELS.get(controller, controller),
            "control_dt_s": CONTROL_DT, "physics_dt_s": b.physics_dt, "rooms": len(ids),
            "python": platform.python_version(), "provenance": "synthetic"}
    if guarded.last_error:
        meta["last_controller_error"] = guarded.last_error
    return EpisodeResult(controller, sc.name, seed, start.isoformat(), days, warmup_days, metrics, per_room, meta,
                         records, [round(v, 4) for _, v in sorted(daily.items())])


def _record(b: ScenarioBuilding, rid: str, rd: Dict, cmd: Dict, age: float, outage: bool,
            scenario: str, seed: int, controller: str) -> Dict:
    tr = b.truth(rid)
    rs = b.specs[rid]
    out = b.outdoor
    return {
        "timestamp": b.time.isoformat(timespec="seconds"), "room_id": rid, "room_number": rs.room_number,
        "floor": rs.floor_id, "room_type": rs.room_type, "scenario": scenario, "seed": seed,
        "controller": controller, "provenance": "synthetic",
        # true simulated state
        "t_air_c": round(tr["t_air"], 4), "t_operative_c": round(tr["t_operative"], 4), "rh_pct": round(tr["rh"], 3),
        "co2_ppm": round(tr["co2"], 2), "lux": round(tr["daylight_lux"] + tr["electric_lux"], 2),
        "daylight_lux": round(tr["daylight_lux"], 2), "occupants": tr["occupants"],
        "pmv": None if tr["pmv"] is None else round(tr["pmv"], 4),
        # what the sensors delivered to the controller (None = missing)
        "meas_temperature_c": rd["temperature"], "meas_humidity_pct": rd["humidity"], "meas_lux": rd["light"],
        "meas_co2_ppm": rd["co2"], "meas_pir_seconds": rd["pir_seconds"],
        "reading_age_s": age, "network_outage": int(outage),
        # commands (validated) and equipment state
        "light_cmd": cmd["light"], "hvac_cmd": cmd["hvac"], "setpoint_c": cmd["sp"], "vent_boost": int(cmd["vent"]),
        "hvac_w": round(tr["hvac_w"], 3), "lighting_w": round(tr["lighting_w"], 3), "plug_w": round(tr["plug_w"], 3),
        "power_w": round(tr["power_w"], 3), "energy_wh_cum": round(tr["energy_wh"], 3),
        "hvac_capacity_factor": b.physics[rid].capacity_factor, "cooling_fraction": round(tr["cooling_fraction"], 4),
        # outdoor (synthetic Colombo climate)
        "t_out_c": round(out.temperature, 3), "rh_out_pct": round(out.relative_humidity, 2),
        "ghi_w_m2": round(out.ghi, 2),
    }
