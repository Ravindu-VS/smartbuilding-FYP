# Repository audit: Smart Building FYP → Edge AI + DevOps + MLOps

Audit date: 28 Nov 2026, against `main` at `0fdd9b7` plus the circuit revision F commit.
Scope: everything in the repository, the deployed Raspberry Pi and the Room 101 hardware as last tested (25 Nov 2026).

Status keys: **[EXISTS]** implemented and tested · **[PARTIAL]** implemented in part or not tested end to end ·
**[MISSING]** not in the repository · **[NEEDS TEST]** implemented, needs a test or a hardware run.

## A. Current architecture

| Layer | Component | Location |
|---|---|---|
| Physical room | Room 101 board, room id `f2_office_a`: ESP32-S3-DevKitC-1 v1.0, BME280, BH1750, MQ-135, HC-SR501, INA219, OLED, relay + 12 V fan, 3 RGB LEDs | `firmware/esp32_smart_building/`, `docs/HARDWARE.md`, `docs/wiring/` |
| Firmware | Arduino C++, non-blocking loop, MQTT (`sb/v1/room/<id>/telemetry`, `command`, `ack`, `status`), BLE GATT link, fail-safe on link loss | `firmware/esp32_smart_building/esp32_smart_building.ino` |
| Edge computer | Raspberry Pi 4B `smartbuilding-pi`, Mosquitto 1883, systemd unit | `raspberry_pi/systemd/edge-brain.service.example`, `docs/DEPLOYMENT.md` |
| Edge brain (backend) | Flask API on :8001 (32 routes), SSE stream `/api/stream`, AI control loop, command verification | `raspberry_pi/edge_brain.py` |
| MQTT bridge | paho-mqtt client, schema validation (`sb.telemetry/1`), QoS 1 commands, acks | `raspberry_pi/mqtt_bridge.py` |
| BLE gateway | bleak, redundant link to the board | `raspberry_pi/ble_gateway.py` |
| Storage | SQLite with migrations: readings, decisions, events, predictions, commands, room snapshots | `raspberry_pi/store.py` (`output/edge_store.sqlite3`) |
| Digital twin / simulation | ISO 13790 5R1C thermal model, 26-room building (25 simulated + Room 101), occupancy, climate, scenarios, live lock-step twin | `twin/` |
| AI control | multi-objective controller, PPO policy (numpy), safety layer R1–R4, comfort (PMV/PPD) | `twin/controllers.py`, `rl/`, `twin/safety.py`, `twin/comfort.py` |
| ML | occupancy (RF, learned fusion), thermal, energy day-ahead; numpy-portable models; shadow mode; drift (PSI); continual learning | `ml/`, `models/registry/` |
| Model registry (own) | versioned artifacts, acceptance tests, promote/rollback, active version per task | `ml/registry.py`, `models/registry/registry.json` |
| Frontend | Next.js 16 + React 19 + Three.js (react-three-fiber) digital twin, static export served by the edge brain | `dashboard/fyp-research-twin/`, `dashboard_dist/` |
| Experiments | 12 reproducible experiments with configs and results | `experiments/` |
| Scripts | start modes, dashboard build, hardware check, commissioning, live test, dataset fetch | `scripts/`, `run_local.bat` |
| Tests | 141 pytest tests (unit, MQTT integration with an in-process broker, twin, RL, ML), Playwright flows | `tests/`, `raspberry_pi/test_*.py` |

## B. Existing technologies

- **Frontend:** Next.js 16.2, React 19.2, Three.js 0.185, react-three-fiber 9, Tailwind 4, TypeScript 5, ESLint 9.
- **Backend:** Python 3.11–3.13, Flask 3.1 (threaded dev server), Server-Sent Events.
- **Database:** SQLite (WAL) on the edge.
- **MQTT:** Mosquitto on the Pi, paho-mqtt 2.1 in the edge brain, amqtt for tests.
- **AI/ML:**
  - numpy PPO
  - scikit-learn 1.8 (Random Forest, gradient boosting, logistic regression)
  - pandas, scipy
  - own registry, PSI drift detection, continual learning
