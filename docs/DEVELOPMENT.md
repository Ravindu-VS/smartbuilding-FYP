# Development

## Set up

```
python3 -m venv .venv && . .venv/bin/activate          # Python 3.12 or 3.13
pip install -r requirements/dev.txt -r requirements/mlops.txt -r requirements/serving.txt -r requirements/ingestion.txt httpx
cd dashboard/fyp-research-twin && npm ci && cd -       # dashboard (Node 22)
cp .env.example .env                                    # container stack secrets (edit every CHANGE_ME)
```

## Everyday commands

| Task | Command |
|---|---|
| Lint | `ruff check .` (rules in `ruff.toml`); `hadolint infrastructure/docker/*.Dockerfile`; `actionlint` |
| Unit tests | `python -m pytest -m "not slow"` |
| Integration tests | `TEST_DATABASE_URL=postgresql://user:pw@127.0.0.1:5432/db python -m pytest tests/test_ingestion.py tests/test_ml_api.py tests/test_mlops.py` (a broker is started in-process; `TEST_MQTT_HOST` uses a real one) |
| Edge brain alone | `scripts/start.sh dev` (twin + dashboard) or `scripts/start.sh harness` (with a local broker and the simulated board) |
| Train a model | `python -m mlops.train` (local MLflow store in `output/mlflow/`); `mlflow ui --backend-store-uri sqlite:///output/mlflow/mlflow.db` |
| Serve it | `MLFLOW_TRACKING_URI=sqlite:///output/mlflow/mlflow.db uvicorn mlops.serving.app:app --port 8080` |
| Whole stack | `docker compose up -d --build`, then `docker compose ps` |
| Check dashboards | `python scripts/check_dashboards.py --prometheus http://localhost:9090` |
| Regenerate dashboards | `python monitoring/grafana/build_dashboards.py` (commit the JSON; CI checks it matches) |
| Kubernetes manifests | `kubectl kustomize infrastructure/kubernetes/overlays/local` |
| Terraform | `cd infrastructure/terraform/azure && terraform fmt -check && terraform init -backend=false && terraform validate` |

## Adding a service

1. Code in its own package. Use `sbops.logs.setup("<name>")` for JSON logs and expose `/health` and `/metrics`.
2. Pin requirements in `requirements/<name>.txt`.
3. Add a Dockerfile in `infrastructure/docker/`: build ARG for the base image, non-root user, `HEALTHCHECK`.
4. Add a Compose service (network, volume, healthcheck, `depends_on` conditions).
5. Add the Kubernetes Deployment/Service to `base/`: probes, limits, `securityContext`, NetworkPolicy.
6. Add the Prometheus scrape job, alert rules and dashboard panels (in the generator).
7. Add tests, and a step in `.github/workflows/ci.yml`.

## Conventions

* **MQTT.** Topics are `sb/v1/room/<room_id>/{telemetry,command,ack,status}` with schemas `sb.telemetry/1`,
  `sb.command/1` and `sb.ack/1`. New rooms need no code change.
* **Provenance.** Provenance is never dropped: measured, simulated, estimated and predicted values stay apart
  (`source` label, `provenance` column).
* **Secrets.** Secrets come from the environment; code and config files hold only placeholders.
* **Results.** Every result quoted in the docs comes from a recorded run in `docs/evidence/`,
  `experiments/results/` or `docs/results/`.
