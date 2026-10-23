"""
Copied from the thesis code (integration/controllers.py, commit eb82674, unchanged at
08427b4).  Changes for the 26-room live twin, all additive:
  * imports point at the twin package;
  * room_overrides may also set "met" and "clo" (activity and clothing used in the
    controller's PMV model; the thesis office uses 1.1 met / 0.5 clo, a gym more);
  * ScheduleController accepts per-room working hours (a mixed-use building has
    shops, a gym and flats, not only offices);
  * RandomForestEstimator wraps the project's original Random Forest pipeline so
    it can be compared in the same loop.
The estimator and controller logic and every number the thesis used are unchanged.

Occupancy estimators and building controllers.

One implementation is shared by the live system (StateManager) and the
offline experiments (experiments/run_evaluation.py), so the numbers reported
in the thesis come from the same code that runs behind the dashboard.

Controller vocabulary (per room, per control step):
    light_action : "OFF" | "DIM" | "ON"
    hvac_action  : "ECO" (unit off) | "LOW" (setback 27 C) | "NORMAL" (comfort)
    setpoint_c   : comfort set-point for NORMAL (None = the default 24 C); only the
                   multi-objective controller chooses it (24, 25 or 26 C)

What a controller may see (Observation): sensor readings, seconds since the
last PIR detection, its own current commands, outdoor temperature and the
clock.  Only the Oracle estimator reads the true head count; it exists as an
upper-bound reference and is never used by the live system.
"""
from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from twin.portable import PortableModel
from twin.comfort import ThermalComfortCalculator

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LIGHT_LEVEL = {"OFF": 0.0, "DIM": 0.4, "ON": 1.0}
HVAC_SETPOINT = {"ECO": None, "LOW": 27.0, "NORMAL": 24.0}
LIGHTING_LUX_FULL = 400.0       # design illuminance of the room lighting at full output
LIGHTING_W_FULL = 280.0
VISUAL_TARGET_LUX = 300.0       # minimum task illuminance used as the visual-comfort target
PMV_LIMIT = 0.5                 # ISO 7730 category B limit |PMV| <= 0.5
COMFORT_MET, COMFORT_CLO, AIR_SPEED = 1.1, 0.5, 0.1


@dataclass
class Observation:
    room_id: str
    room_type: str
    timestamp: datetime
    temperature: float
    humidity: float
    light_lux: float
    co2: Optional[float]                    # None when the node has no CO2 sensor (or it failed)
    humidity_ratio: float
    seconds_since_motion: Optional[float]
    current_light: str = "OFF"
    current_hvac: str = "ECO"
    current_setpoint: Optional[float] = None    # comfort set-point in force (NORMAL only)
    outdoor_temperature: float = 30.0
    hvac_power_w: Optional[float] = None    # AC sub-meter reading
    true_occupants: Optional[int] = None    # Oracle only

    def features(self) -> Dict[str, float]:
        return {"Temperature": self.temperature, "Humidity": self.humidity, "Light": self.light_lux,
                "CO2": self.co2, "HumidityRatio": self.humidity_ratio}


@dataclass
class Decision:
    light_action: str
    hvac_action: str
    occupancy_probability: float
    control_mode: str
    reason: str
    costs: Dict[str, float] = field(default_factory=dict)
    setpoint_c: Optional[float] = None

    @property
    def energy_mode(self) -> str:
        return {"EMPTY": "MAXIMUM_SAVINGS", "STANDBY": "COMFORT_SAVINGS",
                "OCCUPIED": "COMFORT"}.get(self.control_mode, self.control_mode)


# ====================================================================== #
# Occupancy estimators
# ====================================================================== #
class MLEstimator:
    """UCI-trained portable model (see ml/train.py)."""

    def __init__(self, model_dir: str = "models/occupancy/full"):
        path = model_dir if os.path.isabs(model_dir) else os.path.join(PROJECT_ROOT, model_dir)
        fname = "model.json" if os.path.exists(os.path.join(path, "model.json")) else "edge_model.json"
        self.model = PortableModel.load(os.path.join(path, fname))
        self.model.self_test(self.model.spec["reference_samples"])
        self.name = f"ML({os.path.basename(path)})"

    def probability(self, obs: Observation) -> float:
        return float(self.model.predict_proba(self.model.vector_from_dict(obs.features()))[0])


