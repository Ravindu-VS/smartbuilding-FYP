# Architecture

Edge AI + IoT + cyber-physical digital twin, with the DevOps and MLOps platform around it.
Starting point and gap analysis: [AUDIT.md](AUDIT.md). Evidence for every claim: [evidence/](evidence/).

## What is what

| Label | Meaning here | Examples |
|---|---|---|
| **REAL** | measured by hardware in Room 101 | BME280 temperature/humidity, BH1750 lux, PIR, INA219 fan-branch V/I/P, relay state, MQ-135 raw mV |
| **SIMULATED** | produced by software | the 25 digital-twin rooms (5R1C physics), the board simulator (`mqtt_device_sim.py`, `virtual_board.py`) |
| **ESTIMATED** | derived from a real signal with a model | eCO2 from the MQ-135 (provisional, not a ppm measurement) |
| **PREDICTED** | model output | occupancy probability, 30-min temperature, PPO actions |
| **EDGE** | runs on the Raspberry Pi 4B, keeps working without Internet | Mosquitto, edge brain (control loop, twin, store, dashboard), BLE gateway |
| **CLOUD** | runs on the cloud VM / Kubernetes, optional | MLflow, ML API, ingestion + PostgreSQL, Prometheus/Alertmanager/Grafana |
| **AI** | decision making | multi-objective optimiser, PPO policy, safety layer R1–R4 |
| **ML** | learned models | learned occupancy fusion, Random Forest, thermal forecast, MLflow `room-occupancy` |
| **DEVOPS** | how software is built, shipped and run | Git, GitHub Actions, Docker, GHCR/ACR, Compose, Kubernetes, Terraform, monitoring |
| **MLOPS** | how models are built, shipped and watched | data validation, MLflow tracking + registry, promotion gate, FastAPI serving, drift, retraining |

Simulated values never carry the `physical` label: metrics use `source="physical" | "simulated_board" | "simulated"`,
the database uses `provenance`, the dashboard shows LIVE vs SIMULATED.

## System

```mermaid
flowchart LR
  subgraph ROOM["Room 101 · REAL"]
    S["BME280 · BH1750 · PIR · INA219 · MQ-135"] --> ESP["ESP32-S3"]
    ESP --> ACT["CW-020 relay → 12 V fan<br/>RGB LEDs · OLED"]
  end
  subgraph EDGE["Raspberry Pi 4B · EDGE (works offline)"]
    MQ["Mosquitto :1883"]
    EB["Edge brain :8001<br/>validation · SQLite · AI control<br/>digital twin (25 SIMULATED rooms)<br/>dashboard + SSE · /metrics"]
    BLE["BLE gateway"]
    MQ <--> EB
    BLE <--> EB
  end
  subgraph CLOUD["Cloud VM / Kubernetes · CLOUD (optional)"]
    CB["MQTT (bridge target)"]
    ING["Ingestion :8090"]
    PG[("PostgreSQL<br/>telemetry · predictions · MLflow")]
    MLF["MLflow :5000<br/>tracking + registry"]
    API["ML API :8080<br/>FastAPI /predict"]
    TR["Trainer job"]
    MON["Prometheus · Alertmanager · Grafana"]
    CB --> ING --> PG
    ING --> API
    TR --> MLF --> PG
    API --> MLF
  end
  ESP <-->|"MQTT sb/v1/room/&lt;id&gt;/…<br/>telemetry · command · ack · status"| MQ
  ESP <-->|"Bluetooth LE"| BLE
  MQ -.->|"bridge sb/v1/# over TLS 8883"| CB
  MON -.->|scrape /metrics| EB
  MON -.-> ING & API & MLF
  USER(("Browser")) --> EB
  USER --> MON
```

The cloud side is additive: if the Internet or the VM is down, Room 101 keeps being sensed, decided and actuated
by the Pi. The bridge queues messages (QoS 1, persistent session) and delivers them when the link returns.

## Data flow (sensor → digital twin)

```mermaid
sequenceDiagram
  participant B as ESP32-S3 (Room 101)
  participant M as Mosquitto (Pi)
  participant E as Edge brain (Pi)
  participant D as Dashboard / 3D twin
  participant I as Ingestion (cloud)
  participant P as PostgreSQL
  participant A as ML API
  B->>M: sb/v1/room/f2_office_a/telemetry (every 3 s, msg_id, QoS 1)
  M->>E: telemetry
  E->>E: validate · de-duplicate · SQLite (provenance) · AI decision
  E-->>D: Server-Sent Events (state)
  M-->>I: via bridge (cloud)
  I->>I: same validation as the edge
  I->>P: INSERT telemetry (idempotent on room_id+msg_id)
  I->>A: POST /predict
  A-->>I: P(occupied), model version
  I->>P: INSERT predictions
```

