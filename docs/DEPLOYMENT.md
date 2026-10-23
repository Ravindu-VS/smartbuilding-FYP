# Installation, start-up and Raspberry Pi deployment

## Requirements

| Component | Version tested | Notes |
|---|---|---|
| Python | 3.13.16 (dev container) | 3.11+ expected to work; the Pi image's Python 3.11 is fine |
| Node.js | 22.22.0 | dashboard (Next.js 16.2.10); Node 20+ |
| CPU / memory | 2 vCPU, 8 GB (dev) | no GPU needed anywhere; the PPO is numpy |
| Raspberry Pi 4B | not run on a Pi in this work | runtime needs flask + numpy (+ paho-mqtt) only; tested by `tests/test_edge_runtime.py`, which blocks pandas/scikit-learn/scipy/joblib/gymnasium |

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
| `run_local.bat` | Windows (double-click): checks the venv and packages, frees ports 8001/3000, starts the edge brain and the dashboard, opens the browser; `run_local.bat test` adds the HTTP test sender |
| `scripts/train_all.sh` | offline: datasets, synthetic corpus, all models, PPO (never started by the run scripts) |
| `scripts/run_tests.sh` | full test suite |
| `python experiments/run.py --all` | experiments 1-10 |

Start-up waits for each service's health check and stops with a clear message if one does not answer.
The first start of the edge brain runs the AI's 7-day learning week (cached in `output/twin_cache/`).
Environment variables of the edge brain: `SPEED_FACTOR` (360), `API_PORT` (8001), `API_HOST`, `HW_TIMEOUT_S`
(10), `OUTDOOR_TEMP_C` (30, assumed for the real room), `TWIN_SEED`, `TWIN_WARMUP`, `AI_DEFAULT`,
`EDGE_DB` (store path; `none` disables), `SNAPSHOT_S` (60), `MQTT_ENABLED`, `ADMIN_TOKEN`.

## Raspberry Pi 4B

1. Raspberry Pi OS 64-bit, Python 3.11+; `git clone` the repository (models are in git as numpy-only JSON).
2. `python3 -m pip install -r requirements/edge.txt` (no pandas / scikit-learn / torch on the Pi).
3. Optional broker: `sudo apt install mosquitto`, a `password_file`, `listener 1883 127.0.0.1` (or TLS on 8883
   for remote boards); then `MQTT_ENABLED=1`.
4. `raspberry_pi/run_edge.sh` (or `scripts/start.sh edge`); a systemd unit with `Restart=on-failure` keeps it
   running. Restarting is safe: the store's migrations are idempotent and nothing is duplicated
   (`tests/test_integration.py::test_restart_reuses_store_without_duplicates`).
5. Point the board's `secrets.h` `EDGE_SERVER_URL` at `http://<pi-ip>:8001/api/hardware/sensor-data`.

Measured inference cost on the dev machine: models under 5 ms per call (registry acceptance check);
the PPO policy is a 24-64-64-12 network. The Pi 4B is expected to be a few times slower; not measured here.

## Physical safety

This is a research prototype. The board drives a fan, an LED and a servo that stand in for an AC, lights
and a damper; it has no certification. Mains equipment must not be connected to it without a qualified
installer, interlocks and protection designed for that equipment. Software tests do not make the system
safe for real HVAC plant.
