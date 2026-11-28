"""
Model-serving API (FastAPI) against a real MLflow registry in a temporary store.

    python -m pytest tests/test_ml_api.py -q
"""
import os

import pytest

pytest.importorskip("mlflow")
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

READING = {"temperature": 22.8, "humidity": 27.2, "lux": 450.0, "occupancy": 1,
           "timestamp": "2026-11-26T10:30:00", "room_id": "f2_office_a"}


def _wait(cond, timeout=60.0):
    import time
    t0 = time.time()
    while time.time() - t0 < timeout and not cond():
        time.sleep(0.1)
    return cond()


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    uri = "sqlite:///" + os.path.join(str(tmp_path_factory.mktemp("mlflow-api")), "mlflow.db")
    from mlops.train import train
    assert train(tracking_uri=uri)["promotion"]["decision"] == "promoted"
    return uri


@pytest.fixture()
def api(store, monkeypatch):
    import mlflow
    import mlops.serving.app as A
    monkeypatch.setenv("MLFLOW_TRACKING_URI", store)
    monkeypatch.setenv("MODEL_POLL_SECONDS", "0")
    monkeypatch.delenv("MODEL_URI", raising=False)
    mlflow.set_tracking_uri(store)
    monkeypatch.setattr(A, "holder", A.ModelHolder())
    with TestClient(A.app) as c:
        _wait(lambda: A.holder.loaded)                      # the model loads in the background
        yield c, A


def test_health_and_model_info(api):
    c, _ = api
    h = c.get("/health")
    assert h.status_code == 200 and h.json()["model_loaded"] and h.json()["model_version"] == "1"
    assert c.get("/health/live").status_code == 200 and c.get("/health/ready").json() == {"ready": True}
    info = c.get("/model/info").json()
    assert info["name"] == "room-occupancy" and info["alias"] == "production" and info["version"] == "1"
    assert info["features"][:3] == ["Temperature", "Humidity", "Light"]
    assert info["training"]["test_f1"] > 0.9 and info["tags"]["data_version"]
    assert info["gate"]["gate_decision"] == "promoted"


def test_predict_returns_probability_and_model_version(api):
    c, _ = api
    r = c.post("/predict", json=READING)
    assert r.status_code == 200, r.text
    b = r.json()
    assert 0.0 <= b["occupancy_probability"] <= 1.0 and isinstance(b["occupied"], bool)
    assert b["model"]["version"] == "1" and b["model"]["alias"] == "production"
    assert b["inputs_used"]["Light"] == 450.0 and b["latency_ms"] >= 0
    assert r.headers["x-request-id"]
    # lit office on a weekday morning vs dark room at night
    dark = dict(READING, lux=0.0, timestamp="2026-11-26T03:00:00")
    assert c.post("/predict", json=dark).json()["occupancy_probability"] < b["occupancy_probability"]


def test_invalid_input_is_rejected_with_422(api):
    c, A = api
    assert c.post("/predict", json={"temperature": 22.0, "humidity": 140, "lux": 10}).status_code == 422
    assert c.post("/predict", json={"humidity": 40, "lux": 10}).status_code == 422


def test_metrics_cover_requests_predictions_latency_and_drift(api):
    c, _ = api
    for i in range(60):
        c.post("/predict", json=dict(READING, lux=300 + i))
    text = c.get("/metrics").text
    for name in ("sb_ml_requests_total", "sb_ml_request_duration_seconds_bucket", "sb_ml_inference_duration_seconds",
                 "sb_ml_predictions_total", "sb_ml_prediction_probability_bucket", "sb_ml_model_info",
                 "sb_ml_drift_psi", "sb_ml_drift_status", "sb_ml_input_mean", "sb_ml_pir_agreement_total"):
        assert name in text, name
    assert 'sb_ml_model_loaded 1.0' in text
    drift = c.get("/model/info").json()["drift"]
    assert drift["window"] >= 50 and drift["status"] in ("stable", "moderate shift", "significant drift")
    # 60 near-identical readings are far from the training spread: drift must be flagged
    assert drift["status"] == "significant drift"


def test_reload_needs_the_admin_token(api, monkeypatch):
    c, _ = api
    assert c.post("/model/reload").status_code == 403
    monkeypatch.setenv("ADMIN_TOKEN", "test-token-123")
    assert c.post("/model/reload", headers={"X-Admin-Token": "wrong"}).status_code == 401
    r = c.post("/model/reload", headers={"X-Admin-Token": "test-token-123"})
    assert r.status_code == 200 and r.json()["reloaded"]


def test_new_production_version_is_picked_up_without_restart(api, store, monkeypatch):
    c, A = api
    import mlops.promote as P
    from mlops.train import train
    monkeypatch.setattr(P, "MIN_GAIN", -1.0)
    assert train(tracking_uri=store)["promotion"]["decision"] == "promoted"
    assert A.holder.load()
    assert c.post("/predict", json=READING).json()["model"]["version"] == "2"
    P.rollback("room-occupancy", store)
    assert A.holder.load() and c.get("/health").json()["model_version"] == "1"


def test_without_a_model_the_api_is_not_ready(store, monkeypatch):
    import mlops.serving.app as A
    monkeypatch.setenv("MLFLOW_TRACKING_URI", store)
    monkeypatch.setenv("MODEL_POLL_SECONDS", "0")
    monkeypatch.setenv("MODEL_NAME", "no-such-model")
    monkeypatch.setattr(A, "holder", A.ModelHolder())
    with TestClient(A.app) as c:
        assert c.get("/health/live").status_code == 200        # alive at once, before any model load finishes
        _wait(lambda: A.holder.last_error is not None)
        assert c.get("/health").status_code == 503
        assert c.get("/health/ready").status_code == 503
        assert c.get("/health/live").status_code == 200
        assert c.post("/predict", json=READING).status_code == 503
