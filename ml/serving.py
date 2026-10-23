"""
Trained models inside the running system (edge brain), with shadow mode and drift checks.

  occupancy_twin_fusion   SHADOW: for every simulated room and control step, the learned PIR+CO2
                          model predicts occupancy next to the estimator that actually drives the
                          controller (the hand-built FusionEstimator).  Its output is logged and
                          scored against the simulator's true head count, never applied.
  thermal_h30             ACTIVE (display): predicted air temperature 30 min ahead for each
                          simulated room, labelled as a prediction; scored when the 30 min have
                          passed (live MAE against the simulator's true temperature).
  occupancy_rf            used by the 'threshold_rf' controller and shown for the real room
                          (twin/live.py loads it); its inputs from the real room feed a drift monitor.

Every model is loaded from the registry's active version (or, for a shadow model, the newest
version) as numpy-only JSON and must pass its self-test; a model that fails to load is
reported in status() with the error and simply not used - nothing is substituted.
"""
from __future__ import annotations

import math
import os
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from typing import Deque, Dict, List, Optional

import numpy as np

from ml.drift import DriftMonitor
from ml.online import OnlineFeatures, ThermalOnline, pir_features
from ml.portable import ModelError, Portable
from ml.registry import Registry

STORE_EVERY_S = 60.0


class _Loaded:
    def __init__(self, task: str, role: str, registry: Registry, newest: bool = False):
        self.task, self.role = task, role
        self.model: Optional[Portable] = None
        self.version: Optional[str] = None
        self.meta: Dict = {}
        self.error: Optional[str] = None
        try:
            if newest:
                vs = registry.versions(task)
                if not vs:
                    raise FileNotFoundError(f"no version of {task} in the registry")
                self.version = vs[-1]
            else:
                act = registry.active(task)
                if act is None:
                    raise FileNotFoundError(f"no active version of {task} (run python -m ml.registry init)")
                self.version = act["version"]
            path = os.path.join(registry.root, task, self.version)
            self.meta = registry.metadata(task, self.version)
            self.model = Portable.load(os.path.join(path, "model.json"))        # self-test included
            self.active = registry.active(task)
        except (FileNotFoundError, ModelError, OSError, KeyError, ValueError) as e:
            self.error = f"{type(e).__name__}: {e}"
            self.model = None

    def status(self) -> Dict:
        approved = None
        try:
            approved = (Registry().active(self.task) or {}).get("version")
        except Exception:
            pass
        return {"task": self.task, "role": self.role, "version": self.version, "loaded": self.model is not None,
                "error": self.error, "approved_version": approved,
                "features": self.meta.get("features"), "trained_utc": self.meta.get("trained_utc"),
                "provenance_of_training_data": (self.meta.get("training") or {}).get("provenance")}


class Confusion:
    def __init__(self):
        self.tp = self.fp = self.tn = self.fn = 0

    def add(self, pred: bool, truth: bool) -> None:
        if pred and truth:
            self.tp += 1
        elif pred:
            self.fp += 1
        elif truth:
            self.fn += 1
        else:
            self.tn += 1

    def summary(self) -> Dict:
        n = self.tp + self.fp + self.tn + self.fn
        prec = self.tp / (self.tp + self.fp) if self.tp + self.fp else None
        rec = self.tp / (self.tp + self.fn) if self.tp + self.fn else None
        f1 = 2 * prec * rec / (prec + rec) if prec and rec else None
        return {"n": n, "accuracy": (self.tp + self.tn) / n if n else None, "precision": prec, "recall": rec, "f1": f1}


