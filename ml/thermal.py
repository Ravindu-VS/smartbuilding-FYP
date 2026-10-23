#!/usr/bin/env python3
"""
Room temperature prediction 15 and 30 minutes ahead.

    python -m ml.thermal

Two evaluations, kept apart:
  1. Digital twin (synthetic).  The twin's 25 rooms, 5-minute rows from
     scripts/make_synthetic_corpus.sh.  Training: seeds 11-16 (normal, hot, cool, high and
     low occupancy; MO and schedule controllers).  Test: unseen seeds 21-23, including a
     scenario never seen in training (all ACs at 60 % capacity).  Ground truth is the
     simulator's true air temperature at t + h ("simulator ground truth").
  2. UCI office (real).  The same method on the measured temperatures of the UCI office
     (no HVAC information in that dataset), chronological split as in ml/occupancy.py.
     Ground truth is the measured temperature at t + h.

Inputs (all known at decision time t): the measured temperature now and 5/10/15 min ago
(and its trends), measured humidity and CO2 (and CO2 trend, an occupancy proxy), PIR
seconds since motion, the AC command that will be held (mode, set-point), the AC sub-meter
power and the time since the AC command last changed, light command, boost fan, outdoor
temperature and global irradiance (from a weather service), time of day, and the room's
static design data (floor area, AC capacity, window area).  No future reading is an input.

Baselines:
  persistence     T(t + h) = T(t)
  grey-box 1R1C   per room and per AC state (on / off): dT = a (T_target - T) + b + c GHI,
                  T_target = set-point when the AC runs, outdoor temperature when it is off;
                  coefficients fitted by least squares on the training rows.
Models: ridge regression and histogram gradient-boosted trees on the temperature change.
"""
from __future__ import annotations

import glob
import math
from datetime import datetime
import json
import os
import sys
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ml.common import (PROCESSED, SYNTHETIC, feature_reference, git_commit, md_table, next_version,  # noqa: E402
                       regression_metrics, rounded, sha256_file, utc_now, versions, write_artifact)
from ml.features import add_features                                                               # noqa: E402
from ml.portable import export                                                                      # noqa: E402

SEED = 42
HORIZONS_MIN = (15, 30)
TRAIN_FILES = ["normal_seed11_mo", "normal_seed12_schedule", "hot_weather_seed13_mo", "cool_weather_seed14_mo",
               "high_occupancy_seed15_mo", "low_occupancy_seed16_schedule"]
TEST_FILES = ["normal_seed21_mo", "hot_weather_seed22_schedule", "hvac_reduced_seed23_mo"]
FEATURES = ["T", "T_lag5", "T_lag10", "T_lag15", "dT5", "dT15", "RH", "CO2", "CO2_d15", "pir_recent", "ac_on",
            "ac_low", "setpoint_gap", "ac_power_frac", "min_since_hvac_change", "light_level", "vent", "t_out",
            "t_out_gap", "ghi", "hour_sin", "hour_cos", "area_m2", "ac_w_per_m3", "window_m2"]
UNITS = {"T": "degC", "T_lag5": "degC", "T_lag10": "degC", "T_lag15": "degC", "RH": "%", "CO2": "ppm",
         "CO2_d15": "ppm/15min", "pir_recent": "0/1 (motion in last 10 min)", "ac_on": "0/1 (NORMAL)",
         "ac_low": "0/1 (LOW = 27 C setback)", "setpoint_gap": "K (T - active set-point, 0 when AC off)",
         "dT5": "K (T - T 5 min ago)", "dT15": "K (T - T 15 min ago)",
         "ac_power_frac": "AC sub-meter power / AC maximum electric power", "min_since_hvac_change": "min (capped at 120)",
         "light_level": "0/0.4/1", "vent": "0/1", "t_out": "degC", "t_out_gap": "K (t_out - T)",
         "ghi": "W/m2", "hour_sin": "-", "hour_cos": "-", "area_m2": "m2", "ac_w_per_m3": "W/m3", "window_m2": "m2"}
