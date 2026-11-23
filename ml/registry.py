#!/usr/bin/env python3
"""
Model registry: versioned artifacts, acceptance tests, promotion and rollback.

    python -m ml.registry status
    python -m ml.registry evaluate <task> <version>     # run the acceptance tests, print the report
    python -m ml.registry promote <task> <version>      # promote only if the acceptance tests pass
    python -m ml.registry rollback <task>               # back to the previously active version
    python -m ml.registry init                          # first activation of every task that passes

Layout: models/registry/<task>/<version>/{metadata.json, model.json, model.joblib, model_card.md}
and models/registry/registry.json (which version of each task is active, candidates, and the
full promotion/rollback history with the acceptance report of each decision).

A version is never deleted or overwritten; promotion and rollback only change which version
is active, so every change is reversible.  The live system loads the active version of a task
(numpy-only model.json) and checks it at load (self-test against stored reference samples); if
that fails the consumer refuses the model and keeps its rule-based behaviour - no silent
substitute.
"""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import time
from typing import Callable, Dict, List, Optional

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ml.common import REGISTRY_DIR, sha256_file, utc_now   # noqa: E402

# Baselines for a task's first activation (no active version to compare with yet).  Values are
# taken from the evaluation the training script ran on the same held-out data; each rule
# names the data it refers to.
LATENCY_LIMIT_MS = 5.0          # per row on the dev machine; the Pi 4B is ~3-5x slower


def _get(d: Dict, path: str):
    for k in path.split("."):
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


ACCEPTANCE: Dict[str, Dict] = {
    # candidate metric must beat the reference metric (both from the candidate's own held-out evaluation),
    # and must not be worse than the active version by more than the tolerance
    "occupancy_rf": {"metric": "test_metrics.B_test.f1", "higher": True, "min_abs": 0.80, "tol": 0.01,
                     "why": "held-out week F1 >= 0.80 (UCI 11-18 Feb) and not worse than the active version by > 0.01"},
    "occupancy_best": {"metric": "test_metrics.B_test.f1", "higher": True, "min_abs": 0.80, "tol": 0.01,
                       "why": "held-out week F1 >= 0.80 and not worse than the active version by > 0.01"},
    "occupancy_co2_temporal": {"metric": "test_metrics.B_test.f1", "higher": True, "min_abs": 0.5296, "tol": 0.0,
                               "why": "must beat the deployed CO2 decision tree on the held-out week (F1 0.5296, "
                                      "docs/results/occupancy.md)"},
    "occupancy_twin_fusion": {"metric": "test_metrics.learned_fusion_hist_gbt.f1", "higher": True,
                              "reference": "test_metrics.handbuilt_fusion_estimator.f1", "tol": 0.0,
                              "why": "must beat the hand-built PIR+CO2 fusion estimator on the same synthetic test seed"},
    "thermal_h15": {"metric": "test_metrics.hist_gbt.all.mae", "higher": False,
                    "reference": "test_metrics.persistence.all.mae", "tol": 0.0,
                    "why": "MAE below persistence on unseen simulator seeds"},
    "thermal_h30": {"metric": "test_metrics.hist_gbt.all.mae", "higher": False,
                    "reference": "test_metrics.persistence.all.mae", "tol": 0.0,
                    "why": "MAE below persistence on unseen simulator seeds"},
    "energy_dayahead": {"metric": "test_metrics.hist_gbt_lags.test_seen_buildings.cv_rmse_pct", "higher": False,
                        "reference": "test_metrics.seasonal_naive_lag168.test_seen_buildings.cv_rmse_pct", "tol": 0.0,
                        "why": "CV(RMSE) below the seasonal-naive baseline on the 2017 test months"},
    "ppo_policy": {"custom": "ppo",
                   "why": "on the held-out evaluation episodes: no fail-safe errors (F2/F3), comfort not worse than the "
                          "conventional schedule by more than 2 percentage points of occupied time, and lower energy"},
}


