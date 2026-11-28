"""
Promotion gate for the MLflow Model Registry: a new version becomes `production` only when it passes the
acceptance thresholds and beats the current production version on the same held-out test set.

Aliases
  challenger   the newest registered version (always moved)
  production   the version the serving API loads; moved only by this gate or by an explicit rollback
Every decision is written to the version's tags (gate_decision, gate_reason, compared_with) so a replacement
is never silent.

    python -m mlops.promote status
    python -m mlops.promote rollback            # production -> the version it replaced
    python -m mlops.promote promote 4 --reason "..."   # deliberate human promotion (acceptance floor still applies)
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time

os.environ.setdefault("MLFLOW_DISABLE_TELEMETRY", "true")
os.environ.setdefault("DO_NOT_TRACK", "1")
from typing import Dict, Optional

log = logging.getLogger("mlops.promote")
ACCEPTANCE = {"f1": 0.90, "balanced_accuracy": 0.90}     # absolute floor on the test set
MIN_GAIN = 0.002                                          # must beat production F1 by at least this much


def _client(tracking_uri: Optional[str]):
    import mlflow
    from mlflow import MlflowClient
    if tracking_uri:
        mlflow.set_tracking_uri(tracking_uri)
    return MlflowClient()


def _score(model_uri: str, parts) -> Dict:
    """Score a registered model on the test split with the feature list stored in ITS OWN metadata, so an old
    production model is evaluated correctly even after the code's feature sets have changed."""
    import mlflow
    import mlflow.sklearn
    from ml.common import classification_metrics
    from mlops.data import TARGET
    feats = (mlflow.models.get_model_info(model_uri).metadata or {}).get("features")
    if not feats:
        raise ValueError(f"{model_uri} has no feature list in its metadata")
    m = mlflow.sklearn.load_model(model_uri)
    test = parts["test"]
    return classification_metrics(test[TARGET].to_numpy(int), m.predict_proba(test[feats].to_numpy(float))[:, 1])


def gate(name: str, version: str, parts, tracking_uri: Optional[str] = None) -> Dict:
    c = _client(tracking_uri)
    new = _score(f"models:/{name}/{version}", parts)
    c.set_registered_model_alias(name, "challenger", version)
    champ = None
    try:
        champ = c.get_model_version_by_alias(name, "production")
    except Exception:
        pass
    old = None
    if champ is not None and str(champ.version) != str(version):
        old = _score(f"models:/{name}/{champ.version}", parts)

    fails = [f"{k} {new[k]:.4f} < {v}" for k, v in ACCEPTANCE.items() if not new[k] >= v]
    if fails:
        decision, reason = "rejected", "below acceptance: " + "; ".join(fails)
    elif old is None:
        decision, reason = "promoted", "first production version; acceptance passed"
    elif new["f1"] >= old["f1"] + MIN_GAIN:
        decision, reason = "promoted", f"test F1 {new['f1']:.4f} beats production v{champ.version} {old['f1']:.4f}"
    else:
        decision, reason = "kept_production", (f"test F1 {new['f1']:.4f} does not beat production v{champ.version} "
                                               f"{old['f1']:.4f} by {MIN_GAIN}")
    tags = {"gate_decision": decision, "gate_reason": reason, "gate_time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "gate_test_f1": f"{new['f1']:.4f}", "compared_with": f"v{champ.version}" if champ else "none"}
    for k, v in tags.items():
        c.set_model_version_tag(name, version, k, v)
    if decision == "promoted":
        if champ is not None:
            c.set_model_version_tag(name, version, "replaced_production", str(champ.version))
            c.set_registered_model_alias(name, "previous_production", str(champ.version))
        c.set_registered_model_alias(name, "production", version)
    log.info("gate %s v%s: %s (%s)", name, version, decision, reason)
    return {"decision": decision, "reason": reason, "challenger_test": new, "production_test": old,
            "production_version": str(version) if decision == "promoted" else (str(champ.version) if champ else None)}


def promote_manually(name: str, version: str, reason: str, tracking_uri: Optional[str] = None) -> Dict:
    """A deliberate human decision (e.g. a feature-set change that trades a little test score for robustness).
    The acceptance floor still applies; the reason and the replaced version are recorded on the version."""
    if not reason or len(reason.strip()) < 10:
        raise ValueError("a manual promotion needs a written reason (at least 10 characters)")
    c = _client(tracking_uri)
    mv = c.get_model_version(name, version)
    f1 = float(c.get_run(mv.run_id).data.metrics.get("test_f1", 0.0))
    bal = float(c.get_run(mv.run_id).data.metrics.get("test_balanced_accuracy", 0.0))
    if f1 < ACCEPTANCE["f1"] or bal < ACCEPTANCE["balanced_accuracy"]:
        raise ValueError(f"v{version} is below the acceptance floor (test F1 {f1:.4f}, balanced accuracy {bal:.4f})")
    old = None
    try:
        old = str(c.get_model_version_by_alias(name, "production").version)
    except Exception:
        pass
    if old and old != str(version):
        c.set_registered_model_alias(name, "previous_production", old)
        c.set_model_version_tag(name, version, "replaced_production", old)
    c.set_registered_model_alias(name, "production", str(version))
    for k, v in {"gate_decision": "promoted_manually", "gate_reason": reason.strip(),
                 "gate_time": time.strftime("%Y-%m-%dT%H:%M:%S%z")}.items():
        c.set_model_version_tag(name, version, k, v)
    log.info("manual promotion %s v%s (replaces v%s): %s", name, version, old, reason)
    return {"production": str(version), "previous_production": old, "reason": reason.strip()}


def rollback(name: str, tracking_uri: Optional[str] = None) -> Dict:
    c = _client(tracking_uri)
    cur = c.get_model_version_by_alias(name, "production")
    prev = c.get_model_version_by_alias(name, "previous_production")
    new_prod, old_prod = str(prev.version), str(cur.version)
    c.set_registered_model_alias(name, "production", new_prod)
    c.set_registered_model_alias(name, "previous_production", old_prod)
    c.set_model_version_tag(name, new_prod, "rollback", f"restored as production, replacing v{old_prod}")
    log.info("rollback %s: production v%s -> v%s", name, old_prod, new_prod)
    return {"production": new_prod, "previous_production": old_prod}


def status(name: str, tracking_uri: Optional[str] = None) -> Dict:
    c = _client(tracking_uri)
    rm = c.get_registered_model(name)
    out = {"name": name, "aliases": {k: str(v) for k, v in rm.aliases.items()}, "versions": []}
    for v in sorted(c.search_model_versions(f"name='{name}'"), key=lambda v: int(v.version)):
        out["versions"].append({"version": str(v.version), "run_id": v.run_id, "created": v.creation_timestamp,
                                **{k: v.tags[k] for k in ("gate_decision", "gate_reason", "gate_test_f1") if k in v.tags}})
    return out


if __name__ == "__main__":
    import argparse
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["status", "rollback", "promote"])
    p.add_argument("version", nargs="?", help="promote: the version to make production")
    p.add_argument("--reason", default="", help="promote: why (recorded on the version)")
    p.add_argument("--model-name", default="room-occupancy")
    p.add_argument("--tracking-uri", default=None)
    a = p.parse_args()
    from mlops.train import DEFAULT_TRACKING
    uri = a.tracking_uri or os.environ.get("MLFLOW_TRACKING_URI") or DEFAULT_TRACKING
    if a.command == "promote":
        out = promote_manually(a.model_name, a.version, a.reason, uri)
    else:
        out = {"status": status, "rollback": rollback}[a.command](a.model_name, uri)
    print(json.dumps(out, indent=2, default=str))
