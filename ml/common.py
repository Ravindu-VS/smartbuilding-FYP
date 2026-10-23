"""
Shared helpers for the ML pipelines: paths, provenance, metrics, artifact writing.

Every trained model is written as a directory
    models/registry/<task>/<version>/
        model.json        portable model (numpy-only evaluation, no pickle)  [when exportable]
        model.joblib      scikit-learn object (training-side reference)
        metadata.json     everything needed to reproduce and to use the model correctly
        model_card.md     human-readable summary (data, method, metrics, limitations)
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import subprocess
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY_DIR = os.path.join(ROOT, "models", "registry")
PROCESSED = os.path.join(ROOT, "data", "processed")
SYNTHETIC = os.path.join(ROOT, "data", "synthetic")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"], text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"


def versions() -> Dict[str, str]:
    out = {"python": platform.python_version()}
    for mod in ("numpy", "pandas", "sklearn", "scipy"):
        try:
            out[mod] = __import__(mod).__version__
        except Exception:
            pass
    return out


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------- metrics
def classification_metrics(y_true, prob, threshold: float = 0.5) -> Dict[str, float]:
    from sklearn.metrics import (accuracy_score, balanced_accuracy_score, f1_score, precision_score,
                                 recall_score, roc_auc_score, average_precision_score)
    y = np.asarray(y_true).astype(int)
    p = np.asarray(prob, dtype=float)
    pred = (p >= threshold).astype(int)
    tn = int(((pred == 0) & (y == 0)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    tp = int(((pred == 1) & (y == 1)).sum())
    both = len(np.unique(y)) == 2
    return {
        "n": int(len(y)), "positive_share": float(y.mean()) if len(y) else float("nan"),
        "accuracy": float(accuracy_score(y, pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y, pred)) if both else float("nan"),
        "precision": float(precision_score(y, pred, zero_division=0)),
        "recall": float(recall_score(y, pred, zero_division=0)),
        "f1": float(f1_score(y, pred, zero_division=0)),
        "roc_auc": float(roc_auc_score(y, p)) if both else float("nan"),
        "average_precision": float(average_precision_score(y, p)) if both else float("nan"),
        "confusion": {"tn": tn, "fp": fp, "fn": fn, "tp": tp},
        "threshold": float(threshold),
    }


def regression_metrics(y_true, y_pred) -> Dict[str, float]:
    """MAE, RMSE, R2; CV(RMSE) and NMBE as in ASHRAE Guideline 14 (in %, relative to the mean)."""
    y = np.asarray(y_true, dtype=float)
    f = np.asarray(y_pred, dtype=float)
    ok = np.isfinite(y) & np.isfinite(f)
    y, f = y[ok], f[ok]
    err = f - y
    mean = float(y.mean()) if len(y) else float("nan")
    ss_tot = float(((y - mean) ** 2).sum())
    rmse = float(math.sqrt((err ** 2).mean())) if len(y) else float("nan")
    return {
        "n": int(len(y)), "mae": float(np.abs(err).mean()) if len(y) else float("nan"), "rmse": rmse,
        "bias": float(err.mean()) if len(y) else float("nan"),
        "r2": float(1 - (err ** 2).sum() / ss_tot) if ss_tot > 0 else float("nan"),
        "cv_rmse_pct": 100.0 * rmse / mean if mean else float("nan"),
        "nmbe_pct": 100.0 * float(err.sum()) / (len(y) * mean) if mean else float("nan"),
    }


def rounded(obj, nd: int = 4):
    if isinstance(obj, float):
        return round(obj, nd) if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: rounded(v, nd) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [rounded(v, nd) for v in obj]
    if isinstance(obj, (np.floating,)):
        return rounded(float(obj), nd)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    return obj


# ---------------------------------------------------------------------- artifacts
def next_version(task: str) -> str:
    d = os.path.join(REGISTRY_DIR, task)
    nums = []
    if os.path.isdir(d):
        for name in os.listdir(d):
            if name.startswith("v") and name[1:].isdigit():
                nums.append(int(name[1:]))
    return f"v{(max(nums) + 1) if nums else 1}"


def write_artifact(task: str, version: str, metadata: Dict, card: str, portable: Optional[Dict] = None,
                   sk_object=None) -> str:
    d = os.path.join(REGISTRY_DIR, task, version)
    os.makedirs(d, exist_ok=True)
    files = {}
    if portable is not None:
        p = os.path.join(d, "model.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(portable, f, separators=(",", ":"))
        files["model.json"] = {"sha256": sha256_file(p), "bytes": os.path.getsize(p)}
    if sk_object is not None:
        import joblib
        p = os.path.join(d, "model.joblib")
        joblib.dump(sk_object, p, compress=3)
        files["model.joblib"] = {"sha256": sha256_file(p), "bytes": os.path.getsize(p)}
    metadata = dict(metadata, task=task, version=version, files=files)
    with open(os.path.join(d, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(rounded(metadata, 6), f, indent=2, default=str)
        f.write("\n")
    with open(os.path.join(d, "model_card.md"), "w", encoding="utf-8") as f:
        f.write(card)
    return d


def md_table(rows: List[Dict], cols: Sequence[str], fmt: Optional[Dict[str, str]] = None) -> str:
    fmt = fmt or {}
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        cells = []
        for c in cols:
            v = r.get(c, "")
            if isinstance(v, float):
                v = format(v, fmt.get(c, ".3f")) if math.isfinite(v) else "n/a"
            cells.append(str(v))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def feature_reference(X: np.ndarray, features: Sequence[str]) -> Dict[str, Dict]:
    """Training distribution of each feature, kept in the metadata for drift checks (ml/drift.py)."""
    X = np.asarray(X, dtype=float)
    out = {}
    for j, f in enumerate(features):
        col = X[:, j]
        ok = col[np.isfinite(col)]
        if len(ok) == 0:
            out[f] = {"missing_share": 1.0}
            continue
        q = np.quantile(ok, np.linspace(0, 1, 11))
        out[f] = {"deciles": [float(v) for v in q], "mean": float(ok.mean()), "std": float(ok.std()),
                  "min": float(ok.min()), "max": float(ok.max()), "missing_share": float(1 - len(ok) / len(col))}
    return out
