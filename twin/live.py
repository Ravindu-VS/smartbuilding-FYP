"""
LiveTwin: the running digital twin behind the dashboard.

AI control has a master switch (ON/OFF, one click, every room at once):

    AI ON   rooms are decided by the AI: the thesis's PIR+CO2 occupancy estimator
            and multi-objective controller (or, selectable, the project's original
            rule on the Random Forest), then the safety layer;
    AI OFF  rooms are run by conventional control, the way a building without AI
            is run: a time schedule (lights on + AC at the room's design set-point
            during its operating hours), through the same safety layer.

Two copies of the simulated building run in lock-step on the same simulated clock
with identical weather, occupants and sensor noise:

    the building   follows the switch (this is the "real" building: its meter is
                   what the dashboard's energy meter shows);
    the twin copy  always runs the OTHER mode.

So for every minute there is an AI-controlled result and a conventionally
controlled result for exactly the same conditions, whatever the switch position.
Energy, comfort and occupancy-estimation figures are accumulated per mode from the
simulator's true state ("same period" comparison), and the building's meter keeps
one segment per switch position (when it was switched, for how long, kWh used, and
what the other mode used over the same minutes).

Every control step (60 simulated seconds) each room's controller reads that room's
sensors, proposes an action, the safety layer validates it and it is applied; then
both buildings are integrated for 60 s (physics step 15 s).  Every change of
action in the building is logged with the observation it was based on, the
controller's own cost terms, the safety result and, 15 minutes later, the observed
outcome.  While AI is off it keeps observing (it still learns the routine) and the
dashboard can show what it would do.

The clock: start/pause/resume, reset (same seed and start = same scenario), speed
(simulated seconds per real second), fast-forward.  Speed only changes how many
60-s steps run per real second; the physics step is fixed.  Demonstration
scenarios change real simulation inputs and are applied to both copies.
"""
from __future__ import annotations

import copy
import glob
import hashlib
import math
import os
import pickle
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from twin.building import TwinBuilding
from twin.controllers import (FusionEstimator, MultiObjectiveController, Observation,
                              RandomForestEstimator, ScheduleController, ThresholdController,
                              VISUAL_TARGET_LUX)
from twin.safety import SafetyLayer
from twin.spec import RoomSpec, build_spec

CONTROL_DT = 60.0
# The AI learns each room's weekly routine from its own estimates; as in the
# thesis experiments it gets 7 simulated days of learning before measurement.
WARMUP_DAYS = 7
OBSERVE_EVERY = 5            # while AI is off it observes every 5 steps (keeps learning)
TWIN_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(TWIN_DIR)
CACHE_DIR = os.path.join(PROJECT_ROOT, "output", "twin_cache")
DEFAULT_START = datetime(2026, 3, 2, 6, 0)     # a Monday in the dry, hot season
# Multi-objective weights chosen on the thesis's validation seeds (tuned_weights.json);
# light_margin is a live-twin addition against near-tie flicker (thesis: 0).
TUNED_WEIGHTS = {"alpha": 1.0, "beta": 3.0, "gamma": 0.1, "light_margin": 0.03}
# Electricity price: an ASSUMED flat tariff, configurable (env TARIFF_LKR_PER_KWH)
TARIFF_LKR_PER_KWH = float(os.environ.get("TARIFF_LKR_PER_KWH", "50"))

CONTROLLERS = {
    "mo": "AI optimizer: multi-objective (PIR+CO2 estimator, thesis method)",
    "threshold_rf": "Original rule: thresholds on the Random Forest probability",
}
CONVENTIONAL_LABEL = ("Conventional control (AI off): lights on + AC at the room's design set-point "
                      "(24 C; gym and kitchen 22 C, shop 23 C) during its operating hours")
MODES = ("ai", "conventional")

SCENARIOS = ("occupancy", "heat_gain", "co2", "window", "heat_wave", "overcast")


@dataclass
class Scenario:
    sid: int
    kind: str
    room_id: Optional[str]
    value: float
    start: datetime
    end: datetime
    label: str


class ModeAccumulator:
    """Measured results for the building-minutes run under one control mode."""

    def __init__(self, ids: List[str]):
        self.kwh = {"hvac": 0.0, "lighting": 0.0, "plug": 0.0}
        self.kwh_floor: Dict[int, float] = {}
        self.kwh_room: Dict[str, float] = {rid: 0.0 for rid in ids}
        self.minutes = 0
        self.occ_min = 0
        self.stay_min = 0                  # occupied minutes in rooms where people stay (not transit)
        self.by_type: Dict[str, list] = {}  # type -> [occupied min, |PMV| > 0.5 min, sum PMV]
        self.pmv_viol = 0
        self.lux_viol = 0
        self.co2_viol = 0
        self.light_unocc = 0
        self.unocc_min = 0
        self.ac_unocc = 0
        self.unocc_min_ac = 0
        self.ac_onoff = 0
        self.switches = 0
        self.power_window: deque = deque(maxlen=15)
        self.peak_15min_w = 0.0
        self.power_w = 0.0

    def add(self, b: TwinBuilding, d_end: Dict[str, float], d_room: Dict[str, float]) -> None:
        self.minutes += 1
        for k, v in d_end.items():
            self.kwh[k] += v / 1000.0
        for rid, v in d_room.items():
            self.kwh_room[rid] += v / 1000.0
            f = b.specs[rid].floor_id
            self.kwh_floor[f] = self.kwh_floor.get(f, 0.0) + v / 1000.0
        for rid in b.ids:
            rp = b.physics[rid]
            rs = b.specs[rid]
            s = rp.state
            if b.occupants[rid] > 0:
                self.occ_min += 1
                tr = b.truth(rid)
                bad = tr["pmv"] is not None and abs(tr["pmv"]) > 0.5
                ty = self.by_type.setdefault(rs.room_type, [0, 0, 0.0])
                ty[0] += 1
                ty[1] += bad
                ty[2] += tr["pmv"] or 0.0
                if not rs.transit:
                    self.stay_min += 1
                    self.pmv_viol += bad
                self.lux_viol += (s.daylight_lux + s.electric_lux) < VISUAL_TARGET_LUX
                self.co2_viol += s.co2_ppm > 1000
            else:
                self.unocc_min += 1
                self.light_unocc += rp.command.light_level > 0
                if not rs.equipment_cooled:
                    self.unocc_min_ac += 1
                    self.ac_unocc += rp.command.hvac_mode != "off"
        self.power_w = b.power_w
        self.power_window.append(b.power_w)
        if len(self.power_window) == self.power_window.maxlen:
            self.peak_15min_w = max(self.peak_15min_w, sum(self.power_window) / len(self.power_window))

    def summary(self, rooms: int) -> Dict:
        occ = max(1, self.occ_min)
        days = max(1e-9, self.minutes / 1440.0)
        total = sum(self.kwh.values())
        return {
            "total_kwh": total, "end_use_kwh": dict(self.kwh),
            "floor_kwh": {f: v for f, v in sorted(self.kwh_floor.items())},
            "cost_lkr": total * TARIFF_LKR_PER_KWH,
            "power_w": self.power_w,
            "peak_15min_kw": self.peak_15min_w / 1000.0,
            "thermal_discomfort_pct": 100.0 * self.pmv_viol / max(1, self.stay_min),
            "thermal_discomfort_basis": "occupied minutes with |PMV| > 0.5, rooms where people stay "
                                        "(corridors, lobby and restrooms are transit spaces, listed by type)",
            "comfort_by_type": {t: {"occupied_min": v[0], "pmv_over_0_5_pct": round(100.0 * v[1] / v[0], 1),
                                    "mean_pmv": round(v[2] / v[0], 2)} for t, v in sorted(self.by_type.items()) if v[0]},
            "visual_discomfort_pct": 100.0 * self.lux_viol / occ,
            "co2_over_1000_pct": 100.0 * self.co2_viol / occ,
            "lights_on_empty_pct": 100.0 * self.light_unocc / max(1, self.unocc_min),
            "ac_on_empty_pct": 100.0 * self.ac_unocc / max(1, self.unocc_min_ac),
            "ac_onoff_per_room_day": self.ac_onoff / (rooms * days) if self.minutes >= 60 else None,
            "occupied_room_minutes": self.occ_min,
            "minutes": self.minutes,
        }


