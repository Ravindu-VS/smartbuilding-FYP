"""
Data-drift and input-quality checks for deployed models.

Each registered model stores the training distribution of its features
(metadata["feature_reference"]: deciles, mean, std, range, missing share).  DriftMonitor keeps
a rolling window of the live feature vectors and reports, per feature:
  psi            population stability index against the training deciles
                 (< 0.10 stable, 0.10-0.25 moderate shift, > 0.25 significant shift)
  out_of_range   share of values outside the training minimum..maximum
  missing_share  share of missing values (compared with training)
A drift report is a warning for the operator and an input to the retraining decision
(scripts/retrain.py); it never changes the controller by itself.
"""
from __future__ import annotations

from collections import deque
from typing import Deque, Dict, List, Optional, Sequence

import numpy as np

PSI_MODERATE, PSI_SIGNIFICANT = 0.10, 0.25


def psi(values: np.ndarray, deciles: Sequence[float]) -> float:
    edges = np.unique(np.asarray(deciles, dtype=float))
    if len(edges) < 3 or len(values) == 0:
        return float("nan")
    inner = edges[1:-1]
    ref_counts = np.full(len(inner) + 1, 1.0 / (len(inner) + 1))      # deciles: equal shares by construction
    idx = np.searchsorted(inner, values, side="right")
    act = np.bincount(idx, minlength=len(inner) + 1) / len(values)
    eps = 1e-4
    a, e = np.clip(act, eps, None), np.clip(ref_counts, eps, None)
    return float(np.sum((a - e) * np.log(a / e)))


class DriftMonitor:
    def __init__(self, features: Sequence[str], reference: Dict[str, Dict], window: int = 2000, min_rows: int = 200):
        self.features = list(features)
        self.reference = reference
        self.rows: Deque[np.ndarray] = deque(maxlen=window)
        self.min_rows = min_rows

    def add(self, x: Sequence[float]) -> None:
        self.rows.append(np.asarray(x, dtype=float))

    def report(self) -> Dict:
        n = len(self.rows)
        out: Dict = {"rows": n, "enough_data": n >= self.min_rows, "features": {}, "status": "insufficient data"}
        if n == 0:
            return out
        X = np.stack(self.rows)
        worst = 0.0
        for j, f in enumerate(self.features):
            ref = self.reference.get(f, {})
            col = X[:, j]
            ok = col[np.isfinite(col)]
            item = {"missing_share": float(1 - len(ok) / len(col)), "train_missing_share": ref.get("missing_share")}
            if "deciles" in ref and len(ok):
                v = psi(ok, ref["deciles"])
                if np.isfinite(v):
                    item["psi"] = v
                    worst = max(worst, v)
                else:                       # e.g. a 0/1 feature: fewer than 3 distinct training deciles
                    item["psi"] = None
                    item["psi_note"] = "not defined for this feature (fewer than 3 distinct training deciles)"
                item["out_of_range"] = float(np.mean((ok < ref["min"]) | (ok > ref["max"])))
                item["mean"], item["train_mean"] = float(ok.mean()), ref["mean"]
            out["features"][f] = item
        out["max_psi"] = worst
        if n >= self.min_rows:
            out["status"] = ("significant drift" if worst > PSI_SIGNIFICANT else
                             "moderate drift" if worst > PSI_MODERATE else "stable")
        return out
