#!/usr/bin/env python3
"""
Train, evaluate, track and register the room-occupancy model with MLflow.

    python -m mlops.train                                   # local: sqlite tracking in output/mlflow/
    MLFLOW_TRACKING_URI=http://localhost:5000 python -m mlops.train
    python -m mlops.train --feature-set with_co2 --no-register   # comparison run only

Pipeline: load → validate/clean → features → chronological split → candidates fitted on train, chosen on
validation → winner refitted on train+validation → evaluated once on test → logged to MLflow (params,
metrics, data version, git commit, environment, validation report, feature reference, model card) →
registered as a new version → promotion gate (mlops/promote.py) decides whether it becomes `production`.

Why these models: the task is tabular (7 features, ~12 k training rows), so classical models fit the data
and stay explainable on the Pi; deep learning would add cost without a reason. Logistic regression is the
interpretable baseline; Random Forest and histogram gradient boosting capture non-linear thresholds (lights,
time of day).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import sys
import time
from typing import Dict, Optional

import numpy as np

os.environ.setdefault("MLFLOW_DISABLE_TELEMETRY", "true")       # no usage data leaves the edge/lab network
os.environ.setdefault("DO_NOT_TRACK", "1")
os.environ.setdefault("MLFLOW_SUPPRESS_PRINTING_URL_TO_STDOUT", "true")   # stdout carries only the JSON result
os.environ.setdefault("GIT_PYTHON_REFRESH", "quiet")                     # images have no git: commit comes from GIT_COMMIT
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ml.common import classification_metrics, feature_reference, git_commit, sha256_file, versions  # noqa: E402
from mlops import data as D                                                                        # noqa: E402

log = logging.getLogger("mlops.train")
EXPERIMENT = "room-occupancy"
MODEL_NAME = "room-occupancy"
DEFAULT_TRACKING = "sqlite:///" + os.path.join(ROOT, "output", "mlflow", "mlflow.db")
DEFAULT_ARTIFACTS = os.path.join(ROOT, "output", "mlflow", "artifacts")


# skops refuses non-standard types by default. These two are scikit-learn's own tree structures, reviewed and
# trusted because every model is created inside this pipeline; any other type stops the run instead of loading.
SKOPS_REVIEWED_TYPES = {"sklearn.tree._tree.Tree",
                        "sklearn.ensemble._hist_gradient_boosting.predictor.TreePredictor"}


def skops_trusted_types(model) -> list:
    import skops.io as sio
    needed = sorted(sio.get_untrusted_types(data=sio.dumps(model)))
    unknown = [t for t in needed if t not in SKOPS_REVIEWED_TYPES]
    if unknown:
        raise RuntimeError(f"model contains types nobody reviewed for safe loading: {unknown}")
    return needed


def candidates(seed: int = 42) -> Dict[str, object]:
    from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    return {   # order = preference on a tie (simpler first)
        "logistic_regression": make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=1.0)),
        "random_forest": RandomForestClassifier(n_estimators=200, max_depth=10, min_samples_leaf=5, n_jobs=-1,
                                                random_state=seed),
        "hist_gradient_boosting": HistGradientBoostingClassifier(max_iter=200, learning_rate=0.1, max_leaf_nodes=31,
                                                                 random_state=seed),
    }


def _flat(prefix: str, m: Dict) -> Dict[str, float]:
    return {f"{prefix}_{k}": float(v) for k, v in m.items() if isinstance(v, (int, float)) and np.isfinite(v)}


def setup_mlflow(tracking_uri: Optional[str], experiment: str):
    import mlflow
    uri = tracking_uri or os.environ.get("MLFLOW_TRACKING_URI") or DEFAULT_TRACKING
    if uri.startswith("sqlite:///"):
        os.makedirs(os.path.dirname(uri[len("sqlite:///"):]), exist_ok=True)
    mlflow.set_tracking_uri(uri)
    if mlflow.get_experiment_by_name(experiment) is None:
        loc = None
        if not uri.startswith("http"):                    # local store: keep artifacts under output/
            os.makedirs(DEFAULT_ARTIFACTS, exist_ok=True)
            loc = "file://" + DEFAULT_ARTIFACTS
        mlflow.create_experiment(experiment, artifact_location=loc)
    mlflow.set_experiment(experiment)
    return uri


def train(data_path: str = D.DEFAULT_DATA, tracking_uri: Optional[str] = None, feature_set: str = "room101",
          register: bool = True, promote: bool = True, experiment: str = EXPERIMENT,
          model_name: str = MODEL_NAME) -> Dict:
    import mlflow
    import mlflow.sklearn
    from mlflow.models import infer_signature
    from sklearn.base import clone

    uri = setup_mlflow(tracking_uri, experiment)
    features = D.FEATURE_SETS[feature_set]
    raw = D.load(data_path)
    df, report = D.validate_and_clean(raw)
    if not report.ok:
        raise D.DataValidationError("; ".join(report.errors))
    df = D.add_features(df)
    parts = D.split(df)
    X = {k: p[features].to_numpy(float) for k, p in parts.items()}
    y = {k: p[D.TARGET].to_numpy(int) for k, p in parts.items()}
    data_version = sha256_file(data_path)[:12]
    commit = os.environ.get("GIT_COMMIT") or git_commit()

    with mlflow.start_run(run_name=f"{feature_set}-{time.strftime('%Y%m%d-%H%M%S')}") as run:
        mlflow.set_tags({"git_commit": commit, "data_version": data_version, "feature_set": feature_set,
                         "platform": platform.platform(), "pipeline": "mlops.train",
                         **{f"version_{k}": v for k, v in versions().items()}})
        mlflow.log_params({"data_path": os.path.relpath(data_path, ROOT) if data_path.startswith(ROOT) else data_path,
                           "data_version": data_version, "feature_set": feature_set, "features": ",".join(features),
                           "split_validation_from": D.SPLIT_DAYS["validation"], "split_test_from": D.SPLIT_DAYS["test"],
                           "rows_train": len(y["train"]), "rows_validation": len(y["validation"]),
                           "rows_test": len(y["test"]), "threshold": 0.5})
        mlflow.log_dict(report.as_dict(), "data_validation.json")
        mlflow.log_dict(D.summary(parts), "data_splits.json")

        scores = {}
        for name, est in candidates().items():
            with mlflow.start_run(run_name=name, nested=True):
                t0 = time.perf_counter()
                m = clone(est).fit(X["train"], y["train"])
                fit_s = time.perf_counter() - t0
                val = classification_metrics(y["validation"], m.predict_proba(X["validation"])[:, 1])
                mlflow.set_tags({"candidate": name, "data_version": data_version, "git_commit": commit})
                mlflow.log_params({k: v for k, v in est.get_params().items()
                                   if isinstance(v, (int, float, str, bool)) and len(str(v)) < 200})
                mlflow.log_metrics({**_flat("val", val), "fit_seconds": fit_s})
                scores[name] = val
                log.info("candidate %s: validation F1 %.4f, balanced accuracy %.4f", name, val["f1"],
                         val["balanced_accuracy"])
        order = list(candidates())
        best = max(order, key=lambda n: (round(scores[n]["f1"], 4), -order.index(n)))
        final = clone(candidates()[best]).fit(np.vstack([X["train"], X["validation"]]),
                                              np.concatenate([y["train"], y["validation"]]))
        t0 = time.perf_counter()
        prob = final.predict_proba(X["test"])[:, 1]
        latency_ms = (time.perf_counter() - t0) / len(prob) * 1000
        test = classification_metrics(y["test"], prob)
        mlflow.log_metrics({**_flat("test", test), **_flat("val", scores[best]),
                            "inference_ms_per_row": latency_ms})
        mlflow.set_tag("selected_model", best)
        ref = feature_reference(np.vstack([X["train"], X["validation"]]), features)
        mlflow.log_dict({"features": features, "reference": ref}, "feature_reference.json")
        mlflow.log_text(_model_card(best, feature_set, features, scores, test, data_version, commit, parts),
                        "model_card.md")
        info = {"run_id": run.info.run_id, "selected": best, "test": test, "validation": scores[best],
                "data_version": data_version, "git_commit": commit, "tracking_uri": uri, "feature_set": feature_set}
        if register:
            mi = mlflow.sklearn.log_model(
                final, name="model", registered_model_name=model_name,
                serialization_format="skops",      # no arbitrary code runs when the serving API loads it (unlike pickle)
                skops_trusted_types=skops_trusted_types(final),
                signature=infer_signature(parts["test"][features].head(50), prob[:50]),
                input_example=parts["test"][features].head(3),
                metadata={"features": features, "feature_set": feature_set, "threshold": 0.5,
                          "data_version": data_version, "git_commit": commit, "estimator": best})
            info["model_version"] = str(mi.registered_model_version)
            log.info("registered %s version %s", model_name, info["model_version"])
    if register and promote:
        from mlops.promote import gate
        info["promotion"] = gate(model_name, info["model_version"], parts, tracking_uri=uri)
    return info


def _model_card(best, feature_set, features, scores, test, data_version, commit, parts) -> str:
    rows = "\n".join(f"| {n} | {s['f1']:.4f} | {s['balanced_accuracy']:.4f} | {s['roc_auc']:.4f} |"
                     for n, s in scores.items())
    sp = D.summary(parts)
    return f"""# Model card: room occupancy ({feature_set})