class _BatchedEstimator:
    """Gives a controller the probabilities computed for the whole building in one
    batch this control step (the Random Forest is far cheaper per batch)."""

    def __init__(self, inner):
        self.inner = inner
        self.name = getattr(inner, "name", "estimator")
        self.cache: Dict[str, float] = {}

    def probability(self, obs: Observation) -> float:
        p = self.cache.get(obs.room_id)
        return self.inner.probability(obs) if p is None else p


class Confusion:
    def __init__(self):
        self.tp = self.fp = self.fn = self.tn = 0

    def add(self, pred: bool, truth: bool):
        if pred and truth:
            self.tp += 1
        elif pred:
            self.fp += 1
        elif truth:
            self.fn += 1
        else:
            self.tn += 1

    def summary(self) -> Dict:
        n = self.tp + self.fp + self.fn + self.tn
        prec = self.tp / (self.tp + self.fp) if self.tp + self.fp else None
        rec = self.tp / (self.tp + self.fn) if self.tp + self.fn else None
        f1 = 2 * prec * rec / (prec + rec) if prec and rec else None
        return {"n": n, "tp": self.tp, "fp": self.fp, "fn": self.fn, "tn": self.tn,
                "accuracy": (self.tp + self.tn) / n if n else None, "precision": prec, "recall": rec, "f1": f1}


def _reasoning(c: Dict) -> Optional[Dict]:
    """The controller's own numbers for its current choice (multi-objective controller only)."""
    if not c or "J_ac_options" not in c:
        return None
    r2 = lambda v: round(v, 3) if isinstance(v, float) else v
    return {"p_now": r2(c.get("p_now")), "p_ac": r2(c.get("p_ac")), "p_future": r2(c.get("p_future")),
            "p_prior": r2(c.get("p_prior")), "t_pred": r2(c.get("t_pred")), "t_hold": r2(c.get("t_hold")),
            "J_light_options": {k: r2(v) for k, v in c["J_light_options"].items()},
            "ac_options": {k: {kk: r2(vv) for kk, vv in v.items()} for k, v in (c.get("ac_breakdown") or {}).items()}}


def _fmt_sp(hvac: str, sp: Optional[float]) -> str:
    return f"{hvac} {sp:.0f} C" if hvac == "NORMAL" and sp is not None else hvac


def _cmd(light: str = "OFF", hvac: str = "ECO", sp: Optional[float] = None, vent: bool = False) -> Dict:
    return {"light": light, "hvac": hvac, "sp": sp, "vent": vent}