class FusionEstimator:
    """
    PIR + CO2 fusion.

    PIR evidence.  The estimator keeps, per room, the times of recent PIR
    detections (derived from the "seconds since last motion" reading).
      * A presence episode is *confirmed* once two detections occur within
        `confirm_window_s` (10 min); it stays confirmed while detections keep
        arriving within `hold_s`.  Confirmed: P_pir = 0.98 for `sure_s` (5 min)
        after the latest detection, then a linear decay to 0 at `hold_s` (20 min).
      * A single isolated detection (a person passing through, or a false
        trigger) gives P_pir = 0.5 for 2 min, decaying to 0 at 5 min.
    CO2 evidence: the CO2-only model trained on UCI (models/occupancy/co2; a depth-2
    decision tree selected by ml/train.py).
    The two are combined as independent evidence: P = 1 - (1 - P_pir)(1 - P_co2).
    A missing CO2 reading (None or NaN: no sensor fitted, or a failed read on a
    hardware node) contributes no evidence (P_co2 = 0), so the estimate falls
    back to PIR alone instead of failing.

    probability()           all evidence (used for lighting, which reacts at once);
    confirmed_probability() confirmed PIR episodes + CO2 only (used for the air
                            conditioner, which should not start for a single blip).

    The light sensor is deliberately not used: in an automated building the
    lights are switched by the controller itself, so light level would feed
    the controller's own action back into its occupancy estimate.
    """

    def __init__(self, co2_model_dir: str = "models/occupancy/co2", hold_s: float = 1200.0,
                 sure_s: float = 300.0, confirm_window_s: float = 600.0):
        self.co2 = MLEstimator(co2_model_dir)
        self.hold_s, self.sure_s, self.confirm_window_s = hold_s, sure_s, confirm_window_s
        self._last_det: Dict[str, datetime] = {}
        self._prev_det: Dict[str, Optional[datetime]] = {}
        self._confirmed: Dict[str, bool] = {}
        self.name = "Fusion(PIR+CO2)"

    def _track(self, obs: Observation) -> Tuple[Optional[float], bool]:
        """Update the detection history; return (seconds since last detection, confirmed)."""
        room, sec = obs.room_id, obs.seconds_since_motion
        if sec is None:
            return None, False
        det = obs.timestamp.timestamp() - sec
        last = self._last_det.get(room)
        if last is None or det > last + 1.0:          # a new detection
            confirmed = self._confirmed.get(room, False)
            if last is not None and det - last <= (self.hold_s if confirmed else self.confirm_window_s):
                confirmed = True
            else:
                confirmed = False
            self._prev_det[room], self._last_det[room] = last, det
            self._confirmed[room] = confirmed
        return sec, self._confirmed.get(room, False)

    def _pir(self, sec: Optional[float], confirmed: bool) -> float:
        if sec is None:
            return 0.0
        if confirmed:
            if sec <= self.sure_s:
                return 0.98
            if sec >= self.hold_s:
                return 0.0
            return 0.98 * (self.hold_s - sec) / (self.hold_s - self.sure_s)
        if sec <= 120.0:
            return 0.5
        if sec >= 300.0:
            return 0.0
        return 0.5 * (300.0 - sec) / 180.0

    def pir_probability(self, seconds: Optional[float], confirmed: bool = True) -> float:
        return self._pir(seconds, confirmed)

    def _co2(self, obs: Observation) -> float:
        if obs.co2 is None or not math.isfinite(obs.co2):
            return 0.0
        return self.co2.probability(obs)

    def probability(self, obs: Observation) -> float:
        sec, confirmed = self._track(obs)
        p_pir = self._pir(sec, confirmed)
        return 1.0 - (1.0 - p_pir) * (1.0 - self._co2(obs))

    def confirmed_probability(self, obs: Observation) -> float:
        sec, confirmed = self._track(obs)
        p_pir = self._pir(sec, True) if confirmed else 0.0
        return 1.0 - (1.0 - p_pir) * (1.0 - self._co2(obs))


