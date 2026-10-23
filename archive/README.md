# Archive

`legacy_v1/` holds the project's earlier architecture, moved here with `git mv` on 23 Oct 2026 (nothing was
deleted; the full history of every file is kept by git). None of it is imported by the current system
(`raspberry_pi/`, `twin/`, `ml/`, `rl/`, `dashboard/`, `firmware/`) - checked by searching every import before
the move and by running the full test suite after it (see `docs/CLEANUP.md`).

| Path | What it was | Superseded by |
|---|---|---|
| `app/`, `auth/`, `main.py`, `smart_building_api_flask.py`, `Dockerfile`, `docker-compose.yml`, `run_docker.bat` | FastAPI / Flask back end of the first design (JWT, Postgres, Redis) | `raspberry_pi/edge_brain.py` (Flask, SSE, SQLite store) |
| `sim/`, `integration/` (except the room configuration), `data/generator.py`, `config.yaml`, `room_config.json` | first building simulator and its coordinator | `twin/` (ISO 13790 5R1C physics, scenarios, runner) |
| `integration/building_config.py` | moved, not archived: now `twin/building_config.py` | - |
| `control/`, `agents/`, `smart_building_controller.py` | rule / MPC / PPO (stable-baselines3) controllers and room/floor/building agents on the first simulator | `twin/controllers.py` (rules, multi-objective optimiser), `rl/` (PPO on the current twin) |
| `hardware/`, `edge_gateway/` | MQTT/REST gateway of the first design | `raspberry_pi/mqtt_bridge.py`, HTTP endpoint of the edge brain |
| `ai/` | LLM assistant, forecasting and maintenance prototypes | not part of the final system |
| `wso2/`, `k8s/` | WSO2 API manager / micro-integrator and Kubernetes manifests for the first design | single-device deployment on the Raspberry Pi (docs/DEPLOYMENT.md) |
| `train_*.py`, `compare_*.py`, `evaluate_*.py`, `export_model.py`, `generate_simulated_occupancy_data.py`, `occupancy_*.py`, `dataset_comparison.*` | first occupancy-model scripts. `train_final_unified_occupancy_model.py` produced `models/final_unified_occupancy_pipeline.pkl`, which is still loadable for comparison; its training mixed the UCI files with their Kaggle copies, so its scores are not held-out results (docs/results/occupancy.md) | `ml/occupancy.py` |
| `experiments/`, `output/experiments/` | experiments A-C on the first simulator and their outputs (research evidence of that stage) | `experiments/run.py`, `experiments/results/` |
| `docs/` | documents describing the first design; `hardware_implementation_guide.md` has pins that no longer match the firmware | `docs/` (current), `docs/HARDWARE.md` |
| `test_*.py` | tests of the first design | `tests/` |
| `requirements.txt` | dependencies of the first design | `requirements/` |
| `memory/MEMORY.md` | notes of an earlier assistant session | `docs/COMPLETION_LOG.md` |

To run any of it, check out commit `35a384b` or earlier.