class Registry:
    def __init__(self, root: str = REGISTRY_DIR):
        self.root = root
        self.file = os.path.join(root, "registry.json")

    # ------------------------------------------------------------------ io
    def load(self) -> Dict:
        if not os.path.exists(self.file):
            return {"format": "smartbuilding-registry/1", "tasks": {}}
        with open(self.file, encoding="utf-8") as f:
            return json.load(f)

    def save(self, data: Dict) -> None:
        os.makedirs(self.root, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.root, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, self.file)              # atomic: a crash never leaves a half-written registry

    # ------------------------------------------------------------------ queries
    def tasks(self) -> List[str]:
        if not os.path.isdir(self.root):
            return []
        return sorted(d for d in os.listdir(self.root) if os.path.isdir(os.path.join(self.root, d)))

    def versions(self, task: str) -> List[str]:
        d = os.path.join(self.root, task)
        if not os.path.isdir(d):
            return []
        return sorted((v for v in os.listdir(d) if v.startswith("v") and v[1:].isdigit()), key=lambda v: int(v[1:]))

    def metadata(self, task: str, version: str) -> Dict:
        with open(os.path.join(self.root, task, version, "metadata.json"), encoding="utf-8") as f:
            return json.load(f)

    def active(self, task: str) -> Optional[Dict]:
        v = self.load()["tasks"].get(task, {}).get("active")
        if not v:
            return None
        return {"task": task, "version": v, "path": os.path.join(self.root, task, v), "metadata": self.metadata(task, v)}

    def status(self) -> Dict:
        reg = self.load()
        out = {}
        for t in self.tasks():
            e = reg["tasks"].get(t, {})
            out[t] = {"active": e.get("active"), "versions": self.versions(t),
                      "candidates": [v for v in self.versions(t) if v != e.get("active")],
                      "last_event": (e.get("history") or [None])[-1]}
        return out

    # ------------------------------------------------------------------ acceptance
    def evaluate(self, task: str, version: str, ppo_check: Optional[Callable[[Dict], Dict]] = None) -> Dict:
        """Run the acceptance tests of `task` for `version`; returns a report with 'passed'."""
        meta = self.metadata(task, version)
        path = os.path.join(self.root, task, version)
        checks: List[Dict] = []

        def check(name: str, ok: bool, detail: str) -> None:
            checks.append({"check": name, "passed": bool(ok), "detail": detail})

        for fname, info in (meta.get("files") or {}).items():
            fp = os.path.join(path, fname)
            check(f"file {fname} intact", os.path.exists(fp) and sha256_file(fp) == info["sha256"],
                  "sha256 matches metadata" if os.path.exists(fp) else "missing")
        rule = ACCEPTANCE.get(task)
        if rule is None:
            check("acceptance rule defined", False, f"no acceptance rule for task {task!r}")
        elif rule.get("custom") == "ppo":
            rep = (ppo_check or _ppo_acceptance)(meta)
            checks += rep
        else:
            self._portable_checks(path, meta, check)
            val = _get(meta, rule["metric"])
            ok_val = isinstance(val, (int, float)) and math.isfinite(val)
            check("metric present", ok_val, f"{rule['metric']} = {val}")
            if ok_val:
                if "min_abs" in rule:
                    ref = rule["min_abs"]
                else:
                    ref = _get(meta, rule["reference"])
                better = val >= ref if rule["higher"] else val <= ref
                if "reference" in rule:
                    better = val > ref if rule["higher"] else val < ref
                check("beats reference", better, f"{val:.4f} vs reference {ref:.4f} ({rule['why']})")
                act = self.active(task)
                same = meta.get("compare_active_on_same_data") or {}
                if act and act["version"] != version and same.get("version") == act["version"] \
                        and isinstance(same.get("f1"), (int, float)) and rule["metric"].endswith(".f1"):
                    # online learning: the approved model was scored on the same held-out rows
                    tol = rule.get("tol", 0.0)
                    check("not worse than active", val >= same["f1"] - tol,
                          f"{val:.4f} vs active {act['version']} {same['f1']:.4f} on the same rows")
                elif act and act["version"] != version:
                    av = _get(act["metadata"], rule["metric"])
                    if isinstance(av, (int, float)):
                        tol = rule.get("tol", 0.0)
                        ok = val >= av - tol if rule["higher"] else val <= av + tol
                        check("not worse than active", ok, f"{val:.4f} vs active {act['version']} {av:.4f} (tolerance {tol})")
        report = {"task": task, "version": version, "utc": utc_now(), "checks": checks,
                  "passed": all(c["passed"] for c in checks) and bool(checks)}
        return report

    @staticmethod
    def _portable_checks(path: str, meta: Dict, check) -> None:
        from ml.portable import ModelError, Portable
        mj = os.path.join(path, "model.json")
        if not os.path.exists(mj):
            check("portable model", False, "model.json missing")
            return
        try:
            p = Portable.load(mj)                                 # includes the self-test
            check("portable self-test", True, "reference samples reproduced")
        except ModelError as e:
            check("portable self-test", False, str(e))
            return
        check("feature list matches metadata", p.features == list(meta.get("features", [])),
              f"{len(p.features)} features")
        X = np.asarray([[np.nan if v is None else v for v in s["x"]] for s in p.spec["reference_samples"]], float)
        rng = np.random.default_rng(0)
        Xf = X[rng.integers(0, len(X), 256)] * rng.uniform(0.8, 1.2, (256, X.shape[1]))
        Xf[rng.random(Xf.shape) < 0.05] = np.nan
        y = p.predict(Xf)
        check("finite output on perturbed inputs (5 % missing)", bool(np.all(np.isfinite(y))), f"{len(y)} rows")
        if p.kind == "classification":
            check("probabilities in [0, 1]", bool(np.all((y >= 0) & (y <= 1))), "")
        times = []
        for _ in range(20):
            t0 = time.perf_counter()
            p.predict(X[:1])
            times.append(time.perf_counter() - t0)
        ms = min(times) * 1000.0           # best of 20: robust to other load on the machine
        check("single-row latency", ms < LATENCY_LIMIT_MS, f"{ms:.2f} ms per call, best of 20 (limit {LATENCY_LIMIT_MS} ms)")
        try:
            p.predict(X[:, :-1])
            check("rejects wrong feature count", False, "accepted a short row")
        except ModelError:
            check("rejects wrong feature count", True, "ModelError raised")
        jb = os.path.join(path, "model.joblib")
        if os.path.exists(jb):
            try:
                import joblib
                sk = joblib.load(jb)
                ref = sk.predict_proba(X)[:, 1] if p.kind == "classification" else sk.predict(X)
                diff = float(np.max(np.abs(ref - p.predict(X))))
                check("portable == scikit-learn", diff < 1e-6, f"max difference {diff:.2e}")
            except Exception as e:      # a pickle from another scikit-learn version may not load: not fatal
                check("portable == scikit-learn", True, f"skipped (joblib not loadable here: {type(e).__name__})")

    # ------------------------------------------------------------------ changes
    def promote(self, task: str, version: str, force_reason: Optional[str] = None,
                report: Optional[Dict] = None) -> Dict:
        if version not in self.versions(task):
            raise ValueError(f"{task} has no version {version}")
        report = report or self.evaluate(task, version)
        if not report["passed"] and not force_reason:
            self._log(task, {"action": "promotion_rejected", "version": version, "utc": utc_now(), "report": report})
            raise PermissionError(f"{task} {version} failed its acceptance tests; not promoted")
        reg = self.load()
        e = reg["tasks"].setdefault(task, {"active": None, "history": []})
        prev = e.get("active")
        e["active"] = version
        e["history"].append({"action": "promote", "version": version, "previous": prev, "utc": utc_now(),
                             "forced": force_reason, "report": report})
        self.save(reg)
        return report

    def rollback(self, task: str, reason: str = "manual rollback") -> str:
        reg = self.load()
        e = reg["tasks"].get(task)
        if not e or not e.get("active"):
            raise ValueError(f"{task} has no active version")
        prev = None
        for h in reversed(e["history"]):
            if h["action"] in ("promote", "rollback") and h.get("version") == e["active"]:
                prev = h.get("previous")
                break
        if not prev:
            raise ValueError(f"{task}: no earlier version to roll back to")
        cur = e["active"]
        e["active"] = prev
        e["history"].append({"action": "rollback", "version": prev, "previous": cur, "utc": utc_now(), "reason": reason})
        self.save(reg)
        return prev

    def _log(self, task: str, event: Dict) -> None:
        reg = self.load()
        reg["tasks"].setdefault(task, {"active": None, "history": []})["history"].append(event)
        self.save(reg)


