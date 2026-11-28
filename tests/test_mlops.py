"""
MLOps pipeline: data validation, leakage-free split, train/serve feature parity, MLflow training,
registry promotion gate and rollback.

    python -m pytest tests/test_mlops.py -q
"""
import os

import numpy as np
import pandas as pd
import pytest

from mlops import data as D

mlflow = pytest.importorskip("mlflow")


@pytest.fixture(scope="module")
def raw():
    return D.load()


def test_validation_passes_on_the_real_dataset(raw):
    df, rep = D.validate_and_clean(raw)
    assert rep.ok and rep.rows_in == 20560 and rep.rows_out == len(df) > 20000


def test_validation_stops_on_missing_column_and_bad_labels(raw):
    _, rep = D.validate_and_clean(raw.drop(columns=["Light"]))
    assert not rep.ok and "missing columns" in rep.errors[0]
    bad = raw.copy()
    bad.loc[bad.index[:10], "Occupancy"] = 3
    _, rep = D.validate_and_clean(bad)
    assert not rep.ok and "0/1" in rep.errors[0]


def test_cleaning_drops_out_of_range_and_duplicates(raw):
    bad = raw.head(1000).copy()
    bad.loc[bad.index[0], "Temperature"] = 99.0          # sensor fault
    bad.loc[bad.index[1], "Humidity"] = -5.0
    bad = pd.concat([bad, bad.iloc[[5]]])                 # duplicate timestamp
    df, rep = D.validate_and_clean(bad)
    assert rep.ok and len(df) == 998          # 1001 in: 2 out of range + 1 duplicate
    assert rep.dropped["Temperature outside 0.0..50.0"] == 1 and rep.dropped["duplicate timestamp"] == 1
    assert df["date"].is_monotonic_increasing


def test_split_is_chronological_disjoint_and_complete(raw):
    df = D.add_features(D.validate_and_clean(raw)[0])
    parts = D.split(df)
    assert sum(len(p) for p in parts.values()) == len(df)
    assert parts["train"]["date"].max() < parts["validation"]["date"].min()
    assert parts["validation"]["date"].max() < parts["test"]["date"].min()
    for p in parts.values():
        assert set(p[D.TARGET].unique()) == {0, 1}


def test_serving_features_match_training_features(raw):
    """The same reading must give the same feature vector in training (add_features) and serving."""
    df = D.add_features(D.validate_and_clean(raw)[0]).sample(200, random_state=3)
    for _, row in df.iterrows():
        live = D.features_from_reading({"timestamp": row["date"].isoformat(), "temperature": row["Temperature"],
                                        "humidity": row["Humidity"], "lux": row["Light"], "co2": row["CO2"]})
        for f in D.FEATURE_SETS["with_co2"]:
            tol = 0.01 if f == "HumidityRatio" else 1e-9          # recomputed from T and RH (Magnus)
            assert live[f] == pytest.approx(row[f], rel=tol, abs=1e-9), f


def test_live_timestamps_are_converted_to_building_time():
    # 10:41 UTC is 16:11 in Colombo: the time features must use the building's local time
    utc = D.features_from_reading({"timestamp": "2026-11-28T10:41:00+00:00", "temperature": 25, "humidity": 50, "lux": 100})
    local = D.features_from_reading({"timestamp": "2026-11-28T16:11:00", "temperature": 25, "humidity": 50, "lux": 100})
    assert utc["hour_sin"] == pytest.approx(local["hour_sin"]) and utc["hour_cos"] == pytest.approx(local["hour_cos"])
    assert D.local_time().tzinfo is not None


def test_humidity_ratio_formula_matches_the_dataset(raw):
    s = raw.sample(500, random_state=1)
    hr = np.array([D.humidity_ratio(t, h) for t, h in zip(s.Temperature, s.Humidity)])
    assert np.max(np.abs(hr - s.HumidityRatio) / s.HumidityRatio) < 0.01


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    return "sqlite:///" + os.path.join(str(tmp_path_factory.mktemp("mlflow")), "mlflow.db")


def test_train_registers_and_promotes_the_first_version(store):
    from mlops.train import train
    info = train(tracking_uri=store)
    assert info["model_version"] == "1"
    assert info["promotion"]["decision"] == "promoted"
    assert info["test"]["f1"] > 0.9 and info["test"]["n"] == 4880
    from mlflow import MlflowClient
    c = MlflowClient(store)
    run = c.get_run(info["run_id"])
    for tag in ("git_commit", "data_version", "feature_set", "version_python", "version_sklearn"):
        assert run.data.tags.get(tag), tag
    arts = {a.path for a in c.list_artifacts(info["run_id"])}
    assert {"data_validation.json", "data_splits.json", "feature_reference.json", "model_card.md"} <= arts
    assert str(c.get_model_version_by_alias("room-occupancy", "production").version) == "1"


def test_gate_keeps_production_when_the_challenger_is_not_better(store):
    from mlops.train import train
    info = train(tracking_uri=store)                        # same data, same model -> no gain
    assert info["model_version"] == "2"
    assert info["promotion"]["decision"] == "kept_production"
    from mlflow import MlflowClient
    c = MlflowClient(store)
    assert str(c.get_model_version_by_alias("room-occupancy", "production").version) == "1"
    assert str(c.get_model_version_by_alias("room-occupancy", "challenger").version) == "2"
    assert c.get_model_version("room-occupancy", "2").tags["gate_decision"] == "kept_production"


def test_promotion_and_rollback(store, monkeypatch):
    import mlops.promote as P
    from mlops.train import train
    monkeypatch.setattr(P, "MIN_GAIN", -1.0)                # force a promotion to test the rollback path
    info = train(tracking_uri=store)
    assert info["promotion"]["decision"] == "promoted"
    from mlflow import MlflowClient
    c = MlflowClient(store)
    assert str(c.get_model_version_by_alias("room-occupancy", "production").version) == "3"
    assert c.get_model_version("room-occupancy", "3").tags["replaced_production"] == "1"
    out = P.rollback("room-occupancy", store)
    assert out == {"production": "1", "previous_production": "3"}
    assert str(c.get_model_version_by_alias("room-occupancy", "production").version) == "1"


def test_manual_promotion_needs_a_reason_and_records_it(store):
    import mlops.promote as P
    with pytest.raises(ValueError):
        P.promote_manually("room-occupancy", "2", "", store)
    out = P.promote_manually("room-occupancy", "2", "feature-set change approved by the operator", store)
    assert out["production"] == "2"
    from mlflow import MlflowClient
    mv = MlflowClient(store).get_model_version("room-occupancy", "2")
    assert mv.tags["gate_decision"] == "promoted_manually" and "operator" in mv.tags["gate_reason"]


def test_gate_scores_each_model_with_its_own_features(store, monkeypatch):
    """Changing a feature set in the code must not break scoring of the current production model."""
    from mlops import data as D2
    from mlops.train import train
    monkeypatch.setitem(D2.FEATURE_SETS, "room101", D2.FEATURE_SETS["room101"][:-1])   # drop hour_cos
    info = train(tracking_uri=store)
    assert info["promotion"]["production_test"] is not None          # the old champion was scored
    assert info["promotion"]["decision"] in ("promoted", "kept_production", "rejected")
