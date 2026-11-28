# Troubleshooting

## Hardware (Room 101)

| Symptom | Likely cause | Fix |
|---|---|---|
| Fan never stops | Fan + on relay **NC** instead of NO, or the wrong relay option | Run the relay test in `docs/wiring/room101-wiring.html` (section 3); fan + on NO |
| Relay never clicks | No 5 V on the CW-020's VCC, or Q1 legs reversed (BC547B: flat face towards you, C·B·E) | Measure VCC–GND at the module; repeat the relay test |
| INA219 bus voltage ≈ 0 V | MT3608 not set, or INA219 VIN−/GND not wired | Set U1 to 12.0 V before connecting the fan branch |
| Pi reboots when the fan starts | Total load above the bank's 3 A, or a thin Pi cable | Short 3 A cable; `vcgencmd get_throttled` must be `0x0` |
| eCO2 "provisional" | MQ-135 heater warm-up (24 h) | Leave it powered; it is an estimate, not a ppm measurement |
| Board offline in the dashboard | Wi-Fi or broker unreachable | `/api/hardware/mqtt`, `/api/hardware/ble`; alert `BoardOffline`; `scripts/live_test_room101.py` on the Pi |

## Container stack

| Symptom | Likely cause | Fix |
|---|---|---|
| `failed to bind host port ... address already in use` | A native PostgreSQL or Mosquitto on the host | Set `PG_PORT` or `MQTT_PORT` in `.env`, or stop the native service |
| `set POSTGRES_PASSWORD in .env` | `.env` missing or incomplete | `cp .env.example .env` and set every value |
| `mlflow` unhealthy, `ModuleNotFoundError: psycopg` | Old image | `docker compose build mlflow` (MLflow 3.18 uses psycopg 3) |
| `ml-api` unhealthy, `last_error` mentions skops | Serving image without skops | Rebuild `ml-api` (requirements/serving.txt pins `skops`) |
| `ml-api` stays "starting", "no production model" | Trainer not finished, or the gate rejected everything | `docker compose logs trainer`; `docker compose run --rm trainer python -m mlops.promote status` |
| Predictions all ~0 at weekends | A model with the weekend flag (v1 in old stacks) | Promote a `room101` model (no weekend flag); see [MLOPS.md](MLOPS.md) |
| `node-exporter`: "not a shared or slave mount" | `rslave` mount on hosts whose `/` is private | Already removed; pull the latest compose file |
| Grafana container panels empty | cAdvisor and Docker's containerd image store | [MONITORING.md](MONITORING.md#known-limitation) |
| `HostDiskFilling` firing | The disk really is nearly full (`df -h /`) | `docker builder prune -af`, `docker image prune` |
| No telemetry in PostgreSQL | Simulator profile off and no board on this broker | `COMPOSE_PROFILES=simulator,monitoring`, or bridge the Pi ([DEPLOYMENT.md](DEPLOYMENT.md)) |

## Kubernetes

| Symptom | Likely cause | Fix |
|---|---|---|
| Pods `Pending`, taint `disk-pressure` | The node reports low disk | Free space; on small dev machines lower the kubelet eviction thresholds |
| `ImagePullBackOff` for `local/sb/*` | Images not loaded into the cluster | `kind load docker-image ...` / `k3s ctr images import` |
| `mlflow` `OOMKilled` | Old image with MLflow job execution on | Image sets `MLFLOW_SERVER_ENABLE_JOB_EXECUTION=false` (357 MB instead of 2 GB) |
| Requests fail during a rollout | No drain before shutdown | `preStop` sleep and PDB are in `base/ml-api.yaml` |
| `oom_score_adj: Permission denied` (rootless / containers in containers) | Missing `CAP_SYS_RESOURCE` | containerd `restrict_oom_score_adj = true` |

## CI

| Symptom | Fix |
|---|---|
| `Grafana dashboards match their generator` fails | `python monitoring/grafana/build_dashboards.py` and commit the JSON |
| ruff fails | `ruff check --fix .` for import issues; others by hand |
| `stack` job runs out of disk | The job frees ~20 GB first; keep images lean |