**Task:** P(room occupied) from one reading of the room's sensors and the time of day.
**Selected:** `{best}` (highest validation F1; ties go to the simpler model), refitted on train + validation.
**Data:** UCI Occupancy Detection, real office, one-minute readings (version `{data_version}`).
**Features:** {", ".join(features)}.
**Code:** git `{commit}`.

| Split | Rows | Period | Occupied share |
|---|---|---|---|
""" + "\n".join(f"| {k} | {v['rows']} | {v['first'][:10]} … {v['last'][:10]} | {v['positive_share']:.1%} |"
                for k, v in sp.items()) + f"""

## Validation (model selection)

| Candidate | F1 | Balanced accuracy | ROC AUC |
|---|---|---|---|
{rows}

## Test (held out, evaluated once)

F1 {test['f1']:.4f} · accuracy {test['accuracy']:.4f} · balanced accuracy {test['balanced_accuracy']:.4f} ·
precision {test['precision']:.4f} · recall {test['recall']:.4f} · ROC AUC {test['roc_auc']:.4f} ·
confusion {test['confusion']}

## Limits

* One office in Feb 2015. Room 101 differs (room, sensors, season); its live inputs are checked for drift
  against this training distribution (PSI) by the serving API.
* Light is the strongest signal. In Room 101 the AI's own light LED adds to the lux reading, so a lit LED can
  look like an occupied room; the LED's measured contribution is calibrated on the edge (`/api/hardware/calibrate-led`).