- **Simulation:** own 5R1C physics, occupancy and climate generators.
- **Hardware:** ESP32-S3 (Arduino core, ArduinoJson, PubSubClient, ESP32 BLE library), I²C sensors, Raspberry Pi 4B.
- **Communication:** MQTT (primary) and Bluetooth LE (redundant) from the board; HTTP POST ingest on the edge brain (virtual board, test sender); SSE to the dashboard.

## C. Existing working functionality (tested)

- **[EXISTS]** Real board → MQTT and BLE → Pi, a reading every 3 s (live test 25 Nov: link, sensors, INA219 V×I consistency).
- **[EXISTS]** Pi → board commands with acks: light LED ON/DIM/OFF, AC and status LEDs, relay command accepted and reported.
- **[PARTIAL]** Fan relay: the board reports the relay state, but the fan never switches off because relay IN is wired straight to GPIO10. The fix is the Q1 BC547B driver in circuit revision F, still to be soldered.
- **[EXISTS]** AI control loop with verification; learned occupancy model at 96.9 % live accuracy against 92.4 % for the rule (shadow comparison).
- **[EXISTS]** Continual learning thread; registry promotion and rollback with acceptance tests.
- **[EXISTS]** Digital twin of 25 simulated rooms plus the live room. The dashboard marks LIVE versus SIMULATED rooms and serves a 5-minute automatic Demo.
- **[EXISTS]** SQLite persistence with migrations; history, events and provenance APIs.
- **[EXISTS]** MQTT security options (username/password, TLS) read from the environment; no secrets in the repository.
- **[NEEDS TEST]** Reboot recovery of the Pi services and BLE pairing after reboot (noted as untested in `docs/DEPLOYMENT.md`).

## D. Missing functionality for the target architecture

- Containers: no Dockerfile, no compose file, no `.dockerignore`, no `.env.example`.
- CI/CD: no `.github/workflows`; tests only run by hand (`scripts/run_tests.sh`).
- Monitoring: no Prometheus endpoint, no Grafana, no alert rules; health is only `/health` JSON.
- Logging: plain-text Python logging; not structured.
- MLOps: no MLflow (the own registry covers versioning and promotion but not experiment tracking); no model-serving API separate from the edge brain; no `/predict`.
- Cloud-side telemetry database: telemetry lives only in the Pi's SQLite; no PostgreSQL.
- Infrastructure as code: no Terraform, no Kubernetes manifests.
- Backup and restore: no scripts and no restore test.
- Docs: no ARCHITECTURE, DEVELOPMENT, DEVOPS, MLOPS, MONITORING, SECURITY, TROUBLESHOOTING.

## E. DevOps gap analysis

| Area | Current | Required | Implementation |
|---|---|---|---|
| Docker | none | images for every software service, compose stack, health checks, volumes, non-root | Dockerfiles for edge brain, ML API, ingestion, trainer and dashboard; compose with Mosquitto, PostgreSQL, MLflow, Prometheus, Grafana, node-exporter |
| CI/CD | none | lint → unit → integration → build → scan → tag → registry → deploy → health check | GitHub Actions: ruff, pytest, integration against service containers, buildx, Trivy, GHCR push, kind deployment with health checks |
| Linux | Pi runs Raspberry Pi OS with systemd | documented service management | keep systemd on the Pi (edge stays native for GPIO/BLE); containers for cloud-side services |
| Terraform | none | reproducible Azure infrastructure | `infrastructure/terraform/azure`: resource group, VNet, subnet, NSG, ACR (Basic), storage, Log Analytics, one B-series VM with cloud-init; validate in CI, apply only with your credentials |
| Azure | none | hybrid edge + cloud | cloud runs ML/monitoring/storage; the edge keeps running without it |
| Kubernetes | none | Deployments, Services, ConfigMap, Secret, Ingress, probes, limits | kustomize manifests for the cloud-side services; MQTT/hardware control stays on the edge |
| Monitoring | `/health` only | Prometheus metrics, Grafana dashboards, alerts | `/metrics` on the edge brain, ML API and ingestion; scrape config, alert rules, 5 dashboards |
| Logging | plain text | structured, with service, severity, device id | JSON log formatter (opt-in on the edge brain, default in the new services); `docker compose logs` |
| Security | env-based MQTT credentials | secrets out of git, TLS plan, segmentation | `.env.example`, GitHub/Kubernetes Secrets, `SECURITY.md` with ports, firewall, TLS |

