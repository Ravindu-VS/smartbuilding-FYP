#!/usr/bin/env python3
"""
Occupancy detection: training and evaluation on the UCI Occupancy Detection dataset
(real, public), with a domain check on the digital twin's synthetic rooms.

    python -m ml.occupancy                 # full run: compare, select, register, report
    python -m ml.occupancy --quick         # fewer candidates (smoke test)

Splits (chronological; rows are never shuffled across time):
  Protocol B (main, forward in time)
     train       2 Feb 14:19 - 8 Feb 23:59 2015 (datatest + datatraining up to 9 Feb)
     validation  9 Feb 00:00 - 10 Feb 09:33 (end of datatraining): model and feature-set choice
     test        11 Feb 14:48 - 18 Feb 09:19 (datatest2): a later week, used once at the end
     The selected configuration is refitted on train + validation before the test.
  Protocol A (the original paper's split, for comparison with the literature)
     train datatraining (4-10 Feb); test1 datatest (2-4 Feb, BEFORE training); test2 datatest2.
Temporal features are computed inside each contiguous recording only (ml/features.py),
so no value from the test week is used for a training row or vice versa.

Models: logistic regression, decision tree, random forest (the project's interpretable
baseline), histogram gradient-boosted trees, and a small MLP; all with fixed seeds.
Registered (models/registry/):
  occupancy_rf            random forest on the original five inputs (replaces the legacy
                          pickle used by the 'threshold_rf' controller; same inputs)
  occupancy_best          best model + feature set on the validation week
  occupancy_co2_temporal  best model on CO2 level and CO2 trends only (no light, which the
                          controller itself switches): candidate for the fusion estimator,
                          run in shadow mode until promoted
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ml.common import (PROCESSED, ROOT as _R, SYNTHETIC, classification_metrics, feature_reference,  # noqa: E402
                       git_commit, md_table, next_version, rounded, sha256_file, utc_now, versions, write_artifact)
from ml.features import FEATURE_SETS, UNITS, add_features, matrix                                    # noqa: E402
from ml.online import pir_features                                                                   # noqa: E402
from ml.portable import export                                                                       # noqa: E402

SEED = 42
VAL_START = pd.Timestamp("2015-02-09 00:00:00")
REPORT = os.path.join(ROOT, "docs", "results", "occupancy.md")
RESULTS = os.path.join(ROOT, "experiments", "results", "exp02_occupancy")


def candidates(seed: int = SEED, quick: bool = False) -> Dict[str, object]:
    from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.neural_network import MLPClassifier
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.tree import DecisionTreeClassifier
    c = {
        "logreg": Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler()),
                            ("model", LogisticRegression(C=1.0, max_iter=5000))]),
        "decision_tree": Pipeline([("imputer", SimpleImputer(strategy="median")),
                                   ("model", DecisionTreeClassifier(max_depth=6, min_samples_leaf=20, random_state=seed))]),
        "random_forest": Pipeline([("imputer", SimpleImputer(strategy="median")),
                                   ("model", RandomForestClassifier(n_estimators=150, max_depth=12, min_samples_leaf=5,
                                                                    n_jobs=2, random_state=seed))]),
        "hist_gbt": HistGradientBoostingClassifier(max_iter=250, learning_rate=0.05, max_leaf_nodes=15,
                                                   l2_regularization=1.0, early_stopping=False, random_state=seed),
        "mlp": Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler()),
                         ("model", MLPClassifier(hidden_layer_sizes=(32, 16), alpha=1e-3, max_iter=300,
                                                 early_stopping=False, random_state=seed))]),
    }
    if quick:
        c = {k: c[k] for k in ("logreg", "random_forest")}
    return c


def load_uci() -> pd.DataFrame:
    path = os.path.join(PROCESSED, "uci_occupancy.csv")
    if not os.path.exists(path):
        raise SystemExit("data/processed/uci_occupancy.csv missing: run scripts/preprocess_datasets.py")
    df = pd.read_csv(path, parse_dates=["timestamp"])
    return add_features(df)


def splits(df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    tr_files = df.source_file.isin(["datatest.txt", "datatraining.txt"])
    return {
        "B_train": df[tr_files & (df.timestamp < VAL_START)],
        "B_val": df[tr_files & (df.timestamp >= VAL_START)],
        "B_trainval": df[tr_files],
        "B_test": df[df.source_file == "datatest2.txt"],
        "A_train": df[df.source_file == "datatraining.txt"],
        "A_test1": df[df.source_file == "datatest.txt"],
        "A_test2": df[df.source_file == "datatest2.txt"],
    }


def fit_eval(model, feats, train: pd.DataFrame, tests: Dict[str, pd.DataFrame]) -> Tuple[object, Dict]:
    from sklearn.base import clone
    m = clone(model)
    t0 = time.perf_counter()
    m.fit(matrix(train, feats), train["Occupancy"].values)
    fit_s = time.perf_counter() - t0
    out = {"fit_s": fit_s}
    for name, d in tests.items():
        t1 = time.perf_counter()
        p = m.predict_proba(matrix(d, feats))[:, 1]
        out[name] = classification_metrics(d["Occupancy"].values, p)
        out[name]["predict_us_per_row"] = (time.perf_counter() - t1) / max(1, len(d)) * 1e6
    return m, out


def load_synthetic(pattern: str) -> pd.DataFrame:
    """One-minute synthetic rows -> the UCI column names (measured values, label = true occupants > 0)."""
    from twin.climate import humidity_ratio
    files = sorted(glob.glob(os.path.join(SYNTHETIC, pattern)))
    if not files:
        return pd.DataFrame()
    df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    df = df.rename(columns={"meas_temperature_c": "Temperature", "meas_humidity_pct": "Humidity",
                            "meas_lux": "Light", "meas_co2_ppm": "CO2"})
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["HumidityRatio"] = [humidity_ratio(t, h) if pd.notna(t) and pd.notna(h) else np.nan
                           for t, h in zip(df.Temperature, df.Humidity)]
    df["Occupancy"] = (df["occupants"] > 0).astype(int)
    df = df[df.room_type != "corridor"]                    # transit spaces: occupancy is momentary
    return add_features(df, group_col="room_id")


def card(task: str, version: str, meta: Dict) -> str:
    t = meta["test_metrics"]
    rows = [dict(split=k, **{m: v.get(m) for m in ("n", "accuracy", "precision", "recall", "f1", "balanced_accuracy", "roc_auc")})
            for k, v in t.items()]
    return f"""# Model card: {task} {version}

