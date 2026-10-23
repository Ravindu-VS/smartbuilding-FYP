"""
Observation, action and controller definitions shared by the RL environment (training)
and the deployed PPO controller (inference), so both compute exactly the same thing.

Observation (24 values per room, all available to the controller at decision time):
   0 (T - design set-point) / 3          measured air temperature error (K/3)
   1 (RH - 60) / 20                      measured relative humidity
   2 (CO2 - 600) / 400, 3 CO2 missing    measured CO2 (0 and flag 1 when no reading / no sensor)
   4 (CO2 - CO2 15 min ago) / 100        CO2 trend (occupancy proxy)
   5 P(occupied)                         the live system's PIR + CO2 fusion estimate
   6 motion in last 2 min, 7 in last 10 min   (PIR)
   8 inside the room's operating hours   (schedule)
   9 sin(hour), 10 cos(hour), 11 weekday
  12 (outdoor temperature - 30) / 5
  13 daylight estimate / 500             measured lux minus the room's own lighting, capped at 2
  14 light level (0 / 0.4 / 1)           current command
  15-17 AC mode one-hot (ECO, LOW, NORMAL)
  18 (set-point - design) / 3            0 unless NORMAL
  19 AC power / AC maximum electric power (sub-meter)
  20 minutes since the AC command changed / 30 (capped at 1)
  21 floor area / 100 m2, 22 capacity / 20 people, 23 activity (met) - 1.1
Actions (12): light {OFF, DIM, ON} x AC {ECO (off), LOW (27 C set-back), NORMAL at design + 1 C,
NORMAL at design}.  Limits: set-points only from that list (22-27 C); the AC command may change
at most once per 10 min (dwell), decisions every 5 min; every action then passes the same
SafetyLayer as all other controllers (R1-R4), behind the GuardedController fail-safe.
"""
from __future__ import annotations

import math
import os
from collections import deque
from datetime import datetime
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np

from twin.controllers import Decision, FusionEstimator, Observation, ScheduleController

N_OBS = 24
OBS_CLIP = 10.0                 # every observation value is clipped to +-10
LIGHTS = ("OFF", "DIM", "ON")
LIGHT_LEVEL = {"OFF": 0.0, "DIM": 0.4, "ON": 1.0}
AC_CHOICES = ("ECO", "LOW", "NORMAL+1", "NORMAL")
ACTIONS: List[Tuple[str, str]] = [(l, a) for l in LIGHTS for a in AC_CHOICES]
N_ACT = len(ACTIONS)
DECISION_S = 300.0
AC_DWELL_S = 600.0
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def action_command(a: int, design_sp: float) -> Tuple[str, str, Optional[float]]:
    light, ac = ACTIONS[int(a)]
    if ac == "ECO":
        return light, "ECO", None
    if ac == "LOW":
        return light, "LOW", None
    return light, "NORMAL", float(design_sp) + (1.0 if ac == "NORMAL+1" else 0.0)


class ObsBuilder:
    """Per-room observation state (CO2 history, AC change time) and the feature vector."""

    def __init__(self, specs):
        self.spec = {r.room_id: r for r in specs}
        self.fusion = FusionEstimator()
        self.schedule = ScheduleController(room_hours={r.room_id: r.schedule_hours for r in specs})
        self._co2: Dict[str, Deque[Tuple[float, float]]] = {}
        self._ac_cmd: Dict[str, Tuple[str, Optional[float]]] = {}
        self._ac_since: Dict[str, float] = {}
        self.p_occ: Dict[str, float] = {}

    def observe(self, o: Observation) -> float:
        """Update the room's state with this minute's observation; return P(occupied)."""
        now = o.timestamp.timestamp()
        rid = o.room_id
        if o.co2 is not None and math.isfinite(o.co2):
            h = self._co2.setdefault(rid, deque())
            h.append((now, float(o.co2)))
            while h and now - h[0][0] > 1200.0:
                h.popleft()
        ac = (o.current_hvac, o.current_setpoint)
        if self._ac_cmd.get(rid) != ac:
            self._ac_cmd[rid] = ac
            self._ac_since[rid] = now
        p = self.fusion.probability(o)
        self.p_occ[rid] = p
        return p

    def _co2_trend(self, rid: str, now: float, co2: Optional[float]) -> float:
        h = self._co2.get(rid)
        if co2 is None or not h:
            return 0.0
        old = [c for t, c in h if t <= now - 900.0]
        return (co2 - old[-1]) / 100.0 if old else 0.0

    def vector(self, o: Observation) -> np.ndarray:
        rs = self.spec[o.room_id]
        ov = rs.controller_overrides
        now = o.timestamp.timestamp()
        co2 = o.co2 if (o.co2 is not None and math.isfinite(o.co2)) else None
        sec = o.seconds_since_motion
        h = o.timestamp.hour + o.timestamp.minute / 60.0
        own = ov["lighting_lux_full"] * LIGHT_LEVEL.get(o.current_light, 0.0)
        daylight = max(0.0, (o.light_lux if math.isfinite(o.light_lux) else 0.0) - own)
        sp = o.current_setpoint if o.current_hvac == "NORMAL" and o.current_setpoint is not None else None
        ac_max = ov["ac_max_electric_w"]
        since = (now - self._ac_since.get(o.room_id, now - 1800.0)) / 60.0
        v = [
            (o.temperature - rs.design_setpoint) / 3.0,
            (o.humidity - 60.0) / 20.0,
            (co2 - 600.0) / 400.0 if co2 is not None else 0.0,
            0.0 if co2 is not None else 1.0,
            self._co2_trend(o.room_id, now, co2),
            self.p_occ.get(o.room_id, 0.0),
            1.0 if sec is not None and sec <= 120.0 else 0.0,
            1.0 if sec is not None and sec <= 600.0 else 0.0,
            1.0 if self.schedule.is_on(o.room_id, o.timestamp) else 0.0,
            math.sin(2 * math.pi * h / 24.0), math.cos(2 * math.pi * h / 24.0),
            1.0 if o.timestamp.weekday() < 5 else 0.0,
            (o.outdoor_temperature - 30.0) / 5.0,
            min(2.0, daylight / 500.0),
            LIGHT_LEVEL.get(o.current_light, 0.0),
            1.0 if o.current_hvac == "ECO" else 0.0, 1.0 if o.current_hvac == "LOW" else 0.0,
            1.0 if o.current_hvac == "NORMAL" else 0.0,
            (sp - rs.design_setpoint) / 3.0 if sp is not None else 0.0,
            min(2.0, (o.hvac_power_w or 0.0) / ac_max) if ac_max else 0.0,
            min(1.0, since / 30.0),
            rs.area / 100.0, rs.max_occupancy / 20.0, ov["met"] - 1.1,
        ]
        x = np.asarray(v, dtype=np.float64)
        if x.shape != (N_OBS,) or not np.all(np.isfinite(x)):
            raise ValueError(f"invalid observation for {o.room_id}: {x}")
        return np.clip(x, -OBS_CLIP, OBS_CLIP)

    def ac_change_allowed(self, rid: str, now: float) -> bool:
        return now - self._ac_since.get(rid, -1e18) >= AC_DWELL_S