class RandomForestEstimator:
    """
    The project's original occupancy model (models/final_unified_occupancy_pipeline.pkl:
    imputer, scaler, Random Forest on Temperature, Humidity, Light, CO2,
    HumidityRatio), for comparison.  It is given the room's lux reading minus the
    room's own lighting (as the multi-objective controller computes daylight), so
    its own lights cannot feed back into its estimate.
    """
    FEATURES = ("Temperature", "Humidity", "Light", "CO2", "HumidityRatio")

    def __init__(self, path: str = "models/final_unified_occupancy_pipeline.pkl",
                 lighting_lux_full: Optional[Dict[str, float]] = None):
        import joblib
        full = path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path)
        self.pipeline = joblib.load(full)
        self.lux_full = lighting_lux_full or {}
        self.name = "RandomForest(UCI)"

    def _row(self, obs: Observation):
        own = self.lux_full.get(obs.room_id, LIGHTING_LUX_FULL) * LIGHT_LEVEL.get(obs.current_light, 0.0)
        f = obs.features()
        f["Light"] = max(0.0, obs.light_lux - own)
        return [float("nan") if f[k] is None else float(f[k]) for k in self.FEATURES]

    def _fast_setup(self) -> bool:
        """Same arithmetic as the scikit-learn pipeline (median imputer, standard
        scaler, mean of the trees' class fractions) without its per-call validation
        and per-tree job dispatch, which dominate the cost for 25 rows.  Checked
        against pipeline.predict_proba at start-up; any mismatch keeps the pipeline."""
        import numpy as np
        try:
            steps = dict(self.pipeline.named_steps)
            imp, sc, rf = steps["imputer"], steps["scaler"], steps["model"]
            self._fast = (np.asarray(imp.statistics_, float),
                          np.asarray(sc.mean_ if sc.with_mean else np.zeros(len(self.FEATURES)), float),
                          np.asarray(sc.scale_ if sc.with_std else np.ones(len(self.FEATURES)), float),
                          [e.tree_ for e in rf.estimators_], list(rf.classes_).index(1))
            rng = np.random.default_rng(0)
            X = np.column_stack([rng.uniform(18, 35, 200), rng.uniform(30, 90, 200), rng.uniform(0, 1200, 200),
                                 rng.uniform(400, 2000, 200), rng.uniform(0.003, 0.02, 200)])
            X[rng.random(X.shape) < 0.1] = np.nan
            import pandas as pd
            ref = self.pipeline.predict_proba(pd.DataFrame(X, columns=list(self.FEATURES)))[:, self._fast[4]]
            ok = bool(np.max(np.abs(ref - self._fast_proba(X))) < 1e-9)
        except Exception:
            ok = False
        if not ok:
            self._fast = None
        return ok

    def _fast_proba(self, X):
        import numpy as np
        med, mean, scale, trees, k = self._fast
        X = np.array(X, dtype=float)
        nan = np.isnan(X)
        if nan.any():
            X[nan] = np.take(med, np.nonzero(nan)[1])
        Z = np.ascontiguousarray((X - mean) / scale, dtype=np.float32)
        acc = np.zeros(len(Z))
        for t in trees:
            v = t.predict(Z)
            if v.ndim == 3:
                v = v[:, 0, :]
            tot = v.sum(axis=1)
            tot[tot == 0] = 1.0
            acc += v[:, k] / tot
        return acc / len(trees)

    def probability(self, obs: Observation) -> float:
        return float(self.probabilities([obs])[0])

    def probabilities(self, observations: List[Observation]) -> List[float]:
        if not observations:
            return []
        rows = [self._row(o) for o in observations]
        if getattr(self, "_fast", None) is None and not getattr(self, "_fast_checked", False):
            self._fast_checked = True
            self._fast_setup()
        if getattr(self, "_fast", None) is not None:
            return [float(p) for p in self._fast_proba(rows)]
        import pandas as pd
        df = pd.DataFrame(rows, columns=list(self.FEATURES))
        return [float(p[1]) for p in self.pipeline.predict_proba(df)]


class PortableRFEstimator(RandomForestEstimator):
    """
    The registry's random forest (models/registry/occupancy_rf/<active>/model.json: trained by
    ml/occupancy.py on the UCI data with a chronological split), evaluated with numpy only.
    Same five inputs and the same own-light correction as RandomForestEstimator; replaces the
    legacy pickle, whose training data included its own test rows (see docs/results/occupancy.md).
    """

    def __init__(self, model_dir: str, lighting_lux_full: Optional[Dict[str, float]] = None):
        from ml.portable import Portable
        self.portable = Portable.load(os.path.join(model_dir, "model.json"))     # self-test included
        if tuple(self.portable.features) != self.FEATURES:
            raise ValueError(f"occupancy_rf features {self.portable.features} != {list(self.FEATURES)}")
        self.lux_full = lighting_lux_full or {}
        self.version = os.path.basename(model_dir.rstrip("/"))
        self.name = f"RandomForest(registry {self.version})"

    def probabilities(self, observations: List[Observation]) -> List[float]:
        if not observations:
            return []
        import numpy as np
        X = np.asarray([self._row(o) for o in observations], dtype=float)
        return [float(p) for p in self.portable.predict(X)]


def load_rf_estimator(lighting_lux_full: Optional[Dict[str, float]] = None):
    """The registry's active occupancy_rf if there is one, else the legacy pickle (for comparison)."""
    try:
        from ml.registry import Registry
        act = Registry().active("occupancy_rf")
    except Exception:
        act = None
    if act is not None:
        return PortableRFEstimator(act["path"], lighting_lux_full)
    return RandomForestEstimator(lighting_lux_full=lighting_lux_full)


class OracleEstimator:
    """True occupancy (reference upper bound, experiments only)."""
    name = "Oracle(true occupancy)"

    def probability(self, obs: Observation) -> float:
        if obs.true_occupants is None:
            raise ValueError("Oracle estimator needs the true head count")
        return 1.0 if obs.true_occupants > 0 else 0.0


