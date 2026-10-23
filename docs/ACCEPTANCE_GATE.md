# Final acceptance gate

Evaluated on 23 Oct 2026 against the master prompt's checklist (section 21). PASS = verified by a test, a
run or a recorded result; FAIL = checked and not met; BLOCKED = cannot be done in this environment (reason
given); N/A = does not apply. Code existing is never enough for PASS.

## A. Simulation

| Item | Status | Evidence |
|---|---|---|
| The building simulation runs | PASS | `tests/test_simulation.py`, `tests/test_scenarios.py`, every experiment run |
| Five floors and all 26 room identities preserved | PASS | `test_26_rooms_5_floors_one_real_room_and_numbers`; ids unchanged, numbers 101-126 added as labels (docs/ROOMS.md) |
| The 25 simulated rooms behave independently where intended | PASS | `test_rooms_are_not_identical` (areas, types, AC sizes differ); per-room results in `experiments/results/*/per_room.json` |
| Thermal behaviour plausible and tested | PASS | set-point tracking, occupant gains, failed compressor, dt 5-30 s stability; thesis reference trace (`tests/test_twin.py`) |
| HVAC and lighting states update correctly | PASS | `twin/validation.py` checks on every generated file (AC off -> no AC power; lighting = installed x level) |
| Energy calculations consistent, correct units | PASS | experiment 9 (rooms = floors = end uses = building; live meter = room energy) |
| Comfort and supported IAQ constraints monitored | PASS | PMV/PPD and CO2 in every run's metrics; safety rule R4; IAQ minutes reported |
| Synthetic data generation reproducible | PASS | `test_runner_records_validate_and_are_deterministic`; generator writes SHA-256 per file |
| Failure scenarios can be exercised | PASS | 12 scenarios incl. AC failure, sensor dropout/stuck, network outage; experiment 8 |

## B. Real-world datasets

| Item | Status | Evidence |
|---|---|---|
| Suitable public datasets researched | PASS | docs/DATASETS.md (UCI occupancy, BDG2; candidates considered and why not) |
| Source URLs and licences documented | PASS | `data/manifest.json` (CC BY 4.0; CC BY-SA 4.0 as in the BDG2 LICENSE file) |
| Raw and processed data separated | PASS | `data/raw/` vs `data/processed/`; `test_raw_downloads_are_not_committed` |
| Preprocessing reproducible | PASS | `test_preprocessing_is_reproducible` (checksums of the processed tables) |
| Data provenance preserved | PASS | provenance column in every table and store row; `test_export_keeps_provenance_classes_apart` |
| Leakage and inappropriate mixing addressed | PASS | chronological splits (`test_chronological_splits_do_not_overlap`), segment-bounded features; UCI/Kaggle duplicates found and documented; synthetic and real never pooled |
| Measured Colombo weather | BLOCKED | hosts refused by the network proxy (UCI archive, Open-Meteo, NASA POWER, Meteostat, NOAA); synthetic climate kept and labelled |

## C. Machine learning

| Item | Status | Evidence |
|---|---|---|
| Occupancy model trained | PASS | `models/registry/occupancy_rf/v1`, `occupancy_best/v1`, `occupancy_twin_fusion/v1` |
| Appropriate held-out evaluation | PASS | later UCI week (11-18 Feb); twin seed/controller never seen; docs/results/occupancy.md |
| Baseline and final metrics reported | PASS | logistic regression, legacy models, hand-built fusion, persistence, grey-box, seasonal naive |
| Thermal / energy prediction where supported | PASS | `thermal_h15`, `thermal_h30`, `energy_dayahead` (docs/results/thermal.md, energy.md) |
| Training and inference pipelines reproducible | PASS | fixed seeds, `test_training_is_reproducible_with_fixed_seed`, online = batch feature tests, portable = scikit-learn |
| Models load and run in the application | PASS | `/api/models` live models; `occupancy_rf` in the RF rule; `thermal_h30` forecasts in the room state; shadow model scored live |
| Model failures handled safely | PASS | `test_model_failure_is_reported_not_replaced`, tampered model refused, experiment 8 model-load case |

## D. Reinforcement learning