- **Task**: room occupancy (occupied = 1) from indoor environmental readings
- **Model**: {meta['model_family']} ({meta['estimator']})
- **Features ({len(meta['features'])}, in this order)**: {', '.join(meta['features'])}
- **Training data**: UCI Occupancy Detection (Candanedo & Feldheim 2016), CC BY 4.0, provenance public_real;
  rows {meta['training']['rows']} from {meta['training']['first']} to {meta['training']['last']} ({meta['training']['split']})
- **Selection**: {meta['selection']}
- **Seed**: {meta['seed']}; trained {meta['trained_utc']} at commit {meta['git_commit']}

## Held-out results (threshold {meta['threshold']})

{md_table(rows, ['split', 'n', 'accuracy', 'precision', 'recall', 'f1', 'balanced_accuracy', 'roc_auc'])}

B_test = 11-18 Feb 2015, a week after all training data. A_* = original paper split (A_test1 precedes the training
days; reported for comparison only).

## Limitations

- One office in Mons, Belgium, in February (heating season), 1-minute data, a few occupants; labels from photographs.
  Not validated in a tropical, air-conditioned building or in the project's real room (no labelled data there yet).
- Light is a strong cue in this dataset because occupants switched the lights; in an automated building the
  controller switches them, so light-based features feed back the controller's own actions (see `occupancy_co2_temporal`).