* Room 101 has no occupancy ground truth (the PIR is a proxy), so live accuracy cannot be measured there.
"""


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--data", default=D.DEFAULT_DATA)
    p.add_argument("--tracking-uri", default=None)
    p.add_argument("--feature-set", default="room101", choices=sorted(D.FEATURE_SETS))
    p.add_argument("--no-register", action="store_true", help="log the run only")
    p.add_argument("--no-promote", action="store_true", help="register but leave the production alias alone")
    p.add_argument("--model-name", default=MODEL_NAME)
    p.add_argument("--if-no-production", action="store_true",
                   help="exit without training when the registry already has a production version (stack start-up)")
    a = p.parse_args(argv)
    from sbops.logs import setup
    setup("trainer", stream=sys.stderr)
    if a.if_no_production:
        from mlflow import MlflowClient
        setup_mlflow(a.tracking_uri, EXPERIMENT)
        try:
            mv = MlflowClient().get_model_version_by_alias(a.model_name, "production")
            log.info("production is already v%s: nothing to train (retrain: python -m mlops.train)", mv.version)
            print(json.dumps({"skipped": True, "production_version": str(mv.version)}))
            return 0
        except Exception:
            log.info("no production model yet: training the first one")
    info = train(a.data, a.tracking_uri, a.feature_set, register=not a.no_register, promote=not a.no_promote,
                 model_name=a.model_name)
    print(json.dumps({k: v for k, v in info.items() if k != "test"} | {"test_f1": info["test"]["f1"],
                                                                         "test_accuracy": info["test"]["accuracy"]},
                     indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
