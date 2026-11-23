"""Learned fusion as the live estimator, and continual learning of the occupancy model (simulated rooms)."""
import json
import os
from datetime import datetime, timedelta

import numpy as np
import pytest

from ml.learned_fusion import LearnedFusionEstimator
from twin.controllers import Observation

FEATS = ["pir_2min", "pir_10min", "pir_20min", "pir_log", "CO2", "CO2_d5", "CO2_d15", "CO2_std15",
         "T_d15", "HR_d15", "hour_sin", "hour_cos", "weekday"]


class _Rule:
    name = "rule"

    def __init__(self):
        self.calls = 0

    def probability(self, obs):
        self.calls += 1
        return 0.2

    def confirmed_probability(self, obs):
        return 0.1


class _Model:
    features = FEATS

    def predict(self, X):
        return np.where(np.asarray(X)[:, 0] > 0.5, 0.9, 0.05)          # PIR in the last 2 min -> occupied


def _obs(room, ts, pir_s):
    return Observation(room, "office", ts, 25.0, 50.0, 300.0, 600.0, 0.01, pir_s)


def test_learned_fusion_drives_probability_and_keeps_the_ac_rule():
    rule = _Rule()
    est = LearnedFusionEstimator(rule, _Model(), "v9")
    t = datetime(2026, 3, 2, 9, 0)
    est.prepare([_obs("a", t, 30.0), _obs("b", t, 5000.0)])
    assert est.probability(_obs("a", t, 30.0)) == pytest.approx(0.9)
    assert est.probability(_obs("b", t, 5000.0)) == pytest.approx(0.05)
    assert est.rule_probability(_obs("a", t, 30.0)) == pytest.approx(0.2)
    assert est.confirmed_probability(_obs("a", t, 30.0)) == pytest.approx(0.1)   # AC keeps the hand-built rule
    assert rule.calls == 2                       # prepared once per room and step, not again on lookup


def test_without_a_model_the_hand_built_estimate_is_used():
    est = LearnedFusionEstimator(_Rule(), None, None, "no approved version")
    assert est.probability(_obs("a", datetime(2026, 3, 2, 9, 0), 30.0)) == pytest.approx(0.2)
    assert not est.active


def _fake_registry(tmp_path):
    from ml.registry import Registry
    reg = Registry(str(tmp_path / "registry"))
    os.makedirs(os.path.join(reg.root, "occupancy_twin_fusion", "v1"), exist_ok=True)
    with open(os.path.join(reg.root, "occupancy_twin_fusion", "v1", "metadata.json"), "w") as f:
        json.dump({"features": FEATS, "test_metrics": {"learned_fusion_hist_gbt": {"f1": 0.5}}}, f)
    reg.save({"format": "smartbuilding-registry/1",
              "tasks": {"occupancy_twin_fusion": {"active": "v1", "history": []}}})
    return reg


def _data(n, rng):
    X = rng.normal(size=(n, len(FEATS)))
    y = (X[:, 0] + 0.3 * X[:, 4] > 0).astype(int)
    return X, y


def test_online_round_promotes_a_better_model_and_keeps_a_record(tmp_path):
    pytest.importorskip("sklearn")
    from ml.online_learning import OnlineLearner
    reg = _fake_registry(tmp_path)
    promoted = []
    lrn = OnlineLearner(FEATS, on_promoted=lambda: promoted.append(1), registry=reg, min_rows=10)
    rng = np.random.default_rng(1)
    X, y = _data(3000, rng)
    t0 = datetime(2026, 3, 2)
    with lrn.lock:
        for i in range(len(y)):
            lrn.X.append(X[i]); lrn.y.append(int(y[i])); lrn.ts.append((t0 + timedelta(minutes=i)).timestamp())
            lrn.p_rule.append(0.6 if X[i, 0] > 0.5 else 0.4)         # weak hand-built rule
            lrn.p_active.append(0.6 if X[i, 0] > 0.3 else 0.4)       # weak approved model
    rep = lrn.train_round()
    assert rep["f1"]["candidate"] > rep["f1"]["approved"]
    assert rep["result"] == "promoted v2", rep
    assert reg.active("occupancy_twin_fusion")["version"] == "v2" and promoted == [1]
    meta = reg.metadata("occupancy_twin_fusion", "v2")
    assert meta["compare_active_on_same_data"]["version"] == "v1"
    assert meta["training"]["rows"] == 2400 and meta["test_metrics"]["learned_fusion_hist_gbt"]["n"] == 600


def test_online_round_keeps_the_approved_model_when_the_candidate_is_not_better(tmp_path):
    pytest.importorskip("sklearn")
    from ml.online_learning import OnlineLearner
    reg = _fake_registry(tmp_path)
    lrn = OnlineLearner(FEATS, registry=reg, min_rows=10)
    rng = np.random.default_rng(2)
    X, y = _data(2000, rng)
    with lrn.lock:
        for i in range(len(y)):
            lrn.X.append(X[i]); lrn.y.append(int(y[i])); lrn.ts.append(float(i * 60))
            lrn.p_rule.append(float(y[i])); lrn.p_active.append(float(y[i]))     # approved model is perfect
    rep = lrn.train_round()
    assert rep["result"] == "kept approved model"
    assert reg.active("occupancy_twin_fusion")["version"] == "v1"
    assert reg.versions("occupancy_twin_fusion") == ["v1"]


def test_learning_is_disabled_without_scikit_learn_or_by_switch(monkeypatch):
    from ml.online_learning import OnlineLearner
    monkeypatch.setenv("ONLINE_LEARNING", "0")
    lrn = OnlineLearner(FEATS)
    lrn.add(datetime(2026, 3, 2), np.zeros((2, len(FEATS))), np.array([0, 1]), np.array([0.1, 0.9]), np.array([0.1, 0.9]))
    assert lrn.status()["buffer_rows"] == 0 and lrn.status()["enabled"] is False
