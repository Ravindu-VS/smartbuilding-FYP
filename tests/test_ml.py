"""ML: features, train/test separation, metrics, portable models, registry, drift, failure handling."""
import json
import math
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from ml.common import classification_metrics, feature_reference, regression_metrics
from ml.drift import DriftMonitor
from ml.features import FEATURE_SETS, OnlineFeatures, add_features
from ml.portable import ModelError, Portable, export
from ml.registry import Registry

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UCI = os.path.join(ROOT, "data", "processed", "uci_occupancy.csv")


def _uci():
    if not os.path.exists(UCI):
        pytest.skip("run scripts/preprocess_datasets.py")
    return pd.read_csv(UCI, parse_dates=["timestamp"])


def test_online_features_equal_batch_features():
    d = _uci().iloc[2000:2600].copy()
    f = add_features(d)
    on = OnlineFeatures()
    rows = [on.update("r", r.timestamp.to_pydatetime(), {k: getattr(r, k) for k in FEATURE_SETS["env"]})
            for r in d.itertuples()]
    o = pd.DataFrame(rows)
    cols = sorted(set(sum(FEATURE_SETS.values(), [])))
    A, B = f[cols].to_numpy(float), o[cols].to_numpy(float)
    assert np.array_equal(np.isnan(A), np.isnan(B))
    assert np.nanmax(np.abs(A - B)) < 1e-9


def test_temporal_features_never_cross_a_gap():
    d = _uci()
    f = add_features(d)
    first_test_row = f[f.source_file == "datatest2.txt"].sort_values("timestamp").iloc[0]
    assert math.isnan(first_test_row["CO2_d5"]) and math.isnan(first_test_row["T_d15"])


def test_chronological_splits_do_not_overlap():
    from ml.occupancy import splits
    sp = splits(add_features(_uci()))
    assert sp["B_train"].timestamp.max() < sp["B_val"].timestamp.min()
    assert sp["B_trainval"].timestamp.max() < sp["B_test"].timestamp.min()
    assert not set(sp["B_trainval"].timestamp) & set(sp["B_test"].timestamp)


def test_classification_and_regression_metrics():
    m = classification_metrics([0, 0, 1, 1, 1], [0.1, 0.6, 0.7, 0.4, 0.9])
    assert m["confusion"] == {"tn": 1, "fp": 1, "fn": 1, "tp": 2}
    assert math.isclose(m["precision"], 2 / 3) and math.isclose(m["recall"], 2 / 3)
    r = regression_metrics([10, 10, 10, 10], [11, 9, 11, 9])
    assert math.isclose(r["mae"], 1.0) and math.isclose(r["rmse"], 1.0)
    assert math.isclose(r["cv_rmse_pct"], 10.0) and math.isclose(r["nmbe_pct"], 0.0)


def _toy(kind="classification", seed=0):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(600, 4))
    y = (X[:, 0] + 0.5 * X[:, 1] > 0).astype(int) if kind == "classification" else X[:, 0] * 2 + X[:, 2]
    return X, y


@pytest.mark.parametrize("name", ["logreg", "tree", "forest", "hgb", "mlp"])
def test_portable_export_matches_sklearn(name):
    from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.neural_network import MLPClassifier
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.tree import DecisionTreeClassifier
    X, y = _toy()
    X[::17, 2] = np.nan
    models = {
        "logreg": Pipeline([("imputer", SimpleImputer()), ("scaler", StandardScaler()), ("model", LogisticRegression())]),
        "tree": Pipeline([("imputer", SimpleImputer()), ("model", DecisionTreeClassifier(max_depth=5, random_state=0))]),
        "forest": Pipeline([("imputer", SimpleImputer()), ("model", RandomForestClassifier(20, random_state=0))]),
        "hgb": HistGradientBoostingClassifier(max_iter=30, random_state=0),
        "mlp": Pipeline([("imputer", SimpleImputer()), ("scaler", StandardScaler()),
                         ("model", MLPClassifier((8,), max_iter=300, random_state=0))]),
    }
    m = models[name].fit(X, y)
    spec = export(m, ["a", "b", "c", "d"], "classification", X_check=X)
    p = Portable(json.loads(json.dumps(spec)))          # survives a JSON round trip
    p.self_test()
    assert spec["export_check"]["max_abs_diff_vs_sklearn"] < 1e-9


def test_portable_input_validation():
    from sklearn.linear_model import Ridge
    X, y = _toy("regression")
    p = Portable(export(Ridge().fit(X, y), ["a", "b", "c", "d"], "regression", X_check=X))
    with pytest.raises(ModelError):
        p.predict(X[:, :3])                               # wrong feature count
    with pytest.raises(ModelError):
        p.predict(np.array([[np.inf, 0, 0, 0]]))          # infinite value
    with pytest.raises(ModelError):
        p.vector({"a": 1, "b": 2, "c": 3})                 # missing feature
    assert p.vector({"a": 1, "b": 2, "c": 3}, allow_missing=["d"]).shape == (4,)
    with pytest.raises(ModelError):
        Portable({"format": "smartbuilding-model/999"})   # incompatible version
    bad = export(Ridge().fit(X, y), ["a", "b", "c", "d"], "regression", X_check=X)
    bad["reference_samples"][0]["y"] += 1.0
    with pytest.raises(ModelError):
        Portable(bad).self_test()                         # tampered model refuses to load


