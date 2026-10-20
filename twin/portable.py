"""
Copied unchanged from the thesis code (ml/portable.py, commit eb82674).

Portable occupancy model: a plain-JSON representation of a fitted
logistic-regression or decision-tree pipeline, evaluated with numpy only.

Why: a scikit-learn pickle only loads reliably under the exact scikit-learn
version that wrote it (this broke the live system: a 1.7.2 pickle raised inside
predict() under 1.8.0 and every prediction silently became 0.0).  A JSON model
has no such dependency, and the same numbers are exported to C for the ESP32.
"""
from __future__ import annotations

import json
import math
from typing import Dict, List, Optional, Sequence

import numpy as np

FORMAT = "smartbuilding-occupancy-model/1"


class ModelError(RuntimeError):
    """Raised when a model cannot be loaded or fails its self-test."""


def export_pipeline(pipeline, features: Sequence[str], threshold: float,
                    medians: Sequence[float]) -> Dict:
    """Convert a fitted sklearn Pipeline(imputer?, scaler?, model) into a dict."""
    steps = dict(pipeline.named_steps)
    model = steps.get("model")
    scaler = steps.get("scaler")
    out: Dict = {
        "format": FORMAT,
        "features": list(features),
        "threshold": float(threshold),
        "impute_median": [float(m) for m in medians],
    }
    if scaler is not None:
        out["scaler"] = {"mean": [float(v) for v in scaler.mean_],
                         "scale": [float(v) for v in scaler.scale_]}
    name = type(model).__name__
    if name == "LogisticRegression":
        out["model_type"] = "logistic_regression"
        out["lr"] = {"coef": [float(v) for v in model.coef_[0]],
                     "intercept": float(model.intercept_[0])}
    elif name == "DecisionTreeClassifier":
        t = model.tree_
        # probability of class 1 at each node
        values = t.value[:, 0, :]
        totals = values.sum(axis=1)
        p1 = np.where(totals > 0, values[:, 1] / np.maximum(totals, 1e-12), 0.0)
        out["model_type"] = "decision_tree"
        out["tree"] = {
            "children_left": [int(v) for v in t.children_left],
            "children_right": [int(v) for v in t.children_right],
            "feature": [int(v) for v in t.feature],
            "threshold": [float(v) for v in t.threshold],
            "p1": [float(v) for v in p1],
        }
    else:
        raise ModelError(f"Model type {name} has no portable form")
    return out


class PortableModel:
    """numpy-only evaluation of an exported model."""

    def __init__(self, spec: Dict):
        if spec.get("format") != FORMAT:
            raise ModelError(f"Unknown model format: {spec.get('format')}")
        self.spec = spec
        self.features: List[str] = list(spec["features"])
        self.threshold: float = float(spec["threshold"])
        self.model_type: str = spec["model_type"]
        self._median = np.asarray(spec["impute_median"], dtype=float)
        sc = spec.get("scaler")
        self._mean = np.asarray(sc["mean"], dtype=float) if sc else None
        self._scale = np.asarray(sc["scale"], dtype=float) if sc else None
        if self.model_type == "logistic_regression":
            self._coef = np.asarray(spec["lr"]["coef"], dtype=float)
            self._b = float(spec["lr"]["intercept"])
        elif self.model_type == "decision_tree":
            tr = spec["tree"]
            self._left = np.asarray(tr["children_left"], dtype=int)
            self._right = np.asarray(tr["children_right"], dtype=int)
            self._feat = np.asarray(tr["feature"], dtype=int)
            self._thr = np.asarray(tr["threshold"], dtype=float)
            self._p1 = np.asarray(tr["p1"], dtype=float)
        else:
            raise ModelError(f"Unknown model type {self.model_type}")

    @classmethod
    def load(cls, path: str) -> "PortableModel":
        with open(path, "r", encoding="utf-8") as f:
            return cls(json.load(f))

    # ------------------------------------------------------------------ #
    def _prepare(self, X: np.ndarray) -> np.ndarray:
        X = np.array(X, dtype=float, copy=True)
        if X.ndim == 1:
            X = X[None, :]
        nan = np.isnan(X)
        if nan.any():
            X[nan] = np.broadcast_to(self._median, X.shape)[nan]
        if self._mean is not None:
            X = (X - self._mean) / self._scale
        return X

    def predict_proba(self, X) -> np.ndarray:
        """Probability of 'occupied' for each row of X (n x n_features)."""
        Z = self._prepare(np.asarray(X, dtype=float))
        if self.model_type == "logistic_regression":
            z = Z @ self._coef + self._b
            return 1.0 / (1.0 + np.exp(-z))
        out = np.empty(Z.shape[0])
        for i, row in enumerate(Z):
            node = 0
            while self._left[node] != -1:
                node = self._left[node] if row[self._feat[node]] <= self._thr[node] else self._right[node]
            out[i] = self._p1[node]
        return out

    def predict(self, X) -> np.ndarray:
        return (self.predict_proba(X) >= self.threshold).astype(int)

    def vector_from_dict(self, values: Dict[str, Optional[float]]) -> np.ndarray:
        row = []
        for f in self.features:
            v = values.get(f)
            row.append(np.nan if v is None or (isinstance(v, float) and math.isnan(v)) else float(v))
        return np.asarray(row, dtype=float)

    def self_test(self, samples: Sequence[Dict], tol: float = 1e-9) -> None:
        """Re-evaluate stored reference samples; raise if any probability differs."""
        if not samples:
            raise ModelError("Model has no reference samples for its self-test")
        X = np.asarray([s["x"] for s in samples], dtype=float)
        expected = np.asarray([s["p"] for s in samples], dtype=float)
        got = self.predict_proba(X)
        worst = float(np.max(np.abs(got - expected)))
        if worst > tol:
            raise ModelError(f"Model self-test failed (max |dp| = {worst:.3g})")
