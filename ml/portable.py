"""
Portable models: a plain-JSON form of fitted scikit-learn models, evaluated with numpy only.

Why: a scikit-learn pickle only loads reliably under the scikit-learn version that wrote
it (this broke the live system once: a 1.7.2 pickle failed under 1.8.0).  The JSON form has
no such dependency, so the Raspberry Pi needs numpy only, and the training stack is not
part of the edge install.  The exporter checks the JSON model against scikit-learn on the
training data and stores reference samples; `Portable.self_test()` re-checks them at load.

Supported (format "smartbuilding-model/2"):
  preprocessing   median imputation (optional), standard scaling (optional)
  classifiers     LogisticRegression, DecisionTreeClassifier, RandomForestClassifier,
                  HistGradientBoostingClassifier (binary), MLPClassifier (relu/tanh)
  regressors      Ridge/LinearRegression, DecisionTreeRegressor, RandomForestRegressor,
                  HistGradientBoostingRegressor, MLPRegressor
Output: classifiers give P(class 1); regressors give the predicted value.
"""
from __future__ import annotations

import json
import math
from typing import Dict, List, Optional, Sequence

import numpy as np

FORMAT = "smartbuilding-model/2"


class ModelError(RuntimeError):
    """A model cannot be loaded, fails its self-test, or gets unusable input."""


# ====================================================================== export
def _tree_dict(t, kind: str) -> Dict:
    left = t.children_left.astype(int)
    right = t.children_right.astype(int)
    if kind == "classification":
        v = t.value[:, 0, :]
        tot = v.sum(axis=1)
        val = np.where(tot > 0, v[:, 1] / np.maximum(tot, 1e-12), 0.0)
    else:
        val = t.value[:, 0, 0]
    miss = getattr(t, "missing_go_to_left", None)
    return {"left": left.tolist(), "right": right.tolist(), "feature": t.feature.astype(int).tolist(),
            "threshold": [float(x) for x in t.threshold], "value": [float(x) for x in val],
            "missing_left": (np.asarray(miss).astype(int).tolist() if miss is not None else [0] * len(left))}


def _hgb_trees(est) -> List[Dict]:
    trees = []
    for it in est._predictors:
        if len(it) != 1:
            raise ModelError("only binary classification / single-output regression is supported")
        nodes = it[0].nodes
        leaf = nodes["is_leaf"].astype(bool)
        left = np.where(leaf, -1, nodes["left"].astype(int))
        right = np.where(leaf, -1, nodes["right"].astype(int))
        trees.append({"left": left.tolist(), "right": right.tolist(),
                      "feature": nodes["feature_idx"].astype(int).tolist(),
                      "threshold": [float(x) for x in nodes["num_threshold"]],
                      "value": [float(x) for x in nodes["value"]],
                      "missing_left": nodes["missing_go_to_left"].astype(int).tolist()})
        if np.any(nodes["is_categorical"]):
            raise ModelError("categorical splits are not supported")
    return trees


