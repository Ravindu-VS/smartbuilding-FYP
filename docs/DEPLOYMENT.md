# Installation, start-up and Raspberry Pi deployment

## Requirements

| Component | Version tested | Notes |
|---|---|---|
| Python | 3.13.16 (dev container) | 3.11+ expected to work; the Pi image's Python 3.11 is fine |
| Node.js | 22.22.0 | dashboard (Next.js 16.2.10); Node 20+ |
| CPU / memory | 2 vCPU, 8 GB (dev) | no GPU needed anywhere; the PPO is numpy |
| Raspberry Pi | `smartbuilding-pi`, Linux aarch64, Python 3.13.5 | Edge Brain/Mosquitto deployed; reboot recovery and BLE pairing remain untested |

```
python3 -m pip install -r requirements/edge.txt     # Raspberry Pi: inference and control only
python3 -m pip install -r requirements/train.txt    # development PC: data, training, evaluation
python3 -m pip install -r requirements/dev.txt      # + tests (pytest, local MQTT broker)
cd dashboard/fyp-research-twin && npm ci            # dashboard
```
(On Debian/Ubuntu system Python add `--break-system-packages` or use a virtual environment.)

## Modes

| Command | What runs |
|---|---|
| `scripts/start.sh dev` | edge brain (twin + SQLite store at `output/edge_store.sqlite3`) and the dashboard |
| `scripts/start.sh edge` | edge brain only - what runs on the Pi; boards post over HTTP |
| `scripts/start.sh live` | edge brain with the MQTT bridge (`MQTT_HOST`, `MQTT_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD`, `MQTT_TLS`) |
| `scripts/start.sh harness` | local MQTT broker + simulated board + edge brain + dashboard (no hardware) |
| `scripts/start.sh virtual` | edge brain + dashboard + virtual board replaying the UCI office data over HTTP, like the firmware (`run_local.bat virtual` on Windows) |
| `scripts/start.sh virtual-twin` | the same with Office A simulated by the digital twin, reacting to the AI's commands (`run_local.bat virtual-twin`) |
| `run_local.bat` | Windows (double-click): checks the venv and packages, frees ports 8001/3000, starts the edge brain and the dashboard, opens the browser; `run_local.bat test` adds the HTTP test sender |
| `scripts/train_all.sh` | offline: datasets, synthetic corpus, all models, PPO (never started by the run scripts) |
| `scripts/run_tests.sh` | full test suite |
| `python experiments/run.py --all` | experiments 1-11 |

Start-up waits for each service's health check and stops with a clear message if one does not answer.
The first start of the edge brain runs the AI's 7-day learning week (cached in `output/twin_cache/`).
Environment variables of the edge brain: `SPEED_FACTOR` (360), `API_PORT` (8001), `API_HOST`, `HW_TIMEOUT_S`
(10), `OUTDOOR_TEMP_C` (30, assumed for the real room), `TWIN_SEED`, `TWIN_WARMUP`, `AI_DEFAULT`,
`EDGE_DB` (store path; `none` disables), `SNAPSHOT_S` (60), `MQTT_ENABLED`, `ADMIN_TOKEN`.

## Raspberry Pi 4B

1. Raspberry Pi OS 64-bit, Python 3.11+; `git clone` the repository (models are in git as numpy-only JSON).
2. `python3 -m pip install -r requirements/edge.txt` (no pandas / torch on the Pi; scikit-learn is optional and
   only used by the background continual-learning thread, `ml/online_learning.py`).
3. Optional broker: `sudo apt install mosquitto`, a `password_file`, `listener 1883 127.0.0.1` (or TLS on 8883
   for remote boards); then `MQTT_ENABLED=1`. The current commissioning broker is anonymous and has TLS
   disabled on the trusted LAN; do not expose it through router port forwarding.
4. Install/enable BlueZ and start the Edge Brain with `raspberry_pi/run_edge.sh` (`MQTT_ENABLED=1` and
   `BLE_ENABLED=1` by default). Keep BLE disabled until the host controller is powered/unblocked and
   pairing is authorized. The commissioned Pi has its radio powered and the gateway paired with
   `SB-Room101` (commissioning T21). Retrieve the pairing passkey from the Serial Monitor for a new pairing and
   verify the link at `http://<pi-ip>:8001/api/hardware/ble`.
