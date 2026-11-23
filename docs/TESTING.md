# Tests

Run from the repository root.

```
python3 -m pytest                          # everything (about 1-2 min on 2 vCPUs)
python3 -m pytest -q -m "not slow"         # without the multi-hour-simulated tests
python3 tests/e2e/twin_flows.py            # browser flows A-G (needs the edge brain on :8001 and the dashboard on :3000)
cd dashboard/fyp-research-twin && npx tsc --noEmit && npx eslint src && npx next build
python3 -m rl.cartpole_check               # PPO implementation check on CartPole-v1
python3 firmware/tools/check_firmware.py    # firmware syntax / core-stub check (host g++, not an ESP32 compile)
python3 scripts/check_hardware.py --actuators --ask   # bench check of the real room (board + edge brain running)
```

| File | What it checks |
|---|---|
| `tests/test_simulation.py` | 26 rooms / 5 floors / one real room and numbers 101-126; rooms differ; AC cools to set-point with electricity = thermal/COP + fan; occupants warm a room; failed compressor = fan only; stability for dt 5-30 s; lighting power; room/floor/end-use energy totals; seed reproducibility; safety rules R1-R4; invalid commands rejected |
| `tests/test_twin.py` | the thesis physics reference trace, controllers, live twin (moved from `twin/tests`) |
| `tests/test_scenarios.py` | all scenarios exist; runner output validates and is deterministic; validation catches impossible states; occupancy scaling; AC failure window; sensor dropout and network outage; InputGuard hold / missing / implausible / stale / stuck; fail-safe F1/F2/F3; fault scenarios with a sensor-driven controller (slow) |
| `tests/test_datasets.py` | manifest documents every dataset; tracked UCI (and "Kaggle") copies match the checksums; processed table ordered, complete, files not overlapping; preprocessing reproducible (checksums); raw data git-ignored |
| `tests/test_ml.py` | online = batch features; no feature crosses a recording gap; splits do not overlap in time; metric formulas; portable export = scikit-learn for 5 model families; input validation (wrong count, inf, missing feature, incompatible format, tampered model); reproducible training; registry acceptance / promote / rollback / rejection; tampered file detected; drift monitor; registered models load; a failed model is reported, not replaced; thermal online = batch features |
| `tests/test_rl.py` | PPO gradients vs finite differences; GAE; policy save/load and shape check; environment reset/step shapes, finite non-positive rewards, truncation, reproducible reset, invalid action rejected; gymnasium env checker; actions only produce allowed commands; decision hold and AC dwell; inference without the training environment; PPO in the runner keeps safety rules; policy crash -> fail-safe; missing policy file is an error |
| `tests/test_store_mqtt.py` | migrations once, restart, dedupe, provenance check; history and command acks; telemetry validation; MQTT bridge end to end with a broker (commands, acks, duplicates, invalid JSON, out-of-range values, credentials never logged); ack timeout; store export keeps provenance classes apart |
| `tests/test_integration.py` | live vs simulated separation and provenance (real board vs test sender); new API endpoints; admin token; restart without duplicates; end-to-end flow steps 1-12 |
| `tests/test_edge_runtime.py` | the edge brain, store, models and PPO controller run with pandas, scikit-learn, scipy, joblib and gymnasium unavailable |
| `raspberry_pi/test_edge_brain.py` | board link states, no invented values, MQ-2 never used as CO2, missing fields stay missing, board timeout, test sender labelled, LED calibration, AI switch, stream notification, API |
| `tests/test_check_hardware.py` | the bench-check script against a real edge-brain process fed by the test sender: labelled a software check, sensors not sent are MISSING (never PASS), actuator round trip verified, override cleared, no energy label without INA226 data |
| `tests/test_virtual_board.py` | the virtual board sends exactly the firmware's fields (parsed from the `.ino`), replays the recorded UCI values, applies replies and the fail-safe like the firmware, omits dropped sensors, the room model responds to the AC; the edge brain labels it VIRTUAL BOARD and stores synthetic; Room 101's vacancy rule |
| `tests/test_firmware_check.py` | firmware syntax against local stubs for Arduino-ESP32 core 3.x and 2.x (skipped without g++; not a real library or board compile) |
| `tests/e2e/twin_flows.py` | 3D twin in the real dashboard: building/floor/room views, selection, airflow, presentation mode (flows A-F) and provenance / room numbers / models panel (flow G) |

Results of the final run are recorded in `docs/ACCEPTANCE_GATE.md` and `docs/FINAL_REPORT.md`.

## Hardware commissioning (real board)

`scripts/commission_room101.py` is not a unit test: it drives the real ESP32-S3 and Pi, asks the operator
for physical observations and writes evidence to `docs/commissioning_runs/`. `tests/test_commission_runner.py`
checks its offline parts (evidence files, statuses, state lookup). BLE framing is covered by
`raspberry_pi/test_ble_gateway.py`, the firmware by `tests/test_firmware_check.py` (host syntax check with
stubs, not an ESP32 compile).

