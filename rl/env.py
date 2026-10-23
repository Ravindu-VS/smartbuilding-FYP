"""
Building-control environments for PPO, on the digital twin's physics (twin/).

BuildingVecEnv   all 25 simulated rooms step together; each room is one sample of the
                 shared per-room policy (parameter sharing).  Used for training.
RoomControlEnv   gymnasium.Env view of one room (the others run the conventional schedule);
                 passes gymnasium's env checker.  Used for API validation and tests.

Every decision (5 min) is held for five 1-minute control steps; at each step the held
command passes the SafetyLayer (R1-R4) exactly as in deployment, and the physics advances
60 s (four 15 s sub-steps).  Episodes are truncated (not terminated) at the horizon, so the
value of the last state is bootstrapped.

Reward per room and decision (all terms dimensionless, see docs/RL.md):
   r = -( w_E * E / E_max              energy: AC + boost fan + lighting over the 5 min, divided by
                                       the room's maximum AC + lighting energy over 5 min
          + w_C * mean_occ max(0, |PMV| - 0.5)          thermal discomfort (ISO 7730 cat. B limit)
          + w_V * mean_occ max(0, 300 - lux) / 300      visual: task illuminance below 300 lux
          + w_Q * mean_occ max(0, CO2 - 1000) / 500     indoor air (true CO2)
          + w_S * (number of command changes) )         switching / cycling
   mean_occ averages over the minutes with people present (zero when the room is empty);
   transit rooms (corridors) have no comfort terms, as in the evaluation metrics.
The reward uses the simulator's true state; the policy only sees the observation.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence

import numpy as np

from rl.policy import ACTIONS, DECISION_S, N_ACT, N_OBS, OBS_CLIP, ObsBuilder, action_command, apply_dwell
from twin.controllers import Observation
from twin.runner import CONTROL_DT, make_controller
from twin.safety import InputGuard, SafetyLayer, blocking
from twin.scenarios import ScenarioBuilding, SensorPath, get_scenario
from twin.spec import build_spec

try:                                  # gymnasium is a training dependency, not needed for inference
    import gymnasium as _gym
    from gymnasium import spaces as _spaces
    _EnvBase = _gym.Env
except ImportError:                   # pragma: no cover
    _gym, _spaces, _EnvBase = None, None, object

REWARD_WEIGHTS = {"energy": 1.0, "comfort": 3.0, "visual": 1.0, "iaq": 1.0, "switch": 0.05}
TRAIN_SCENARIOS = ("normal", "hot_weather", "cool_weather", "high_occupancy", "low_occupancy", "sudden_occupancy",
                   "unusual_demand")


def _cmd(light="OFF", hvac="ECO", sp=None, vent=False):
    return {"light": light, "hvac": hvac, "sp": sp, "vent": vent}


class BuildingVecEnv:
    def __init__(self, days: float = 2.0, warmup_h: float = 12.0, weights: Optional[Dict[str, float]] = None):
        self.specs = build_spec()
        self.days, self.warmup_h = days, warmup_h
        self.w = dict(REWARD_WEIGHTS, **(weights or {}))
        self.n_steps_per_decision = int(round(DECISION_S / CONTROL_DT))
        self.b: Optional[ScenarioBuilding] = None

    # ------------------------------------------------------------------ #
    def reset(self, seed: int, scenario="normal", start: Optional[datetime] = None) -> np.ndarray:
        self.scenario = get_scenario(scenario)
        start = start or datetime(2026, 3, 2)
        t0 = start - timedelta(hours=self.warmup_h)
        self.b = b = ScenarioBuilding(self.specs, seed, t0, self.scenario)
        self.ids: List[str] = b.ids
        self.path = SensorPath(self.scenario, self.ids, seed, t0)
        self.guard = InputGuard()
        self.safety = SafetyLayer({r.room_id: r.equipment_cooled for r in self.specs})
        self.builder = ObsBuilder(self.specs)
        self.fallback = make_controller("schedule", self.specs)
        self.cmd = {rid: _cmd() for rid in self.ids}
        for rid in self.ids:
            b.apply(rid, "OFF", "ECO", None)
        self.end = start + timedelta(days=self.days)
        self.start = start
        # warm-up under the conventional schedule (thermal state, estimator history)
        while b.time < start:
            obs = self._observe()
            for rid in self.ids:
                d = self.fallback.decide(obs[rid][0])
                self._apply(rid, d.light_action, d.hvac_action, d.setpoint_c, obs[rid])
            self._advance()
        self._last_obs = self._observe()
        return self._vectors(self._last_obs)

    def _observe(self) -> Dict[str, tuple]:
        b = self.b
        delivered, age, _ = self.path.deliver(b.readings, b.time)
        out = {}
        for rid in self.ids:
            rd = delivered[rid]
            rs = b.specs[rid]
            vals, problems = self.guard.check(rid, {"temperature": rd["temperature"], "humidity": rd["humidity"],
                                                    "light": rd["light"], "co2": rd["co2"] if "co2" in rs.sensors else None},
                                              b.time, age)
            nan = float("nan")
            o = Observation(rid, rs.room_type, b.time,
                            vals["temperature"] if vals["temperature"] is not None else nan,
                            vals["humidity"] if vals["humidity"] is not None else nan,
                            vals["light"] if vals["light"] is not None else nan, vals["co2"],
                            rd.get("humidity_ratio") or nan, rd["pir_seconds"], current_light=self.cmd[rid]["light"],
                            current_hvac=self.cmd[rid]["hvac"], current_setpoint=self.cmd[rid]["sp"],
                            outdoor_temperature=b.outdoor.temperature,
                            hvac_power_w=b.physics[rid].state.hvac_electric_w)
            p = self.builder.observe(o)
            out[rid] = (o, p, problems)
        return out

    def _apply(self, rid: str, light: str, hvac: str, sp: Optional[float], ob) -> int:
        o, p, _ = ob
        rs = self.b.specs[rid]
        if hvac == "NORMAL" and sp is None:
            sp = rs.design_setpoint
        va = self.safety.validate(rid, light, hvac, sp, p, o.temperature if math.isfinite(o.temperature) else None, o.co2)
        new = _cmd(va.light, va.hvac, va.setpoint, va.vent_boost)
        prev = self.cmd[rid]
        if new == prev:
            return 0
        changes = int(new["light"] != prev["light"]) + int((new["hvac"], new["sp"]) != (prev["hvac"], prev["sp"]))
        self.cmd[rid] = new
        self.b.apply(rid, new["light"], new["hvac"], new["sp"], new["vent"])
        return changes

    def _advance(self) -> None:
        self.b.advance(CONTROL_DT)
        self.b.read_sensors(CONTROL_DT)

    def _vectors(self, obs: Dict[str, tuple]) -> np.ndarray:
        return np.stack([self.builder.vector(obs[rid][0]) for rid in self.ids])

    # ------------------------------------------------------------------ #
    def step(self, actions: Sequence[int]):
        b, w = self.b, self.w
        if len(actions) != len(self.ids):
            raise ValueError(f"expected {len(self.ids)} actions")
        targets = {}
        for rid, a in zip(self.ids, actions):
            if not 0 <= int(a) < N_ACT:
                raise ValueError(f"action {a} outside 0..{N_ACT - 1}")
            o = self._last_obs[rid][0]
            light, hvac, sp = action_command(int(a), b.specs[rid].design_setpoint)
            targets[rid] = apply_dwell(self.builder, o, light, hvac, sp)[:3]
        e0 = {rid: self._ctrl_energy(rid) for rid in self.ids}
        acc = {rid: np.zeros(5) for rid in self.ids}          # comfort, visual, iaq, switches, occupied minutes
        obs = self._last_obs
        fallbacks = 0
        for k in range(self.n_steps_per_decision):
            if k > 0:
                obs = self._observe()
            for rid in self.ids:
                light, hvac, sp = targets[rid]
                if blocking(obs[rid][2]):              # inputs unusable: fail-safe rule, as deployed
                    d = self.fallback.decide(obs[rid][0])
                    light, hvac, sp = d.light_action, d.hvac_action, d.setpoint_c
                    fallbacks += 1
                acc[rid][3] += self._apply(rid, light, hvac, sp, obs[rid])
            self._advance()
            for rid in self.ids:
                rs = b.specs[rid]
                if b.occupants[rid] > 0 and not rs.transit:
                    tr = b.truth(rid)
                    pmv = tr["pmv"] if tr["pmv"] is not None else 0.0
                    acc[rid][0] += max(0.0, abs(pmv) - 0.5)
                    acc[rid][1] += max(0.0, 300.0 - (tr["daylight_lux"] + tr["electric_lux"])) / 300.0
                    acc[rid][2] += max(0.0, tr["co2"] - 1000.0) / 500.0
                    acc[rid][4] += 1
        n = self.n_steps_per_decision
        rewards = np.zeros(len(self.ids))
        info = {"energy_wh": 0.0, "discomfort": 0.0, "fallbacks": fallbacks}
        for i, rid in enumerate(self.ids):
            ov = b.specs[rid].controller_overrides
            e = self._ctrl_energy(rid) - e0[rid]
            e_max = (ov["ac_max_electric_w"] + ov["lighting_w_full"]) * n * CONTROL_DT / 3600.0
            c = acc[rid]
            occ_share = c[4] / n
            terms = (w["energy"] * e / e_max + w["comfort"] * c[0] / n + w["visual"] * c[1] / n
                     + w["iaq"] * c[2] / n + w["switch"] * c[3])
            rewards[i] = -terms
            info["energy_wh"] += e
            info["discomfort"] += c[0] / n
        self._last_obs = self._observe()
        done = b.time >= self.end
        return self._vectors(self._last_obs), rewards, done, info

    def _ctrl_energy(self, rid: str) -> float:
        s = self.b.physics[rid].state
        return s.e_hvac_wh + s.e_lighting_wh


class RoomControlEnv(_EnvBase):
    """gymnasium.Env for one room; the other 24 rooms follow the conventional schedule."""

    metadata = {"render_modes": []}

    def __init__(self, room_id: str = "f2_office_b2", scenario: str = "normal", days: float = 1.0, warmup_h: float = 6.0):
        if _gym is None:
            raise ImportError("gymnasium is required for RoomControlEnv (pip install -r requirements/train.txt)")
        self.observation_space = _spaces.Box(low=-OBS_CLIP, high=OBS_CLIP, shape=(N_OBS,), dtype=np.float64)
        self.action_space = _spaces.Discrete(N_ACT)
        self.room_id, self.scenario = room_id, scenario
        self.vec = BuildingVecEnv(days=days, warmup_h=warmup_h)

    def _others(self) -> np.ndarray:
        acts = []
        for rid in self.vec.ids:
            o = self.vec._last_obs[rid][0]
            d = self.vec.fallback.decide(o)
            light = d.light_action
            ac = "ECO" if d.hvac_action == "ECO" else ("LOW" if d.hvac_action == "LOW" else "NORMAL")
            acts.append(ACTIONS.index((light, ac)))
        return np.asarray(acts)

    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        super().reset(seed=seed)
        obs = self.vec.reset(seed=0 if seed is None else int(seed), scenario=self.scenario)
        self.idx = self.vec.ids.index(self.room_id)
        return obs[self.idx], {}

    def step(self, action):
        acts = self._others()
        acts[self.idx] = int(action)
        obs, rew, done, info = self.vec.step(acts)
        return obs[self.idx], float(rew[self.idx]), False, bool(done), info