5. Configure the ESP32's `MQTT_BROKER_IP` in its git-ignored `secrets.h` to the Pi's current LAN IP.
   The ESP32 uses Wi-Fi/MQTT first; paired BLE forwards the same telemetry and commands through the Pi's
   local Mosquitto broker when direct MQTT is offline.
6. On the commissioned Pi, the sanitized project is deployed to
   `/home/pi/Desktop/Project-pi-ble`; the pre-existing `/home/pi/Desktop/Project` is a separate codebase and
   was preserved. The running Edge Brain uses a user-level service with MQTT and BLE enabled.
   Firmware revision `room101-2026.11.20` sends BLE frames sized to the negotiated MTU, which the previous
   `ble_gateway.py` rejects: update `ble_gateway.py`, `mqtt_bridge.py` and `edge_brain.py` on the Pi together
   with the firmware (`scripts/commission_room101.py --deploy-pi` backs them up and copies them). `Linger=yes` is configured for the Pi user service so it can start without an
   interactive login; reboot recovery was tested on 23 Nov 2026 (commissioning T18: Mosquitto, the Edge
   Brain, the BLE link and the board all came back without manual steps). The system-level
   `raspberry_pi/systemd/edge-brain.service.example` is an alternative, not installed on this Pi; edit its
   project path and service security settings before using it. Verify `/health` and
   `/api/hardware/mqtt` after any deployment or restart.
7. **Dashboard on the Pi (final setup).** Build the static dashboard once (`bash scripts/build_dashboard_for_pi.sh`
   on any machine with Node.js 20+, or copy a built `dashboard_dist/`) into the project root on the Pi. The Edge
   Brain serves it at `http://<pi-ip>:8001/` (API calls are same-origin), so nothing has to run on a laptop: any
   phone or PC on the network opens the dashboard. `DASHBOARD_DIR` overrides the folder.
8. Restarting is safe: the store migrations are idempotent and nothing is duplicated
   (`tests/test_integration.py::test_restart_reuses_store_without_duplicates`).

Measured inference cost on the dev machine: models under 5 ms per call (registry acceptance check);
the PPO policy is a 24-64-64-12 network. The Pi 4B is expected to be a few times slower; not measured here.

## Physical safety

This is a research prototype. The tested design scope is a fused low-voltage DC fan and RGB LED switched
by a relay; it is not certified. Do not connect mains equipment without a qualified installer, interlocks
and protection designed for that equipment. Software tests do not make the system safe for real HVAC plant.


## Container stack, Kubernetes and Azure (cloud side)

The Pi keeps running the edge natively (above). The platform services run in containers anywhere else:

| Where | How | Guide |
|---|---|---|
| Laptop / any Docker host | `cp .env.example .env` (set secrets) → `docker compose up -d` | [DEVOPS.md](DEVOPS.md#docker-compose) |
| Kubernetes (k3s, kind, AKS) | `kubectl apply -k infrastructure/kubernetes/overlays/local` (or `azure`) | [DEVOPS.md](DEVOPS.md#kubernetes-infrastructurekubernetes) |
| Azure VM | `terraform apply` in `infrastructure/terraform/azure`, then the gated `Deploy to Azure` workflow | [DEVOPS.md](DEVOPS.md#terraform-infrastructureterraformazure) |

### Connect the Pi to the cloud side

1. `/metrics` on the Pi: `python3 -m pip install prometheus-client==0.26.0`, restart `edge-brain`, check
   `curl localhost:8001/metrics | head`. Add the Pi to `monitoring/prometheus/targets/edge-pi.yml`.
2. MQTT bridge: copy `infrastructure/mosquitto/bridge-to-cloud.conf.example` to `/etc/mosquitto/conf.d/` on the Pi,
   set the cloud address and the `edge` password, then `sudo systemctl restart mosquitto`. The bridge queues while
   the link is down; Room 101 is controlled locally either way.
3. Ingestion in the cloud stores every reading with provenance `physical` (sender `esp32_room101`) and asks the
   ML API for a prediction.
4. JSON logs on the Pi (optional): `LOG_FORMAT=json` in the service environment.