def apply_dwell(builder: ObsBuilder, o: Observation, light: str, hvac: str, sp: Optional[float]):
    """Keep the current AC command if it changed less than AC_DWELL_S ago."""
    if (hvac, sp) != (o.current_hvac, o.current_setpoint) and not builder.ac_change_allowed(o.room_id, o.timestamp.timestamp()):
        return light, o.current_hvac, o.current_setpoint, True
    return light, hvac, sp, False


class PPOController:
    """
    The trained PPO policy as a controller (same interface as the others: decide(obs)).
    Called every control step (60 s); it re-decides each room every 5 min and holds the
    decision in between.  Deterministic (most likely action).  numpy only.
    If the policy file is missing or fails its checks, construction raises; the runner and
    the live twin then do not offer the controller (no silent substitute).
    """

    def __init__(self, policy, specs=None, path: str = ""):
        from twin.spec import build_spec
        if policy.n_obs != N_OBS or policy.n_act != N_ACT:
            raise ValueError(f"policy shape {policy.n_obs}x{policy.n_act} does not match {N_OBS}x{N_ACT}")
        self.policy = policy
        self.specs = specs or build_spec()
        self.builder = ObsBuilder(self.specs)
        self.estimator = None
        self.path = path
        self.name = f"PPO({os.path.basename(os.path.dirname(path)) or 'policy'})"
        self._held: Dict[str, Tuple[float, Decision]] = {}

    @classmethod
    def load(cls, path: str) -> "PPOController":
        from rl.ppo import Policy
        full = path if os.path.isabs(path) else os.path.join(ROOT, path)
        return cls(Policy.load(full), path=full)

    @classmethod
    def load_active(cls) -> "PPOController":
        from ml.registry import Registry
        entry = Registry().active("ppo_policy")
        if entry is None:
            raise FileNotFoundError("no active ppo_policy in models/registry (train with python -m rl.train)")
        return cls.load(os.path.join(entry["path"], "policy.json"))

    def decide(self, o: Observation) -> Decision:
        p = self.builder.observe(o)
        now = o.timestamp.timestamp()
        held = self._held.get(o.room_id)
        if held is not None and now - held[0] < DECISION_S - 1e-6:
            d = held[1]
            return Decision(d.light_action, d.hvac_action, p, d.control_mode, d.reason, setpoint_c=d.setpoint_c)
        x = self.builder.vector(o)
        probs = self.policy.probs(x[None, :])[0]
        a = int(np.argmax(probs))
        rs = self.builder.spec[o.room_id]
        light, hvac, sp = action_command(a, rs.design_setpoint)
        light, hvac, sp, dwelled = apply_dwell(self.builder, o, light, hvac, sp)
        mode = "OCCUPIED" if hvac == "NORMAL" else ("STANDBY" if hvac == "LOW" or light != "OFF" else "EMPTY")
        reason = (f"PPO action {ACTIONS[a][0]}/{ACTIONS[a][1]} (p={probs[a]:.2f}), P(occ)={p:.2f}"
                  + ("; AC held (10-min dwell)" if dwelled else ""))
        d = Decision(light, hvac, p, mode, reason, setpoint_c=sp)
        self._held[o.room_id] = (now, d)
        return d