def export(estimator, features: Sequence[str], kind: str, threshold: float = 0.5,
           X_check: Optional[np.ndarray] = None, n_reference: int = 32) -> Dict:
    """Convert a fitted estimator or Pipeline(imputer?, scaler?, model) into a JSON-able dict."""
    if kind not in ("classification", "regression"):
        raise ValueError("kind must be 'classification' or 'regression'")
    steps = dict(getattr(estimator, "named_steps", {"model": estimator}))
    model = steps.get("model") or list(steps.values())[-1]
    imp, sc = steps.get("imputer"), steps.get("scaler")
    spec: Dict = {"format": FORMAT, "kind": kind, "features": list(features), "threshold": float(threshold)}
    if imp is not None:
        spec["impute_median"] = [float(v) for v in imp.statistics_]
    if sc is not None:
        spec["scaler"] = {"mean": [float(v) for v in (sc.mean_ if sc.with_mean else np.zeros(len(features)))],
                          "scale": [float(v) for v in (sc.scale_ if sc.with_std else np.ones(len(features)))]}
    name = type(model).__name__
    if name == "LogisticRegression":
        spec["model_type"] = "linear"
        spec["linear"] = {"coef": [float(v) for v in model.coef_[0]], "intercept": float(model.intercept_[0]),
                          "link": "logistic"}
    elif name in ("Ridge", "LinearRegression"):
        coef = np.ravel(model.coef_)
        spec["model_type"] = "linear"
        spec["linear"] = {"coef": [float(v) for v in coef], "intercept": float(np.ravel([model.intercept_])[0]),
                          "link": "identity"}
    elif name in ("DecisionTreeClassifier", "DecisionTreeRegressor"):
        spec["model_type"] = "forest"
        spec["forest"] = {"trees": [_tree_dict(model.tree_, kind)], "combine": "mean", "base": 0.0,
                          "float32_inputs": True}
    elif name in ("RandomForestClassifier", "RandomForestRegressor", "ExtraTreesClassifier", "ExtraTreesRegressor"):
        spec["model_type"] = "forest"
        spec["forest"] = {"trees": [_tree_dict(e.tree_, kind) for e in model.estimators_], "combine": "mean",
                          "base": 0.0, "float32_inputs": True}   # sklearn trees compare float32 inputs
    elif name in ("HistGradientBoostingClassifier", "HistGradientBoostingRegressor"):
        base = float(np.ravel(model._baseline_prediction)[0])
        spec["model_type"] = "forest"
        spec["forest"] = {"trees": _hgb_trees(model), "combine": "sum", "base": base,
                          "link": "logistic" if kind == "classification" else "identity"}
    elif name in ("MLPClassifier", "MLPRegressor"):
        if model.activation not in ("relu", "tanh", "logistic", "identity"):
            raise ModelError(f"activation {model.activation} not supported")
        spec["model_type"] = "mlp"
        spec["mlp"] = {"weights": [w.tolist() for w in model.coefs_], "biases": [b.tolist() for b in model.intercepts_],
                       "activation": model.activation,
                       "out": "logistic" if kind == "classification" else "identity"}
    else:
        raise ModelError(f"model type {name} has no portable form")
    port = Portable(spec)
    if X_check is not None and len(X_check):
        X_check = np.asarray(X_check, dtype=float)
        ref = estimator.predict_proba(X_check)[:, 1] if kind == "classification" else estimator.predict(X_check)
        got = port.predict(X_check)
        worst = float(np.max(np.abs(got - ref)))
        spec["export_check"] = {"rows": int(len(X_check)), "max_abs_diff_vs_sklearn": worst}
        if worst > 1e-6:
            raise ModelError(f"portable model differs from scikit-learn by {worst:.3g}")
        idx = np.linspace(0, len(X_check) - 1, min(n_reference, len(X_check))).astype(int)
        spec["reference_samples"] = [{"x": [None if not math.isfinite(v) else float(v) for v in X_check[i]],
                                      "y": float(got[i])} for i in idx]
    return spec


# ====================================================================== evaluate
_ACT = {
    "relu": lambda z: np.maximum(z, 0.0),
    "tanh": np.tanh,
    "logistic": lambda z: 1.0 / (1.0 + np.exp(-z)),
    "identity": lambda z: z,
}