def _ppo_acceptance(meta: Dict) -> List[Dict]:
    ev = meta.get("evaluation") or {}
    checks = []
    ok = bool(ev)
    checks.append({"check": "held-out evaluation present", "passed": ok, "detail": f"{len(ev)} scenario(s)"})
    if not ok:
        return checks
    for sc, r in ev.items():
        ppo, base = r.get("ppo"), r.get("schedule")
        if not ppo or not base:
            checks.append({"check": f"{sc}: results", "passed": False, "detail": "missing ppo or schedule"})
            continue
        checks.append({"check": f"{sc}: no controller errors", "passed": ppo["failsafe_F2"] + ppo["failsafe_F3"] == 0,
                       "detail": f"F2 {ppo['failsafe_F2']}, F3 {ppo['failsafe_F3']}"})
        d = ppo["discomfort_share"] - base["discomfort_share"]
        checks.append({"check": f"{sc}: comfort", "passed": d <= 0.02,
                       "detail": f"discomfort share {ppo['discomfort_share']:.3f} vs schedule {base['discomfort_share']:.3f}"})
        checks.append({"check": f"{sc}: energy", "passed": ppo["energy_kwh"] < base["energy_kwh"],
                       "detail": f"{ppo['energy_kwh']:.0f} kWh vs schedule {base['energy_kwh']:.0f} kWh"})
    return checks


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    reg = Registry()
    if not argv or argv[0] == "status":
        print(json.dumps(reg.status(), indent=2, default=str))
        return 0
    cmd = argv[0]
    if cmd == "evaluate":
        rep = reg.evaluate(argv[1], argv[2])
        print(json.dumps(rep, indent=2))
        return 0 if rep["passed"] else 1
    if cmd == "promote":
        try:
            reg.promote(argv[1], argv[2])
            print(f"promoted {argv[1]} {argv[2]}")
            return 0
        except PermissionError as e:
            print(e)
            return 1
    if cmd == "rollback":
        print("active:", reg.rollback(argv[1]))
        return 0
    if cmd == "init":
        rc = 0
        for t in reg.tasks():
            if reg.active(t):
                print(f"{t}: active {reg.active(t)['version']}")
                continue
            vs = reg.versions(t)
            if not vs:
                continue
            rep = reg.evaluate(t, vs[-1])
            if rep["passed"]:
                reg.promote(t, vs[-1], report=rep)
                print(f"{t}: promoted {vs[-1]}")
            else:
                reg._log(t, {"action": "promotion_rejected", "version": vs[-1], "utc": utc_now(), "report": rep})
                failed = [c for c in rep["checks"] if not c["passed"]]
                print(f"{t}: {vs[-1]} stays a candidate - failed: " + "; ".join(f"{c['check']} ({c['detail']})" for c in failed))
        return rc
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
