#!/usr/bin/env python3
"""
Building electricity prediction on real metered data (BDG2, Panther site offices).

    python -m ml.energy

Task: day-ahead hourly electricity (kWh per hour) of an office building.  A forecast for
day D is made at the end of day D-1, so load inputs are at least 24 h old (same hour
yesterday, two days ago, last week; mean of the previous day).  Weather inputs are the
observed weather of the target hour, i.e. a perfect-forecast assumption (as in the ASHRAE
GEPIII competition, which used the same weather files); real day-ahead forecasts would
add error.

Splits (chronological):  train 1 Jun 2016 - 31 May 2017 (a full year), test 1 Jun - 31 Dec 2017.
Two test views: the same buildings in the test period, and 5 buildings never seen in
training (group split by building) in the test period.
Targets are normalised per building by its mean training-period load (so one model
serves buildings of different size); metrics are reported in kWh after scaling back.

Baselines:  seasonal naive (same hour last week), persistence (same hour yesterday).
Models:     ridge regression and histogram gradient-boosted trees, each with and without
            load lags ("weather + calendar only" is the measurement-and-verification style
            baseline model of ASHRAE Guideline 14).
Metrics:    MAE, RMSE (kWh), CV(RMSE) and NMBE (%, ASHRAE Guideline 14 definitions).
An energy-prediction model predicts consumption; it does not save energy by itself.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Dict, List

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ml.common import (PROCESSED, feature_reference, git_commit, md_table, next_version, regression_metrics,  # noqa: E402
                       rounded, sha256_file, utc_now, versions, write_artifact)
from ml.portable import export                                                                      # noqa: E402

SEED = 42
TRAIN_END = pd.Timestamp("2017-06-01 00:00:00")
N_UNSEEN = 5
WEATHER = ["airTemperature", "dewTemperature", "cloudCoverage", "windSpeed"]
CALENDAR = ["hour_sin", "hour_cos", "dow_sin", "dow_cos", "weekend", "holiday", "month_sin", "month_cos"]
LAGS = ["lag24", "lag48", "lag168", "lag336", "same_hour_4wk", "mean_prev_day", "mean_prev_week", "temp_mean24"]
FEATURES_LAG = CALENDAR + WEATHER + LAGS
FEATURES_MV = CALENDAR + WEATHER + ["temp_mean24"]
REPORT = os.path.join(ROOT, "docs", "results", "energy.md")
RESULTS = os.path.join(ROOT, "experiments", "results", "exp04_energy")


def load() -> pd.DataFrame:
    path = os.path.join(PROCESSED, "bdg2_panther_office.csv")
    if not os.path.exists(path):
        raise SystemExit("data/processed/bdg2_panther_office.csv missing: run scripts/fetch_datasets.py and "
                         "scripts/preprocess_datasets.py")
    df = pd.read_csv(path, parse_dates=["timestamp"])
    from pandas.tseries.holiday import USFederalHolidayCalendar
    hol = set(USFederalHolidayCalendar().holidays(df.timestamp.min(), df.timestamp.max()).date)
    t = df["timestamp"]
    df["hour_sin"], df["hour_cos"] = np.sin(2 * np.pi * t.dt.hour / 24), np.cos(2 * np.pi * t.dt.hour / 24)
    df["dow_sin"], df["dow_cos"] = np.sin(2 * np.pi * t.dt.weekday / 7), np.cos(2 * np.pi * t.dt.weekday / 7)
    df["month_sin"], df["month_cos"] = np.sin(2 * np.pi * (t.dt.month - 1) / 12), np.cos(2 * np.pi * (t.dt.month - 1) / 12)
    df["weekend"] = (t.dt.weekday >= 5).astype(int)
    df["holiday"] = t.dt.date.isin(hol).astype(int)
    df = df.sort_values(["building_id", "timestamp"], kind="mergesort").reset_index(drop=True)
    # normalise by the building's mean load in the training period (computed on training rows only)
    scale = df[df.timestamp < TRAIN_END].groupby("building_id")["electricity_kwh"].mean()
    df["scale_kwh"] = df["building_id"].map(scale)
    df["y"] = df["electricity_kwh"] / df["scale_kwh"]
    g = df.groupby("building_id", sort=False)
    df["lag24"] = g["y"].shift(24)
    df["lag48"] = g["y"].shift(48)
    df["lag168"] = g["y"].shift(168)
    df["lag336"] = g["y"].shift(336)
    df["same_hour_4wk"] = (df["lag168"] + df["lag336"] + g["y"].shift(504) + g["y"].shift(672)) / 4.0
    # mean of the previous calendar day (known at the end of D-1)
    day = df["timestamp"].dt.floor("D")
    dmean = df.groupby([df["building_id"], day])["y"].mean()
    prev = pd.MultiIndex.from_arrays([df["building_id"], day - pd.Timedelta(days=1)])
    df["mean_prev_day"] = dmean.reindex(prev).values
    week = dmean.groupby(level=0).transform(lambda s: s.rolling(7, min_periods=4).mean())   # days D-6..D
    df["mean_prev_week"] = week.reindex(prev).values                                        # -> D-7..D-1
    df["temp_mean24"] = df.groupby("building_id", sort=False)["airTemperature"].transform(
        lambda s: s.rolling(24, min_periods=12).mean())
    return df


def models(seed: int = SEED):
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    return {
        "ridge": lambda: Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler()),
                                   ("model", Ridge(alpha=1.0))]),
        "hist_gbt": lambda: HistGradientBoostingRegressor(max_iter=500, learning_rate=0.05, max_leaf_nodes=31,
                                                          l2_regularization=1.0, early_stopping=False, random_state=seed),
    }


def metrics_kwh(d: pd.DataFrame, pred_norm: np.ndarray) -> Dict:
    y = d["electricity_kwh"].values
    p = pred_norm * d["scale_kwh"].values
    pooled = regression_metrics(y, p)
    per_b = []
    for b, idx in d.groupby("building_id").indices.items():
        per_b.append(regression_metrics(y[idx], p[idx]))
    pooled["median_building_cv_rmse_pct"] = float(np.median([m["cv_rmse_pct"] for m in per_b]))
    pooled["median_building_nmbe_pct"] = float(np.median([m["nmbe_pct"] for m in per_b]))
    pooled["buildings_cv_rmse_le_30pct"] = int(sum(m["cv_rmse_pct"] <= 30 for m in per_b))
    pooled["buildings"] = len(per_b)
    return pooled


def main(argv=None) -> int:
    os.makedirs(RESULTS, exist_ok=True)
    df = load()
    buildings = sorted(df.building_id.unique())
    rng = np.random.default_rng(SEED)
    unseen = sorted(rng.choice(buildings, size=N_UNSEEN, replace=False).tolist())
    seen = [b for b in buildings if b not in unseen]
    ok = df["electricity_kwh"].notna() & df["lag168"].notna()
    train = df[ok & (df.timestamp < TRAIN_END) & df.building_id.isin(seen)]
    test_seen = df[ok & (df.timestamp >= TRAIN_END) & df.building_id.isin(seen)]
    test_unseen = df[ok & (df.timestamp >= TRAIN_END) & df.building_id.isin(unseen)]
    views = {"test_seen_buildings": test_seen, "test_unseen_buildings": test_unseen}
    res: Dict[str, Dict] = {}
    for v, d in views.items():
        res.setdefault("seasonal_naive_lag168", {})[v] = metrics_kwh(d, d["lag168"].values)
        res.setdefault("persistence_lag24", {})[v] = metrics_kwh(d, d["lag24"].values)
    fitted = {}
    for name, make in models().items():
        for fs_name, feats in (("lags", FEATURES_LAG), ("weather_calendar", FEATURES_MV)):
            m = make()
            m.fit(train[feats].to_numpy(float), train["y"].values)
            key = f"{name}_{fs_name}"
            fitted[key] = (m, feats)
            for v, d in views.items():
                res.setdefault(key, {})[v] = metrics_kwh(d, m.predict(d[feats].to_numpy(float)))
    for k, r in res.items():
        print(f"  {k:28s} seen: CV(RMSE) {r['test_seen_buildings']['cv_rmse_pct']:6.2f}%  MAE {r['test_seen_buildings']['mae']:7.2f} kWh"
              f" | unseen: CV(RMSE) {r['test_unseen_buildings']['cv_rmse_pct']:6.2f}%")
    m, feats = fitted["hist_gbt_lags"]
    X = train[feats].to_numpy(float)
    portable = export(m, feats, "regression", X_check=X[:: max(1, len(X) // 20000)])
    task = "energy_dayahead"
    version = next_version(task)
    data_path = os.path.join(PROCESSED, "bdg2_panther_office.csv")
    meta = {
        "kind": "regression", "target": "hourly electricity / building mean training-period load (multiply by "
                                        "scale_kwh of the building to get kWh)",
        "features": feats, "model_family": "hist_gbt", "estimator": "HistGradientBoostingRegressor", "seed": SEED,
        "feature_code": "ml/energy.py load()",
        "training": {"dataset": "bdg2_panther_office (BDG2, CC BY-SA 4.0)", "file": "data/processed/bdg2_panther_office.csv",
                     "sha256": sha256_file(data_path), "rows": int(len(train)), "buildings": seen,
                     "period": [str(train.timestamp.min()), str(train.timestamp.max())], "provenance": "public_real"},
        "unseen_buildings": unseen, "test_metrics": res, "feature_reference": feature_reference(X, feats),
        "assumptions": "weather of the target hour is known (perfect forecast); load inputs >= 24 h old",
        "training_code": "ml/energy.py", "trained_utc": utc_now(), "git_commit": git_commit(),
        "dependencies": versions(), "provenance": "prediction",
    }
    rows = [{"method": k, "CV(RMSE) % seen": r["test_seen_buildings"]["cv_rmse_pct"],
             "NMBE % seen": r["test_seen_buildings"]["nmbe_pct"], "MAE kWh seen": r["test_seen_buildings"]["mae"],
             "CV(RMSE) % unseen": r["test_unseen_buildings"]["cv_rmse_pct"],
             "MAE kWh unseen": r["test_unseen_buildings"]["mae"]} for k, r in res.items()]
    card = (f"# Model card: {task} {version}\n\n- **Task**: day-ahead hourly electricity of an office building\n"
            f"- **Data**: BDG2 Panther site offices (Orlando FL area by metadata coordinates; humid subtropical), "
            f"{len(seen)} training buildings, {len(train)} rows, provenance public_real\n"
            f"- **Model**: histogram gradient-boosted trees; features: {', '.join(feats)}\n\n"
            + md_table(rows, list(rows[0].keys())) +
            "\n\n## Limitations\n\n- Observed weather used as if it were a perfect forecast.\n- University office buildings in one "
            "US site; not the project's building (the twin's rooms are simulated in Colombo).\n- Predicts consumption; "
            "savings must be measured separately (experiments 1 and 5).\n")
    write_artifact(task, version, meta, card, portable=portable, sk_object=m)
    print("registered", task, version)
    L = ["# Energy prediction results (BDG2, real metered data)", "",
         f"Generated by `python -m ml.energy` at {utc_now()} (commit {git_commit()}).", "",
         f"- Buildings: {len(buildings)} Panther offices; unseen in training: {', '.join(unseen)}",
         f"- Train {train.timestamp.min()} - {train.timestamp.max()} ({len(train)} rows); test from {TRAIN_END.date()} "
         f"(seen: {len(test_seen)} rows, unseen: {len(test_unseen)} rows)",
         "- ASHRAE Guideline 14 reference for hourly calibrated models: CV(RMSE) <= 30 %, |NMBE| <= 10 %", "",
         md_table(rows, list(rows[0].keys()), {k: ".2f" for k in rows[0]}), "",
         "Per-building view (seen buildings): median CV(RMSE) and the number of buildings meeting CV(RMSE) <= 30 %:", ""]
    L.append(md_table([{"method": k, "median CV(RMSE) %": r["test_seen_buildings"]["median_building_cv_rmse_pct"],
                        "median NMBE %": r["test_seen_buildings"]["median_building_nmbe_pct"],
                        "buildings <= 30 %": f"{r['test_seen_buildings']['buildings_cv_rmse_le_30pct']}/{r['test_seen_buildings']['buildings']}"}
                       for k, r in res.items()], ["method", "median CV(RMSE) %", "median NMBE %", "buildings <= 30 %"]))
    L += ["", f"Registered: `{task}` {version}"]
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(rounded({"results": res, "unseen_buildings": unseen, "registered": {task: version},
                           "generated_utc": utc_now(), "git_commit": git_commit()}), f, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
