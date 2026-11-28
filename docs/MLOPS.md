# MLOps

The occupancy model's whole life: data → validation → features → training → MLflow tracking → registry →
promotion gate → serving → monitoring → retraining. Code in `mlops/`, tests in `tests/test_mlops.py` and
`tests/test_ml_api.py`, evidence in [evidence/mlops-registry.txt](evidence/mlops-registry.txt).

The edge brain's own models (`ml/`, numpy-portable, own registry with acceptance tests, continual learning on the
Pi) keep running as before; see [ML.md](ML.md). The MLflow pipeline is the cloud-side lifecycle around them.

## The model and why

* **Task.** P(room occupied) from one reading of the room's sensors and the time of day.
* **Data.** UCI Occupancy Detection (Candanedo & Feldheim 2016): 20 560 one-minute readings of a real office,
  2–18 Feb 2015, `data/raw/kaggle_occupancy/Occupancy.csv`. Its version is the file's SHA-256, logged with every run.
* **Features (`room101`).** Temperature, Humidity, Light, HumidityRatio, hour_sin, hour_cos. This is only what
  Room 101's board measures: it has no NDIR CO2, and the MQ-135 is not a calibrated ppm sensor.
* **Models.** Logistic regression (interpretable baseline), Random Forest and histogram gradient boosting. The data
  is tabular, with 6 features and about 12 k training rows, so deep learning would add cost without a reason.
* **Not used: the weekend flag.** Nobody entered the UCI office at weekends, so a model with the flag learns that
  office's timetable. The first production version (v1) had it and predicted P = 0.00 for every Saturday reading
  of Room 101. Without it, test F1 drops from 0.991 to 0.984, and the model describes the room's conditions instead
  of one office's calendar. The comparison runs `with_weekend` and `with_co2` are kept in the experiment.

## Pipeline (`python -m mlops.train`)

| Step | What happens | Leakage control |
|---|---|---|
| Validation | Schema, numeric types, physical ranges, label ∈ {0,1}, missing share ≤ 5 %. Rows that fail are dropped and counted. A hard error, or more than 10 % of rows dropped, stops the run. | — |
| Features | Per reading only: the current values plus the time of day in the building's time zone (`BUILDING_TZ`). | No neighbouring rows, no target-derived features |
| Split | Chronological by calendar day: train ≤ 11 Feb, validation 12–14 Feb, test 15–18 Feb. Every part has both classes. | Disjoint in time (asserted) |
| Selection | Each candidate is fitted on train and scored on validation (F1; ties go to the simpler model). | The test set is unseen until the end |
| Final model | The winner is refitted on train + validation and evaluated **once** on test. | Scaler inside the pipeline |
| Tracking | MLflow run: params, validation and test metrics, data version, git commit, Python and library versions, platform. Artifacts: validation report, split summary, feature reference (training deciles), model card. One nested run per candidate. | — |
| Registry | The model is logged in **skops** format, not pickle, so loading it runs no arbitrary code. Only reviewed scikit-learn tree types are trusted. Registered as a new version of `room-occupancy`. | — |
| Gate | `mlops/promote.py`; see below. | Each model is scored with the feature list stored in its own metadata |

```
python -m mlops.train                              # local MLflow store in output/mlflow/
MLFLOW_TRACKING_URI=http://localhost:5000 python -m mlops.train
python -m mlops.train --feature-set with_co2 --no-register      # comparison run only
docker compose run --rm trainer python -m mlops.train           # in the stack
```

## Registry: versions, aliases, gate

| Alias | Meaning |
|---|---|
| `challenger` | The newest registered version (always moved) |
| `production` | What the ML API serves; moved only by the gate, a manual promotion or a rollback |
| `previous_production` | The version that `production` replaced, the target of a rollback |

The gate promotes the new version only if, on the same test split, **(1)** F1 ≥ 0.90 and balanced accuracy ≥ 0.90,
and **(2)** its F1 beats the current production version's by at least 0.002. Otherwise production stays where it
is, and the decision and reason are written to the version's tags (`gate_decision`, `gate_reason`, `gate_test_f1`,
`compared_with`). A replacement is never silent.