## Control loop (twin / AI → fan → energy feedback)

```mermaid
sequenceDiagram
  participant U as User (dashboard) or AI
  participant E as Edge brain
  participant M as Mosquitto
  participant B as ESP32-S3
  participant R as Relay + fan
  participant N as INA219
  U->>E: manual override / AI decision
  E->>M: sb/v1/room/f2_office_a/command (msg_id)
  M->>B: command
  B->>R: GPIO10 HIGH → relay → fan ON
  B->>M: ack (msg_id)
  N->>B: bus V, current, power
  B->>M: next telemetry (fan_on, power_mW)
  M->>E: telemetry → command verified against the measured current
  E-->>U: dashboard + /metrics (sb_room_fan_on, sb_room_power_watts)
```

## ML lifecycle

```mermaid
flowchart LR
  DATA["UCI occupancy data<br/>(+ future labelled telemetry)"] --> VAL["validate · clean"] --> FE["features<br/>(per reading, no look-ahead)"]
  FE --> SPLIT["chronological split<br/>train / validation / test"] --> TRAIN["3 candidates<br/>LR · RF · HGB"]
  TRAIN --> TRACK["MLflow run<br/>params · metrics · data version · git · env"]
  TRACK --> REG["Model Registry<br/>new version → @challenger"]
  REG --> GATE{"gate: acceptance<br/>+ beats @production?"}
  GATE -- yes --> PROD["@production"]
  GATE -- no --> KEEP["production unchanged<br/>(reason recorded)"]
  KEEP -. "manual promote with reason" .-> PROD
  PROD --> SERVE["ML API (hot reload)"] --> MONI["latency · predictions · PSI drift"] --> RETRAIN["weekly retrain<br/>CronJob / CI"] --> DATA
```

## DevOps pipeline

```mermaid
flowchart LR
  PUSH["git push"] --> LINT["lint<br/>ruff · actionlint · hadolint"]
  LINT --> UT["unit tests<br/>Py 3.12 + 3.13"] & IT["integration<br/>PostgreSQL · MQTT · MLflow"] & CFG["config<br/>promtool · kubeconform · terraform"]
  UT & IT & CFG --> BUILD["docker compose build"] --> E2E["stack e2e · recovery · restore<br/>Grafana provisioning"]
  E2E --> SCAN["Trivy scan"] --> K8S["kind deploy + health"] --> GHCR["push GHCR :sha + :latest"]
  GHCR -. "manual, approved" .-> AZ["Azure: ACR → VM (cloud-init) · health"]
  TF["Terraform (Azure)"] -. "plan / apply" .-> AZ
```

## Repository map

The brief's target layout and where each part lives (files were not moved: the Pi, scripts and thesis use these paths).

| Target | Here |
|---|---|
| `esp32/` | `firmware/esp32_smart_building/` |
| `edge/mqtt`, `edge/services` | `raspberry_pi/` (edge brain, MQTT bridge, BLE gateway, store, metrics), `infrastructure/mosquitto/` |
| `edge/ingestion` | `ingestion/` |
| `backend/api` | `raspberry_pi/edge_brain.py` (Flask, SSE), `mlops/serving/` (FastAPI) |
| `frontend/` | `dashboard/fyp-research-twin/` |
| `simulation/` | `twin/` |
| `ai/` | `rl/` (PPO), `twin/controllers.py`, `twin/safety.py` |
| `mlops/` | `mlops/` (data, train, promote, serving), `ml/` (edge models, registry, drift) |
| `infrastructure/docker`, `terraform`, `kubernetes` | `infrastructure/` |
| `monitoring/` | `monitoring/` (Prometheus, Alertmanager, Grafana) |
| `.github/workflows` | `.github/workflows/` |
| shared helpers | `sbops/` (JSON logs) |

## Ports

| Port | Service | Exposure |
|---|---|---|
| 1883 | Mosquitto (password + ACL) | edge LAN only |
| 8883 | Mosquitto TLS (bridge) | cloud VM, from the edge's IP only (NSG) |
| 8001 | edge brain + dashboard | edge LAN / `BIND_ADDR` |
| 8080 | ML API | localhost / cluster / reverse proxy |
| 8090 | ingestion health + metrics | internal |
| 5000 | MLflow | localhost / reverse proxy |
| 5432 | PostgreSQL | internal (127.0.0.1 in Compose) |
| 9090 / 9093 / 3000 | Prometheus / Alertmanager / Grafana | localhost / reverse proxy |
