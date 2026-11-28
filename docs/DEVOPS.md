# DevOps

How the software is built, tested, shipped and run. Architecture: [ARCHITECTURE.md](ARCHITECTURE.md). Monitoring:
[MONITORING.md](MONITORING.md). Security: [SECURITY.md](SECURITY.md). Evidence: [evidence/](evidence/).

## Services and images

| Service | Image (built from `infrastructure/docker/`) | Port | Runs as |
|---|---|---|---|
| edge brain + dashboard | `edge-brain` (multi-stage: Next.js static export → Python 3.12) | 8001 | uid 10001 |
| ML API | `ml-api` (FastAPI, MLflow client, scikit-learn, skops) | 8080 | uid 10001 |
| ingestion | `ingestion` (paho-mqtt, psycopg 3) | 8090 | uid 10001 |
| trainer | `trainer` (one-shot job) | — | uid 10001 |
| MLflow | `mlflow` (server + PostgreSQL backend + Prometheus exporter) | 5000 | uid 10001 |
| Mosquitto | `eclipse-mosquitto:2.0.20` + config/ACL | 1883 | mosquitto |
| PostgreSQL | `postgres:16-alpine` + init script (one role per service) | 5432 | postgres |
| Prometheus, Alertmanager, node-exporter, cAdvisor, Grafana | official images | 9090, 9093, 3000 | image default |

* **Built from the repo:** five images, with registry `ghcr.io/<owner>/smartbuilding/<service>` and tags `<git sha
  12>` plus `latest` on `main`.
* **Base images:** build ARGs (`PYTHON_IMAGE`, `NODE_IMAGE`) whose pinned defaults can be swapped for an offline
  mirror.
* **Health checks:** every image has one.
* **Dependencies:** Python packages are pinned in `requirements/*.txt`.

## Docker Compose

```
cp .env.example .env            # set every CHANGE_ME (openssl rand -hex 16)
docker compose up -d            # COMPOSE_PROFILES=simulator,monitoring in .env
docker compose ps               # all (healthy)
docker compose logs -f ingestion
docker compose down             # keep data;  down -v deletes the volumes
```

| What | How it is set up |
|---|---|
| Networks | `edge` (MQTT, edge brain, simulator, ingestion), `backend` (PostgreSQL, MLflow, ML API, trainer, ingestion), `monitoring`. Prometheus joins all three. |
| Volumes | `pgdata`, `mlflow-artifacts`, `mosquitto-data`, `edge-output`, `prometheus-data`, `alertmanager-data`, `grafana-data` |
| Start order | Health-checked dependencies: PostgreSQL → MLflow → trainer (completed) → ML API → ingestion |
| Restarts | `unless-stopped` |
| Logs | JSON per line, rotated at 10 MB × 3 |
| Profiles | `simulator`: the board simulator; drop it when the real board feeds this broker. `monitoring`. `backup`: on demand. |
| Ports | Bound to `127.0.0.1` unless `BIND_ADDR`/`MQTT_BIND` are set |

Recorded run with all 12 services healthy: [evidence/compose-ps.txt](evidence/compose-ps.txt).

## CI/CD (`.github/workflows/ci.yml`)

```
push / PR → lint → { unit (3.12, 3.13) | integration | config } → stack → (main) push to GHCR
```

| Job | Steps |
|---|---|
| lint | `ruff check .` (ruff.toml), actionlint + shellcheck on the workflows, hadolint on the Dockerfiles, generated Grafana dashboards up to date, `docker compose config` |
| unit | `pytest -m "not slow"` on Python 3.12 and 3.13, JUnit reports kept |
| integration | PostgreSQL 16 service container: MQTT → ingestion → PostgreSQL, backend → MQTT, model API → backend, MLflow registry and gate, broker reconnect, metrics, backups |
| config | promtool, amtool, `kubectl kustomize` + kubeconform (strict, Kubernetes 1.33) for both overlays, `terraform fmt` + `validate` |
| stack | `docker compose build` and `up` (all profiles, random secrets per run, masked) → end to end: telemetry and predictions in PostgreSQL, board connected, `/predict`, all dashboard queries, Grafana dashboards and data-source health → recovery test → backup/restore test → logs artifact → Trivy report → kind cluster: load images, apply the overlay, wait for the trainer Job, roll out, `/predict` through a port-forward → on `main`: push `:sha` and `:latest` to GHCR |

Other workflows:

| Workflow | What it does |
|---|---|
| `deploy-azure.yml` | Manual, gated by `vars.AZURE_DEPLOY_ENABLED` and the `production` environment. Logs in to Azure with OIDC (no stored password), copies the image tag from GHCR to ACR, deploys over SSH (`sb-deploy <tag>` from cloud-init) and health-checks the ML API. |
| `terraform.yml` | `fmt` + `validate` on PRs; `plan` with OIDC when Azure is enabled |
| `retrain.yml` | Weekly retraining with the gate ([MLOPS.md](MLOPS.md)) |

Secrets used by the workflows are GitHub Secrets only: `AZURE_*`, `VM_SSH_KEY`, `MLFLOW_TRACKING_*`. The stack job
generates throw-away secrets per run.