| Item | Status | Evidence |
|---|---|---|
| Environment with valid observations, actions, rewards | PASS | `tests/test_rl.py` (shapes, finite rewards, truncation, invalid actions), gymnasium `check_env` |
| PPO trained | PASS | numpy PPO verified on CartPole (500/500, 3 seeds); runs in `models/ppo_runs/` |
| Saved policy reloads for inference | PASS | `test_policy_save_load_roundtrip_and_shape_check`, `test_policy_runs_without_training_environment`, edge runtime test |
| Policy respects control constraints | PASS | action set limited to 22-27 C set-points; AC dwell; safety layer in every step (`test_ppo_in_the_runner_passes_safety_and_guard`) |
| Compared with relevant baselines | see below | experiments 5-8 |
| Energy, comfort and failure outcomes reported | see below | |
| No unsupported superiority or savings claims | see below | |

## E. Self-learning

| Item | Status | Evidence |
|---|---|---|
| New data collected with provenance | PASS | SQLite store (readings, decisions, predictions, commands, events); `tests/test_store_mqtt.py`, `tests/test_integration.py` |
| Model versions recorded | PASS | registry metadata (data SHA-256, seed, versions, metrics); model version in decision rows |
| Retraining reproducible | PASS | training scripts with fixed seeds; evaluation-only reruns reproduce the reported numbers (experiments 2-4) |
| Candidates evaluated before promotion | PASS | `ml/registry.py` acceptance tests; `occupancy_co2_temporal` rejected; registry history |
| Safety fallback and rollback available | PASS | `GuardedController` (F1-F3), `test_registry_acceptance_promote_rollback`, `POST /api/models/rollback` |
| Real-world online exploration not uncontrolled | PASS | no learning on the real room; PPO limited to simulated rooms; real room = rule-based estimator + optimiser + safety layer |

## F. Hardware integration

| Item | Status | Evidence |
|---|---|---|
| Room 101 uses the correct live-room mapping | PASS | Room 101 = `f2_office_a` = the only `data_source: hardware` room; firmware sends `room_id: f2_office_a` |
| Hardware data reaches backend and twin | PASS (software path) | HTTP and MQTT harness, experiment 10; `raspberry_pi/test_edge_brain.py`. With the physical board: BLOCKED (no board here) |
| MQTT and connection status handled | PASS (edge side) | `test_bridge_end_to_end_with_broker`, ack timeout test, status endpoint; firmware still HTTP |
| Hardware and simulated values distinguishable | PASS | provenance per value group; test sender / harness never shown as the real board |
| Physical verification status documented honestly | PASS | docs/HARDWARE.md status table (not compiled, not bench-tested here) |
| Test harness for unavailable hardware | PASS | `raspberry_pi/esp32_test_sender.py`, `raspberry_pi/mqtt_device_sim.py`, `scripts/start.sh harness` |
| Firmware compiled / physically verified | BLOCKED | no Arduino-ESP32 toolchain reachable (GitHub release downloads refused) and no board attached |

## G. Digital twin

| Item | Status | Evidence |
|---|---|---|
| Exterior, floor and room views work | see final browser run | `tests/e2e/twin_flows.py` flows A-F |
| Room selection maps to the correct data | see final browser run | flows A, B, G |
| HVAC and occupancy visualisations reflect actual states | see final browser run | flow C (airflow intensity = AC cooling output) |
| Live room clearly distinguished | see final browser run | flow G (Room 101, board status) |
| No fabricated values used as live measurements | PASS | `test_no_board_means_not_connected_and_no_values`, `test_missing_fields_stay_missing`, provenance tests |
| Interface responsive and stable | see final browser run | flows run without console errors |

## H. Quality and clean-up

| Item | Status | Evidence |
|---|---|---|
| Automated tests executed | see final run | docs/TESTING.md |
| Frontend and backend builds checked | PASS | `npx tsc --noEmit`, `npx eslint src`, `npx next build` succeeded; backend imports and tests |
| Model-loading and integration tests pass | see final run | |
| No known critical runtime errors | see final run | |
| Unnecessary files safely removed | PASS (quarantined) | moved to `archive/legacy_v1/` with git mv, verified by the full test run; permanent deletion deliberately left to the owner (docs/CLEANUP.md) |
| No required project assets lost | PASS | nothing deleted; datasets, models, firmware, results kept; `run_local.bat` restored after the reference check |
| Repository starts from documented instructions | see final run | README section 4, docs/DEPLOYMENT.md |
| Research evidence and model artifacts reproducible | PASS | manifest checksums, registry metadata, experiment configs and status files |
