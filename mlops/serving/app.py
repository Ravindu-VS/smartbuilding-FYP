"""
Model-serving API: the production room-occupancy model from the MLflow registry, behind FastAPI.

    uvicorn mlops.serving.app:app --host 0.0.0.0 --port 8080

    POST /predict          {"temperature": 25.6, "humidity": 43.8, "lux": 157.5, "motion": 1}
    GET  /health           liveness + readiness (503 until a model is loaded)
    GET  /health/live      process is up (Kubernetes liveness)
    GET  /health/ready     model loaded (Kubernetes readiness)
    GET  /model/info       name, version, alias, run, features, training metrics, data version
    POST /model/reload     reload the alias now (needs X-Admin-Token when ADMIN_TOKEN is set)
    GET  /metrics          Prometheus: requests, latency, errors, prediction and input distributions, drift

Configuration (environment): MLFLOW_TRACKING_URI, MODEL_NAME (room-occupancy), MODEL_ALIAS (production),
MODEL_URI (overrides name/alias, e.g. a local exported model directory for offline edge use),
MODEL_POLL_SECONDS (60: picks up a new production version without a restart), ADMIN_TOKEN, DRIFT_WINDOW (500).

`motion` (or `occupancy`, the PIR) is not a model input: it is recorded to measure how often the PIR and the
model agree, which is the only live signal available in a room without occupancy ground truth.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import sys
import threading
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from typing import Dict, List, Optional

os.environ.setdefault("MLFLOW_DISABLE_TELEMETRY", "true")
os.environ.setdefault("DO_NOT_TRACK", "1")
os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "2")     # fail fast; the loader retries every 5 s
os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", "15")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np                                                       # noqa: E402
from fastapi import FastAPI, Header, HTTPException, Request              # noqa: E402
from fastapi.responses import JSONResponse, Response                     # noqa: E402
from prometheus_client import (CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram,  # noqa: E402
                               generate_latest)
from pydantic import BaseModel, ConfigDict, Field                        # noqa: E402

from ml.drift import PSI_MODERATE, PSI_SIGNIFICANT, psi                  # noqa: E402
from mlops.data import features_from_reading                             # noqa: E402
from sbops.logs import setup as setup_logs                               # noqa: E402

log = logging.getLogger("ml-api")
SERVICE_VERSION = "1.0.0"


# ---------------------------------------------------------------- request / response
class PredictRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    temperature: float = Field(..., ge=-20, le=60, description="°C")
    humidity: float = Field(..., ge=0, le=100, description="% RH")
    lux: float = Field(..., ge=0, le=200000, description="illuminance, lux")
    co2: Optional[float] = Field(None, ge=0, le=10000, description="ppm; used only by a with_co2 model")
    motion: Optional[int] = Field(None, ge=0, le=1, alias="occupancy", description="PIR 0/1, not a model input")
    timestamp: Optional[str] = Field(None, description="ISO time of the reading (default: now)")
    room_id: Optional[str] = Field(None, max_length=64)


# ---------------------------------------------------------------- metrics
REG = CollectorRegistry()
M_REQ = Counter("sb_ml_requests", "HTTP requests", ["endpoint", "status"], registry=REG)
M_LAT = Histogram("sb_ml_request_duration_seconds", "HTTP request latency", ["endpoint"],
                  buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1), registry=REG)
M_INF = Histogram("sb_ml_inference_duration_seconds", "Model inference time",
                  buckets=(0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1), registry=REG)
M_PRED = Counter("sb_ml_predictions", "Predictions by outcome", ["outcome"], registry=REG)
M_PROB = Histogram("sb_ml_prediction_probability", "Distribution of P(occupied)",
                   buckets=(0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95), registry=REG)
M_ERR = Counter("sb_ml_errors", "Errors by type", ["type"], registry=REG)
M_LOADED = Gauge("sb_ml_model_loaded", "1 when a model is loaded and serving", registry=REG)
M_INFO = Gauge("sb_ml_model_info", "Loaded model (value 1)", ["name", "version", "alias", "run_id"], registry=REG)
M_RELOAD = Counter("sb_ml_model_reloads", "Model loads by result", ["result"], registry=REG)
M_INPUT = Gauge("sb_ml_input_mean", "Rolling mean of each model input", ["feature"], registry=REG)
M_PSI = Gauge("sb_ml_drift_psi", "PSI of recent inputs against the training deciles", ["feature"], registry=REG)
M_DRIFT = Gauge("sb_ml_drift_status", "0 stable, 1 moderate, 2 significant, -1 not enough data", registry=REG)
M_PIR = Counter("sb_ml_pir_agreement", "PIR motion vs model decision", ["agree"], registry=REG)


# ---------------------------------------------------------------- model holder
class ModelHolder:
    def __init__(self):
        self.lock = threading.Lock()
        self.model = None
        self.info: Dict = {}
        self.features: List[str] = []
        self.threshold = 0.5
        self.reference: Dict = {}
        self.window: deque = deque(maxlen=int(os.environ.get("DRIFT_WINDOW", "500")))
        self.last_error: Optional[str] = None

    @property
    def loaded(self) -> bool:
        return self.model is not None

    def target_uri(self) -> str:
        if os.environ.get("MODEL_URI"):
            return os.environ["MODEL_URI"]
        return f"models:/{os.environ.get('MODEL_NAME', 'room-occupancy')}@{os.environ.get('MODEL_ALIAS', 'production')}"

    def load(self) -> bool:
        """Load (or reload) the target model; keeps the old model if anything fails."""
        import mlflow
        import mlflow.sklearn
        uri = self.target_uri()
        try:
            info = {"uri": uri, "name": os.environ.get("MODEL_NAME", "room-occupancy"),
                    "alias": os.environ.get("MODEL_ALIAS", "production"), "version": None, "run_id": None}
            reference: Dict = {}
            if uri.startswith("models:/"):
                from mlflow import MlflowClient
                c = MlflowClient()
                mv = c.get_model_version_by_alias(info["name"], info["alias"])
                info["version"], info["run_id"] = str(mv.version), mv.run_id
                if self.model is not None and self.info.get("version") == info["version"]:
                    return True                                  # already serving this version
                run = c.get_run(mv.run_id)
                info["training"] = {k: round(v, 4) for k, v in run.data.metrics.items() if k.startswith("test_")}
                info["tags"] = {k: run.data.tags.get(k) for k in ("git_commit", "data_version", "feature_set",
                                                                    "selected_model", "version_sklearn")}
                info["gate"] = {k: mv.tags.get(k) for k in ("gate_decision", "gate_reason")}
                path = mlflow.artifacts.download_artifacts(run_id=mv.run_id, artifact_path="feature_reference.json")
                with open(path) as f:
                    reference = json.load(f)
                uri = f"models:/{info['name']}/{info['version']}"     # pin the exact version we read
            meta = mlflow.models.get_model_info(uri).metadata or {}
            model = mlflow.sklearn.load_model(uri)
            features = list(meta.get("features") or reference.get("features") or [])
            if not features:
                raise ValueError("model has no feature list in its metadata")
            with self.lock:
                self.model, self.features = model, features
                self.threshold = float(meta.get("threshold", 0.5))
                self.reference = reference.get("reference", {})
                info["features"], info["threshold"] = features, self.threshold
                info["loaded_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
                self.info = info
                self.window.clear()
                self.last_error = None
            M_INFO.clear()
            M_INFO.labels(info["name"], str(info["version"]), info["alias"], str(info["run_id"])).set(1)
            M_LOADED.set(1)
            M_RELOAD.labels("loaded").inc()
            log.info("serving %s", uri, extra={"model_version": info["version"]})
            return True
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            M_RELOAD.labels("failed").inc()
            M_LOADED.set(1 if self.model is not None else 0)
            log.warning("model load failed (%s): %s", uri, self.last_error)
            return False

    def predict(self, feats: Dict[str, float]) -> float:
        with self.lock:
            model, names = self.model, list(self.features)
        missing = [f for f in names if feats.get(f) is None]
        if missing:
            raise ValueError(f"missing inputs for this model: {missing}")
        x = np.array([[float(feats[f]) for f in names]])
        t0 = time.perf_counter()
        p = float(model.predict_proba(x)[0, 1])
        M_INF.observe(time.perf_counter() - t0)
        self.window.append(x[0])
        return p

    def drift(self) -> Dict:
        with self.lock:
            rows, names, ref = list(self.window), list(self.features), dict(self.reference)
        out = {"window": len(rows), "features": {}, "status": "insufficient data", "max_psi": None}
        if len(rows) < 50 or not ref:
            M_DRIFT.set(-1)
            return out
        X = np.array(rows)
        worst = 0.0
        for j, f in enumerate(names):
            M_INPUT.labels(f).set(float(X[:, j].mean()))
            dec = (ref.get(f) or {}).get("deciles")
            v = psi(X[:, j], dec) if dec else float("nan")
            if np.isfinite(v):
                M_PSI.labels(f).set(v)
                worst = max(worst, v)
                out["features"][f] = round(v, 4)
        out["max_psi"] = round(worst, 4)
        level = 2 if worst > PSI_SIGNIFICANT else 1 if worst > PSI_MODERATE else 0
        out["status"] = ["stable", "moderate shift", "significant drift"][level]
        M_DRIFT.set(level)
        return out


holder = ModelHolder()
_stop = threading.Event()


def _loader():
    """Loads in the background so the API answers liveness probes at once (readiness stays 503 until a model is
    loaded); retries every 5 s until the first load, then polls the alias every MODEL_POLL_SECONDS (0 = never)."""
    holder.load()
    period = float(os.environ.get("MODEL_POLL_SECONDS", "60"))
    while not _stop.is_set():
        if holder.loaded and period <= 0:
            return
        if _stop.wait(5 if not holder.loaded else period):
            return
        holder.load()


@asynccontextmanager
async def lifespan(_app):
    setup_logs("ml-api")
    _stop.clear()
    threading.Thread(target=_loader, name="model-loader", daemon=True).start()
    yield
    _stop.set()


app = FastAPI(title="Smart Building ML API", version=SERVICE_VERSION, lifespan=lifespan,
              description="Room-occupancy model served from the MLflow registry")


@app.middleware("http")
async def _observe(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    t0 = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        M_ERR.labels("unhandled").inc()
        raise
    endpoint = request.scope.get("route").path if request.scope.get("route") else "unmatched"
    if endpoint != "/metrics":
        M_LAT.labels(endpoint).observe(time.perf_counter() - t0)
    M_REQ.labels(endpoint, str(response.status_code)).inc()
    response.headers["x-request-id"] = rid
    return response


@app.post("/predict")
def predict(req: PredictRequest):
    if not holder.loaded:
        M_ERR.labels("model_not_loaded").inc()
        raise HTTPException(503, "no model loaded yet")
    t0 = time.perf_counter()
    feats = features_from_reading(req.model_dump())
    try:
        p = holder.predict(feats)
    except ValueError as e:
        M_ERR.labels("bad_input").inc()
        raise HTTPException(422, str(e))
    occupied = p >= holder.threshold
    M_PRED.labels("occupied" if occupied else "vacant").inc()
    M_PROB.observe(p)
    if req.motion is not None:
        M_PIR.labels("yes" if bool(req.motion) == occupied else "no").inc()
    info = holder.info
    return {"room_id": req.room_id, "occupancy_probability": round(p, 4), "occupied": occupied,
            "threshold": holder.threshold,
            "model": {"name": info.get("name"), "version": info.get("version"), "alias": info.get("alias"),
                      "run_id": info.get("run_id")},
            "inputs_used": {f: (round(float(feats[f]), 6) if feats.get(f) is not None else None)
                            for f in holder.features},
            "latency_ms": round((time.perf_counter() - t0) * 1000, 3)}


@app.get("/health")
def health():
    body = {"status": "ok" if holder.loaded else "starting", "service": "ml-api", "version": SERVICE_VERSION,
            "model_loaded": holder.loaded, "model_version": holder.info.get("version"),
            "last_error": holder.last_error}
    return JSONResponse(body, status_code=200 if holder.loaded else 503)


@app.get("/health/live")
def live():
    return {"status": "alive"}


@app.get("/health/ready")
def ready():
    return JSONResponse({"ready": holder.loaded}, status_code=200 if holder.loaded else 503)


@app.get("/model/info")
def model_info():
    if not holder.loaded:
        raise HTTPException(503, "no model loaded yet")
    return {**{k: v for k, v in holder.info.items() if k != "uri"}, "drift": holder.drift()}


@app.post("/model/reload")
def reload(x_admin_token: Optional[str] = Header(None)):
    token = os.environ.get("ADMIN_TOKEN")
    if not token:
        raise HTTPException(403, "reload disabled: ADMIN_TOKEN is not set")
    if not x_admin_token or not secrets.compare_digest(x_admin_token, token):
        raise HTTPException(401, "bad admin token")
    ok = holder.load()
    return JSONResponse({"reloaded": ok, "version": holder.info.get("version"), "error": holder.last_error},
                        status_code=200 if ok else 500)


@app.get("/metrics")
def metrics():
    holder.drift()                      # refresh drift gauges at scrape time
    return Response(generate_latest(REG), media_type=CONTENT_TYPE_LATEST)
