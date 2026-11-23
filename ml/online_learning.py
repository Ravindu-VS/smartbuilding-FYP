"""
Continual learning while the system runs: the occupancy model of the simulated rooms retrains itself.

Every control step the learned-fusion features of the 25 simulated rooms are stored with their label (the
simulator's true head count > 0) and the hand-built estimate. At a fixed interval of simulated time a
background thread trains a new gradient-boosted candidate on the older part of the buffer and tests it,
forward in time, on the newest part (data the candidate never saw), next to the approved model and the
hand-built estimator on exactly the same rows. The candidate goes live only if

  * it beats the hand-built estimator (the registry's rule for occupancy_twin_fusion),
  * its F1 on the held-out window is at least the approved model's plus MIN_GAIN, and
  * it passes the registry's acceptance tests (portable self-test, latency, finite outputs, ...).

Then it is registered as a new version (metadata: data window, rows, metrics, comparison) and promoted;
the live estimators switch to it at the next control step. Otherwise the report is kept and the approved
model stays. Rollback: `python -m ml.registry rollback occupancy_twin_fusion`.

What does NOT learn online, on purpose:
  * Room 101 (real): there is no ground-truth occupancy label; training on the model's own predictions would
    only reinforce its mistakes. Its readings are stored with provenance for supervised retraining once
    labels exist (docs/RETRAINING.md).
  * PPO policy: reinforcement learning explores, i.e. tries bad actions on purpose. That stays in the
    simulator (rl/train.py) and passes the registry's acceptance test before deployment.
  * The multi-objective controller does adapt online already: its per-room occupancy prior is updated
    from every observation.

Training needs scikit-learn on the edge device; without it the learner reports "unavailable" and the
system keeps the approved model (nothing else changes).
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque
from datetime import datetime
from typing import Callable, Deque, Dict, List, Optional

import numpy as np

TASK = "occupancy_twin_fusion"
MIN_GAIN = 0.002                 # F1 points the candidate must add over the approved model on the same rows
RETRAIN_EVERY_SIM_H = 24.0       # simulated hours between training rounds
MIN_ROWS = 25 * 60 * 24          # one simulated day of the 25 rooms
MAX_ROWS = 25 * 60 * 24 * 5      # buffer: the last five simulated days
HOLDOUT_SHARE = 0.2              # newest 20 % of the buffer is the forward-in-time test window
KEEP_AUTO_VERSIONS = 5           # older automatically trained versions (not active) are pruned


def sklearn_available() -> Optional[str]:
    try:
        import sklearn  # noqa: F401
        return None
    except ImportError as e:
        return f"scikit-learn not installed ({e})"


class OnlineLearner:
    def __init__(self, features: List[str], on_promoted: Optional[Callable[[], None]] = None,
                 registry=None, retrain_every_h: float = RETRAIN_EVERY_SIM_H, min_rows: int = MIN_ROWS,
                 max_rows: int = MAX_ROWS):
        self.features = list(features)
        self.on_promoted = on_promoted
        self.registry = registry
        self.retrain_every_h, self.min_rows = retrain_every_h, min_rows
        self.X: Deque[np.ndarray] = deque(maxlen=max_rows)
        self.y: Deque[int] = deque(maxlen=max_rows)
        self.p_rule: Deque[float] = deque(maxlen=max_rows)
        self.p_active: Deque[float] = deque(maxlen=max_rows)
        self.ts: Deque[float] = deque(maxlen=max_rows)
        self.lock = threading.Lock()
        self.thread: Optional[threading.Thread] = None
        self.last_round_sim: Optional[datetime] = None
        self.rounds: Deque[Dict] = deque(maxlen=20)
        self.unavailable = sklearn_available()
        self.enabled = os.environ.get("ONLINE_LEARNING", "1") != "0"

    # ------------------------------------------------------------------ data
    def add(self, sim_time: datetime, X: np.ndarray, y: np.ndarray, p_rule: np.ndarray, p_active: np.ndarray) -> None:
        if not self.enabled:
            return
        with self.lock:
            t = sim_time.timestamp()
            for i in range(len(X)):
                self.X.append(np.asarray(X[i], dtype=float))
                self.y.append(int(y[i]))
                self.p_rule.append(float(p_rule[i]))
                self.p_active.append(float(p_active[i]))
                self.ts.append(t)
        if self.last_round_sim is None:
            self.last_round_sim = sim_time
        due = (sim_time - self.last_round_sim).total_seconds() >= self.retrain_every_h * 3600.0
        if due and len(self.y) >= self.min_rows and not self.busy and self.unavailable is None:
            self.last_round_sim = sim_time
            self.thread = threading.Thread(target=self._round_safe, name="online-learning", daemon=True)
            self.thread.start()

    def reset(self) -> None:
        """The twin restarted or jumped in time: old rows no longer describe the running building."""
        with self.lock:
            for d in (self.X, self.y, self.p_rule, self.p_active, self.ts):
                d.clear()
            self.last_round_sim = None

    @property
    def busy(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    # ------------------------------------------------------------------ training round
    def _round_safe(self) -> None:
        try:
            rep = self.train_round()
        except Exception as e:                    # never let training disturb the control loop
            rep = {"utc": _utc(), "result": "error", "error": f"{type(e).__name__}: {e}"}
        self.rounds.append(rep)

    def train_round(self) -> Dict:
        os.environ.setdefault("OMP_NUM_THREADS", "2")      # leave cores for the control loop on the Pi
        from sklearn.ensemble import HistGradientBoostingClassifier

        from ml.common import classification_metrics, feature_reference
        from ml.portable import export
        from ml.registry import Registry

        t0 = time.time()
        with self.lock:
            X = np.vstack(list(self.X))
            y = np.asarray(self.y, dtype=int)
            pr = np.asarray(self.p_rule, dtype=float)
            pa = np.asarray(self.p_active, dtype=float)
            ts = np.asarray(self.ts, dtype=float)
        cut = int(len(y) * (1 - HOLDOUT_SHARE))
        if len(np.unique(y[:cut])) < 2 or len(np.unique(y[cut:])) < 2:
            return {"utc": _utc(), "result": "skipped", "why": "training or test window has a single class"}
        model = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=31,
                                               l2_regularization=1.0, early_stopping=False, random_state=42)
        model.fit(X[:cut], y[:cut])
        pc = model.predict_proba(X[cut:])[:, 1]
        m_cand = classification_metrics(y[cut:], pc)
        m_rule = classification_metrics(y[cut:], pr[cut:])
        m_act = classification_metrics(y[cut:], pa[cut:])
        rep = {"utc": _utc(), "train_rows": int(cut), "test_rows": int(len(y) - cut),
               "train_window": [_iso(ts[0]), _iso(ts[cut - 1])], "test_window": [_iso(ts[cut]), _iso(ts[-1])],
               "f1": {"candidate": m_cand["f1"], "approved": m_act["f1"], "hand_built": m_rule["f1"]},
               "accuracy": {"candidate": m_cand["accuracy"], "approved": m_act["accuracy"],
                            "hand_built": m_rule["accuracy"]},
               "train_s": round(time.time() - t0, 1)}
        if m_cand["f1"] < m_act["f1"] + MIN_GAIN:
            rep["result"] = "kept approved model"
            rep["why"] = f"candidate F1 {m_cand['f1']:.4f} < approved {m_act['f1']:.4f} + {MIN_GAIN}"
            return rep
        reg = self.registry or Registry()
        nums = [int(v[1:]) for v in reg.versions(TASK)]
        version = f"v{(max(nums) + 1) if nums else 1}"
        sub = X[: cut: max(1, cut // 20000)]
        portable = export(model, self.features, "classification", 0.5, X_check=sub)
        act = reg.active(TASK)
        meta = {
            "kind": "classification", "target": "true simulated head count > 0", "features": self.features,
            "feature_set": "twin_fusion", "model_family": "hist_gbt", "estimator": "HistGradientBoostingClassifier",
            "threshold": 0.5, "seed": 42,
            "selection": "online learning round: forward-in-time test on the newest 20 % of the live buffer",
            "training": {"dataset": "live digital twin, simulated rooms (one row per room and control step)",
                         "rows": int(cut), "first": _iso(ts[0]), "last": _iso(ts[cut - 1]),
                         "positive_share": float(y[:cut].mean()), "provenance": "synthetic (live twin)",
                         "split": "chronological: older 80 % train, newest 20 % test"},
            "test_metrics": {"learned_fusion_hist_gbt": m_cand, "handbuilt_fusion_estimator": m_rule,
                             "approved_model_same_rows": m_act},
            "compare_active_on_same_data": {"version": act["version"] if act else None, "f1": m_act["f1"]},
            "feature_reference": feature_reference(X[:cut], self.features),
            "inference": {"runtime": "numpy only (ml/portable.py)", "scope": "simulated rooms only"},
            "training_code": "ml/online_learning.py OnlineLearner.train_round", "trained_utc": _utc(),
            "provenance": "prediction",
            "extra_limitations": "Trained on simulator labels: valid for the simulated rooms only (sim-to-real gap).",
        }
        card = (f"# Model card: {TASK} {version} (online learning)\n\n"
                f"- Trained while the system ran, on {cut} room-steps of the live twin\n"
                f"- Held-out (newest {len(y) - cut} room-steps): F1 {m_cand['f1']:.4f} vs approved "
                f"{m_act['f1']:.4f} vs hand-built {m_rule['f1']:.4f}\n- Simulated rooms only.\n")
        _write(reg.root, version, meta, card, portable)
        report = reg.evaluate(TASK, version)
        rep["version"] = version
        rep["acceptance_passed"] = report["passed"]
        if not report["passed"]:
            reg._log(TASK, {"action": "promotion_rejected", "version": version, "utc": _utc(), "report": report})
            rep["result"] = "rejected by acceptance tests"
            rep["failed_checks"] = [c["check"] for c in report["checks"] if not c["passed"]]
            return rep
        reg.promote(TASK, version, report=report)
        rep["result"] = f"promoted {version}"
        self._prune(reg)
        if self.on_promoted:
            self.on_promoted()
        return rep

    def _prune(self, reg) -> None:
        import json
        import shutil
        active = (reg.active(TASK) or {}).get("version")
        auto = []
        for v in reg.versions(TASK):
            try:
                with open(os.path.join(reg.root, TASK, v, "metadata.json"), encoding="utf-8") as f:
                    if "online_learning" in json.load(f).get("training_code", ""):
                        auto.append(v)
            except (OSError, ValueError):
                pass
        for v in auto[:-KEEP_AUTO_VERSIONS]:
            if v != active:
                shutil.rmtree(os.path.join(reg.root, TASK, v), ignore_errors=True)

    # ------------------------------------------------------------------ status
    def status(self) -> Dict:
        with self.lock:
            n = len(self.y)
        return {"enabled": self.enabled, "unavailable": self.unavailable, "buffer_rows": n,
                "min_rows": self.min_rows, "retrain_every_sim_h": self.retrain_every_h, "training_now": self.busy,
                "last_round_sim_time": self.last_round_sim.isoformat() if self.last_round_sim else None,
                "rounds": list(self.rounds),
                "scope": "simulated rooms (labels from the simulator); Room 101 has no labels, PPO trains offline"}


def _write(root: str, version: str, meta: Dict, card: str, portable: Dict) -> None:
    import json

    from ml.common import rounded, sha256_file
    d = os.path.join(root, TASK, version)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "model.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(portable, f, separators=(",", ":"))
    meta = dict(meta, task=TASK, version=version,
                files={"model.json": {"sha256": sha256_file(p), "bytes": os.path.getsize(p)}})
    with open(os.path.join(d, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(rounded(meta, 6), f, indent=2, default=str)
        f.write("\n")
    with open(os.path.join(d, "model_card.md"), "w", encoding="utf-8") as f:
        f.write(card)


def _utc() -> str:
    from ml.common import utc_now
    return utc_now()


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t).isoformat(timespec="minutes")