class LiveTwin:
    def __init__(self, seed: int = 7, start: datetime = DEFAULT_START, speed: float = 360.0,
                 controller: str = "mo", warmup: bool = True):
        self.lock = threading.RLock()
        self.specs: List[RoomSpec] = build_spec()
        self.spec_by_id = {r.room_id: r for r in self.specs}
        try:
            self.rf = RandomForestEstimator(lighting_lux_full={
                r.room_id: r.controller_overrides["lighting_lux_full"] for r in self.specs})
        except Exception as e:                       # the comparison is optional
            self.rf, self.rf_error = None, str(e)
        else:
            self.rf_error = None
        self.speed = float(speed)
        self.running = True
        self.max_steps_per_tick = 60
        self._ff_steps = 0
        self.phase = "learning"
        self.ai_enabled = True
        self.reset(seed=seed, start=start, controller=controller, warmup=warmup)

    # ------------------------------------------------------------------ #
    def _make_mo(self) -> MultiObjectiveController:
        overrides = {r.room_id: dict(r.controller_overrides) for r in self.specs}
        return MultiObjectiveController(FusionEstimator(), room_overrides=overrides, **TUNED_WEIGHTS)

    def _make_ai(self, name: str):
        if name == "mo":
            return self._make_mo()
        if name == "threshold_rf":
            if self.rf is None:
                raise ValueError(f"Random Forest not available: {self.rf_error}")
            return ThresholdController(_BatchedEstimator(self.rf))
        raise ValueError(f"unknown AI controller {name!r}; choose from {list(CONTROLLERS)}")

    def reset(self, seed: Optional[int] = None, start: Optional[datetime] = None,
              controller: Optional[str] = None, warmup: Optional[bool] = None) -> None:
        """Start the scenario again.  The same seed and start give the same weather,
        occupants and sensor noise.  With warmup, both copies first run the
        WARMUP_DAYS before `start` under the AI (its learning week); the result is
        cached in memory and on disk, so a repeated reset is immediate."""
        with self.lock:
            self.seed = int(seed) if seed is not None else getattr(self, "seed", 7)
            self.start = start or getattr(self, "start", DEFAULT_START)
            self.ai_name = controller or getattr(self, "ai_name", "mo")
            if self.ai_name not in CONTROLLERS:
                raise ValueError(f"unknown AI controller {self.ai_name!r}")
            if warmup is None:
                warmup = getattr(self, "warmup_days", WARMUP_DAYS) > 0
            self.warmup_days = WARMUP_DAYS if warmup else 0
            self.schedule = ScheduleController(room_hours={r.room_id: r.schedule_hours for r in self.specs})
            self.timeline = deque(maxlen=500)
            self.event_seq = 0
            self.scenarios: List[Scenario] = []
            self._scn_seq = 0
            self._accum = 0.0
            self._ff_steps = 0
            self.step_ms: deque = deque(maxlen=200)
            snap = self._load_warm() if self.warmup_days else None
            if snap is not None:
                self._restore(snap)
                self._begin_measurement(cached=True)
                return
            t0 = self.start - timedelta(days=self.warmup_days)
            self.ctrl = TwinBuilding(self.specs, self.seed, t0)
            self.base = TwinBuilding(self.specs, self.seed, t0)
            self.ids = self.ctrl.ids
            self.mo = {"ctrl": self._make_mo(), "base": self._make_mo()}
            eq = {r.room_id: r.equipment_cooled for r in self.specs}
            self.safety = {"ctrl": SafetyLayer(eq), "base": SafetyLayer(eq)}
            self.cmd = {"ctrl": {rid: _cmd() for rid in self.ids}, "base": {rid: _cmd() for rid in self.ids}}
            for rid in self.ids:
                self.ctrl.apply(rid, "OFF", "ECO", None)
                self.base.apply(rid, "OFF", "ECO", None)
            self._setup_ai()
            self._init_measurement_state()
            if self.warmup_days:
                self.phase = "learning"
                self.warm_total = int(self.warmup_days * 86400 / CONTROL_DT)
                self.warm_done = 0
                self._log_system(f"Learning week started: {t0:%a %d %b} to {self.start:%a %d %b %Y %H:%M}. "
                                 f"The AI learns each room's routine from its own PIR/CO2 estimates; "
                                 f"results are measured from {self.start:%a %d %b %H:%M}.", kind="learning")
            else:
                self._begin_measurement(cached=False)

    def _setup_ai(self) -> None:
        """The AI controller of each copy (each copy has its own learned instance)."""
        if self.ai_name == "mo":
            self.ai = dict(self.mo)
        else:
            self.ai = {"ctrl": self._make_ai(self.ai_name), "base": self._make_ai(self.ai_name)}
        self.est_view = FusionEstimator()             # the building's occupancy estimate, always on

    def _init_measurement_state(self) -> None:
        self.acc = {m: ModeAccumulator(self.ids) for m in MODES}
        self.conf_fusion, self.conf_rf = Confusion(), Confusion()
        self.last: Dict[str, Dict] = {}               # building: last decision per room
        self.would: Dict[str, Dict] = {}              # what the AI would do while it is off
        self.twin_last: Dict[str, Dict] = {}          # twin copy: last decision per room
        self._pending: List[Tuple[datetime, Dict]] = []
        self.history: Dict[str, deque] = {rid: deque(maxlen=288) for rid in self.ids}
        self.series: deque = deque(maxlen=2016)
        self.steps = 0
        self._last_notes: Dict[str, List[str]] = {}
        self.watch: set = set()                 # rooms whose estimate changes are explained too
        self._watch_state: Dict[str, bool] = {}
        self._watch_until: Dict[str, Optional[datetime]] = {}
        self._e_snap = {k: self._energy_snapshot(b) for k, b in (("ctrl", self.ctrl), ("base", self.base))}
        self.segments: List[Dict] = []
        self.hourly = {m: [[0.0, 0] for _ in range(24)] for m in MODES}   # building only: [kWh, minutes]
        self.meter_kwh = 0.0

    def _begin_measurement(self, cached: bool) -> None:
        if self.warmup_days and not cached:
            self._save_warm()
        self.phase = "running"
        self.warm_total = int(self.warmup_days * 86400 / CONTROL_DT)
        self.warm_done = self.warm_total
        self._setup_ai()
        self._init_measurement_state()
        self._open_segment()
        self._log_system(f"Measurement started {self.ctrl.time:%a %d %b %Y %H:%M} (seed {self.seed}); "
                         f"AI control {'ON' if self.ai_enabled else 'OFF'}: {CONTROLLERS[self.ai_name]}"
                         + (f"; learning week {'restored from cache' if cached else 'complete'}"
                            if self.warmup_days else "; no learning week"))

    # ---- warm-up cache -------------------------------------------------- #
    def _cache_path(self) -> str:
        h = hashlib.sha1()
        files = sorted(glob.glob(os.path.join(TWIN_DIR, "*.py"))) + \
            [os.path.join(PROJECT_ROOT, "integration", "building_config.py")]
        for f in files:
            try:
                with open(f, "rb") as fh:
                    h.update(fh.read().replace(b"\r\n", b"\n"))
            except OSError:
                pass
        return os.path.join(CACHE_DIR, f"warm_s{self.seed}_{self.start:%Y%m%d%H%M}_{self.warmup_days}d_"
                                       f"{h.hexdigest()[:12]}.pkl")

    def _snapshot(self) -> Dict:
        return {"ctrl": self.ctrl, "base": self.base, "mo": self.mo, "safety": self.safety, "cmd": self.cmd}

    def _restore(self, snap: Dict) -> None:
        snap = copy.deepcopy(snap)
        self.ctrl, self.base, self.mo = snap["ctrl"], snap["base"], snap["mo"]
        self.safety, self.cmd = snap["safety"], snap["cmd"]
        self.ids = self.ctrl.ids

    _memory_cache: Dict[str, Dict] = {}

    def _load_warm(self) -> Optional[Dict]:
        path = self._cache_path()
        if path in LiveTwin._memory_cache:
            return LiveTwin._memory_cache[path]
        try:
            with open(path, "rb") as fh:
                snap = pickle.load(fh)
            LiveTwin._memory_cache[path] = snap
            return snap
        except Exception:
            return None

    def _save_warm(self) -> None:
        path = self._cache_path()
        snap = copy.deepcopy(self._snapshot())
        LiveTwin._memory_cache[path] = snap
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "wb") as fh:
                pickle.dump(snap, fh, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp, path)
        except Exception:
            pass                       # cache is an optimisation only

    # ------------------------------------------------------------------ #
    # the master switch
    def mode_of(self, key: str) -> str:
        """Control mode of a copy: the building follows the switch, the twin runs the other."""
        building_mode = "ai" if self.ai_enabled else "conventional"
        if key == "ctrl":
            return building_mode
        return "conventional" if building_mode == "ai" else "ai"

    def set_ai(self, enabled: bool) -> Dict:
        with self.lock:
            enabled = bool(enabled)
            if enabled == self.ai_enabled:
                return self.meter()
            self.ai_enabled = enabled
            if self.phase == "running":
                self._close_segment()
                self._open_segment()
                self._log_system(
                    f"AI control switched {'ON' if enabled else 'OFF'} for every room"
                    + ("" if enabled else " - conventional schedule control from now; the AI keeps observing"),
                    kind="switch")
            return self.meter()

    def _open_segment(self) -> None:
        self.segments.append({"mode": "ai" if self.ai_enabled else "conventional",
                              "start": self.ctrl.time.isoformat(timespec="minutes"), "end": None,
                              "minutes": 0, "kwh": 0.0, "other_kwh": 0.0, "peak_kw": 0.0,
                              "occ_min": 0, "uncomfortable_min": 0})
        self.segments = self.segments[-200:]

    def _close_segment(self) -> None:
        if self.segments and self.segments[-1]["end"] is None:
            self.segments[-1]["end"] = self.ctrl.time.isoformat(timespec="minutes")

    # ------------------------------------------------------------------ #
    # clock
    def advance_real(self, dt_real: float, budget_s: float = 0.25) -> int:
        """Called by the tick loop with the real time elapsed; runs whole control
        steps.  The learning week and fast-forward run as fast as the machine
        allows, within budget_s of real time per call so the API stays responsive."""
        with self.lock:
            n = 0
            if self.phase == "learning":
                t_end = time.perf_counter() + budget_s
                while self.warm_done < self.warm_total and time.perf_counter() < t_end:
                    self.control_step(measure=False)
                    self.warm_done += 1
                    n += 1
                if self.warm_done >= self.warm_total:
                    self._begin_measurement(cached=False)
                return n
            if self._ff_steps > 0:
                budget_s = max(budget_s, 0.2)
                t_end = time.perf_counter() + budget_s
                while self._ff_steps > 0 and time.perf_counter() < t_end:
                    self.control_step()
                    self._ff_steps -= 1
                    n += 1
                return n
            if not self.running:
                return 0
            self._accum += dt_real * self.speed
            while self._accum >= CONTROL_DT and n < self.max_steps_per_tick:
                self.control_step()
                self._accum -= CONTROL_DT
                n += 1
            if self._accum > CONTROL_DT * self.max_steps_per_tick:
                self._accum = 0.0          # machine too slow for this speed: drop backlog, never fake time
            return n

    def finish_learning(self) -> None:
        """Run the rest of the learning week now (blocking; tests and tools)."""
        with self.lock:
            while self.phase == "learning":
                self.advance_real(0.0, budget_s=3600.0)

    def set_speed(self, speed: float) -> None:
        with self.lock:
            self.speed = max(1.0, min(3600.0, float(speed)))

    def fast_forward(self, minutes: float) -> None:
        with self.lock:
            if self.phase != "running":
                return
            n = max(0, int(minutes * 60 / CONTROL_DT))
            self._ff_steps += n
            self._ff_total = self._ff_steps
            if n:
                self._log_system(f"Fast-forward {minutes:.0f} min (every minute is simulated and controlled)")

    def fast_forward_until(self, hour: int, minute: int = 0, weekday: bool = True) -> float:
        """Fast-forward to the next hh:mm (on a weekday if asked); returns the minutes."""
        with self.lock:
            t = self.ctrl.time + timedelta(minutes=self._ff_steps * CONTROL_DT / 60.0)
            target = t.replace(hour=int(hour) % 24, minute=int(minute) % 60, second=0, microsecond=0)
            if target <= t + timedelta(minutes=1):
                target += timedelta(days=1)
            while weekday and target.weekday() >= 5:
                target += timedelta(days=1)
            minutes = (target - t).total_seconds() / 60.0
            self.fast_forward(minutes)
            return minutes

    @property
    def time(self) -> datetime:
        return self.ctrl.time

    # ------------------------------------------------------------------ #
    def _observation(self, b: TwinBuilding, rid: str, cmd: Dict) -> Observation:
        rd = b.readings[rid]
        rs = b.specs[rid]
        return Observation(
            room_id=rid, room_type=rs.room_type, timestamp=b.time,
            temperature=rd["temperature"], humidity=rd["humidity"], light_lux=rd["light"],
            co2=rd["co2"] if "co2" in rs.sensors else None, humidity_ratio=rd["humidity_ratio"],
            seconds_since_motion=rd["pir_seconds"], current_light=cmd["light"], current_hvac=cmd["hvac"],
            current_setpoint=cmd["sp"], outdoor_temperature=b.outdoor.temperature,
            hvac_power_w=b.physics[rid].state.hvac_electric_w, true_occupants=b.occupants[rid])

    @staticmethod
    def _energy_snapshot(b: TwinBuilding) -> Tuple[Dict[str, float], Dict[str, float]]:
        return b.energy_by_end_use_wh(), {rid: b.physics[rid].total_energy_wh for rid in b.ids}

    def _energy_delta(self, key: str, b: TwinBuilding) -> Tuple[Dict[str, float], Dict[str, float]]:
        end0, room0 = self._e_snap[key]
        end1, room1 = self._energy_snapshot(b)
        self._e_snap[key] = (end1, room1)
        return {k: end1[k] - end0[k] for k in end1}, {r: room1[r] - room0[r] for r in room1}

    def _decide_copy(self, key: str, b: TwinBuilding, obs: Dict[str, Observation], rf_p: Dict[str, float],
                     measure: bool) -> None:
        """Decide, validate and apply every room of one copy under its current mode."""
        mode = self.mode_of(key)
        ai = self.ai[key]
        observe = mode == "conventional" and self.ai_name == "mo" and self.steps % OBSERVE_EVERY == 0
        for rid in self.ids:
            o = obs[rid]
            prev = dict(self.cmd[key][rid])
            if mode == "ai":
                d = ai.decide(o)
            else:
                d = self.schedule.decide(o)
                if observe:
                    w = ai.decide(o)          # the AI keeps observing (learning); result not applied
                    if key == "ctrl":
                        self.would[rid] = {"decision": w, "time": b.time}
            p_f = None
            if key == "ctrl":
                p_f = self.est_view.probability(o)
            p_dec = d.occupancy_probability if not math.isnan(d.occupancy_probability) else \
                (p_f if p_f is not None else (1.0 if d.control_mode == "OCCUPIED" else 0.0))
            sp = d.setpoint_c
            if d.hvac_action == "NORMAL" and sp is None:
                sp = self.spec_by_id[rid].design_setpoint
            va = self.safety[key].validate(rid, d.light_action, d.hvac_action, sp, p_dec, o.temperature, o.co2)
            new = _cmd(va.light, va.hvac, va.setpoint, va.vent_boost)
            if key == "ctrl":
                if measure:
                    truth = o.true_occupants > 0
                    self.conf_fusion.add(p_f >= 0.5, truth)
                    if rid in rf_p:
                        self.conf_rf.add(rf_p[rid] >= 0.5, truth)
                    notes_changed = va.notes != self._last_notes.get(rid, [])
                    self._last_notes[rid] = list(va.notes)
                    if new != prev or (va.notes and notes_changed):
                        self._log_decision(rid, o, d, va, prev, new, p_f, rf_p.get(rid), mode)
                    elif rid in self.watch and mode == "ai":
                        was = self._watch_state.get(rid)
                        now_occ = (p_dec or 0.0) >= 0.5
                        if was is None or was != now_occ:
                            txt = (f"AI estimates people present (P {p_dec:.2f}); no change needed"
                                   if now_occ else f"AI estimates the room is empty (P {p_dec:.2f}); no change yet")
                            self._log_decision(rid, o, d, va, prev, new, p_f, rf_p.get(rid), mode, held=txt)
                        self._watch_state[rid] = now_occ
                    if rid in self.watch and new != prev:
                        self._watch_state[rid] = (p_dec or 0.0) >= 0.5
                self.last[rid] = {"decision": d, "validated": va, "p_fusion": p_f, "p_rf": rf_p.get(rid)}
            else:
                self.twin_last[rid] = {"decision": d, "validated": va}
            if new != prev:
                acc = self.acc[mode]
                if measure:
                    acc.switches += (new["light"] != prev["light"]) + (new["hvac"] != prev["hvac"] or new["sp"] != prev["sp"])
                    acc.ac_onoff += (new["hvac"] == "ECO") != (prev["hvac"] == "ECO")
                self.cmd[key][rid] = new
                b.apply(rid, new["light"], new["hvac"], new["sp"], new["vent"])

    def control_step(self, measure: bool = True) -> None:
        t0 = time.perf_counter()
        ts = self.ctrl.time
        self._expire_scenarios(ts)
        obs_c = {rid: self._observation(self.ctrl, rid, self.cmd["ctrl"][rid]) for rid in self.ids}
        obs_b = {rid: self._observation(self.base, rid, self.cmd["base"][rid]) for rid in self.ids}
        rf_p: Dict[str, float] = {}
        rf_b: Dict[str, float] = {}
        if self.rf is not None:
            if measure or self.ai_name == "threshold_rf":
                rf_p = dict(zip(self.ids, self.rf.probabilities([obs_c[r] for r in self.ids])))
            if self.ai_name == "threshold_rf":
                rf_b = dict(zip(self.ids, self.rf.probabilities([obs_b[r] for r in self.ids])))
                self.ai["ctrl"].estimator.cache = rf_p
                self.ai["base"].estimator.cache = rf_b
        if not measure:
            # learning week: both copies run the AI so each copy's controller learns
            saved = self.ai_enabled
            self.ai_enabled = True
            self._decide_copy("ctrl", self.ctrl, obs_c, rf_p, False)
            self.ai_enabled = False             # mode_of("base") == "ai"
            self._decide_copy("base", self.base, obs_b, rf_b, False)
            self.ai_enabled = saved
        else:
            self._decide_copy("ctrl", self.ctrl, obs_c, rf_p, True)
            self._decide_copy("base", self.base, obs_b, rf_b, True)
        self.ctrl.advance(CONTROL_DT)
        self.base.advance(CONTROL_DT)
        self.ctrl.read_sensors(CONTROL_DT)
        self.base.read_sensors(CONTROL_DT)
        if measure:
            dc_end, dc_room = self._energy_delta("ctrl", self.ctrl)
            db_end, db_room = self._energy_delta("base", self.base)
            self.acc[self.mode_of("ctrl")].add(self.ctrl, dc_end, dc_room)
            self.acc[self.mode_of("base")].add(self.base, db_end, db_room)
            self._meter_step(ts, sum(dc_end.values()) / 1000.0, sum(db_end.values()) / 1000.0)
            self.steps += 1
            self._fill_outcomes()
            if self.steps % 5 == 0:
                self._sample_history()
            if self.steps % 15 == 0:
                self._sample_series()
        self.step_ms.append((time.perf_counter() - t0) * 1000.0)

    def _meter_step(self, ts: datetime, kwh: float, other_kwh: float) -> None:
        seg = self.segments[-1]
        seg["minutes"] += 1
        seg["kwh"] += kwh
        seg["other_kwh"] += other_kwh
        seg["peak_kw"] = max(seg["peak_kw"], self.ctrl.power_w / 1000.0)
        for rid in self.ids:
            if self.ctrl.occupants[rid] > 0 and not self.spec_by_id[rid].transit:
                seg["occ_min"] += 1
                pmv = self.ctrl.truth(rid)["pmv"]
                seg["uncomfortable_min"] += pmv is not None and abs(pmv) > 0.5
        h = self.hourly[seg["mode"]][ts.hour]
        h[0] += kwh
        h[1] += 1
        self.meter_kwh += kwh

    # ------------------------------------------------------------------ #
    # decisions, explanations, outcomes
    def _log_decision(self, rid, o: Observation, d, va, prev, new, p_f, p_rf, mode: str,
                      held: Optional[str] = None) -> None:
        rs = self.spec_by_id[rid]
        p_dec = d.occupancy_probability if not math.isnan(d.occupancy_probability) else None
        c = d.costs or {}
        own = rs.controller_overrides["lighting_lux_full"] * {"OFF": 0.0, "DIM": 0.4, "ON": 1.0}[o.current_light]
        daylight = max(0.0, o.light_lux - own)
        light_changed = new["light"] != prev["light"]
        ac_changed = new["hvac"] != prev["hvac"] or new["sp"] != prev["sp"]
        changes = []
        if light_changed:
            changes.append(f"lights {prev['light']} -> {new['light']}")
        if ac_changed:
            changes.append(f"AC {_fmt_sp(prev['hvac'], prev['sp'])} -> {_fmt_sp(new['hvac'], new['sp'])}")
        if new["vent"] != prev["vent"]:
            changes.append(f"fresh-air fan {'ON' if new['vent'] else 'OFF'}")
        why = []
        if mode == "conventional":
            start_h, end_h, wd = rs.schedule_hours
            fmt = lambda h: f"{int(h):02d}:{int(round((h % 1) * 60)):02d}"
            why.append(f"AI control is OFF: conventional schedule, operating hours {fmt(start_h)}-{fmt(end_h)}"
                       + (" on weekdays" if wd else " every day") + " (occupancy is not considered)")
        elif self.ai_name == "mo":
            p_now = c.get("p_now", p_f)
            why.append(f"occupancy probability {p_now:.2f} now"
                       + (f", {c.get('p_future'):.2f} over the next 30 min" if c.get("p_future") is not None else ""))
            if o.seconds_since_motion is not None:
                sec = o.seconds_since_motion
                why.append(f"last PIR motion {sec / 60:.0f} min ago" if sec >= 90 else "PIR motion within the last minute")
            else:
                why.append("no PIR motion seen yet")
            if o.co2 is not None:
                why.append(f"CO2 {o.co2:.0f} ppm")
            if light_changed or held:
                why.append(f"daylight about {daylight:.0f} lux vs 300 lux target")
            jl, ja = c.get("J_light_options") or {}, c.get("J_ac_options") or {}
            chosen_ac = _fmt_sp(new["hvac"], new["sp"]).replace(" C", "")
            if ja and (ac_changed or held):
                best = min(ja, key=ja.get)
                ranked = sorted(ja.items(), key=lambda kv: kv[1])
                runner = next((k for k, _ in ranked if k != best), None)
                why.append(f"cost J: {best} {ja[best]:.2f} lowest" + (f", next {runner} {ja[runner]:.2f}" if runner else ""))
                if c.get("t_pred") is not None:
                    why.append(f"predicted {c['t_pred']:.1f} C in 30 min with {chosen_ac}")
                pp = c.get("p_prior")
                if pp is not None and pp > (c.get("p_ac") or 0.0) + 0.05:
                    why.append(f"learned weekly routine: this room is usually in use in the next 30 min ({pp:.2f})")
                bd = (c.get("ac_breakdown") or {}).get("ECO")
                if bd and chosen_ac != "ECO" and (c.get("p_now") or 0.0) < 0.5:
                    why.append(f"switching off would score J {bd['J']:.2f}: re-cooling later {bd['recovery_kwh']:.2f} kWh, "
                               f"expected discomfort {bd['discomfort_h']:.2f} h")
                if held and best != chosen_ac and chosen_ac in ja:
                    why.append(f"AC held at {chosen_ac}: the 10-min minimum AC dwell has not elapsed")
            if jl and held:
                bl = min(jl, key=jl.get)
                if bl != new["light"]:
                    why.append(f"lights held {new['light']}: the 2-min minimum light dwell has not elapsed")
        else:
            why.append(d.reason)
        if held:
            changes = [held]
        ev = {
            "seq": None, "kind": "assessment" if held else "decision",
            "sim_time": o.timestamp.isoformat(timespec="minutes"),
            "room_id": rid, "room_name": rs.name, "floor_id": rs.floor_id,
            "controller": self.ai_name if mode == "ai" else "schedule", "mode": mode,
            "summary": "; ".join(changes) if changes else "safety rule active",
            "why": why,
            "observed": {"temperature": o.temperature, "humidity": o.humidity, "light_lux": o.light_lux,
                         "daylight_lux_est": round(daylight), "co2": o.co2,
                         "pir_seconds": o.seconds_since_motion, "outdoor_c": round(o.outdoor_temperature, 1),
                         "p_occupancy": round(c.get("p_now", p_dec if p_dec is not None else p_f), 3) if (p_dec is not None or p_f is not None) else None,
                         "p_fusion": round(p_f, 3) if p_f is not None else None,
                         "p_ac": round(c["p_ac"], 3) if "p_ac" in c else None,
                         "p_future": round(c["p_future"], 3) if "p_future" in c else None,
                         "p_random_forest": round(p_rf, 3) if p_rf is not None else None},
            "simulator_truth": {"occupants": o.true_occupants},
            "proposed": {"light": d.light_action, "hvac": d.hvac_action, "setpoint": d.setpoint_c},
            "safety": {"accepted": va.accepted, "notes": va.notes},
            "validated": dict(new),
            "previous": dict(prev),
            "expected": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in c.items()
                         if k in ("t_pred", "t_hold", "energy_kwh_horizon", "J_light", "J_ac",
                                  "J_light_options", "J_ac_options", "visual_discomfort_h", "thermal_discomfort_h",
                                  "p_prior")},
            "reasoning": _reasoning(c),
            "outcome": None,
        }
        self._add_event(ev)
        self._pending.append((o.timestamp + timedelta(minutes=15), ev))

    def _fill_outcomes(self) -> None:
        now = self.ctrl.time
        keep = []
        for due, ev in self._pending:
            if now >= due:
                rid = ev["room_id"]
                tr = self.ctrl.truth(rid)
                ev["outcome"] = {"after_min": 15, "temperature": round(self.ctrl.readings[rid]["temperature"], 2),
                                 "power_w": round(tr["power_w"]), "lux": round(tr["daylight_lux"] + tr["electric_lux"]),
                                 "occupants": tr["occupants"],
                                 "pmv": round(tr["pmv"], 2) if tr["pmv"] is not None else None}
            else:
                keep.append((due, ev))
        self._pending = keep[-500:]

    def _add_event(self, ev: Dict) -> None:
        self.event_seq += 1
        ev["seq"] = self.event_seq
        self.timeline.append(ev)

    def add_event(self, ev: Dict) -> Dict:
        """An event from outside the simulation (the real rooms' decisions)."""
        with self.lock:
            self._add_event(ev)
            return ev

    def get_timeline(self, after: int = 0, room_id: Optional[str] = None, limit: int = 100,
                     kinds: Optional[List[str]] = None) -> List[Dict]:
        with self.lock:
            evs = [e for e in self.timeline if e["seq"] > after and (room_id is None or e.get("room_id") == room_id)
                   and (not kinds or e.get("kind") in kinds)]
            return [dict(e) for e in evs[-limit:]]

    def watch_room(self, room_id: Optional[str]) -> None:
        """Explain estimate changes of the room the user is looking at (selected room)."""
        with self.lock:
            for rid, until in list(self._watch_until.items()):
                if until is None:
                    self._watch_until.pop(rid, None)
                    if not any(x.room_id == rid for x in self.scenarios):
                        self.watch.discard(rid)
            if room_id in self.ctrl.specs:
                self.watch.add(room_id)
                self._watch_until[room_id] = None      # until another room is selected

    def room_history(self, room_id: str) -> List[Dict]:
        with self.lock:
            return list(self.history.get(room_id, []))

    def restart_comparison(self) -> None:
        with self.lock:
            self.acc = {m: ModeAccumulator(self.ids) for m in MODES}
            self.conf_fusion, self.conf_rf = Confusion(), Confusion()
            self.series.clear()
            self._close_segment()
            self.segments = []
            self.hourly = {m: [[0.0, 0] for _ in range(24)] for m in MODES}
            self.meter_kwh = 0.0
            self._open_segment()
            self._log_system("Comparison and meter restarted (energy, comfort and accuracy counters from now)")

    def set_running(self, running: bool) -> None:
        with self.lock:
            if self.running != bool(running):
                self.running = bool(running)
                self._log_system("Simulation paused" if not running else "Simulation resumed")

    def analytics(self) -> Dict:
        with self.lock:
            return {"comparison": self.comparison(), "series": list(self.series), "floors": self.floors(),
                    "clock": self.clock(), "meter": self.meter(detail=True)}

    def _log_system(self, text: str, kind: str = "system", room_id: Optional[str] = None) -> None:
        t = self.ctrl.time if hasattr(self, "ctrl") else DEFAULT_START
        rs = self.spec_by_id.get(room_id) if room_id else None
        self._add_event({"seq": None, "kind": kind, "sim_time": t.isoformat(timespec="minutes"),
                         "room_id": room_id, "room_name": rs.name if rs else None,
                         "floor_id": rs.floor_id if rs else None, "summary": text})

    # ------------------------------------------------------------------ #
    # scenarios (applied to both copies)
    def add_scenario(self, kind: str, room_id: Optional[str] = None, value: float = 0.0,
                     minutes: float = 60.0) -> Dict:
        with self.lock:
            if self.phase != "running":
                raise ValueError("the AI is still in its learning week; scenarios start once measurement begins")
            if kind not in SCENARIOS:
                raise ValueError(f"unknown scenario {kind!r}; choose from {SCENARIOS}")
            if kind in ("occupancy", "heat_gain", "co2", "window"):
                if room_id not in self.ctrl.specs:
                    raise ValueError(f"room {room_id!r} is not a simulated room")
            minutes = max(1.0, min(24 * 60.0, float(minutes)))
            start = self.ctrl.time
            end = start + timedelta(minutes=minutes)
            rs = self.spec_by_id.get(room_id) if room_id else None
            for b in (self.ctrl, self.base):
                if kind == "occupancy":
                    n = int(max(0, min(rs.max_occupancy * 2, round(value))))
                    b.occupancy.force(room_id, n, start, minutes)
                elif kind == "heat_gain":
                    b.physics[room_id].extra_gain_w += float(value)
                elif kind == "co2":
                    b.physics[room_id].extra_co2_m3s += float(value) / 1000.0     # value in L/s
                elif kind == "window":
                    b.physics[room_id].extra_ach += float(value)
                elif kind == "heat_wave":
                    b.climate.temp_offset_k += float(value)
                elif kind == "overcast":
                    b.climate.daylight_scale = max(0.02, min(1.0, float(value)))
            label = {
                "occupancy": f"{int(round(value))} people in {rs.name if rs else ''} for {minutes:.0f} min",
                "heat_gain": f"+{value:.0f} W heat gain in {rs.name if rs else ''} for {minutes:.0f} min",
                "co2": f"CO2 release {value:.2f} L/s in {rs.name if rs else ''} for {minutes:.0f} min "
                       f"(one seated person breathes out about 0.005 L/s)",
                "window": f"window open (+{value:.1f} air changes/h) in {rs.name if rs else ''} for {minutes:.0f} min",
                "heat_wave": f"outdoor air +{value:.1f} C for {minutes / 60:.1f} h",
                "overcast": f"overcast sky: daylight x{value:.2f} for {minutes / 60:.1f} h",
            }[kind]
            self._scn_seq += 1
            sc = Scenario(self._scn_seq, kind, room_id, float(value), start, end, label)
            self.scenarios.append(sc)
            if room_id:
                self.watch.add(room_id)
                self._watch_state.pop(room_id, None)
            self._log_system(f"Scenario started: {label}", kind="scenario", room_id=room_id)
            return self._scenario_dict(sc)

    def _undo(self, sc: Scenario) -> None:
        for b in (self.ctrl, self.base):
            if sc.kind == "occupancy":
                b.occupancy.unforce(sc.room_id, sc.start, (sc.end - sc.start).total_seconds() / 60.0)
            elif sc.kind == "heat_gain":
                b.physics[sc.room_id].extra_gain_w -= sc.value
            elif sc.kind == "co2":
                b.physics[sc.room_id].extra_co2_m3s -= sc.value / 1000.0
            elif sc.kind == "window":
                b.physics[sc.room_id].extra_ach -= sc.value
            elif sc.kind == "heat_wave":
                b.climate.temp_offset_k -= sc.value
            elif sc.kind == "overcast":
                b.climate.daylight_scale = 1.0

    def _expire_scenarios(self, ts: datetime) -> None:
        for rid, until in list(self._watch_until.items()):
            if until is not None and ts >= until and not any(x.room_id == rid for x in self.scenarios):
                self.watch.discard(rid)
                self._watch_until.pop(rid, None)
        keep = []
        for sc in self.scenarios:
            if ts >= sc.end:
                self._undo(sc)
                self._log_system(f"Scenario ended: {sc.label}", kind="scenario", room_id=sc.room_id)
                if sc.room_id:
                    self._watch_until[sc.room_id] = ts + timedelta(minutes=30)
            else:
                keep.append(sc)
        self.scenarios = keep

    def clear_scenarios(self) -> None:
        with self.lock:
            for sc in self.scenarios:
                self._undo(sc)
            if self.scenarios:
                self._log_system("All scenarios stopped", kind="scenario")
            self.scenarios = []

    def _scenario_dict(self, sc: Scenario) -> Dict:
        return {"id": sc.sid, "kind": sc.kind, "room_id": sc.room_id, "value": sc.value, "label": sc.label,
                "start": sc.start.isoformat(timespec="minutes"), "end": sc.end.isoformat(timespec="minutes")}

    # ------------------------------------------------------------------ #
    def set_controller(self, name: str) -> None:
        """Which AI runs when AI control is on (the comparison restarts)."""
        with self.lock:
            if name not in CONTROLLERS:
                raise ValueError(f"unknown AI controller {name!r}; choose from {list(CONTROLLERS)}")
            if name == self.ai_name:
                return
            self.ai_name = name
            if self.phase != "running":
                return                                  # applied when measurement starts
            self._setup_ai()
            self.acc = {m: ModeAccumulator(self.ids) for m in MODES}
            self.conf_fusion, self.conf_rf = Confusion(), Confusion()
            self._close_segment()
            self._open_segment()
            self._log_system(f"AI controller changed to: {CONTROLLERS[name]} (comparison restarted)")

    # ------------------------------------------------------------------ #
    def _copy_for(self, mode: str) -> Tuple[str, TwinBuilding]:
        return ("ctrl", self.ctrl) if self.mode_of("ctrl") == mode else ("base", self.base)

    def _sample_history(self) -> None:
        ka, ba = self._copy_for("ai")
        kc, bc = self._copy_for("conventional")
        for rid in self.ids:
            tr = self.ctrl.truth(rid)
            rd = self.ctrl.readings[rid]
            last = self.last.get(rid, {})
            tra, trc = ba.truth(rid), bc.truth(rid)
            self.history[rid].append({
                "t": self.ctrl.time.isoformat(timespec="minutes"), "mode": self.mode_of("ctrl"),
                "temperature": rd["temperature"], "humidity": rd["humidity"], "co2": rd["co2"], "lux": rd["light"],
                "occupants": tr["occupants"], "p_occ": last.get("p_fusion"), "p_rf": last.get("p_rf"),
                "light": self.cmd["ctrl"][rid]["light"], "hvac": self.cmd["ctrl"][rid]["hvac"],
                "setpoint": self.cmd["ctrl"][rid]["sp"],
                "power_w": round(tr["power_w"]), "pmv": round(tr["pmv"], 2) if tr["pmv"] is not None else None,
                "ai_power_w": round(tra["power_w"]), "ai_temperature": round(tra["t_air"], 2),
                "conv_power_w": round(trc["power_w"]), "conv_temperature": round(trc["t_air"], 2),
            })

    def _sample_series(self) -> None:
        ka, ba = self._copy_for("ai")
        kc, bc = self._copy_for("conventional")
        self.series.append({
            "t": self.ctrl.time.isoformat(timespec="minutes"), "mode": self.mode_of("ctrl"),
            "power_kw": round(self.ctrl.power_w / 1000.0, 2),
            "ai_power_kw": round(ba.power_w / 1000.0, 2), "conv_power_kw": round(bc.power_w / 1000.0, 2),
            "meter_kwh": round(self.meter_kwh, 2),
            "ai_kwh": round(sum(self.acc["ai"].kwh.values()), 2),
            "conv_kwh": round(sum(self.acc["conventional"].kwh.values()), 2),
            "outdoor_c": round(self.ctrl.outdoor.temperature, 1),
            "occupied_rooms": sum(1 for rid in self.ids if self.ctrl.occupants[rid] > 0),
            "people": sum(self.ctrl.occupants.values()),
        })

    # ------------------------------------------------------------------ #
    def _mode_view(self, mode: str, rid: str) -> Dict:
        key, b = self._copy_for(mode)
        tr = b.truth(rid)
        cmd = self.cmd[key][rid]
        return {"copy": "building" if key == "ctrl" else "twin", "power_w": round(tr["power_w"]),
                "temperature": round(b.readings[rid]["temperature"], 2), "co2": b.readings[rid]["co2"],
                "pmv": round(tr["pmv"], 2) if tr["pmv"] is not None else None,
                "light_action": cmd["light"], "hvac_action": cmd["hvac"], "setpoint_c": cmd["sp"],
                "vent_boost": cmd["vent"],
                "energy_wh": round(self.acc[mode].kwh_room[rid] * 1000.0, 1)}

    def room_states(self) -> List[Dict]:
        out = []
        mode_c = self.mode_of("ctrl")
        for rid in self.ids:
            rs = self.spec_by_id[rid]
            rd = self.ctrl.readings[rid]
            tr = self.ctrl.truth(rid)
            last = self.last.get(rid)
            cmd = self.cmd["ctrl"][rid]
            d = last["decision"] if last else None
            va = last["validated"] if last else None
            p = last["p_fusion"] if last else None
            costs = (d.costs or {}) if d else {}
            would = None
            if mode_c == "conventional":
                w = self.would.get(rid) or self.twin_last.get(rid)
                if w:
                    wd = w["decision"]
                    would = {"light_action": wd.light_action, "hvac_action": wd.hvac_action,
                             "setpoint_c": wd.setpoint_c, "reason": wd.reason, "reasoning": _reasoning(wd.costs or {}),
                             "basis": "the AI observing this room (not applied)" if rid in self.would
                             else "the twin copy run by the AI"}
            out.append({
                "room_id": rid, "room_type": rs.room_type, "floor_id": rs.floor_id, "display_name": rs.name,
                "source": "simulated", "timestamp": self.ctrl.time.isoformat(timespec="seconds"),
                "sensors": {"Temperature": rd["temperature"], "Humidity": rd["humidity"], "Light": rd["light"],
                            "CO2": rd["co2"], "HumidityRatio": round(rd["humidity_ratio"], 6),
                            "PIR_seconds_since_motion": rd["pir_seconds"]},
                "ground_truth": {"true_occupancy": tr["occupants"], "max_occupancy": rs.max_occupancy},
                "ai": None if p is None else {
                    "occupancy_probability": round(p, 4), "predicted_occupancy": int(p >= 0.5),
                    "confidence": round(max(p, 1 - p), 4), "method": "fusion_pir_co2",
                    "p_ac": round(costs["p_ac"], 4) if "p_ac" in costs else None,
                    "p_future": round(costs["p_future"], 4) if "p_future" in costs else None,
                    "random_forest_probability": round(last["p_rf"], 4) if last and last["p_rf"] is not None else None,
                },
                "control": None if d is None else {
                    "light_action": cmd["light"], "hvac_action": cmd["hvac"], "setpoint_c": cmd["sp"],
                    "vent_boost": cmd["vent"], "control_mode": d.control_mode,
                    "controller": self.ai_name if mode_c == "ai" else "schedule", "mode": mode_c,
                    "reason": d.reason, "safety_notes": va.notes if va else [],
                    "t_pred": round(costs["t_pred"], 2) if "t_pred" in costs else None,
                    "reasoning": _reasoning(costs),
                    "ai_would": would,
                },
                "device_state": {"light_on": tr["light_level"] > 0, "light_level": tr["light_level"],
                                 "hvac_mode": tr["hvac_mode"], "hvac_speed": round(tr["cooling_fraction"] * 100),
                                 "setpoint": tr["setpoint"], "vent_boost": tr["vent_boost"]},
                "energy": {"power_w": round(tr["power_w"]),
                           "hvac_w": round(tr["hvac_w"]), "lighting_w": round(tr["lighting_w"]),
                           "plug_w": round(tr["plug_w"]), "basis": "simulated (5R1C physics)"},
                "comfort": {"pmv": round(tr["pmv"], 2) if tr["pmv"] is not None else None,
                            "operative_c": round(tr["t_operative"], 2),
                            "lux_total": round(tr["daylight_lux"] + tr["electric_lux"]),
                            "daylight_lux": round(tr["daylight_lux"])},
                "modes": {"ai": self._mode_view("ai", rid), "conventional": self._mode_view("conventional", rid)},
                "scenarios": [s.label for s in self.scenarios if s.room_id == rid],
                "disturbances": {
                    "extra_gain_w": round(self.ctrl.physics[rid].extra_gain_w),
                    "co2_release_ls": round(self.ctrl.physics[rid].extra_co2_m3s * 1000.0, 3),
                    "window_ach": round(self.ctrl.physics[rid].extra_ach, 2),
                    "forced_occupancy_until": (lambda u: u.isoformat(timespec="minutes") if u else None)(
                        self.ctrl.occupancy.forced_until(rid, self.ctrl.time)),
                },
                "area_m2": round(rs.area, 1),
                "design_setpoint_c": rs.design_setpoint,
                "watched": rid in self.watch,
            })
        return out

    def floors(self) -> List[Dict]:
        out = []
        _, ba = self._copy_for("ai")
        _, bc = self._copy_for("conventional")
        ea, ec = self.acc["ai"].kwh_floor, self.acc["conventional"].kwh_floor
        for f in sorted({r.floor_id for r in self.specs}):
            rids = [rid for rid in self.ids if self.spec_by_id[rid].floor_id == f]
            temps = [self.ctrl.readings[r]["temperature"] for r in rids]
            out.append({
                "floor_id": f,
                "power_w": round(sum(self.ctrl.physics[r].total_power_w for r in rids)),
                "ai_power_w": round(sum(ba.physics[r].total_power_w for r in rids)),
                "conv_power_w": round(sum(bc.physics[r].total_power_w for r in rids)),
                "ai_energy_kwh": round(ea.get(f, 0.0), 3), "conv_energy_kwh": round(ec.get(f, 0.0), 3),
                "people": sum(self.ctrl.occupants[r] for r in rids),
                "rooms_occupied": sum(1 for r in rids if self.ctrl.occupants[r] > 0),
                "rooms_predicted_occupied": sum(1 for r in rids if ((self.last.get(r) or {}).get("p_fusion") or 0) >= 0.5),
                "mean_temperature": round(sum(temps) / len(temps), 2) if temps else None,
                "simulated_rooms": len(rids),
            })
        return out

    def comparison(self) -> Dict:
        n = len(self.ids)
        a = self.acc["ai"].summary(n)
        c = self.acc["conventional"].summary(n)
        saving = None
        if c["total_kwh"] > 0.05:
            saving = 100.0 * (1.0 - a["total_kwh"] / c["total_kwh"])
        return {
            "ai_controller": self.ai_name, "ai_label": CONTROLLERS[self.ai_name],
            "conventional_label": CONVENTIONAL_LABEL,
            "ai": a, "conventional": c, "saving_pct": saving,
            "basis": "same simulated minutes, same weather, people and sensor noise: one copy under each mode",
            "tariff_lkr_per_kwh": TARIFF_LKR_PER_KWH, "tariff_note": "assumed flat tariff (set TARIFF_LKR_PER_KWH)",
            "occupancy_fusion": self.conf_fusion.summary(),
            "occupancy_random_forest": self.conf_rf.summary() if self.rf is not None else None,
            "since": (self.ctrl.time - timedelta(minutes=a["minutes"])).isoformat(timespec="minutes"),
        }

    def meter(self, detail: bool = False) -> Dict:
        """The building's energy meter: live power, total, and one segment per switch position."""
        segs = []
        for s in self.segments[-50:]:
            hours = s["minutes"] / 60.0
            saving = None
            if s["minutes"] >= 5:
                ai_kwh = s["kwh"] if s["mode"] == "ai" else s["other_kwh"]
                conv_kwh = s["other_kwh"] if s["mode"] == "ai" else s["kwh"]
                saving = 100.0 * (1.0 - ai_kwh / conv_kwh) if conv_kwh > 0.01 else None
            segs.append({**s, "kwh": round(s["kwh"], 3), "other_kwh": round(s["other_kwh"], 3),
                         "peak_kw": round(s["peak_kw"], 2),
                         "avg_kw": round(s["kwh"] / hours, 2) if hours > 0 else None,
                         "other_avg_kw": round(s["other_kwh"] / hours, 2) if hours > 0 else None,
                         "uncomfortable_pct": round(100.0 * s["uncomfortable_min"] / s["occ_min"], 1) if s["occ_min"] else None,
                         "ai_saving_pct": round(saving, 1) if saving is not None else None})
        cur = segs[-1] if segs else None
        out = {
            "ai_enabled": self.ai_enabled, "mode": self.mode_of("ctrl"),
            "power_kw": round(self.ctrl.power_w / 1000.0, 2),
            "other_power_kw": round(self.base.power_w / 1000.0, 2),
            "total_kwh": round(self.meter_kwh, 2),
            "current": cur,
            "segments": segs if detail else segs[-12:],
        }
        by = {}
        for m in MODES:
            mins = sum(h[1] for h in self.hourly[m])
            kwh = sum(h[0] for h in self.hourly[m])
            by[m] = {"minutes": mins, "kwh": round(kwh, 3), "avg_kw": round(kwh / (mins / 60.0), 2) if mins else None}
        out["building_by_mode"] = by
        if detail:
            # Same hours of the day, building meter, by switch position (different days: conditions differ)
            rows = []
            for hr in range(24):
                a, c = self.hourly["ai"][hr], self.hourly["conventional"][hr]
                if a[1] or c[1]:
                    rows.append({"hour": hr,
                                 "ai_avg_kw": round(a[0] / (a[1] / 60.0), 2) if a[1] else None, "ai_minutes": a[1],
                                 "conv_avg_kw": round(c[0] / (c[1] / 60.0), 2) if c[1] else None, "conv_minutes": c[1]})
            out["same_hours"] = rows
        return out

    def alerts(self) -> List[Dict]:
        out = []
        for rid in self.ids:
            rs = self.spec_by_id[rid]
            rd = self.ctrl.readings[rid]
            occ = self.ctrl.occupants[rid] > 0
            if occ and rd["co2"] is not None and rd["co2"] > 1000:
                out.append({"level": "warning", "room_id": rid, "text": f"{rs.name}: CO2 {rd['co2']:.0f} ppm"})
            if occ and rd["temperature"] > 28.0:
                out.append({"level": "warning", "room_id": rid, "text": f"{rs.name}: {rd['temperature']:.1f} C with people present"})
            if rs.equipment_cooled and rd["temperature"] > 27.0:
                out.append({"level": "critical", "room_id": rid, "text": f"{rs.name}: equipment room at {rd['temperature']:.1f} C"})
        return out

    def clock(self) -> Dict:
        t = self.ctrl.time
        return {"time": t.strftime("%H:%M:%S"), "date": t.strftime("%Y-%m-%d"), "weekday": t.strftime("%A"),
                "iso": t.isoformat(timespec="seconds"), "speed": self.speed, "running": self.running,
                "fast_forward_minutes": self._ff_steps * CONTROL_DT / 60.0,
                "fast_forward_total_minutes": getattr(self, "_ff_total", 0) * CONTROL_DT / 60.0 if self._ff_steps else 0.0,
                "seed": self.seed,
                "phase": self.phase,
                "ai_enabled": self.ai_enabled,
                "learning_progress": round(self.warm_done / self.warm_total, 3) if self.warm_total else 1.0,
                "learning_days": self.warmup_days,
                "start": self.start.isoformat(timespec="minutes"), "control_step_s": CONTROL_DT,
                "physics_step_s": self.ctrl.physics_dt,
                "step_ms_median": sorted(self.step_ms)[len(self.step_ms) // 2] if self.step_ms else None,
                "outdoor_c": round(self.ctrl.outdoor.temperature, 1),
                "outdoor_rh": round(self.ctrl.outdoor.relative_humidity, 0),
                "outdoor_lux": round(self.ctrl.outdoor.illuminance_lux),
                "cloud_cover": round(self.ctrl.outdoor.cloud_cover, 2),
                "sun_altitude": round(self.ctrl.outdoor.sun_altitude, 1)}