# ====================================================================== #
# Controllers
# ====================================================================== #
class ScheduleController:
    """Conventional time-scheduled BMS: lights ON and AC comfort mode during
    working hours on weekdays, everything off otherwise."""
    name = "Schedule baseline"
    estimator = None

    def __init__(self, start_h: float = 7.5, end_h: float = 18.5, setpoint_c: Optional[float] = None,
                 room_hours: Optional[Dict[str, Tuple[float, float, bool]]] = None):
        """room_hours: optional {room_id: (start_h, end_h, weekdays_only)}; end < start = overnight."""
        self.start_h, self.end_h, self.setpoint_c = start_h, end_h, setpoint_c
        self.room_hours = room_hours or {}
        if setpoint_c is not None:
            self.name = f"Schedule baseline ({setpoint_c:.0f} C)"

    def is_on(self, room_id: str, ts: datetime) -> bool:
        h = ts.hour + ts.minute / 60.0
        start, end, weekdays_only = self.room_hours.get(room_id, (self.start_h, self.end_h, True))
        if weekdays_only and ts.weekday() >= 5:
            return False
        return start <= h < end if start <= end else (h >= start or h < end)

    def decide(self, obs: Observation) -> Decision:
        on = self.is_on(obs.room_id, obs.timestamp)
        if on:
            return Decision("ON", "NORMAL", float("nan"), "OCCUPIED", "Working hours (schedule)",
                            setpoint_c=self.setpoint_c)
        return Decision("OFF", "ECO", float("nan"), "EMPTY", "Outside working hours (schedule)")


class AlwaysOnController:
    """Reference only: lights ON and AC comfort mode 24 h a day (what the old
    dashboard called its "baseline")."""
    name = "Always on (reference)"
    estimator = None

    def decide(self, obs: Observation) -> Decision:
        return Decision("ON", "NORMAL", float("nan"), "OCCUPIED", "Always on")


class ThresholdController:
    """Three-state rule on occupancy probability (the project's original logic)."""

    def __init__(self, estimator, empty_threshold: float = 0.20, occupied_threshold: float = 0.60):
        if not 0 < empty_threshold < occupied_threshold < 1:
            raise ValueError("need 0 < empty < occupied < 1")
        self.estimator = estimator
        self.empty, self.occupied = empty_threshold, occupied_threshold
        self.name = f"Threshold[{estimator.name}]"

    def decide(self, obs: Observation) -> Decision:
        p = self.estimator.probability(obs)
        if p < self.empty:
            return Decision("OFF", "ECO", p, "EMPTY", f"P(occ)={p:.2f} < {self.empty}")
        if p < self.occupied:
            return Decision("DIM", "LOW", p, "STANDBY", f"{self.empty} <= P(occ)={p:.2f} < {self.occupied}")
        return Decision("ON", "NORMAL", p, "OCCUPIED", f"P(occ)={p:.2f} >= {self.occupied}")


class OccupancyPrior:
    """
    Weekly occupancy routine learned on the controller from its OWN occupancy
    estimates (never from ground truth unless the estimator is the Oracle).
    Two daily profiles (weekday, weekend) per room, each made of slots of
    `slot_minutes` (15 min: 96 per day); each slot is an exponentially weighted
    share of time the room was estimated occupied.  (Hourly slots made the
    controller pre-cool up to an hour before people who usually arrive late in
    an hour: a slot with a high share enters the 30-min look-ahead 30 min before
    the slot starts.)
    """

    def __init__(self, learning_rate_per_day: float = 0.3, slot_minutes: int = 15):
        if 1440 % slot_minutes:
            raise ValueError("slot_minutes must divide a day")
        self.lr = learning_rate_per_day
        self.slot_s = 60 * slot_minutes
        self.n_slots = 1440 // slot_minutes
        self.table: Dict[str, List[List[float]]] = {}
        self.seen: Dict[str, List[List[float]]] = {}

    def _slot(self, ts: datetime) -> int:
        return (ts.hour * 3600 + ts.minute * 60 + ts.second) // self.slot_s

    def update(self, room_id: str, ts: datetime, occupied: float, dt_s: float) -> None:
        n = self.n_slots
        tab = self.table.setdefault(room_id, [[0.0] * n, [0.0] * n])
        w = self.seen.setdefault(room_id, [[0.0] * n, [0.0] * n])
        k, i = (0 if ts.weekday() < 5 else 1), self._slot(ts)
        # per-step learning rate so that one full slot on one day moves the slot by `lr`
        a = min(1.0, self.lr * dt_s / self.slot_s)
        tab[k][i] += a * (occupied - tab[k][i])
        w[k][i] = min(1.0, w[k][i] + a)

    def forecast(self, room_id: str, ts: datetime, horizon_s: float) -> float:
        """Highest learned occupancy share of the slots that overlap [ts, ts + horizon)."""
        tab = self.table.get(room_id)
        if tab is None:
            return 0.0
        best = 0.0
        day0 = ts.replace(hour=0, minute=0, second=0, microsecond=0)
        t = day0 + timedelta(seconds=self._slot(ts) * self.slot_s)       # start of the current slot
        end = ts + timedelta(seconds=max(0.0, horizon_s))
        while t < end:
            best = max(best, tab[0 if t.weekday() < 5 else 1][self._slot(t)])
            t += timedelta(seconds=self.slot_s)
        return best


