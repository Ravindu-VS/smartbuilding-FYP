# Edge Intelligence Based Energy Management and Optimization System for Smart Buildings — Hybrid Cyber-Physical Digital Twin

**Author:** Vinusha Rathnayaka · BSc (Hons) Computer Engineering, Final Year Project

A five-floor, 26-room smart building: 25 rooms simulated by a physics-based digital twin and one real room
(Room 101, Office A) measured by an ESP32-S3 sensor/actuator node. A Raspberry Pi 4B "edge brain" estimates
occupancy, decides lighting and air conditioning with a multi-objective optimiser behind a safety layer,
learns from public datasets and the simulator (occupancy, thermal and energy models; a PPO policy), keeps
every model versioned behind acceptance tests, stores history with provenance, and streams the building to a
Next.js dashboard with a 3D digital twin.

Every number in this README comes from a run recorded in `experiments/results/` or `docs/results/`.
What is real, simulated, predicted or estimated is stated everywhere (see [provenance](#provenance)).

**Status (25 Oct 2026):** software complete and verified (104 tests, browser flows 40/40, experiments 1-11 PASS). The Room 101
hardware has not been delivered yet: until it arrives the virtual board (`run_local.bat virtual`) sends Room 101
readings exactly like the firmware, and the bring-up steps plus a bench-check script are ready in
[docs/HARDWARE.md](docs/HARDWARE.md). Final report: [docs/FINAL_REPORT.md](docs/FINAL_REPORT.md).

---

## 1. Architecture

```
ESP32-S3 (Room 101)  --HTTP every 3 s (edge also accepts MQTT sb/v1/room/f2_office_a/*)-->  Raspberry Pi 4B: edge brain (Flask :8001)
  BME280, BH1750, SCD41, LD2410C,                                          |- validation, InputGuard, SQLite store (provenance)
  INA226, MQ-2, PIR; fan / LED / damper  <--decision (fan, LED, servo)--   |- Room 101: PIR+CO2 fusion -> multi-objective controller -> SafetyLayer
                                                                           |- digital twin: 25 rooms, ISO 13790 5R1C physics, 2 copies (AI vs conventional)
                                                                           |     controllers: schedule | RF rule | multi-objective (MPC-like) | PPO (when approved)
                                                                           |- models (numpy JSON, registry): occupancy, thermal forecast (live), shadow model, drift
                                                                           '- API v3 + Server-Sent Events --> dashboard (Next.js :3000) + 3D twin (three.js)
Offline (development PC): public datasets -> ml/ (training, evaluation, registry) ; twin -> rl/ (PPO training, evaluation) ; experiments/
```

| Part | Where |
|---|---|
| Edge brain (API, SSE, store, MQTT, models) | `raspberry_pi/` |
| Digital twin (physics, weather, occupants, sensors, controllers, safety, scenarios) | `twin/` ([docs/SIMULATION.md](docs/SIMULATION.md)) |
| Machine learning (occupancy, thermal, energy, portable models, registry, drift, shadow) | `ml/` ([docs/ML.md](docs/ML.md)) |
| Reinforcement learning (numpy PPO, environment, controller, evaluation) | `rl/` ([docs/RL.md](docs/RL.md)) |
| Firmware | `firmware/esp32_smart_building/` ([docs/HARDWARE.md](docs/HARDWARE.md)) |
| Dashboard and 3D twin | `dashboard/fyp-research-twin/` ([docs/twin3d.md](docs/twin3d.md)) |
| Data (manifest, processed tables), models, experiments, tests, scripts | `data/`, `models/`, `experiments/`, `tests/`, `scripts/` |

## 2. The building: 5 floors, 26 rooms

Floors 0 Retail & Lobby, 1 Health & Recreation, 2 Operations, 3 Residential, 4 Penthouse. **Room 101 = Office A
(`f2_office_a`, floor 2) is the real room; Rooms 102-126 are simulated.** Room numbers are labels; room ids are
the keys in code, API, store and 3D twin. Full table: [docs/ROOMS.md](docs/ROOMS.md).

| | Room 101 (real) | Rooms 102-126 (simulated) |
|---|---|---|
| Sensors | BME280, BH1750, SCD41 (NDIR CO2), LD2410C mmWave, PIR, INA226 power, MQ-2 (gas; never used as CO2) | modelled: noise + lag, PIR as a Poisson process |
| Values shown | only while the board posts (no reading for 10 s = NOT CONNECTED, no values) | always, labelled simulated |
| Control | PIR+CO2 fusion -> multi-objective controller -> safety layer -> fan (AC), LED (lights), servo (damper) | the selected controller -> the same safety layer -> simulated AC and lights |
| Energy | measured by the INA226 | computed by the physics |

## <a id="provenance"></a>3. What is real, simulated, predicted, estimated

| Class | Examples | Shown as |
|---|---|---|
| `room101_measured` | the board's readings (source `sensor_node`) | LIVE ESP32 |
| `synthetic` | the 25 simulated rooms, the HTTP test sender, the MQTT device harness | SIMULATED / TEST SENDER |
| `prediction` | occupancy probability, 30-min temperature forecast, shadow-model outputs | "estimate", "forecast (prediction)" |
| `public_real` | UCI occupancy, BDG2 electricity and weather (training and evaluation only) | model cards |
| unavailable | a disconnected or stale board | NOT CONNECTED, values "—" |

The twin's weather is synthetic (Colombo monthly normals), not measured; measured Colombo weather could not be
downloaded from the development environment (docs/DATASETS.md).

## 4. Run it

Windows (development PC): double-click **`run_local.bat`** (checks the venv and packages, frees ports
8001/3000, starts the edge brain and the dashboard, opens http://localhost:3000; `run_local.bat test` adds the
HTTP test sender). **Until the hardware arrives:** `run_local.bat virtual` adds the virtual board, which sends
Room 101 readings exactly like the firmware, replaying the real UCI office measurements (`virtual-twin`: Office A
simulated by the digital twin, reacting to the AI's commands). The dashboard labels it VIRTUAL BOARD and the
store keeps it as synthetic. Linux / Raspberry Pi:

```
python3 -m pip install -r requirements/edge.txt     # Pi: flask, numpy, paho-mqtt only
python3 -m pip install -r requirements/train.txt    # development PC (adds pandas, scikit-learn, gymnasium)
python3 -m pip install -r requirements/dev.txt      # + tests
scripts/start.sh dev | edge | live | harness | virtual | virtual-twin   # see docs/DEPLOYMENT.md
```

| URL | What |
|---|---|
| http://localhost:3000 | dashboard with the 3D twin |
| http://127.0.0.1:8001/health | edge brain health |
| http://127.0.0.1:8001/api/stream | the SSE stream the dashboard uses |
| http://127.0.0.1:8001/api/models | registry, live models, shadow comparison, drift |

The first start runs the AI's 7-day learning week (cached in `output/twin_cache/`). Offline training is never
started by the run scripts. Full install, modes, environment variables and Raspberry Pi steps:
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). API: [docs/API.md](docs/API.md).

## 5. The dashboard and the 3D twin

Header: simulated clock, the **AI CONTROL** master switch (all rooms, simulated and real), the AI controller
(thesis optimiser, Random Forest rule, PPO - offered only once approved), edge and board status, Viva demo.
KPI strip: same-period energy, cost, discomfort, peak, lights in empty rooms, estimation accuracy (AI vs AI off).
3D twin: building, floor and room views (furnished rooms, people, AC units, airflow layer, daylight), driven
only by the streamed state. Building list (room numbers), room panel (readings with provenance badges, the AI's
decision and reasons, the 30-min forecast, AI vs AI off, scenario buttons), bottom panels: decisions, energy
meter, analytics, **Models & data** (models in use, shadow comparison, live forecast accuracy, drift, data
sources). AI ON vs AI OFF: two copies of the building run in lock-step with identical weather, occupants and
sensor noise, so every minute has both results.

## 6. Results

### Machine learning (held-out evaluation; [docs/ML.md](docs/ML.md))

| Model | Data and split | Result | Baseline |
|---|---|---|---|
| Occupancy, random forest, 5 UCI inputs (`occupancy_rf` v1, used by the RF rule) | UCI; trained 2-10 Feb, tested on 11-18 Feb 2015 | F1 0.973, AUC 0.997, accuracy 0.989 | legacy deployed RF scored 0.997 on the same week but had been trained on it (Kaggle copies) - not a held-out result |
| Occupancy, best on validation: gradient boosting + trends (`occupancy_best` v1) | same | F1 0.981, AUC 0.998 | - |
| Occupancy from CO2 only (any model) | same | F1 0.47-0.52 | deployed CO2 tree F1 0.530: CO2 alone is weak; the candidate `occupancy_co2_temporal` failed its acceptance test and was not promoted |
| Learned PIR+CO2 fusion, simulated rooms (`occupancy_twin_fusion` v1, shadow mode) | twin seed 31 (MO) -> seed 32 (schedule controller) | F1 0.962 (precision 0.957, recall 0.967) | hand-built fusion F1 0.932 (precision 0.883) |
| UCI-trained models on the twin | domain check | F1 0.005-0.62 | large gap between the domains in both directions |
| Room temperature 15 min ahead (`thermal_h15` v1) | twin, unseen seeds 21-23 (incl. unseen scenario) | MAE 0.158 K | persistence 0.226, grey-box 1R1C 0.214 |
| Room temperature 30 min ahead (`thermal_h30` v1, live) | same | MAE 0.267 K (unseen scenario 0.292) | persistence 0.341, grey-box 0.332 |
| Same method on the real UCI office (no HVAC data) | UCI later week | MAE 0.071 K (15 min), 0.114 K (30 min) | persistence 0.076, 0.126 |
| Day-ahead hourly electricity (`energy_dayahead` v1) | BDG2, 18 offices Jun 2016-May 2017 -> Jun-Dec 2017 | CV(RMSE) 15.4 %, NMBE 0.1 %; 17/18 buildings <= 30 % | seasonal naive 22.5 %, persistence 22.6 % |
| Same, 5 buildings never seen in training | | CV(RMSE) 13.5 % | persistence 14.0 % (little gain on unseen buildings) |

### Control (digital twin, synthetic; 7 days x 3 seeds, matched conditions; [docs/RL.md](docs/RL.md))

Normal week (experiments 1 and 5; mean ± sd over seeds; 25 simulated rooms, 7 measured days):

| Controller | Energy, 7 days (kWh) | vs schedule | Occupied time with \|PMV\| > 0.5 | PMV-hours > 0.5 | AC on/off cycles | Light switches | Decision time (ms) |
|---|---|---|---|---|---|---|---|
| Conventional schedule | 10,964 ± 76 | +0.0 % | 21.7 % | 197.9 | 324 | 334 | 0.01 |
| Always on | 14,705 ± 99 | -34.1 % | 8.6 % | 2.9 | 0 | 0 | 0.00 |
| RF threshold rule (original) | 11,836 ± 113 | -7.9 % | 36.9 % | 153.9 | 0 | 1567 | 0.01 |
| Multi-objective (MPC-like) | 10,120 ± 109 | +7.7 % | 13.6 % | 28.6 | 640 | 2020 | 0.38 |
| PPO (v2) | 9,721 ± 92 | +11.3 % | 5.2 % | 26.6 | 771 | 911 | 0.05 |

All scenarios (experiments 5-8): energy change vs the conventional schedule (negative = more energy) and share of
occupied time with |PMV| > 0.5:

| Scenario | Schedule: energy (kWh) / discomfort | Multi-objective: vs schedule / discomfort | PPO: vs schedule / discomfort | PPO AC cycles (schedule) | Fail-safe F1 / F2 / F3 (PPO) |
|---|---|---|---|---|---|
| normal | 10,964 / 21.7 % | +7.7 % / 13.6 % | +11.3 % / 5.2 % | 771 (324) | 0 / 0 / 0 |
| low_occupancy | 10,498 / 18.3 % | +9.7 % / 10.4 % | +14.9 % / 5.3 % | 724 (324) | 0 / 0 / 0 |
| high_occupancy | 11,228 / 22.5 % | +7.2 % / 14.7 % | +10.4 % / 5.8 % | 771 (324) | 0 / 0 / 0 |
| sudden_occupancy | 10,993 / 22.7 % | +6.8 % / 13.8 % | +10.8 % / 5.4 % | 810 (324) | 0 / 0 / 0 |
| hot_weather | 12,242 / 27.0 % | +4.7 % / 21.7 % | +7.0 % / 9.5 % | 978 (324) | 0 / 0 / 0 |
| cool_weather | 8,504 / 20.6 % | +11.9 % / 0.7 % | +21.0 % / 5.1 % | 316 (324) | 0 / 0 / 0 |
| sensor_dropout | 10,964 / 21.7 % | +6.9 % / 14.6 % | +10.9 % / 7.6 % | 1201 (324) | 23374 / 0 / 0 |
| network_outage | 10,964 / 21.7 % | +6.8 % / 14.2 % | +10.7 % / 7.2 % | 872 (324) | 14632 / 0 / 0 |
| hvac_failure | 10,933 / 22.5 % | +7.4 % / 13.6 % | +11.2 % / 6.6 % | 788 (324) | 0 / 0 / 0 |
| hvac_reduced | 10,808 / 32.0 % | +7.0 % / 21.9 % | +11.0 % / 12.2 % | 830 (324) | 0 / 0 / 0 |

* **PPO v2** (approved by the registry) used 7.0-21.0 % less energy than the schedule in every scenario and had a
  lower discomfort share than the schedule and the multi-objective controller in every scenario except cool
  weather. The result held on evaluation seeds 4-6, which were not used when the reward was redesigned: 11.1 % less
  energy, discomfort 4.6 % (schedule 22.2 %; multi-objective 7.9 % less energy, 11.2 %). The policy of the second
  training seed gave 9,770 kWh and 6.1 % on seeds 1-3.
* **Costs and weak spots.** PPO switches the AC on/off 2.2-3.7 x as often as the schedule (except in cool weather:
  316 vs 324); the 10-min dwell is enforced, compressor wear is not modelled. In cool weather the multi-objective
  controller kept discomfort at 0.7 % against PPO's 5.1 % (PPO saved more energy). PMV-hours (how far outside the
  comfort band) are higher for PPO than for the multi-objective controller in 6 of the 10 scenarios (low occupancy,
  cool weather and all four fault scenarios; AC failure 48.3 vs 28.6): PPO's advantage is in how often people are
  uncomfortable, not consistently in how much.
* **Original RF rule** used 7.9 % *more* energy than the schedule and was less comfortable (36.9 % of occupied
  time; 45,509 overheated room-minutes vs 12,153).
* **Faults.** With sensor dropouts / stuck sensors and network outages the fail-safe replaced the affected decisions
  with the schedule's (F1 counts above); no controller raised an exception or issued an invalid command (F2 = F3 = 0).
  A controller that crashes on every decision falls back to the schedule on every decision (F2 = 12,600) and the
  building keeps running; a corrupted model is reported as not loaded and no prediction is produced.
* These are **simulation results** on a twin that is not calibrated against metered data from the building; they
  compare controllers under identical conditions and are not a savings forecast for the real building.
  Full tables: [experiments/results/SUMMARY.md](experiments/results/SUMMARY.md).

### Room 101's pipeline on replayed real data (experiment 11; virtual board, before the hardware arrives)

The held-out UCI week (11-18 Feb 2015, 9,752 min) was sent through Room 101's own pipeline exactly as the board
would send it (every 3 s): recorded temperature, humidity, light and CO2; PIR / mmWave from sensor models driven
by the recorded occupancy.

| Room 101 pipeline | occupancy F1 | lights on in empty minutes |
|---|---|---|
| PIR + CO2, quiet sensors | 0.884 | 9.8 % |
| PIR + mmWave + CO2, quiet sensors | 0.790 | 22.1 % |
| PIR + CO2, noisy sensors (10x false triggers) | 0.516 | 57.2 % |
| CO2 only (recorded inputs only) | 0.529 | 91.4 % |
| reference: `occupancy_rf` (T, RH, light, CO2) | 0.973 | - |

* **Finding and fix:** before the fix, CO2 lingering after people left kept the lights on in 92 % of the empty
  minutes. Room 101's controller now has a vacancy rule: no PIR / mmWave detection for 15 min -> lights off, AC
  to ECO.
* Presence-sensor false triggers dominate the remaining waste (each restarts the 15 min), so the empty-room
  false-trigger rate is part of the bench check (`scripts/check_hardware.py --empty-room`).
* The PIR / mmWave results depend on the assumed sensor models; only the CO2-only row uses recorded inputs alone.
* The edge brain handled both virtual-board sources end to end (every reading answered, actuator feedback
  verified, labelled VIRTUAL BOARD, stored as synthetic), and the bench check was rehearsed against it
  (22 pass, 0 fail).

## 7. Self-learning, safety and the hardware path

* Models are trained offline, evaluated on held-out data, versioned in `models/registry/`, run in shadow mode,
  and promoted only after acceptance tests (`python -m ml.registry evaluate|promote|rollback`); history and
  every rejection are kept ([docs/RETRAINING.md](docs/RETRAINING.md)). No learning agent explores on the real room.
* Every controller sits behind `InputGuard` + `GuardedController` (fall-back to the rule-based schedule on
  missing, implausible, stuck or stale inputs, an exception or an invalid action) and the `SafetyLayer` (valid
  values and 22-27 C set-points, equipment rooms always cooled, heat-stress guard, CO2 fresh-air rule).
* The edge needs only flask + numpy (+ paho-mqtt): models are numpy-only JSON; tested with the training stack
  blocked. Credentials live in the environment (MQTT) or a git-ignored `secrets.h` (Wi-Fi).
* Hardware status ([docs/HARDWARE.md](docs/HARDWARE.md)): firmware implemented (HTTP); edge HTTP and MQTT paths
  implemented and tested with a test sender and a simulated MQTT board; **firmware not compiled and no physical
  bench test in this work** (no toolchain or board available here). A host-side syntax and library-API check
  (`firmware/tools/check_firmware.py`) found and fixed two library problems (SCD41 silently skipped with the
  current SCD4x library; INA226 code that compiled with no INA226 library). When the board is wired, follow the
  bring-up steps in docs/HARDWARE.md and run `python3 scripts/check_hardware.py --actuators --ask`. Until then the
  virtual board (`raspberry_pi/virtual_board.py`) feeds Room 101 with firmware-identical readings.

## 8. Reproduce

```
python3 scripts/fetch_datasets.py && python3 scripts/preprocess_datasets.py   # public data (internet), checksums
scripts/make_synthetic_corpus.sh                                              # simulator corpus
python3 -m ml.occupancy ; python3 -m ml.thermal ; python3 -m ml.energy ; python3 -m ml.registry init
python3 -m rl.cartpole_check ; python3 -m rl.train --seed 0                   # PPO (about 1 h per run on 2 vCPUs)
python3 experiments/run.py --all                                              # experiments 1-11
python3 -m pytest -q                                                          # tests (docs/TESTING.md)
```

## 9. Repository layout

| Path | What |
|---|---|
| `raspberry_pi/` | edge brain, store, MQTT bridge, device harness, HTTP test sender, virtual board, Pi run script |
| `twin/` | digital twin (`building_config.py` = the 26 rooms), controllers, safety, scenarios, runner, validation |
| `ml/`, `rl/` | training, evaluation and inference code |
| `models/registry/` | approved and candidate model versions (JSON + metadata + model card); `models/ppo_runs/` training runs |
| `data/manifest.json` | dataset provenance and checksums (raw and processed data are regenerated, git-ignored) |
| `experiments/configs/`, `experiments/results/` | experiments 1-11 and their recorded results |
| `docs/` | technical documents; `COMPLETION_MATRIX.md`, `COMPLETION_LOG.md`, `ACCEPTANCE_GATE.md`, `FINAL_REPORT.md` |
| `tests/` | automated tests; `tests/e2e/twin_flows.py` browser flows |
| `archive/legacy_v1/` | the first architecture, superseded (see `archive/README.md`, `docs/CLEANUP.md`) |
| `Dataset/` | the original dataset copies (UCI and its "Kaggle" duplicates) |

## 10. Known limitations

* Simulated rooms are simulated: a 5R1C model with synthetic weather and stochastic occupants, not a validated
  building model or CFD; the 3D furnishing and airflow are illustrative.
* Models trained on the simulator learn the simulator; the UCI data is one office in a Belgian winter; the
  real room has no labelled occupancy data yet, so its controller stays rule-based plus the optimiser.
* PPO is a single policy shared by the rooms (not a multi-agent system) and controls simulated rooms only. Its
  energy and comfort results are simulation results; it cycles the AC more than the schedule and its comfort
  deviations are not always smaller than the optimiser's (section 6).
* Re-running experiments 1 and 5-8 from scratch takes hours: the 108 distinct runs took 3.9 h of worker time
  on 2 vCPUs (about 2 h with 2 workers). The run cache `experiments/results/run_cache/` is not committed.
* Firmware not compiled for the ESP32-S3 and not bench-tested in this work (only a host-side syntax / library-API
  check); the board uses HTTP (MQTT is implemented on the edge).
* Raspberry Pi GPIO outputs are recorded, not driven (`gpio_driving: false`).
* This is a research prototype without safety certification ([docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)).