## F. MLOps gap analysis

| Area | Current | Required | Implementation |
|---|---|---|---|
| Dataset | UCI/Kaggle occupancy (20 560 rows, real lab data), simulated corpus, manifest with checksums | versioned dataset | dataset hash and row counts logged with every run |
| Preprocessing | `ml/features.py`, `scripts/preprocess_datasets.py` | validation, cleaning, feature engineering, no leakage | `mlops/data.py`: schema and range checks, de-duplication, chronological train/validation/test split |
| Training | scripts per task (`scripts/train_all.sh`) | reproducible pipeline | `mlops/train.py` with several scikit-learn candidates |
| Experiment tracking | JSON metadata in the own registry | parameters, metrics, artifacts, git commit, environment | MLflow tracking |
| Model registry | own registry (promote/rollback with acceptance tests) | versions and a production stage, never silent replacement | MLflow Model Registry with a `production` alias moved only when the challenger beats the champion on the test set |
| Model serving | inside the edge brain (no separate API) | FastAPI `/predict`, `/health`, `/model/info` | `mlops/serving/app.py` loading the production model from MLflow |
| Model monitoring | shadow accuracy and PSI drift inside the edge brain | latency, requests, errors, prediction/input distributions, model version | Prometheus metrics in the ML API |
| Drift detection | PSI per feature (`ml/drift.py`) | basic drift in the serving path | same PSI method against the training deciles, exposed as metrics |
| Automated retraining | continual learning thread on the Pi; manual registry promotion | scheduled retrain with a gate | CI job and `mlops/retrain` entry: train, compare, promote only on improvement |

## G. Implementation sequence

Additive only: nothing working is replaced. The edge brain, SQLite store, MQTT topics, firmware and dashboard stay as they are.

| # | Task | Depends on | Status before |
|---|---|---|---|
| 1 | Verify the existing system (test suite baseline, live test) | – | [EXISTS] |
| 2 | Finish the relay hardware (Q1 driver, circuit rev F) and rerun the live test | 1 | [NEEDS TEST] |
| 3 | Prometheus `/metrics` and JSON logs in the edge brain | 1 | [MISSING] |
| 4 | MLOps data pipeline and MLflow training/registry | 1 | [MISSING] |
| 5 | FastAPI model serving with monitoring and drift | 4 | [MISSING] |
| 6 | Telemetry ingestion MQTT → PostgreSQL | 1 | [MISSING] |
| 7 | Dockerfiles and Docker Compose stack | 3–6 | [MISSING] |
| 8 | Prometheus, Grafana, alerts | 3, 5, 6, 7 | [MISSING] |
| 9 | Backup, restore and failure recovery | 6, 7 | [MISSING] |
| 10 | GitHub Actions CI/CD | 3–9 | [MISSING] |
| 11 | Kubernetes manifests and a real cluster test | 7 | [MISSING] |
| 12 | Terraform (Azure), validated | 7 | [MISSING] |
| 13 | Documentation and evidence | all | [PARTIAL] |
| 14 | End-to-end validation on the Pi and the board | 2, 3, 6 | [NEEDS TEST] |

### Decisions that need your approval (not done)

1. **Moving the Pi's telemetry store from SQLite to PostgreSQL.** SQLite stays on the edge: one writer, no server to fail, works offline. PostgreSQL is added as the cloud-side store fed by the ingestion service.
2. **Splitting MQTT commands into per-actuator topics** (`command/fan`, `command/rgb`, …). The current single versioned `command` topic carries all actuators with one msg_id and ack, which is what the firmware implements.
3. **Moving the repository to the `esp32/ edge/ backend/ …` layout.** The current layout maps onto it one to one (table in `ARCHITECTURE.md`); moving files would break paths used by the Pi, the scripts and the thesis.
4. **Running the Pi's own services in containers.** The edge brain needs BLE (BlueZ D-Bus) and GPIO, so it stays on systemd on the Pi; its image is used for the cloud and CI stack.