def test_training_is_reproducible_with_fixed_seed():
    from ml.occupancy import candidates
    X, y = _toy()
    a = candidates()["random_forest"].fit(X, y).predict_proba(X)[:, 1]
    b = candidates()["random_forest"].fit(X, y).predict_proba(X)[:, 1]
    assert np.allclose(a, b, rtol=0, atol=1e-12)        # identical up to parallel summation order


def _tiny_registry(tmp_path, f1=0.9):
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from ml import common
    X, y = _toy()
    m = Pipeline([("imputer", SimpleImputer()), ("scaler", StandardScaler()), ("model", LogisticRegression())]).fit(X, y)
    spec = export(m, ["a", "b", "c", "d"], "classification", X_check=X)
    old = common.REGISTRY_DIR
    common.REGISTRY_DIR = str(tmp_path)
    try:
        v = common.next_version("occupancy_rf")
        common.write_artifact("occupancy_rf", v, {"features": ["a", "b", "c", "d"],
                                                  "test_metrics": {"B_test": {"f1": f1}}}, "card", portable=spec, sk_object=m)
    finally:
        common.REGISTRY_DIR = old
    return Registry(str(tmp_path)), v


def test_registry_acceptance_promote_rollback(tmp_path):
    reg, v1 = _tiny_registry(tmp_path, 0.90)
    rep = reg.evaluate("occupancy_rf", v1)
    assert rep["passed"], rep
    reg.promote("occupancy_rf", v1, report=rep)
    assert reg.active("occupancy_rf")["version"] == "v1"
    _, v2 = _tiny_registry(tmp_path, 0.95)
    reg.promote("occupancy_rf", v2)
    assert reg.active("occupancy_rf")["version"] == "v2"
    assert reg.rollback("occupancy_rf") == "v1"
    assert reg.active("occupancy_rf")["version"] == "v1"
    _, v3 = _tiny_registry(tmp_path, 0.50)               # fails the absolute F1 rule
    with pytest.raises(PermissionError):
        reg.promote("occupancy_rf", v3)
    assert reg.active("occupancy_rf")["version"] == "v1"
    hist = reg.load()["tasks"]["occupancy_rf"]["history"]
    assert [h["action"] for h in hist] == ["promote", "promote", "rollback", "promotion_rejected"]


def test_registry_detects_tampered_file(tmp_path):
    reg, v1 = _tiny_registry(tmp_path)
    p = os.path.join(str(tmp_path), "occupancy_rf", v1, "model.json")
    with open(p, "a") as f:
        f.write(" ")
    assert not reg.evaluate("occupancy_rf", v1)["passed"]


def test_drift_monitor():
    rng = np.random.default_rng(1)
    ref = feature_reference(rng.normal(size=(4000, 2)), ["x", "y"])
    m = DriftMonitor(["x", "y"], ref, min_rows=100)
    for r in rng.normal(size=(500, 2)):
        m.add(r)
    assert m.report()["status"] == "stable"
    m2 = DriftMonitor(["x", "y"], ref, min_rows=100)
    for r in rng.normal(loc=2.0, size=(500, 2)):
        m2.add(r)
    rep = m2.report()
    assert rep["status"] == "significant drift" and rep["features"]["x"]["out_of_range"] > 0


def test_registered_models_load_and_self_test():
    reg = Registry()
    tasks = reg.tasks()
    if not tasks:
        pytest.skip("no registry yet (python -m ml.occupancy etc.)")
    for t in tasks:
        if t == "ppo_policy":
            continue
        for v in reg.versions(t):
            p = Portable.load(os.path.join(reg.root, t, v, "model.json"))
            assert p.features == reg.metadata(t, v)["features"]


def test_model_failure_is_reported_not_replaced(tmp_path):
    from ml.serving import LiveModels
    lm = LiveModels(registry=Registry(str(tmp_path)))      # empty registry
    s = lm.summary()
    assert all(not m["loaded"] and m["error"] for m in s["models"])
    assert s["thermal"]["live_mae_c"] is None


def test_thermal_online_features_equal_batch(tmp_path, monkeypatch):
    from twin.runner import run_episode
    import csv, gzip
    from ml import thermal
    r = run_episode("mo", "normal", seed=8, start=datetime(2026, 3, 2), days=0.3, warmup_days=0.1, record_every=5)
    path = tmp_path / "t_seed8.csv.gz"
    with gzip.open(path, "wt", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(r.records[0]))
        w.writeheader()
        w.writerows(r.records)
    monkeypatch.setattr(thermal, "SYNTHETIC", str(tmp_path))
    df = thermal.twin_frame(["t_seed8"]).sort_values(["room_id", "timestamp"])
    raw = pd.read_csv(path).sort_values(["room_id", "timestamp"])
    on = thermal.ThermalOnline()
    rows = []
    for rec in raw.to_dict("records"):
        rec = {k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in rec.items()}
        rows.append(on.update(rec))
    A = df[thermal.FEATURES].to_numpy(float)
    B = pd.DataFrame(rows)[thermal.FEATURES].to_numpy(float)
    assert np.array_equal(np.isnan(A), np.isnan(B)) and np.nanmax(np.abs(A - B)) < 1e-9
