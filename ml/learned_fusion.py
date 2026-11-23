"""
Learned PIR + CO2 occupancy fusion as a live estimator for the simulated rooms.

`occupancy_twin_fusion` (gradient-boosted trees on PIR history, CO2 level and trends and time of day,
trained on twin seed 31 under the multi-objective controller) scored F1 0.962 / balanced accuracy 0.959 on
twin seed 32 under the schedule controller, against 0.932 / 0.919 for the hand-built estimator
(docs/results/occupancy.md). This class puts the approved version in front of the hand-built
FusionEstimator:

* probability(obs)            -> the learned model's P(occupied) (the hand-built value if the model or an
                                 input is unavailable);
* confirmed_probability(obs)  -> the hand-built confirmed-PIR estimate, unchanged: the air conditioning
                                 keeps its confirmation rule, so a single false PIR trigger never starts it.

The hand-built estimator is still updated with every reading, so it can take over at any time.
`prepare(observations)` computes one batch for all rooms of a control step (the Pi runs 25 rooms per step);
probability() falls back to a single-row prediction for a room that was not prepared.
The real room (Room 101) does not use this class: the model learned the simulator's sensors, so the real
room keeps the hand-built estimator until labelled real data exists (docs/RETRAINING.md).
"""
from __future__ import annotations

import math
import os
from typing import Dict, Iterable, Optional, Tuple

import numpy as np

from ml.online import OnlineFeatures, pir_features
from ml.portable import ModelError, Portable
from ml.registry import Registry

TASK = "occupancy_twin_fusion"
_GENERATION = [0]          # bumped when online learning promotes a new version; estimators reload


def bump_generation() -> None:
    _GENERATION[0] += 1


def load_active_fusion(registry: Optional[Registry] = None) -> Tuple[Optional[Portable], Optional[str], Optional[str]]:
    """(model, version, error). Only the approved (active) version is ever used for control."""
    try:
        reg = registry or Registry()
        act = reg.active(TASK)
        if act is None:
            return None, None, f"no approved version of {TASK}"
        version = act["version"]
        return Portable.load(os.path.join(reg.root, TASK, version, "model.json")), version, None
    except (FileNotFoundError, ModelError, OSError, KeyError, ValueError) as e:
        return None, None, f"{type(e).__name__}: {e}"


class LearnedFusionEstimator:
    def __init__(self, fallback, model: Optional[Portable] = None, version: Optional[str] = None,
                 error: Optional[str] = None):
        self.fallback = fallback
        self.model, self.version, self.error = model, version, error
        self.features = OnlineFeatures()
        self._cache: Dict[str, Tuple[object, float, float]] = {}     # room -> (timestamp, p_learned, p_rule)
        self._generation = _GENERATION[0]
        self.name = f"LearnedFusion[{TASK} {version}]" if model is not None else getattr(fallback, "name", "Fusion")

    @classmethod
    def from_registry(cls, fallback, registry: Optional[Registry] = None) -> "LearnedFusionEstimator":
        model, version, error = load_active_fusion(registry)
        return cls(fallback, model, version, error)

    @property
    def active(self) -> bool:
        return self.model is not None

    def _row(self, obs) -> list:
        f = self.features.update(obs.room_id, obs.timestamp, {
            "Temperature": obs.temperature, "Humidity": obs.humidity, "Light": obs.light_lux,
            "CO2": obs.co2, "HumidityRatio": obs.humidity_ratio})
        f.update(pir_features(obs.seconds_since_motion))
        return [f[k] for k in self.model.features]

    def _maybe_reload(self) -> None:
        if self._generation != _GENERATION[0] and self.model is not None:
            self._generation = _GENERATION[0]
            model, version, error = load_active_fusion()
            if model is not None and model.features == self.model.features:
                self.model, self.version, self.error = model, version, None
                self.name = f"LearnedFusion[{TASK} {version}]"

    def prepare(self, observations: Iterable) -> None:
        """One batch for every room of this control step."""
        self._maybe_reload()
        obs = [o for o in observations if self._cache.get(o.room_id, (None,))[0] != o.timestamp]
        if not obs:
            return
        rule = [self.fallback.probability(o) for o in obs]
        if self.model is None:
            for o, pr in zip(obs, rule):
                self._cache[o.room_id] = (o.timestamp, pr, pr)
            return
        X = np.asarray([self._row(o) for o in obs], dtype=float)
        try:
            p = self.model.predict(X)
        except (ModelError, ValueError) as e:
            self.error = f"{type(e).__name__}: {e}"
            p = rule
        for o, pl, pr in zip(obs, p, rule):
            pl = float(pl)
            self._cache[o.room_id] = (o.timestamp, pl if math.isfinite(pl) else pr, pr)

    def probability(self, obs) -> float:
        c = self._cache.get(obs.room_id)
        if c is None or c[0] != obs.timestamp:
            self.prepare([obs])
            c = self._cache[obs.room_id]
        return c[1]

    def rule_probability(self, obs) -> float:
        """The hand-built estimate for the same reading (for comparison and explanations)."""
        c = self._cache.get(obs.room_id)
        if c is None or c[0] != obs.timestamp:
            self.prepare([obs])
            c = self._cache[obs.room_id]
        return c[2]

    def confirmed_probability(self, obs) -> float:
        return self.fallback.confirmed_probability(obs)

    def __getattr__(self, name):
        # anything else (prior learning, PIR helpers) comes from the hand-built estimator
        if name in ("fallback", "model", "features", "_cache", "_generation", "version", "error"):
            raise AttributeError(name)
        return getattr(self.fallback, name)