```
python -m mlops.promote status
python -m mlops.promote promote 4 --reason "why this trade-off is accepted"   # acceptance floor still applies
python -m mlops.promote rollback                                              # production <-> previous_production
```

Recorded example (container stack, [evidence](evidence/mlops-registry.txt)):

1. v1 (with the weekend flag) became the first production version.
2. v4 (without it) scored lower on the UCI test days, so the gate kept v1.
3. v4 was then promoted manually with the reason recorded.
4. The ML API switched to v4 within 10 s, with no restart.

## Serving (`mlops/serving/app.py`, FastAPI)

| Endpoint | Purpose |
|---|---|
| `POST /predict` | Body: `{"temperature", "humidity", "lux", "occupancy"/"motion" (PIR, optional), "timestamp" (optional), "room_id" (optional)}`. Returns `occupancy_probability`, `occupied`, `threshold`, model name/version/alias/run, the inputs used, and `latency_ms`. |
| `GET /health` | 200 once a model is loaded, 503 before |
| `GET /health/live`, `GET /health/ready` | Kubernetes liveness and readiness |
| `GET /model/info` | Version, alias, run, features, training test metrics, data version, git commit, gate decision, live drift |
| `POST /model/reload` | Reloads at once; needs the `X-Admin-Token` header, and is disabled while `ADMIN_TOKEN` is unset |
| `GET /metrics` | Prometheus metrics |

* **Loading.** The model loads in the background, so the process is alive at once and becomes ready when the model is in.
* **Picking up promotions.** The alias is polled every `MODEL_POLL_SECONDS` (default 60), so a promotion or rollback reaches the API without a restart.
* **When a load fails.** The old model keeps serving.
* **PIR.** The PIR is not a model input. It is recorded to count how often it agrees with the model, which is the only live signal in a room without occupancy ground truth.

## Monitoring and drift

The ML API exports these metrics (dashboard *Smart Building · Machine learning*, alerts in `monitoring/prometheus/alerts.yml`):

| Metric | What it measures |
|---|---|
| `sb_ml_requests_total{endpoint,status}`, `sb_ml_request_duration_seconds` | Traffic and latency |
| `sb_ml_errors_total{type}` | Errors |
| `sb_ml_inference_duration_seconds` | Model-only time |
| `sb_ml_predictions_total{outcome}`, `sb_ml_prediction_probability` | Prediction distribution |
| `sb_ml_input_mean{feature}` | Input distribution |
| `sb_ml_drift_psi{feature}`, `sb_ml_drift_status` | PSI of the last 500 inputs against the training deciles: < 0.10 stable, 0.10–0.25 moderate, > 0.25 significant. Alert `InputDrift` fires after 15 min significant. |
| `sb_ml_model_info{name,version,alias,run_id}`, `sb_ml_model_loaded`, `sb_ml_model_reloads_total` | Which model is serving |
| `sb_ml_pir_agreement_total{agree}` | PIR versus model agreement |

Drift here is basic and honest: a per-feature PSI on a rolling window. There is no concept-drift detection,
because Room 101 has no labels.

## Retraining

* **Kubernetes.** The `retrain` CronJob runs weekly (Sunday 02:17); the gate decides. Run it now with:
  `kubectl -n smartbuilding create job --from=cronjob/retrain retrain-now`.
* **GitHub Actions.** `retrain.yml` runs weekly and on demand. It logs to your MLflow server when the
  `MLFLOW_TRACKING_URI` secret is set, and writes the gate decision to the run summary.
* **Compose.** `docker compose run --rm trainer python -m mlops.train`.
* **New data.** Any CSV with the same schema (`--data`) goes through the same validation, so labelled data from
  Room 101 can be added once it exists.

## Reproducibility

* **What a run records.** Data hash, git commit (`GIT_COMMIT` in images), Python, numpy, pandas, scikit-learn and
  scipy versions, and the platform.
* **Determinism.** Seeds are fixed (`random_state=42`), so the same data and code give the same model; this was
  checked by re-running.
* **Pinned dependencies.** The trainer and serving images pin the same scikit-learn (1.8.0) and skops (0.16.0).