class Portable:
    def __init__(self, spec: Dict):
        if spec.get("format") != FORMAT:
            raise ModelError(f"unknown model format {spec.get('format')!r}")
        self.spec = spec
        self.kind = spec["kind"]
        self.features: List[str] = list(spec["features"])
        self.threshold = float(spec.get("threshold", 0.5))
        self.model_type = spec["model_type"]
        self._median = np.asarray(spec["impute_median"], float) if "impute_median" in spec else None
        sc = spec.get("scaler")
        self._mean = np.asarray(sc["mean"], float) if sc else None
        self._scale = np.asarray(sc["scale"], float) if sc else None
        if self.model_type == "forest":
            fo = spec["forest"]
            self._trees = [{k: np.asarray(v, dtype=float if k in ("threshold", "value") else int)
                            for k, v in t.items()} for t in fo["trees"]]
            self._combine, self._base = fo["combine"], float(fo.get("base", 0.0))
            self._link = fo.get("link", "identity")
            self._f32 = bool(fo.get("float32_inputs", False))
        elif self.model_type == "linear":
            self._coef = np.asarray(spec["linear"]["coef"], float)
            self._b = float(spec["linear"]["intercept"])
            self._link = spec["linear"]["link"]
        elif self.model_type == "mlp":
            m = spec["mlp"]
            self._W = [np.asarray(w, float) for w in m["weights"]]
            self._B = [np.asarray(b, float) for b in m["biases"]]
            self._act = _ACT[m["activation"]]
            self._out = m["out"]
        else:
            raise ModelError(f"unknown model type {self.model_type!r}")

    @classmethod
    def load(cls, path: str, self_test: bool = True) -> "Portable":
        try:
            with open(path, "r", encoding="utf-8") as f:
                p = cls(json.load(f))
        except (OSError, ValueError, KeyError) as e:
            raise ModelError(f"cannot load {path}: {e}") from e
        if self_test:
            p.self_test()
        return p

    # ------------------------------------------------------------------ #
    def _prepare(self, X) -> np.ndarray:
        X = np.array(X, dtype=float, copy=True)
        if X.ndim == 1:
            X = X[None, :]
        if X.shape[1] != len(self.features):
            raise ModelError(f"expected {len(self.features)} features {self.features}, got {X.shape[1]}")
        if np.isinf(X).any():
            raise ModelError("infinite input value")
        if self._median is not None:
            nan = np.isnan(X)
            if nan.any():
                X[nan] = np.broadcast_to(self._median, X.shape)[nan]
        if self._mean is not None:
            X = (X - self._mean) / self._scale
        return X

    @staticmethod
    def _tree_eval(t: Dict, X: np.ndarray) -> np.ndarray:
        n = X.shape[0]
        idx = np.zeros(n, dtype=int)
        rows = np.arange(n)
        left, right, feat, thr, miss = t["left"], t["right"], t["feature"], t["threshold"], t["missing_left"]
        for _ in range(len(left)):
            leaf = left[idx] == -1
            if leaf.all():
                break
            f = np.where(leaf, 0, feat[idx])
            x = X[rows, f]
            nan = np.isnan(x)
            go_left = np.where(nan, miss[idx] == 1, x <= thr[idx])
            idx = np.where(leaf, idx, np.where(go_left, left[idx], right[idx]))
        return t["value"][idx]

    def predict(self, X) -> np.ndarray:
        """P(class 1) for classifiers, the value for regressors; one per row."""
        Z = self._prepare(X)
        if self.model_type == "linear":
            z = Z @ self._coef + self._b
            return 1.0 / (1.0 + np.exp(-z)) if self._link == "logistic" else z
        if self.model_type == "mlp":
            a = Z
            for i, (W, B) in enumerate(zip(self._W, self._B)):
                a = a @ W + B
                if i < len(self._W) - 1:
                    a = self._act(a)
            a = a[:, 0]
            return 1.0 / (1.0 + np.exp(-a)) if self._out == "logistic" else a
        if self._f32:
            Z = Z.astype(np.float32).astype(np.float64)
        vals = np.stack([self._tree_eval(t, Z) for t in self._trees])
        raw = vals.mean(axis=0) if self._combine == "mean" else self._base + vals.sum(axis=0)
        if self._link == "logistic":
            return 1.0 / (1.0 + np.exp(-raw))
        return raw

    def predict_label(self, X) -> np.ndarray:
        if self.kind != "classification":
            raise ModelError("predict_label is for classifiers")
        return (self.predict(X) >= self.threshold).astype(int)

    def vector(self, values: Dict[str, Optional[float]], allow_missing: Sequence[str] = ()) -> np.ndarray:
        """Feature vector in the model's order.  A feature absent from `values` raises
        ModelError unless listed in allow_missing (then it is NaN, imputed if the model
        imputes); None/NaN values are passed as NaN."""
        row = []
        for f in self.features:
            if f not in values and f not in allow_missing:
                raise ModelError(f"missing feature {f!r}")
            v = values.get(f)
            row.append(np.nan if v is None or (isinstance(v, float) and math.isnan(v)) else float(v))
        return np.asarray(row, dtype=float)

    def self_test(self, tol: float = 1e-9) -> None:
        samples = self.spec.get("reference_samples") or []
        if not samples:
            raise ModelError("model has no reference samples for its self-test")
        X = np.asarray([[np.nan if v is None else v for v in s["x"]] for s in samples], dtype=float)
        exp = np.asarray([s["y"] for s in samples], dtype=float)
        got = self.predict(X)
        worst = float(np.max(np.abs(got - exp)))
        if worst > tol:
            raise ModelError(f"self-test failed (max difference {worst:.3g})")