UCI_FEATURES = ["T", "T_lag5", "T_lag10", "T_lag15", "dT5", "dT15", "RH", "CO2", "CO2_d15", "Light", "hour_sin",
                "hour_cos", "weekday"]
REPORT = os.path.join(ROOT, "docs", "results", "thermal.md")
RESULTS = os.path.join(ROOT, "experiments", "results", "exp03_thermal")
LIGHT = {"OFF": 0.0, "DIM": 0.4, "ON": 1.0}


def _room_static() -> Dict[str, Dict[str, float]]:
    from twin.spec import build_spec
    return {r.room_id: {"area_m2": r.area, "ac_w_per_m3": r.physics_params["ac_cool_capacity_w"] / r.volume,
                        "window_m2": r.window_area, "ac_max_electric_w": r.controller_overrides["ac_max_electric_w"]}
            for r in build_spec()}


def twin_frame(names: List[str]) -> pd.DataFrame:
    static = _room_static()
    parts = []
    for n in names:
        path = os.path.join(SYNTHETIC, n + ".csv.gz")
        if not os.path.exists(path):
            raise SystemExit(f"{path} missing: run scripts/make_synthetic_corpus.sh")
        d = pd.read_csv(path, parse_dates=["timestamp"])
        d["file"] = n
        parts.append(d)
    df = pd.concat(parts, ignore_index=True).sort_values(["file", "room_id", "timestamp"], kind="mergesort")
    g = df.groupby(["file", "room_id"], sort=False)
    df["T"] = g["meas_temperature_c"].transform(lambda s: s.ffill(limit=2))   # short dropouts held (as InputGuard)
    for k in (5, 10, 15):
        df[f"T_lag{k}"] = g["T"].shift(k // 5)
    df["dT5"] = df["T"] - df["T_lag5"]
    df["dT15"] = df["T"] - df["T_lag15"]
    df["ac_power_frac"] = df["hvac_w"] / df["room_id"].map(lambda r: static[r]["ac_max_electric_w"])
    # (pandas 3 keeps NaN through astype(str), so missing values are filled before building the keys)
    cmd = df["hvac_cmd"].fillna("?").astype(str) + "|" + df["setpoint_c"].fillna(-1.0).astype(str)
    prev = g["hvac_cmd"].shift(1).fillna("start").astype(str) + "|" + g["setpoint_c"].shift(1).fillna(-1.0).astype(str)
    changed = (cmd != prev).astype(int)
    block = changed.groupby([df["file"], df["room_id"]]).cumsum()
    df["min_since_hvac_change"] = (df.groupby([df["file"], df["room_id"], block]).cumcount() * 5).clip(upper=120)
    df["RH"] = df["meas_humidity_pct"]
    df["CO2"] = df["meas_co2_ppm"]
    df["CO2_d15"] = df["CO2"] - g["CO2"].shift(3)
    df["pir_recent"] = (df["meas_pir_seconds"].fillna(1e9) <= 600).astype(int)
    df["ac_on"] = (df["hvac_cmd"] == "NORMAL").astype(int)
    df["ac_low"] = (df["hvac_cmd"] == "LOW").astype(int)
    sp = np.where(df["hvac_cmd"] == "NORMAL", df["setpoint_c"], np.where(df["hvac_cmd"] == "LOW", 27.0, np.nan))
    df["setpoint_gap"] = np.where(np.isnan(sp), 0.0, df["T"] - sp)
    df["light_level"] = df["light_cmd"].map(LIGHT)
    df["vent"] = df["vent_boost"]
    df["t_out"] = df["t_out_c"]
    df["t_out_gap"] = df["t_out"] - df["T"]
    df["ghi"] = df["ghi_w_m2"]
    h = df["timestamp"].dt.hour + df["timestamp"].dt.minute / 60.0
    df["hour_sin"], df["hour_cos"] = np.sin(2 * np.pi * h / 24), np.cos(2 * np.pi * h / 24)
    for k in ("area_m2", "ac_w_per_m3", "window_m2"):
        df[k] = df["room_id"].map(lambda r: static[r][k])
    df["sp_active"] = sp
    for hmin in HORIZONS_MIN:
        df[f"y_true_{hmin}"] = g["t_air_c"].shift(-hmin // 5)            # simulator ground truth
        df[f"y_meas_{hmin}"] = g["meas_temperature_c"].shift(-hmin // 5)  # what the sensor will read
        df[f"cmd_held_{hmin}"] = (g["hvac_cmd"].shift(-hmin // 5) == df["hvac_cmd"]).astype(int)
    return df


class GreyBox:
    """Per room and AC state: dT_h = a (T_target - T) + b + c GHI (least squares)."""

    def __init__(self, horizon_min: int):
        self.h = horizon_min
        self.coef: Dict[Tuple[str, int], np.ndarray] = {}

    @staticmethod
    def _design(d: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        on = (d["ac_on"] + d["ac_low"]).values > 0
        target = np.where(on, d["sp_active"].values, d["t_out"].values)
        A = np.column_stack([target - d["T"].values, np.ones(len(d)), d["ghi"].values / 1000.0])
        return A, on

    def fit(self, d: pd.DataFrame, y: np.ndarray) -> "GreyBox":
        A, on = self._design(d)
        dy = y - d["T"].values
        for rid in d["room_id"].unique():
            for state in (0, 1):
                m = (d["room_id"].values == rid) & (on == bool(state)) & np.isfinite(dy) & np.isfinite(A).all(1)
                if m.sum() >= 20:
                    self.coef[(rid, state)] = np.linalg.lstsq(A[m], dy[m], rcond=None)[0]
        return self

    def predict(self, d: pd.DataFrame) -> np.ndarray:
        A, on = self._design(d)
        out = d["T"].values.astype(float).copy()
        for i, (rid, state) in enumerate(zip(d["room_id"].values, on.astype(int))):
            c = self.coef.get((rid, state))
            if c is not None and np.isfinite(A[i]).all():
                out[i] += A[i] @ c
        return out


def models(seed: int = SEED):
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    return {
        "ridge": Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler()),
                           ("model", Ridge(alpha=1.0))]),
        "hist_gbt": HistGradientBoostingRegressor(max_iter=400, learning_rate=0.05, max_leaf_nodes=31,
                                                  l2_regularization=1.0, early_stopping=False, random_state=seed),
    }


def evaluate_twin() -> Dict:
    tr = twin_frame(TRAIN_FILES)
    te = twin_frame(TEST_FILES)
    out: Dict = {"horizons": {}, "fitted": {}}
    for hmin in HORIZONS_MIN:
        ytr, yte = f"y_true_{hmin}", f"y_true_{hmin}"
        trm = tr[np.isfinite(tr[ytr]) & np.isfinite(tr["T"])]
        tem = te[np.isfinite(te[yte]) & np.isfinite(te["T"])]
        res = {}
        preds = {"persistence": tem["T"].values}
        gb = GreyBox(hmin).fit(trm, trm[ytr].values)
        preds["greybox_1r1c"] = gb.predict(tem)
        fitted = {}
        for name, m in models().items():
            m.fit(trm[FEATURES].to_numpy(float), (trm[ytr] - trm["T"]).values)
            preds[name] = tem["T"].values + m.predict(tem[FEATURES].to_numpy(float))
            fitted[name] = m
        for name, p in preds.items():
            r = {"all": regression_metrics(tem[yte].values, p)}
            for f in TEST_FILES:
                mk = (tem["file"] == f).values
                r[f] = regression_metrics(tem[yte].values[mk], p[mk])
            held = (tem[f"cmd_held_{hmin}"] == 1).values
            r["command_held"] = regression_metrics(tem[yte].values[held], p[held])
            r["vs_measured_reading"] = regression_metrics(tem[f"y_meas_{hmin}"].values, p)
            res[name] = r
            print(f"  twin h={hmin:2d} {name:13s} MAE {r['all']['mae']:.3f} RMSE {r['all']['rmse']:.3f} "
                  f"(unseen scenario hvac_reduced MAE {r['hvac_reduced_seed23_mo']['mae']:.3f})")
        out["horizons"][hmin] = res
        out["fitted"][hmin] = (fitted, trm)
    return out


def evaluate_uci() -> Dict:
    path = os.path.join(PROCESSED, "uci_occupancy.csv")
    df = add_features(pd.read_csv(path, parse_dates=["timestamp"])).sort_values("timestamp")
    t = df["timestamp"]
    seg = (t.diff().dt.total_seconds().fillna(0) > 300).cumsum()
    df["T"] = df["Temperature"]
    tv = t.values.astype("datetime64[ns]").astype(np.int64)
    temp = df["Temperature"].values

    def at_offset(minutes):
        target = tv + int(minutes * 60e9)
        pos = np.searchsorted(tv, target, side="right") - 1 if minutes < 0 else np.searchsorted(tv, target, side="left")
        pos_c = np.clip(pos, 0, len(tv) - 1)
        ok = (pos >= 0) & (pos < len(tv)) & (seg.values[pos_c] == seg.values) & \
             (np.abs(tv[pos_c] - target) <= 90e9)
        return np.where(ok, temp[pos_c], np.nan)

    for k in (5, 10, 15):
        df[f"T_lag{k}"] = at_offset(-k)
    df["dT5"] = df["T"] - df["T_lag5"]
    df["dT15"] = df["T"] - df["T_lag15"]
    df["RH"] = df["Humidity"]
    for hmin in HORIZONS_MIN:
        df[f"y_{hmin}"] = at_offset(hmin)
    from ml.occupancy import splits
    sp = splits(df)
    out = {}
    for hmin in HORIZONS_MIN:
        y = f"y_{hmin}"
        tr = sp["B_trainval"][np.isfinite(sp["B_trainval"][y])]
        te = sp["B_test"][np.isfinite(sp["B_test"][y])]
        res = {"persistence": regression_metrics(te[y], te["T"])}
        for name, m in models().items():
            m.fit(tr[UCI_FEATURES].to_numpy(float), (tr[y] - tr["T"]).values)
            res[name] = regression_metrics(te[y], te["T"].values + m.predict(te[UCI_FEATURES].to_numpy(float)))
        for name, r in res.items():
            print(f"  UCI  h={hmin:2d} {name:13s} MAE {r['mae']:.4f} RMSE {r['rmse']:.4f}")
        out[hmin] = res
    return out


def main(argv=None) -> int:
    os.makedirs(RESULTS, exist_ok=True)
    twin = evaluate_twin()
    uci = evaluate_uci()
    registered = {}
    for hmin in HORIZONS_MIN:
        fitted, trm = twin["fitted"][hmin]
        m = fitted["hist_gbt"]
        X = trm[FEATURES].to_numpy(float)
        portable = export(m, FEATURES, "regression", X_check=X[:: max(1, len(X) // 20000)])
        task = f"thermal_h{hmin}"
        version = next_version(task)
        res = twin["horizons"][hmin]
        meta = {
            "kind": "regression", "target": f"room air temperature change over the next {hmin} min (degC); "
                                            f"prediction = current measured temperature + model output",
            "horizon_min": hmin, "features": FEATURES, "feature_units": {f: UNITS[f] for f in FEATURES},
            "feature_code": "ml/thermal.py twin_frame()", "model_family": "hist_gbt",
            "estimator": "HistGradientBoostingRegressor", "seed": SEED,
            "training": {"dataset": "synthetic twin corpus", "files": TRAIN_FILES, "rows": int(len(trm)),
                         "sha256": {f: sha256_file(os.path.join(SYNTHETIC, f + ".csv.gz")) for f in TRAIN_FILES},
                         "provenance": "synthetic"},
            "test_files": TEST_FILES, "feature_reference": feature_reference(X, FEATURES),
            "test_metrics": {k: {"all": v["all"], "hvac_reduced_unseen": v["hvac_reduced_seed23_mo"]} for k, v in res.items()},
            "real_data_check_uci": uci[hmin],
            "training_code": "ml/thermal.py", "trained_utc": utc_now(), "git_commit": git_commit(),
            "dependencies": versions(), "provenance": "prediction",
        }
        rows = [{"method": k, "MAE": v["all"]["mae"], "RMSE": v["all"]["rmse"],
                 "unseen hvac_reduced MAE": v["hvac_reduced_seed23_mo"]["mae"]} for k, v in res.items()]
        card = (f"# Model card: {task} {version}\n\n- **Task**: room air temperature {hmin} min ahead (simulated rooms)\n"
                f"- **Model**: histogram gradient-boosted trees on the temperature change\n"
                f"- **Features**: {', '.join(FEATURES)}\n- **Training data**: synthetic twin corpus ({len(trm)} rows; "
                f"provenance synthetic)\n- **Test**: unseen seeds and an unseen scenario; ground truth = simulator air temperature\n\n"
                + md_table(rows, ["method", "MAE", "RMSE", "unseen hvac_reduced MAE"]) +
                "\n\n## Limitations\n\n- Trained on simulator output only: it learns the 5R1C model's behaviour, not a real "
                "building's. Its real-data check on the UCI office (no HVAC data there) is in docs/results/thermal.md.\n"
                "- Assumes the AC command at time t is held for the horizon.\n")
        write_artifact(task, version, meta, card, portable=portable, sk_object=m)
        registered[task] = version
        print("registered", task, version)
    write_report(twin, uci, registered)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(rounded({"twin": {h: twin["horizons"][h] for h in HORIZONS_MIN}, "uci": uci,
                           "registered": registered, "generated_utc": utc_now(), "git_commit": git_commit()}), f, indent=2)
    return 0


def write_report(twin: Dict, uci: Dict, registered: Dict) -> None:
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    L = ["# Thermal prediction results", "", f"Generated by `python -m ml.thermal` at {utc_now()} (commit {git_commit()}).", "",
         "## 1. Digital twin (synthetic; ground truth = simulator air temperature)", "",
         f"Training files: {', '.join(TRAIN_FILES)}. Test files (unseen seeds): {', '.join(TEST_FILES)}; "
         "`hvac_reduced` is a scenario not present in training.", ""]
    for h in HORIZONS_MIN:
        rows = []
        for name, r in twin["horizons"][h].items():
            rows.append({"method": name, "MAE all": r["all"]["mae"], "RMSE all": r["all"]["rmse"],
                         "MAE normal": r["normal_seed21_mo"]["mae"], "MAE hot (schedule)": r["hot_weather_seed22_schedule"]["mae"],
                         "MAE hvac_reduced (unseen)": r["hvac_reduced_seed23_mo"]["mae"],
                         "MAE cmd held": r["command_held"]["mae"], "MAE vs future reading": r["vs_measured_reading"]["mae"]})
        L += [f"### Horizon {h} min (degC)", "", md_table(rows, list(rows[0].keys())), ""]
    L += ["## 2. UCI office (real measurements; no HVAC data in this dataset)", "",
          "Train: 2-10 Feb 2015; test: 11-18 Feb 2015 (as protocol B in ml/occupancy.py). Ground truth = measured temperature.", ""]
    for h in HORIZONS_MIN:
        rows = [{"method": k, "MAE": v["mae"], "RMSE": v["rmse"], "R2": v["r2"]} for k, v in uci[h].items()]
        L += [f"### Horizon {h} min (degC)", "", md_table(rows, ["method", "MAE", "RMSE", "R2"], {"MAE": ".4f", "RMSE": ".4f"}), ""]
    L += ["## Registered", ""] + [f"- `{t}` {v}" for t, v in registered.items()]
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    sys.exit(main())


class ThermalOnline:
    """
    The thermal-model features computed live, one 5-minute sample at a time, exactly as
    twin_frame() computes them from a table (checked by tests/test_ml.py).  Feed it every
    5 minutes with a record in the generator's format (twin/runner.py _record keys).
    """

    def __init__(self):
        self.static = _room_static()
        self.hist: Dict[str, List[Dict]] = {}

    def update(self, rec: Dict) -> Dict[str, float]:
        rid = rec["room_id"]
        h = self.hist.setdefault(rid, [])
        t_meas = rec.get("meas_temperature_c")
        if t_meas is None or (isinstance(t_meas, float) and math.isnan(t_meas)):
            # forward fill for at most two samples, as twin_frame does
            prev = [x for x in h[-2:] if x["_T_raw"] is not None]
            t_val = h[-1]["T"] if h and len(prev) > 0 and _ffill_ok(h) else float("nan")
        else:
            t_val = float(t_meas)
        sp = rec["setpoint_c"] if rec["hvac_cmd"] == "NORMAL" else (27.0 if rec["hvac_cmd"] == "LOW" else None)
        cmd_key = f"{rec['hvac_cmd']}|{rec['setpoint_c']}"
        since = 0
        if h and h[-1]["_cmd"] == cmd_key:
            since = min(120, h[-1]["min_since_hvac_change_raw"] + 5)
        co2 = rec.get("meas_co2_ppm")
        co2 = float("nan") if co2 is None else float(co2)

        def lag(key, k):
            return h[-k][key] if len(h) >= k else float("nan")

        ts = rec["timestamp"] if isinstance(rec["timestamp"], datetime) else datetime.fromisoformat(rec["timestamp"])
        hr = ts.hour + ts.minute / 60.0
        st = self.static[rid]
        f = {"T": t_val, "T_lag5": lag("T", 1), "T_lag10": lag("T", 2), "T_lag15": lag("T", 3)}
        f["dT5"], f["dT15"] = t_val - f["T_lag5"], t_val - f["T_lag15"]
        f["RH"] = float("nan") if rec.get("meas_humidity_pct") is None else float(rec["meas_humidity_pct"])
        f["CO2"] = co2
        f["CO2_d15"] = co2 - lag("CO2", 3)
        pir = rec.get("meas_pir_seconds")
        f["pir_recent"] = 1.0 if (pir is not None and not (isinstance(pir, float) and math.isnan(pir)) and pir <= 600) else 0.0
        f["ac_on"] = 1.0 if rec["hvac_cmd"] == "NORMAL" else 0.0
        f["ac_low"] = 1.0 if rec["hvac_cmd"] == "LOW" else 0.0
        f["setpoint_gap"] = 0.0 if sp is None else t_val - sp
        f["ac_power_frac"] = rec["hvac_w"] / st["ac_max_electric_w"]
        f["min_since_hvac_change"] = float(since)
        f["light_level"] = LIGHT[rec["light_cmd"]]
        f["vent"] = float(rec["vent_boost"])
        f["t_out"] = float(rec["t_out_c"])
        f["t_out_gap"] = f["t_out"] - t_val
        f["ghi"] = float(rec["ghi_w_m2"])
        f["hour_sin"], f["hour_cos"] = math.sin(2 * math.pi * hr / 24), math.cos(2 * math.pi * hr / 24)
        f["area_m2"], f["ac_w_per_m3"], f["window_m2"] = st["area_m2"], st["ac_w_per_m3"], st["window_m2"]
        h.append({"T": t_val, "_T_raw": t_meas, "CO2": co2, "_cmd": cmd_key, "min_since_hvac_change_raw": since})
        if len(h) > 6:
            del h[0]
        return f


def _ffill_ok(h: List[Dict]) -> bool:
    """True when the last real temperature is at most two samples back."""
    missing = 0
    for x in reversed(h):
        if x["_T_raw"] is not None and not (isinstance(x["_T_raw"], float) and math.isnan(x["_T_raw"])):
            return missing < 2
        missing += 1
    return False