class LiveModels:
    def __init__(self, registry: Optional[Registry] = None, store=None):
        self.registry = registry or Registry()
        self.store = store
        self.lock = threading.Lock()
        self.reload()

    def reload(self) -> None:
        with self.lock:
            self.shadow = _Loaded("occupancy_twin_fusion", "shadow", self.registry, newest=True)
            self.thermal = _Loaded("thermal_h30", "active", self.registry)
            self.rf = _Loaded("occupancy_rf", "active", self.registry)
            self.features = OnlineFeatures()
            self.thermal_online = ThermalOnline()
            self.conf_candidate, self.conf_active = Confusion(), Confusion()
            self.agree = self.compared = 0
            self.pending: Deque[tuple] = deque()
            self.thermal_err: Deque[float] = deque(maxlen=5000)
            self.latest_thermal: Dict[str, Dict] = {}
            self.errors: Deque[str] = deque(maxlen=20)
            self._step = 0
            self._last_store = 0.0
            ref = (self.rf.meta or {}).get("feature_reference") or {}
            self.drift_real = DriftMonitor(self.rf.meta.get("features", []), ref) if self.rf.model else None
            sref = (self.shadow.meta or {}).get("feature_reference") or {}
            self.drift_shadow = DriftMonitor(self.shadow.meta.get("features", []), sref, window=5000) if self.shadow.model else None
            self.loaded_at = datetime.now().isoformat(timespec="seconds")

    # ------------------------------------------------------------------ twin hook
    def observe_twin(self, twin, obs: Dict, measure: bool) -> None:
        """Called by LiveTwin after each control step with the step's observations (simulated rooms)."""
        if not measure:
            return
        try:
            with self.lock:
                ts = twin.ctrl.time
                last = getattr(self, "_last_twin_time", None)
                if last is not None and (ts <= last or (ts - last).total_seconds() > 600):
                    # the twin was reset or jumped: per-room histories no longer apply
                    self.features = OnlineFeatures()
                    self.thermal_online = ThermalOnline()
                    self.pending.clear()
                    self.latest_thermal.clear()
                self._last_twin_time = ts
                self._step += 1
                self._shadow_step(twin, obs)
                if self._step % 5 == 0:
                    self._thermal_step(twin, obs)
        except Exception as e:            # a model problem must never stop the control loop
            self.errors.append(f"{datetime.now().isoformat(timespec='seconds')} {type(e).__name__}: {e}")

    def _shadow_step(self, twin, obs: Dict) -> None:
        m = self.shadow.model
        if m is None:
            return
        rows, rids = [], []
        for rid, o in obs.items():
            f = self.features.update(rid, o.timestamp, {"Temperature": o.temperature, "Humidity": o.humidity,
                                                        "Light": o.light_lux, "CO2": o.co2,
                                                        "HumidityRatio": o.humidity_ratio})
            f.update(pir_features(o.seconds_since_motion))
            rows.append([f[k] for k in m.features])
            rids.append(rid)
        X = np.asarray(rows, dtype=float)
        p = m.predict(X)
        store_rows = []
        now = time.monotonic()
        do_store = self.store is not None and now - self._last_store >= STORE_EVERY_S
        for i, rid in enumerate(rids):
            o = obs[rid]
            truth = (o.true_occupants or 0) > 0
            last = twin.last.get(rid) or {}
            p_act = last.get("p_fusion")
            self.conf_candidate.add(p[i] >= 0.5, truth)
            if p_act is not None:
                self.conf_active.add(p_act >= 0.5, truth)
                self.compared += 1
                self.agree += (p[i] >= 0.5) == (p_act >= 0.5)
            if self.drift_shadow is not None and self._step % 5 == 0:
                self.drift_shadow.add(X[i])
            if do_store:
                ts = o.timestamp.isoformat(timespec="seconds")
                store_rows.append((ts, rid, "occupancy_twin_fusion", self.shadow.version, "shadow", float(p[i]), float(truth)))
                if p_act is not None:
                    store_rows.append((ts, rid, "fusion_estimator", "rule-based", "active", float(p_act), float(truth)))
        if store_rows:
            self.store.add_predictions(store_rows)
            self._last_store = now

    def _thermal_step(self, twin, obs: Dict) -> None:
        m = self.thermal.model
        if m is None:
            return
        b = twin.ctrl
        ts = b.time
        rows, rids = [], []
        for rid, o in obs.items():
            tr = b.truth(rid)
            cmd = twin.cmd["ctrl"][rid]
            rec = {"room_id": rid, "timestamp": o.timestamp, "meas_temperature_c": o.temperature,
                   "meas_humidity_pct": o.humidity, "meas_co2_ppm": o.co2, "meas_pir_seconds": o.seconds_since_motion,
                   "hvac_cmd": cmd["hvac"], "setpoint_c": cmd["sp"], "light_cmd": cmd["light"], "vent_boost": int(cmd["vent"]),
                   "hvac_w": tr["hvac_w"], "t_out_c": b.outdoor.temperature, "ghi_w_m2": b.outdoor.ghi}
            f = self.thermal_online.update(rec)
            rows.append([f[k] for k in m.features])
            rids.append(rid)
        X = np.asarray(rows, dtype=float)
        ok = np.isfinite(X[:, 0])
        pred = np.full(len(rids), np.nan)
        if ok.any():
            pred[ok] = X[ok, 0] + m.predict(X[ok])
        target = ts + timedelta(minutes=30)
        for i, rid in enumerate(rids):
            if math.isfinite(pred[i]):
                self.latest_thermal[rid] = {"predicted_c": round(float(pred[i]), 2), "for_time": target.isoformat(timespec="minutes"),
                                            "made_at": ts.isoformat(timespec="minutes"), "model": f"thermal_h30 {self.thermal.version}",
                                            "provenance": "prediction"}
                self.pending.append((target, rid, float(pred[i])))
        while self.pending and self.pending[0][0] <= ts + timedelta(seconds=1):
            t_target, rid, pv = self.pending.popleft()
            if abs((t_target - ts).total_seconds()) <= 61:
                self.thermal_err.append(pv - b.truth(rid)["t_air"])

    # ------------------------------------------------------------------ real room
    def observe_real(self, values: Dict[str, Optional[float]]) -> None:
        if self.drift_real is None:
            return
        with self.lock:
            self.drift_real.add([np.nan if values.get(f) is None else values[f] for f in self.drift_real.features])

    # ------------------------------------------------------------------ reporting
    def summary(self) -> Dict:
        with self.lock:
            err = np.asarray(self.thermal_err, dtype=float)
            return {
                "loaded_at": self.loaded_at,
                "models": [self.shadow.status(), self.thermal.status(), self.rf.status()],
                "shadow": {
                    "task": "occupancy_twin_fusion", "version": self.shadow.version,
                    "compared_room_steps": self.compared,
                    "agreement_with_active": self.agree / self.compared if self.compared else None,
                    "candidate_vs_truth": self.conf_candidate.summary(),
                    "active_vs_truth": self.conf_active.summary(),
                    "active": "FusionEstimator (rule-based PIR+CO2) - drives the controller",
                    "note": "simulated rooms; truth = simulated head count; the candidate is never applied",
                },
                "thermal": {"task": "thermal_h30", "version": self.thermal.version, "scored": int(len(err)),
                            "live_mae_c": float(np.mean(np.abs(err))) if len(err) else None,
                            "live_bias_c": float(np.mean(err)) if len(err) else None,
                            "basis": "prediction vs simulator true air temperature 30 min later"},
                "drift": {"real_room_inputs_vs_occupancy_rf_training": self.drift_real.report() if self.drift_real else None,
                          "simulated_inputs_vs_shadow_training": self.drift_shadow.report() if self.drift_shadow else None},
                "errors": list(self.errors),
            }

    def thermal_for(self, rid: str) -> Optional[Dict]:
        with self.lock:
            return self.latest_thermal.get(rid)