- {meta.get('extra_limitations', 'Synthetic-domain results are reported separately in docs/results/occupancy.md.')}
"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--no-register", action="store_true")
    args = ap.parse_args(argv)
    os.makedirs(RESULTS, exist_ok=True)
    df = load_uci()
    sp = splits(df)
    data_sha = sha256_file(os.path.join(PROCESSED, "uci_occupancy.csv"))
    cands = candidates(quick=args.quick)
    fsets = list(FEATURE_SETS) if not args.quick else ["env", "co2_temporal"]

    # ---- 1. compare every model x feature set on the validation week (protocol B)
    comparison = []
    for fs in fsets:
        feats = FEATURE_SETS[fs]
        for name, model in cands.items():
            _, res = fit_eval(model, feats, sp["B_train"], {"B_val": sp["B_val"]})
            v = res["B_val"]
            comparison.append({"feature_set": fs, "model": name, "val_f1": v["f1"], "val_auc": v["roc_auc"],
                               "val_bal_acc": v["balanced_accuracy"], "val_precision": v["precision"],
                               "val_recall": v["recall"], "fit_s": res["fit_s"]})
            print(f"  {fs:17s} {name:14s} val F1 {v['f1']:.4f} AUC {v['roc_auc']:.4f}")
    comp = pd.DataFrame(comparison)

    # ---- 2. final evaluation: refit on train+val, test on the later week; also protocol A
    def final(fs: str, name: str) -> Tuple[object, Dict]:
        feats = FEATURE_SETS[fs]
        m, resB = fit_eval(cands[name], feats, sp["B_trainval"], {"B_test": sp["B_test"]})
        _, resA = fit_eval(cands[name], feats, sp["A_train"], {"A_test1": sp["A_test1"], "A_test2": sp["A_test2"]})
        return m, {"B_test": resB["B_test"], "A_test1": resA["A_test1"], "A_test2": resA["A_test2"],
                   "fit_s": resB["fit_s"]}

    test_rows = []
    finals: Dict[Tuple[str, str], Tuple[object, Dict]] = {}
    for fs in fsets:
        best_name = comp[comp.feature_set == fs].sort_values(["val_f1", "val_auc"], ascending=False).iloc[0]["model"]
        for name in sorted(set([best_name, "random_forest"] if "random_forest" in cands else [best_name])):
            m, r = final(fs, name)
            finals[(fs, name)] = (m, r)
            test_rows.append({"feature_set": fs, "model": name, "selected_on_val": name == best_name,
                              **{f"{k}_{m_}": r[k][m_] for k in ("B_test", "A_test1", "A_test2")
                                 for m_ in ("f1", "accuracy", "roc_auc")}})
    tests = pd.DataFrame(test_rows)

    # ---- 3. legacy models on the same test week
    legacy = evaluate_legacy(sp)

    # ---- 4. synthetic domain check (twin rooms, one-minute rows) for features the twin has
    syn = synthetic_check(cands, sp) if not args.quick else {}

    # ---- 5. register
    registered = {}
    if not args.no_register:
        overall = comp.sort_values(["val_f1", "val_auc"], ascending=False).iloc[0]
        co2b = comp[comp.feature_set == "co2_temporal"].sort_values(["val_f1", "val_auc"], ascending=False).iloc[0]
        plan = [("occupancy_rf", "env", "random_forest", "random forest on the project's original five inputs"),
                ("occupancy_best", overall.feature_set, overall.model, "highest validation F1 over all models and feature sets"),
                ("occupancy_co2_temporal", "co2_temporal", co2b.model, "highest validation F1 using CO2 level and trends only")]
        for task, fs, name, why in plan:
            if (fs, name) not in finals:
                finals[(fs, name)] = final(fs, name)
            m, r = finals[(fs, name)]
            registered[task] = register(task, fs, name, m, r, sp, data_sha, why, syn.get((fs, name)))
            print(f"registered {task} {registered[task]}")

    fusion_model, fusion_res, fusion_tr = (None, {}, None) if args.quick else twin_fusion()
    if fusion_model is not None and not args.no_register:
        registered["occupancy_twin_fusion"] = register_twin_fusion(fusion_model, fusion_res, fusion_tr)
        print("registered occupancy_twin_fusion", registered["occupancy_twin_fusion"])
    write_report(comp, tests, legacy, syn, registered, sp, fusion_res)
    with open(os.path.join(RESULTS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(rounded({"validation_comparison": comparison, "test": test_rows, "legacy": legacy,
                           "synthetic_domain": {f"{k[0]}|{k[1]}": v for k, v in syn.items()},
                           "twin_fusion": fusion_res,
                           "registered": registered, "dataset_sha256": data_sha, "seed": SEED,
                           "generated_utc": utc_now(), "git_commit": git_commit()}), f, indent=2)
    return 0


def register(task: str, fs: str, name: str, model, res: Dict, sp, data_sha: str, why: str, syn_res) -> str:
    feats = FEATURE_SETS[fs]
    trv = sp["B_trainval"]
    X = matrix(trv, feats)
    portable = export(model, feats, "classification", 0.5, X_check=X)
    version = next_version(task)
    est = model.named_steps["model"] if hasattr(model, "named_steps") else model
    meta = {
        "kind": "classification", "target": "Occupancy (1 = occupied)", "features": feats,
        "feature_units": {f: UNITS[f] for f in feats}, "feature_set": fs,
        "feature_code": "ml/features.py (add_features for tables, OnlineFeatures for live readings)",
        "model_family": name, "estimator": type(est).__name__, "params": {k: v for k, v in est.get_params().items()
                                                                           if isinstance(v, (int, float, str, bool, type(None)))},
        "threshold": 0.5, "seed": SEED, "selection": why,
        "training": {"dataset": "uci_occupancy", "file": "data/processed/uci_occupancy.csv", "sha256": data_sha,
                     "split": "protocol B train+validation (datatest + datatraining)", "rows": int(len(trv)),
                     "first": str(trv.timestamp.min()), "last": str(trv.timestamp.max()),
                     "positive_share": float(trv.Occupancy.mean()), "provenance": "public_real"},
        "test_metrics": {k: res[k] for k in ("B_test", "A_test1", "A_test2")},
        "feature_reference": feature_reference(X, feats),
        "synthetic_domain_metrics": syn_res,
        "inference": {"input_validation": "missing feature -> ModelError; NaN -> imputed median (trees/linear) or "
                                          "native missing handling (gradient boosting); inf -> ModelError",
                      "runtime": "numpy only (ml/portable.py)"},
        "training_code": "ml/occupancy.py", "trained_utc": utc_now(), "git_commit": git_commit(),
        "dependencies": versions(), "provenance": "prediction",
    }
    write_artifact(task, version, meta, card(task, version, meta), portable=portable, sk_object=model)
    return version


def register_twin_fusion(model, res: Dict, tr: pd.DataFrame) -> str:
    feats = TWIN_FUSION_FEATURES
    X = tr[feats].to_numpy(float)
    portable = export(model, feats, "classification", 0.5, X_check=X[:: max(1, len(X) // 20000)])
    task = "occupancy_twin_fusion"
    version = next_version(task)
    path = os.path.join(SYNTHETIC, "normal_seed31_mo.csv.gz")
    units = dict(UNITS, **TWIN_FUSION_UNITS)
    meta = {
        "kind": "classification", "target": "true simulated head count > 0", "features": feats,
        "feature_units": {f: units[f] for f in feats}, "feature_set": "twin_fusion",
        "feature_code": "ml/features.py (CO2/T/HR trends) + ml/occupancy.py pir_features()",
        "model_family": "hist_gbt", "estimator": "HistGradientBoostingClassifier", "threshold": 0.5, "seed": SEED,
        "selection": "single candidate; compared with the hand-built FusionEstimator on a different seed and controller",
        "training": {"dataset": "synthetic twin, one-minute rows", "file": "data/synthetic/normal_seed31_mo.csv.gz",
                     "sha256": sha256_file(path), "rows": int(len(tr)), "first": str(tr.timestamp.min()),
                     "last": str(tr.timestamp.max()), "positive_share": float(tr.Occupancy.mean()),
                     "split": "seed 31 (MO controller); test seed 32 (schedule controller)", "provenance": "synthetic"},
        "test_metrics": {k: v for k, v in res.items() if isinstance(v, dict)},
        "feature_reference": feature_reference(X, feats),
        "inference": {"runtime": "numpy only (ml/portable.py)", "scope": "simulated rooms only"},
        "training_code": "ml/occupancy.py twin_fusion()", "trained_utc": utc_now(), "git_commit": git_commit(),
        "dependencies": versions(), "provenance": "prediction",
        "extra_limitations": "Trained on simulator labels: valid for the simulated rooms only (sim-to-real gap).",
    }
    t = meta["test_metrics"]
    rows = [{"method": k, **{m: v[m] for m in ("f1", "precision", "recall", "roc_auc")}} for k, v in t.items()]
    card = (f"# Model card: {task} {version}\n\n- **Task**: occupancy of a simulated room from PIR and CO2 (learned fusion)\n"
            f"- **Features**: {', '.join(feats)}\n- **Training data**: synthetic (twin seed 31, {len(tr)} room-minutes)\n"
            f"- **Test**: twin seed 32 under a different controller\n\n" + md_table(rows, ["method", "f1", "precision", "recall", "roc_auc"])
            + "\n\n## Limitations\n\n- Synthetic labels: it learns the simulator's occupant and sensor models; not "
              "valid for the real room without labelled real data.\n- Light is deliberately not an input (the controller switches it).\n")
    write_artifact(task, version, meta, card, portable=portable, sk_object=model)
    return version


def evaluate_legacy(sp) -> Dict:
    """The models that were deployed before this work, on the same held-out week."""
    out = {}
    d = sp["B_test"]
    try:
        import joblib
        pipe = joblib.load(os.path.join(ROOT, "models", "final_unified_occupancy_pipeline.pkl"))
        p = pipe.predict_proba(d[FEATURE_SETS["env"]])[:, 1]
        out["legacy_final_unified_rf"] = {
            "metrics": classification_metrics(d.Occupancy.values, p),
            "caveat": "trained by train_final_unified_occupancy_model.py on UCI + its Kaggle copies (which include "
                      "datatest2 itself) + old simulated data: this test week was part of its training data, so the "
                      "score is not a held-out result"}
    except Exception as e:
        out["legacy_final_unified_rf"] = {"error": str(e)}
    try:
        from twin.portable import PortableModel
        m = PortableModel.load(os.path.join(ROOT, "models", "occupancy", "co2", "model.json"))
        p = m.predict_proba(d[["CO2"]].to_numpy(float))
        out["legacy_co2_tree"] = {"metrics": classification_metrics(d.Occupancy.values, p),
                                  "caveat": "trained on datatraining only (protocol A); datatest2 is held out"}
    except Exception as e:
        out["legacy_co2_tree"] = {"error": str(e)}
    return out


def synthetic_check(cands, sp) -> Dict:
    """Train on UCI, test on the twin (and train on the twin, test on the twin's other seed)."""
    tr = load_synthetic("normal_seed31_mo.csv.gz")
    te = load_synthetic("normal_seed32_schedule.csv.gz")
    if tr.empty or te.empty:
        print("  synthetic one-minute data missing (scripts/make_synthetic_corpus.sh): domain check skipped")
        return {}
    out = {}
    for fs in ("co2", "co2_temporal", "nolight_temporal"):
        feats = FEATURE_SETS[fs]
        for name in ("random_forest", "hist_gbt", "logreg"):
            if name not in cands:
                continue
            _, r_uci = fit_eval(cands[name], feats, sp["B_trainval"], {"syn_test": te})
            _, r_syn = fit_eval(cands[name], feats, tr, {"syn_test": te, "uci_B_test": sp["B_test"]})
            out[(fs, name)] = {"train_uci_test_syn": r_uci["syn_test"], "train_syn_test_syn": r_syn["syn_test"],
                               "train_syn_test_uci": r_syn["uci_B_test"]}
            print(f"  synthetic {fs:17s} {name:14s} UCI->syn F1 {r_uci['syn_test']['f1']:.3f}  "
                  f"syn->syn F1 {r_syn['syn_test']['f1']:.3f}  syn->UCI F1 {r_syn['uci_B_test']['f1']:.3f}")
    return out


TWIN_FUSION_FEATURES = ["pir_2min", "pir_10min", "pir_20min", "pir_log", "CO2", "CO2_d5", "CO2_d15", "CO2_std15",
                        "T_d15", "HR_d15", "hour_sin", "hour_cos", "weekday"]
TWIN_FUSION_UNITS = {"pir_2min": "0/1 motion in last 2 min", "pir_10min": "0/1 motion in last 10 min",
                     "pir_20min": "0/1 motion in last 20 min", "pir_log": "ln(1 + seconds since motion), capped at 1 day"}


def add_pir(df: pd.DataFrame) -> pd.DataFrame:
    f = pd.DataFrame([pir_features(v) for v in df["meas_pir_seconds"].values], index=df.index)
    return pd.concat([df, f], axis=1)


def fusion_baseline(df: pd.DataFrame) -> np.ndarray:
    """The live system's hand-built FusionEstimator (PIR + CO2 tree), stepped through time per room."""
    from twin.controllers import FusionEstimator, Observation
    est = FusionEstimator()
    out = np.empty(len(df))
    order = df.sort_values(["room_id", "timestamp"], kind="mergesort").index
    pos = {ix: i for i, ix in enumerate(df.index)}
    for ix in order:
        r = df.loc[ix]
        co2 = None if pd.isna(r["CO2"]) else float(r["CO2"])
        sec = None if pd.isna(r["meas_pir_seconds"]) else float(r["meas_pir_seconds"])
        o = Observation(r["room_id"], r["room_type"], r["timestamp"].to_pydatetime(), 0.0, 0.0, 0.0, co2, 0.0, sec)
        out[pos[ix]] = est.probability(o)
    return out


def twin_fusion(seed: int = SEED) -> Tuple[object, Dict, pd.DataFrame]:
    """Learned PIR + CO2 fusion for the simulated rooms (synthetic labels), against the hand-built fusion."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    tr = load_synthetic("normal_seed31_mo.csv.gz")
    te = load_synthetic("normal_seed32_schedule.csv.gz")
    if tr.empty or te.empty:
        return None, {}, tr
    tr, te = add_pir(tr), add_pir(te)
    m = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=31, l2_regularization=1.0,
                                       early_stopping=False, random_state=seed)
    m.fit(tr[TWIN_FUSION_FEATURES].to_numpy(float), tr["Occupancy"].values)
    p = m.predict_proba(te[TWIN_FUSION_FEATURES].to_numpy(float))[:, 1]
    res = {"learned_fusion_hist_gbt": classification_metrics(te.Occupancy.values, p),
           "handbuilt_fusion_estimator": classification_metrics(te.Occupancy.values, fusion_baseline(te)),
           "pir_only_10min": classification_metrics(te.Occupancy.values, te["pir_10min"].values)}
    for k, v in res.items():
        print(f"  twin fusion {k:28s} F1 {v['f1']:.4f} precision {v['precision']:.4f} recall {v['recall']:.4f}")
    res["train_rows"], res["test_rows"] = int(len(tr)), int(len(te))
    return m, res, tr


def write_report(comp: pd.DataFrame, tests: pd.DataFrame, legacy: Dict, syn: Dict, registered: Dict, sp,
                 fusion: Dict = None) -> None:
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    bal = {k: (len(v), float(v.Occupancy.mean()), str(v.timestamp.min()), str(v.timestamp.max()))
           for k, v in sp.items()}
    lines = ["# Occupancy detection results", "",
             f"Generated by `python -m ml.occupancy` at {utc_now()} (commit {git_commit()}). Seed {SEED}.", "",
             "## Data and splits", "",
             md_table([{"split": k, "rows": n, "occupied_share": s, "first": a, "last": b} for k, (n, s, a, b) in bal.items()],
                      ["split", "rows", "occupied_share", "first", "last"]), "",
             "## Validation week (protocol B): every model x feature set", "",
             md_table(comp.sort_values(["feature_set", "val_f1"], ascending=[True, False]).to_dict("records"),
                      ["feature_set", "model", "val_f1", "val_auc", "val_bal_acc", "val_precision", "val_recall", "fit_s"]),
             "", "## Held-out test (refit on train + validation)", "",
             md_table(tests.to_dict("records"), ["feature_set", "model", "selected_on_val", "B_test_f1", "B_test_accuracy",
                                                  "B_test_roc_auc", "A_test1_f1", "A_test2_f1"]), "",
             "## Legacy models on the same test week (B_test)", ""]
    for k, v in legacy.items():
        if "metrics" in v:
            mm = v["metrics"]
            lines.append(f"- **{k}**: F1 {mm['f1']:.4f}, accuracy {mm['accuracy']:.4f}, AUC {mm['roc_auc']:.4f}. {v['caveat']}")
        else:
            lines.append(f"- **{k}**: could not be evaluated ({v['error']})")
    if syn:
        lines += ["", "## Domain check on the digital twin (synthetic, one-minute rows; corridors excluded)", "",
                  "Train on UCI and test on the twin; train on twin seed 31 (MO controller) and test on twin seed 32 "
                  "(schedule controller) and on the UCI test week. Labels: true simulated head count > 0.", "",
                  md_table([{"feature_set": k[0], "model": k[1],
                             "UCI->twin F1": v["train_uci_test_syn"]["f1"], "UCI->twin AUC": v["train_uci_test_syn"]["roc_auc"],
                             "twin->twin F1": v["train_syn_test_syn"]["f1"], "twin->twin AUC": v["train_syn_test_syn"]["roc_auc"],
                             "twin->UCI F1": v["train_syn_test_uci"]["f1"]} for k, v in syn.items()],
                           ["feature_set", "model", "UCI->twin F1", "UCI->twin AUC", "twin->twin F1", "twin->twin AUC", "twin->UCI F1"])]
    if fusion:
        lines += ["", "## Learned PIR + CO2 fusion for the simulated rooms (synthetic labels)", "",
                  f"Train: twin seed 31 under the MO controller ({fusion['train_rows']} room-minutes); test: twin seed 32 "
                  f"under the schedule controller ({fusion['test_rows']} room-minutes, a different controller and different "
                  "occupants). Threshold 0.5.", "",
                  md_table([{"method": k, **{m: v[m] for m in ("f1", "precision", "recall", "balanced_accuracy", "roc_auc")}}
                            for k, v in fusion.items() if isinstance(v, dict)],
                           ["method", "f1", "precision", "recall", "balanced_accuracy", "roc_auc"]),
                  "", "This model learns the simulator's sensor models; it is registered as a candidate for the "
                  "simulated rooms only and runs in shadow mode until it passes the promotion gate."]
    if registered:
        lines += ["", "## Registered models", ""] + [f"- `{t}` {v} (models/registry/{t}/{v}/)" for t, v in registered.items()]
    else:
        from ml.common import registry_note
        lines += ["", "## Registry", "", registry_note(["occupancy_rf", "occupancy_best", "occupancy_co2_temporal",
                                                        "occupancy_twin_fusion"])]
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    sys.exit(main())