## Kubernetes (`infrastructure/kubernetes/`)

Kustomize base plus overlays: `local` (k3s, kind, minikube) and `azure` (ACR images, LoadBalancer for the MQTT bridge).

| Kind | Objects |
|---|---|
| Workloads | PostgreSQL StatefulSet (PVC), MQTT Deployment, MLflow Deployment (PVC), trainer Job, weekly `retrain` CronJob, ml-api Deployment (2 replicas, PodDisruptionBudget, 8 s `preStop` drain), ingestion Deployment |
| Config | ConfigMaps (settings, Mosquitto config/ACL, PostgreSQL init); Secrets from `secretGenerator` (git-ignored `secrets.env`, `mqtt.env`) |
| Network | Services, Traefik Ingress (`ml.smartbuilding.local`, `mlflow.smartbuilding.local`), default-deny NetworkPolicies with per-service allow rules |
| Every container | Readiness/liveness probes, requests/limits, `runAsNonRoot`, no privilege escalation, capabilities dropped, read-only root filesystem where the app allows it, seccomp RuntimeDefault |

```
cp infrastructure/kubernetes/secrets.env.example infrastructure/kubernetes/overlays/local/secrets.env   # edit
cp infrastructure/kubernetes/mqtt.env.example    infrastructure/kubernetes/overlays/local/mqtt.env      # edit
kubectl apply -k infrastructure/kubernetes/overlays/local
kubectl -n smartbuilding get pods
```

Hardware control (Mosquitto for the board, the edge brain, BLE, GPIO) deliberately stays on the Pi: a cluster
outage must not stop Room 101.

Tested on a real k3s v1.33 cluster ([evidence/kubernetes.txt](evidence/kubernetes.txt)):
* all pods ready, and the trainer Job completed;
* `/predict` and MLflow answered through the ingress;
* telemetry flowed to PostgreSQL inside the cluster;
* 673 of 673 requests succeeded while a pod was deleted and a rolling restart ran. Before the `preStop` drain was
  added, 7 of 515 failed.

## Terraform (`infrastructure/terraform/azure/`)

Low-cost Azure for the cloud side:

| Area | What is created |
|---|---|
| Network | Resource group, VNet `10.20.0.0/16` and subnet. NSG: SSH and HTTPS from your IP only, MQTT-TLS 8883 from the edge's IP only, everything else denied. Static public IP. |
| Compute | Ubuntu 24.04 VM (`Standard_B2s`) with cloud-init: Docker, fail2ban, unattended upgrades, the repo, `sb-env-from-keyvault` and `sb-deploy` |
| Registry | ACR Basic, admin user off; the VM pulls with its managed identity (AcrPull) |
| Secrets | Key Vault with RBAC; the VM reads secrets, which are set with `az keyvault secret set` and never stored in Terraform state |
| Storage | Storage account for backups: TLS 1.2, no public blobs, shared keys off, 7-day soft delete |
| Monitoring and cost | Log Analytics (30 days, 0.5 GB/day cap), Key Vault audit logs, CPU alert, monthly budget alerts at 50/80/100 % |

```
cd infrastructure/terraform/azure
cp terraform.tfvars.example terraform.tfvars     # your IP, the Pi's IP, SSH key, budget e-mail
az login && terraform init && terraform plan && terraform apply
```

Validated with `fmt` and `validate` ([evidence/terraform.txt](evidence/terraform.txt)). **Not applied:** that needs
your Azure subscription. Remote state: `backend.tf.example`.

## Rollback

| What | How |
|---|---|
| Images | Every build is tagged with its git SHA: `TAG=<previous sha> docker compose up -d`, or `kubectl -n smartbuilding rollout undo deploy/ml-api` |
| Models | `python -m mlops.promote rollback`; the ML API follows within `MODEL_POLL_SECONDS` |
| Data | [Backups](#backup-and-recovery) |

## Backup and recovery

| What | How |
|---|---|
| PostgreSQL (both databases, roles), MLflow artifacts, edge output | `docker compose --profile backup run --rm backup` writes `backups/<UTC>/` with SHA-256 sums and keeps the newest 7 |
| Restore | `docker compose --profile backup run --rm --entrypoint /bin/sh backup /scripts/restore.sh /backups/<UTC>`. Checksums are verified, and each database is restored as its owning role. |
| Edge SQLite (Pi) | `python scripts/backup/sqlite_backup.py output/edge_store.sqlite3 backups/`: an online backup with the SQLite API and an integrity check |
| Restore test | `sh scripts/backup/test_restore.sh`: marker row → backup → drop the table and the registry rows → restore → verify ([evidence](evidence/restore-test.txt)) |
| Failure test | `sh scripts/chaos/recovery_test.sh`: process crash → automatic restart; 100 s ingestion outage → alert fires, the edge keeps running, no reading lost ([evidence](evidence/recovery-test.txt)) |
| Off-site | Copy `backups/` to the Terraform storage account (`az storage blob upload-batch --auth-mode login`) |