@lru_cache(maxsize=400000)
def _pmv_cached(t_air_dk: int, rh_pct: int, radiant_offset_dk: int,
                met_c: int = int(round(COMFORT_MET * 100)), clo_c: int = int(round(COMFORT_CLO * 100))) -> float:
    """PMV on a 0.1 K / 1 % RH grid (the controller's comfort model; cached for speed)."""
    t = t_air_dk / 10.0
    return ThermalComfortCalculator.pmv_iso7730(t, t + radiant_offset_dk / 10.0, AIR_SPEED, float(rh_pct),
                                                met_c / 100.0, clo_c / 100.0)


class MultiObjectiveController:
    """
    Predictive, occupancy-aware multi-objective controller.

    Lighting and air conditioning are decided separately at every control step
    (1 min) by minimising, over the next `horizon_s` (30 min),

        J = alpha * E  +  beta * P * D  +  gamma * S

        E  electrical energy (kWh), including the energy that an option defers
           to later (see "recovery" below);
        D  discomfort-hours: visual  max(0, 300 lux - lux)/300,
                             thermal max(0, |PMV| - pmv_target)   (pmv_target 0.4,
                             a margin below the ISO 7730 category-B limit 0.5);
        P  occupancy probability: lighting uses the current estimate (any PIR
           detection); the AC uses the *confirmed* estimate, raised to the learned
           weekly occupancy routine (15-min slots) over the horizon (allows pre-cooling);
        S  1 if the AC command (mode or set-point) changes, else 0.  The stability
           term applies to the air conditioner; lighting changes are limited by a
           2-min minimum dwell instead.

    Air-conditioning options: ECO (off), LOW (27 C set-back), NORMAL at 26, 25
    or 24 C.  The controller predicts each option with its own 1R1C room model
    (it does not see the simulator):
        C dT/dt = UA (T_ref - T) - Q_ac,   T_ref = T_out + gain_offset_k,
    refined for free running by a slow "fabric" temperature T_m, estimated as a
    3-h moving average of the measured air temperature: without AC the air
    returns to T_m within ~tau_air_s (15 min) while T_m drifts to T_ref with
    tau_free_s - so a room cooled for only a few minutes is predicted to warm
    up again quickly once the unit stops.
    written in electrical-equivalent units: k_e = UA/COP (W per K), learned online
    from the AC sub-meter while the unit holds a set-point; C_e = tau_free_s * k_e.
    Without AC the room relaxes to T_ref with time constant tau_free_s; with AC it
    approaches the set-point (plus the offset the unit is observed to hold, learned
    online) with tau_ac_s, limited to the unit's rated electrical input.
    Energy of an option over the horizon follows from the same balance:
        E = k_e * integral(T_ref - T) dt + C_e * (T_start - T_end)       (>= 0)
    Recovery: an option that leaves the room warmer than the temperature the
    controller would hold when the room is used (T_hold) is charged
        P_ac * C_e * max(0, T_end - T_hold),
    the energy needed later to remove that heat.  Because E and the recovery come
    from one energy balance, switching the unit off for a short vacancy is not
    mistaken for a saving.
    Minimum dwell times: AC 10 min, lights 2 min (switching the AC on for a
    confirmed occupant, P >= 0.6, is always allowed).  light_margin (live twin:
    0.03; thesis experiments: 0) keeps the lights unchanged unless another option
    scores at least that much lower, so two near-equal options do not alternate.

    room_overrides: per-room calibration for real rooms (hardware stage), e.g.
        {"office_1": {"lighting_lux_full": 350, "lighting_w_full": 36,
                      "light_options": ["OFF", "ON"], "ac_max_electric_w": 1500}}
    lighting_lux_full is the illuminance the room lighting adds at the sensor at
    full output (measured lights-on minus lights-off at night); light_options
    restricts lighting to what the actuator can do (a relay cannot dim).
    ac_options replaces the AC choices for a room (e.g. down to 22 C for a gym).
    energy_norm multiplies the energy terms inside J (not the reported kWh): the
    weights were tuned on the thesis's 36 m2 office, so for a room of area A the
    live twin uses 36/A, i.e. J compares energy per 36 m2 of floor (energy
    intensity) with the discomfort felt in the room, and a large room is not
    pushed to sacrifice comfort just because its kWh are larger.
    Without overrides the digital-twin values are used.
    """

    AC_OPTIONS: Tuple[Tuple[str, Optional[float]], ...] = (
        ("ECO", None), ("LOW", 27.0), ("NORMAL", 26.0), ("NORMAL", 25.0), ("NORMAL", 24.0))
    COMFORT_SETPOINTS = (26.0, 25.0, 24.0)

    def __init__(self, estimator, alpha: float = 1.0, beta: float = 1.0, gamma: float = 0.02,
                 horizon_s: float = 1800.0, tau_free_s: float = 7200.0, tau_ac_s: float = 600.0,
                 gain_offset_k: float = 3.0, radiant_offset_k: float = 1.5,
                 ac_dwell_s: float = 600.0, light_dwell_s: float = 120.0, use_prior: bool = True,
                 k_e_init_w_per_k: float = 150.0, ac_max_electric_w: float = 1700.0,
                 pmv_target: float = 0.4, tau_air_s: float = 900.0, tau_mass_obs_s: float = 10800.0,
                 room_overrides: Optional[Dict[str, Dict]] = None, light_margin: float = 0.0):
        self.estimator = estimator
        self.light_margin = light_margin
        self.alpha, self.beta, self.gamma = alpha, beta, gamma
        self.horizon_s, self.tau_free_s, self.tau_ac_s = horizon_s, tau_free_s, tau_ac_s
        self.gain_offset_k, self.radiant_offset_k = gain_offset_k, radiant_offset_k
        self.ac_dwell_s, self.light_dwell_s = ac_dwell_s, light_dwell_s
        self.use_prior = use_prior
        self.k_e_init, self.ac_max_w = k_e_init_w_per_k, ac_max_electric_w
        self.pmv_target = pmv_target
        self.tau_air_s, self.tau_mass_obs_s = tau_air_s, tau_mass_obs_s
        self.room_overrides: Dict[str, Dict] = {}
        for room, ov in (room_overrides or {}).items():
            bad = set(ov) - {"lighting_lux_full", "lighting_w_full", "light_options", "ac_max_electric_w",
                             "met", "clo", "ac_options", "energy_norm"}
            if bad:
                raise ValueError(f"room_overrides[{room!r}]: unknown keys {sorted(bad)}")
            opts = tuple(ov.get("light_options", ("OFF", "DIM", "ON")))
            if not opts or any(o not in LIGHT_LEVEL for o in opts) or "OFF" not in opts:
                raise ValueError(f"room_overrides[{room!r}]: light_options must include OFF, from {list(LIGHT_LEVEL)}")
            ac_opts = tuple((m, None if sp is None else float(sp)) for m, sp in ov.get("ac_options", self.AC_OPTIONS))
            if not ac_opts or ("ECO", None) not in ac_opts or any(m not in HVAC_SETPOINT for m, _ in ac_opts):
                raise ValueError(f"room_overrides[{room!r}]: ac_options must include ('ECO', None)")
            self.room_overrides[room] = dict(ov, light_options=opts, ac_options=ac_opts)
        self._t_mass: Dict[str, float] = {}                     # observer: slow (fabric) temperature
        self.prior = OccupancyPrior()
        self.k_e: Dict[str, float] = {}                         # learned W_elec per K
        self.sp_offset: Dict[str, Dict[str, float]] = {}        # learned (room temp - set-point) per mode
        self._last_change: Dict[Tuple[str, str], datetime] = {}
        self._last_ts: Dict[str, datetime] = {}
        self._current_sp: Dict[str, Optional[float]] = {}
        self.name = f"MultiObjective[{estimator.name}] a={alpha} b={beta} g={gamma}"

    # ------------------------------------------------------------------ #
    def _pmv(self, t_air: float, rh: float, room: Optional[str] = None) -> float:
        met = self.room_overrides.get(room, {}).get("met", COMFORT_MET) if room else COMFORT_MET
        clo = self.room_overrides.get(room, {}).get("clo", COMFORT_CLO) if room else COMFORT_CLO
        return _pmv_cached(int(round(t_air * 10)), int(round(rh)), int(round(self.radiant_offset_k * 10)),
                           int(round(met * 100)), int(round(clo * 100)))

    def _offset(self, room: str, mode: str) -> float:
        return self.sp_offset.get(room, {}).get(mode, 0.0)

    def _learn(self, obs: Observation, p_ac: float) -> None:
        room = obs.room_id
        last = self._last_ts.get(room)
        dt = (obs.timestamp - last).total_seconds() if last else 0.0
        self._last_ts[room] = obs.timestamp
        tm = self._t_mass.get(room)
        if tm is None or not 0 < dt <= 3600:
            self._t_mass[room] = obs.temperature
        else:
            self._t_mass[room] = tm + min(1.0, dt / self.tau_mass_obs_s) * (obs.temperature - tm)
        if not 0 < dt <= 3600:
            return
        self.prior.update(room, obs.timestamp, 1.0 if p_ac >= 0.5 else 0.0, dt)
        if obs.hvac_power_w is None or obs.current_hvac == "ECO":
            return
        changed = self._last_change.get((room, "ac"))
        if changed is not None and (obs.timestamp - changed).total_seconds() < 1800:
            return                                             # not settled yet
        sp = HVAC_SETPOINT[obs.current_hvac] if obs.current_hvac == "LOW" else \
            (self._current_sp.get(room) or HVAC_SETPOINT["NORMAL"])
        if abs(obs.temperature - sp) >= 2.0:
            return
        a = min(1.0, dt / 3600.0)
        off = self.sp_offset.setdefault(room, {"LOW": 0.0, "NORMAL": 0.0})
        off[obs.current_hvac] += a * ((obs.temperature - sp) - off[obs.current_hvac])
        drive = obs.outdoor_temperature + self.gain_offset_k - obs.temperature
        if drive > 1.0:
            k = self.k_e.setdefault(room, self.k_e_init)
            self.k_e[room] = k + a * (obs.hvac_power_w / drive - k)

    def _path(self, obs: Observation, mode: str, sp: Optional[float], n: int = 3) -> List[float]:
        """Predicted air temperature at n equally spaced points over the horizon."""
        t_ref = obs.outdoor_temperature + self.gain_offset_k
        sp_eff = None if sp is None else sp + self._offset(obs.room_id, mode)
        tm0 = self._t_mass.get(obs.room_id, obs.temperature)
        out = []
        for i in range(1, n + 1):
            h = self.horizon_s * i / n
            tm = t_ref + (tm0 - t_ref) * math.exp(-h / self.tau_free_s)
            t_free = tm + (obs.temperature - tm0) * math.exp(-h / self.tau_air_s)
            if sp_eff is None or t_free <= sp_eff:
                out.append(t_free)
            elif obs.temperature > sp_eff:
                out.append(sp_eff + (obs.temperature - sp_eff) * math.exp(-h / self.tau_ac_s))
            else:
                out.append(sp_eff)
        return out

    def _room(self, room: str, key: str, default):
        return self.room_overrides.get(room, {}).get(key, default)

    def _energy_kwh(self, obs: Observation, mode: str, path: List[float]) -> float:
        if mode == "ECO":
            return 0.0
        k = self.k_e.get(obs.room_id, self.k_e_init)
        t_ref = obs.outdoor_temperature + self.gain_offset_k
        dt = self.horizon_s / len(path)
        temps = [obs.temperature] + path
        integral = sum(0.5 * (temps[i] + temps[i + 1]) for i in range(len(path))) * dt
        e_j = k * (t_ref * self.horizon_s - integral) + k * self.tau_free_s * (obs.temperature - path[-1])
        ac_max = self._room(obs.room_id, "ac_max_electric_w", self.ac_max_w)
        return min(max(e_j, 0.0), ac_max * self.horizon_s) / 3.6e6

    def _t_hold(self, obs: Observation) -> float:
        """Warmest comfort set-point whose predicted PMV stays within the target."""
        off = self._offset(obs.room_id, "NORMAL")
        sps = sorted((sp for m, sp in self._room(obs.room_id, "ac_options", self.AC_OPTIONS)
                      if m == "NORMAL" and sp is not None), reverse=True) or list(self.COMFORT_SETPOINTS)
        for sp in sps:
            if abs(self._pmv(sp + off, obs.humidity, obs.room_id)) <= self.pmv_target:
                return sp + off
        return sps[-1] + off

    def _dwell_ok(self, room: str, actuator: str, ts: datetime, dwell_s: float) -> bool:
        last = self._last_change.get((room, actuator))
        return last is None or (ts - last).total_seconds() >= dwell_s

    # ------------------------------------------------------------------ #
    def decide(self, obs: Observation) -> Decision:
        room, ts, hh = obs.room_id, obs.timestamp, self.horizon_s / 3600.0
        p_now = self.estimator.probability(obs)
        p_ac = getattr(self.estimator, "confirmed_probability", self.estimator.probability)(obs)
        if obs.current_hvac != "NORMAL":
            self._current_sp[room] = None
        elif obs.current_setpoint is not None:
            self._current_sp[room] = obs.current_setpoint
        self._learn(obs, p_ac)
        p_prior = self.prior.forecast(room, ts, self.horizon_s) if self.use_prior else None
        p_fut = max(p_ac, p_prior) if self.use_prior else p_ac

        # ---- lighting (immediate) -------------------------------------------
        e_norm = self._room(room, "energy_norm", 1.0)     # energy per reference floor area (see class doc)
        lux_full = self._room(room, "lighting_lux_full", LIGHTING_LUX_FULL)
        w_full = self._room(room, "lighting_w_full", LIGHTING_W_FULL)
        daylight = max(0.0, obs.light_lux - lux_full * LIGHT_LEVEL.get(obs.current_light, 0.0))
        light_costs = {}
        for light in self._room(room, "light_options", ("OFF", "DIM", "ON")):
            lux = daylight + lux_full * LIGHT_LEVEL[light]
            d_vis = max(0.0, VISUAL_TARGET_LUX - lux) / VISUAL_TARGET_LUX * hh
            e = w_full * LIGHT_LEVEL[light] / 1000.0 * hh
            light_costs[light] = (self.alpha * e * e_norm + self.beta * p_now * d_vis, e, d_vis)
        light = min(light_costs, key=lambda k: light_costs[k][0])
        if (self.light_margin > 0 and light != obs.current_light and obs.current_light in light_costs
                and light_costs[obs.current_light][0] - light_costs[light][0] < self.light_margin):
            light = obs.current_light       # within the margin: keep the lights as they are (no flicker)
        if light != obs.current_light and not self._dwell_ok(room, "light", ts, self.light_dwell_s) \
                and obs.current_light in light_costs:
            light = obs.current_light

        # ---- air conditioning (look-ahead) -------------------------------------
        current = (obs.current_hvac, self._current_sp.get(room) if obs.current_hvac == "NORMAL" else
                   HVAC_SETPOINT.get(obs.current_hvac))
        if current[0] == "NORMAL" and current[1] is None:
            current = ("NORMAL", HVAC_SETPOINT["NORMAL"])
        t_hold = self._t_hold(obs)
        k = self.k_e.get(room, self.k_e_init)
        c_e = k * self.tau_free_s                                   # J per K (electrical equivalent)
        ac_costs = {}
        for opt in self._room(room, "ac_options", self.AC_OPTIONS):
            mode, sp = opt
            path = self._path(obs, mode, sp)
            pen = [max(0.0, abs(self._pmv(t, obs.humidity, room)) - self.pmv_target) for t in path]
            d_th = sum(pen) / len(pen) * hh
            e = self._energy_kwh(obs, mode, path)
            recovery = p_fut * c_e * max(0.0, path[-1] - t_hold) / 3.6e6
            s = float(opt != current)
            ac_costs[opt] = (self.alpha * (e + recovery) * e_norm + self.beta * p_fut * d_th + self.gamma * s,
                             e, d_th, path[-1], recovery)
        choice = min(ac_costs, key=lambda o: ac_costs[o][0])
        urgent_on = current[0] == "ECO" and choice[0] != "ECO" and p_ac >= 0.6
        if choice != current and not urgent_on and not self._dwell_ok(room, "ac", ts, self.ac_dwell_s):
            choice = current if current in ac_costs else ("NORMAL", HVAC_SETPOINT["NORMAL"])
        hvac, sp = choice

        if light != obs.current_light:
            self._last_change[(room, "light")] = ts
        if choice != current:
            self._last_change[(room, "ac")] = ts
        self._current_sp[room] = sp if hvac == "NORMAL" else None
        lc, ac = light_costs[light], ac_costs[choice]
        costs = {"J_light_options": {k: v[0] for k, v in light_costs.items()},
                 "J_ac_options": {(f"{m} {sp_:.0f}" if sp_ is not None else m): v[0] for (m, sp_), v in ac_costs.items()},
                 "J_light": lc[0], "J_ac": ac[0], "energy_kwh_horizon": lc[1] + ac[1],
                 "recovery_kwh": ac[4], "visual_discomfort_h": lc[2], "thermal_discomfort_h": ac[2],
                 "t_pred": ac[3], "t_hold": t_hold, "p_now": p_now, "p_ac": p_ac, "p_future": p_fut,
                 "p_prior": p_prior, "k_e_w_per_k": k,
                 "ac_breakdown": {(f"{m} {sp_:.0f}" if sp_ is not None else m):
                                  {"J": v[0], "kwh": v[1], "recovery_kwh": v[4], "discomfort_h": v[2], "t_end": v[3]}
                                  for (m, sp_), v in ac_costs.items()}}
        mode = "OCCUPIED" if p_now >= 0.6 else ("STANDBY" if p_now >= 0.2 else "EMPTY")
        ac_txt = f"AC {hvac}" + (f" {sp:.0f} C" if hvac == "NORMAL" else "")
        reason = (f"P(occ) now {p_now:.2f}, AC basis {p_ac:.2f}, next {self.horizon_s / 60:.0f} min {p_fut:.2f}; "
                  f"lights {light}, {ac_txt} (pred. {ac[3]:.1f} C)")
        return Decision(light, hvac, p_now, mode, reason, costs,
                        setpoint_c=sp if hvac == "NORMAL" else None)


# ====================================================================== #
def build_controller(name: str, **kw):
    """Factory used by config files, the live system and experiments."""
    if name == "schedule":
        return ScheduleController()
    if name == "schedule_25":
        return ScheduleController(setpoint_c=25.0)
    if name == "always_on":
        return AlwaysOnController()
    if name == "threshold_full":
        return ThresholdController(MLEstimator("models/occupancy/full"))
    if name == "threshold_fusion":
        return ThresholdController(FusionEstimator())
    if name == "mo_fusion":
        return MultiObjectiveController(FusionEstimator(), **kw)
    if name == "mo_fusion_noprior":
        return MultiObjectiveController(FusionEstimator(), use_prior=False, **kw)
    if name == "mo_oracle":
        return MultiObjectiveController(OracleEstimator(), **kw)
    if name == "mo_full":
        return MultiObjectiveController(MLEstimator("models/occupancy/full"), **kw)
    raise ValueError(f"unknown controller {name!r}")


def timed_decide(controller, obs: Observation) -> Tuple[Decision, float]:
    t0 = time.perf_counter()
    d = controller.decide(obs)
    return d, (time.perf_counter() - t0) * 1000.0
