# Final report

Smart Building FYP - Edge Intelligence Based Energy Management and Optimization System, Hybrid Cyber-Physical
Digital Twin. Work of 23 Oct 2026 on top of commit `35a384b`. Every figure below comes from a recorded run
(`experiments/results/`, `docs/results/`) or a test; nothing was filled in.

## 1. Overall completion

<!-- OVERALL -->

## 2. Architecture

```
                ┌───────────── offline (development PC) ─────────────┐
 public data ──►│ scripts/fetch + preprocess ─► ml/ (occupancy,        │
 (UCI, BDG2)    │   thermal, energy) ─► models/registry (JSON, cards) │
 twin ─────────►│ rl/ (env, numpy PPO) ─► models/ppo_runs ─► registry  │
                │ experiments/run.py (1-10) ─► experiments/results      │
                └───────────────────────────┬─────────────────────────┘
                                            │ approved versions (git)
ESP32-S3 (Room 101) ──HTTP 3 s / MQTT──► Raspberry Pi 4B edge brain (raspberry_pi/edge_brain.py)
 sensors, fan/LED/damper ◄──decision──    ├ validation + InputGuard ─► SQLite store (provenance, migrations)
                                          ├ Room 101: PIR+CO2 fusion ─► multi-objective controller ─► SafetyLayer
                                          ├ digital twin: 25 rooms (5R1C) x 2 copies; controller: schedule |
                                          │   RF rule (registry RF) | multi-objective | PPO (approved only),
                                          │   each behind GuardedController + SafetyLayer
                                          ├ LiveModels: thermal forecast (active), learned fusion (shadow), drift
                                          └ REST API v3 + SSE ─► Next.js dashboard + three.js 3D twin
```

Data flow of a reading: sensor -> firmware (missing sensor = field omitted) -> HTTP/MQTT -> validation (finite
numbers, ranges, schema, msg_id dedupe) -> one ingestion function -> store (`room101_measured` only for the real
board) -> estimator, controller, safety layer -> reply / MQTT command -> board actuates and reports its actuator
levels (verified against the command) -> SSE -> dashboard and 3D twin. A board silent for 10 s is shown NOT
CONNECTED with no values.

## 3. Dataset inventory

| Dataset | Source | Licence | Used variables | Preprocessing | Use |
|---|---|---|---|---|---|
| UCI Occupancy Detection (Candanedo & Feldheim 2016) | archive.ics.uci.edu dataset 357 (DOI 10.24432/C5X01N), downloaded from the author's GitHub repository (UCI host refused here); identical to `Dataset/UCI/` | CC BY 4.0 | Temperature, Humidity, Light, CO2, HumidityRatio, Occupancy; 1 min; 20,560 rows | concatenated, time-ordered, no value changed; features per contiguous recording | occupancy models; real-data thermal check |
| BDG2 (Miller et al. 2020) | github.com/buds-lab/building-data-genome-project-2 (LFS) | CC BY-SA 4.0 (repository LICENSE) | hourly electricity (kWh), NOAA ISD-Lite weather, metadata; Panther site, 23 offices, Jun 2016-Dec 2017 | completeness rule >= 90 %, weather gaps <= 3 h interpolated (none needed), electricity never filled | energy model |
| Synthetic corpus (twin) | `scripts/make_synthetic_corpus.sh` | project | all simulator outputs, sensors as delivered | validation checks on every file | thermal model, learned fusion, domain check |

Finding: the "Kaggle" occupancy files in the repository are byte-identical copies of UCI; the previously deployed
RF was trained on them and on its own test rows. Measured Colombo weather: BLOCKED (hosts refused).

## 4. Model inventory

| Task / version | Training data | Evaluation | Metrics (held-out) | Status |
|---|---|---|---|---|
| `occupancy_rf` v1 - random forest, 5 UCI inputs | UCI 2-10 Feb | UCI 11-18 Feb | F1 0.973, AUC 0.997 | active (RF rule; real-room comparison; drift reference) |
| `occupancy_best` v1 - gradient boosting + trends | same | same | F1 0.981, AUC 0.998 | active |
| `occupancy_co2_temporal` v1 - MLP on CO2 + trends | same | same | F1 0.465 | rejected (must beat the deployed CO2 tree, F1 0.530) |
| `occupancy_twin_fusion` v1 - gradient boosting on PIR + CO2 | twin seed 31 | twin seed 32, other controller | F1 0.962 vs hand-built 0.932 | approved; runs in shadow mode |
| `thermal_h15` v1 | twin seeds 11-16 | unseen seeds 21-23 | MAE 0.158 K (persistence 0.226) | active |
| `thermal_h30` v1 | same | same | MAE 0.267 K (persistence 0.341) | active (live forecasts in the dashboard) |
| `energy_dayahead` v1 | BDG2 Jun 2016-May 2017, 18 offices | Jun-Dec 2017; 5 unseen buildings | CV(RMSE) 15.4 % (seasonal naive 22.5 %); unseen 13.5 % (persistence 14.0 %) | active (evaluation only; not used for control) |
| `ppo_policy` v1 - PPO, reward v1 | twin, simulator seeds >= 1000 | twin seeds 1-3 | 16.0 % less energy, discomfort 25.5 % (schedule 21.7 %) | rejected (comfort) |
| `ppo_policy` v2 - PPO, reward v2 | same | twin seeds 1-3; confirmed on 4-6 | 11.3 % less energy, discomfort 5.2 % (seeds 4-6: 11.1 %, 4.6 %) | approved (simulated rooms only) |

Artifacts: `models/registry/<task>/<version>/` (numpy-only `model.json`, `model.joblib`, `metadata.json` with
data SHA-256, features and units, split, seed, metrics, training distribution; `model_card.md`). Limitations per
model are in the cards: UCI is one office in winter; twin-trained models learn the simulator; energy data is one US
site with observed weather as a perfect forecast.

## 5. Controller comparison

Protocol (`rl/evaluate.py`, experiments 1 and 5-8): 25 simulated rooms, identical weather, occupants, sensor noise
and faults for every controller of a seed; 7 measured days from 2 Mar 2026 after warm-up (7 days for the
multi-objective controller's learning week, 2 days otherwise); evaluation seeds 1-3; PPO trained on simulator seeds
>= 1000 only. Savings = (E_schedule - E_controller) / E_schedule, negative when more energy is used.

**PPO registration.** Reward v1 (comfort severity only, small switching cost) saved 16.0 % / 10.6 % / 14.6 % energy
(normal / hot / high occupancy) but left people outside |PMV| <= 0.5 for more of the occupied time than the schedule
(25.5 % vs 21.7 % in the normal scenario) and cycled the AC 2,066 times a week: the registry rejected it
(`models/registry/ppo_policy/v1`). Reward v2 (adds discomfort duration and larger switching costs), trained from
scratch with the same settings, passed and is the approved version (`ppo_policy` v2, selected by validation return
before evaluation).

Normal week:

| Controller | Energy, 7 days (kWh) | vs schedule | Occupied time with \|PMV\| > 0.5 | PMV-hours > 0.5 | AC on/off cycles | Light switches | Decision time (ms) |
|---|---|---|---|---|---|---|---|
| Conventional schedule | 10,964 ± 76 | +0.0 % | 21.7 % | 197.9 | 324 | 334 | 0.01 |
| Always on | 14,705 ± 99 | -34.1 % | 8.6 % | 2.9 | 0 | 0 | 0.00 |
| RF threshold rule (original) | 11,836 ± 113 | -7.9 % | 36.9 % | 153.9 | 0 | 1567 | 0.01 |
| Multi-objective (MPC-like) | 10,120 ± 109 | +7.7 % | 13.6 % | 28.6 | 640 | 2020 | 0.38 |
| PPO (v2) | 9,721 ± 92 | +11.3 % | 5.2 % | 26.6 | 771 | 911 | 0.05 |

All scenarios (energy change vs schedule / share of occupied time with |PMV| > 0.5):

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

* PPO v2: 7.0-21.0 % less energy than the schedule in every scenario; lower discomfort share than the schedule and
  the multi-objective controller in every scenario except cool weather (0.7 % multi-objective vs 5.1 % PPO).
* Confirmation on seeds 4-6 (not used in the reward redesign): schedule 10,892 kWh / 22.2 %; multi-objective
  -7.9 % energy / 11.2 %; PPO -11.1 % / 4.6 %. Training-seed variability: the second run's policy 9,770 kWh / 6.1 %
  (selected run 9,721 kWh / 5.2 %).
* Costs: AC on/off cycles 2.2-3.7 x the schedule's (cool weather: 316 vs 324); PMV-hours higher than the
  multi-objective controller's in 6 of 10 scenarios (low occupancy, cool weather, all four fault scenarios).
* The original RF rule used 7.9 % more energy than the schedule and was less comfortable (36.9 %).
* Fault tolerance: sensor dropout / stuck sensors and network outages handled by the fail-safe (F1 counts above), no
  exceptions or invalid actions from any controller (F2 = F3 = 0 in all 10 scenarios); a crashing controller falls
  back to the schedule on every decision (F2 = 12,600); a corrupted model is refused with its error and no
  substitute prediction.
* Experiment 9: room, floor, end-use and building energy agree to < 1e-9 kWh in every run; the live meter equals the
  rooms' energy.

Conclusion: in the digital twin, PPO v2 is the most energy-efficient controller tested and reduces how often people
are uncomfortable, at the cost of more AC cycling and, in some scenarios, larger comfort deviations than the
multi-objective controller. These are simulation results (synthetic data); no savings are claimed for the real
building. Results: `experiments/results/SUMMARY.md`, `experiments/results/exp0*/`.

## 6. Integration status

| Path | Status |
|---|---|
| REST API v3 + SSE | implemented, tested (`raspberry_pi/test_edge_brain.py`, `tests/test_integration.py`) |
| SQLite store with migrations, provenance, dedupe, restart safety | implemented, tested |
| Model registry, shadow mode, drift, promotion/rollback API | implemented, tested |
| MQTT bridge (schemas, dedupe, acks, status, last will, env credentials) | implemented, tested with a local broker and a simulated board (experiment 10) |
| HTTP path from the firmware | implemented and tested with the firmware's payload |
| Manual override, actuator verification | implemented, tested |
| Edge runtime without the training stack | tested (`tests/test_edge_runtime.py`) |
| ESP32-S3 firmware | implemented (HTTP); **not compiled, not bench-tested in this work** |
| Raspberry Pi 4B | runtime requirements tested in a Linux container; **not run on a Pi here**; GPIO outputs recorded, not driven |

## 7. Testing evidence

`python3 -m pytest` on 23 Oct 2026 (Linux container, Python 3.13, 2 vCPUs): **94 passed in 55 s**, no failures, no
skips.

| File | Tests | Covers |
|---|---|---|
| `tests/test_simulation.py` | 11 | 26 rooms / 5 floors / one real room / numbers, rooms not identical, AC physics (cooling, COP, capacity factor), time-step stability, lighting power, energy sums, seeds, safety layer, invalid commands rejected |
| `tests/test_twin.py` | 15 | thesis physics reference trace, both copies see the same weather and people, determinism, AI switch and same-period meter, truth vs prediction vs baseline in the room state, scenarios, clock, real-room controller |
| `tests/test_scenarios.py` | 9 | every scenario exists, records validate and are deterministic, validation catches impossible states, occupancy scaling, AC failure, dropout / outage, InputGuard and GuardedController |
| `tests/test_datasets.py` | 5 | manifest documents every raw dataset, tracked UCI copy = manifest, processed table ordered and complete, reproducible preprocessing, raw data not committed |
| `tests/test_ml.py` | 17 | online = batch features (occupancy, thermal), no feature across a gap, chronological splits, metrics, portable JSON = scikit-learn, input validation, reproducible training, registry acceptance / promote / rollback / tampering, drift, registered models self-test, model failure reported (not replaced) |
| `tests/test_rl.py` | 11 | gradients vs finite differences, GAE, save/load, environment API (gymnasium check), allowed commands only, decision hold and AC dwell, inference without the training stack, PPO behind guard and safety layer, policy failure -> rules, missing policy is an error |
| `tests/test_store_mqtt.py` | 7 | SQLite migrations and restart, history and commands, telemetry schema, MQTT end-to-end with a broker (dedupe, acks, credentials never logged), ack time-outs, reconnect after a broker restart, export keeps provenance classes apart |
| `tests/test_integration.py` | 6 | live and simulated rooms stay separate, new endpoints, admin token on model changes, restart without duplicates, end-to-end ingestion -> store -> decision -> command, manual override and actuator verification |
| `tests/test_edge_runtime.py` | 1 | the edge brain runs with pandas / scikit-learn / scipy / joblib / gymnasium blocked |
| `raspberry_pi/test_edge_brain.py` | 12 | 26 rooms / one hardware room, no board = not connected and no values, readings shown exactly, MQ-2 never used as CO2, missing fields stay missing, board time-out, test sender never shown as the board, AI switch, SSE, API |

Dashboard: `npx tsc --noEmit`, `npx eslint src` and `npx next build` clean. Browser flows: see below.
Experiments 1-10: all PASS (`experiments/results/SUMMARY.md`).

<!-- BROWSER -->

## 8. Repository clean-up

Superseded first architecture (FastAPI/WSO2/K8s stack, first simulator, old controllers and SB3 agents, old
scripts, old docs, old experiment outputs) moved to `archive/legacy_v1/` with `git mv` after an import-by-import
reference check; the 26-room configuration moved to `twin/building_config.py`; tests consolidated in `tests/`;
requirements split into `requirements/edge|train|dev.txt`; `.gitignore` covers raw/processed/synthetic data,
caches, stores and secrets. Nothing deleted; `run_local.bat` (live Windows launcher) was restored after the check
missed `.bat` references. Details: `docs/CLEANUP.md`, `archive/README.md`.

## 9. Run instructions

```
python3 -m pip install -r requirements/dev.txt ; (cd dashboard/fyp-research-twin && npm ci)
run_local.bat                      # Windows; or scripts/start.sh dev | edge | live | harness
python3 -m pytest -q               # tests
python3 -m ml.registry status      # models; promote / rollback with python -m ml.registry promote|rollback
python3 experiments/run.py --all   # experiments 1-10
```

## 10. Remaining limitations

1. **Physical hardware not exercised here.** The ESP32-S3 firmware was not compiled (no Arduino-ESP32 toolchain
   reachable) and not bench-tested; the Raspberry Pi runtime was tested in a Linux container, not on a Pi; GPIO
   outputs are recorded, not driven. The firmware still sends HTTP; MQTT is implemented and tested on the edge side
   with a local broker and a simulated board only. Room 101's live path is verified in software, not physically.
2. **Control results are simulation results.** All energy and comfort comparisons come from the digital twin
   (synthetic). The twin's physics is checked against the thesis reference trace and physical sanity tests, but it
   is not calibrated against metered data from the real building, so the savings are not a prediction for it.
3. **Weather is synthetic.** The twin uses a Colombo climate built from published monthly normals; measured Colombo
   weather could not be downloaded (hosts refused by the network proxy).
4. **Occupancy models and the real room.** The UCI models come from one office in winter; on twin data they reach
   F1 0.005-0.62, so they are not used to control the real room, which keeps the PIR + CO2 fusion estimator. The
   learned fusion model is trained on twin data and runs in shadow mode only.
5. **Twin-trained models learn the simulator** (thermal forecasts, learned fusion). Their real-data check is limited
   to the UCI temperature series (15/30-min forecasts, small gain over persistence).
6. **Energy model** is evaluated on one US site (BDG2 Panther offices) with observed weather used as a perfect
   forecast; it is not used for control.
7. **PPO.** Two training seeds per reward version. The reward was redesigned once (v1 -> v2) after v1 failed the
   comfort acceptance test on evaluation seeds 1-3, so v2 was confirmed on seeds 4-6 that played no part in that
   decision (section 5). PPO switches the AC on/off more often than the schedule (minimum 10-min dwell enforced;
   compressor wear is not modelled). PPO is a per-room policy shared by all rooms, not a multi-agent system, and it
   controls simulated rooms only.
8. **Evaluation window.** Every control run covers 7 days starting 2 Mar 2026 (after warm-up); other seasons are
   only represented by the hot and cool weather scenarios.
9. **Self-learning is offline and gated.** New data is collected with provenance; retraining, evaluation and
   promotion are run by command or API after acceptance tests. Nothing learns online on the real room, by design.
10. **Browser checks** ran in headless Chromium with software WebGL on the development container, not on the Pi or
    the target display.
11. **Earlier reported results.** The previously deployed RF's 0.997 accuracy is not valid (trained on its own test
    rows; the "Kaggle" files are UCI copies). It is kept only as a documented reference.

## 11. Viva demonstration sequence

1. `run_local.bat`; open http://localhost:3000 - the modern five-storey building on its site (building view);
   the footer shows "3D rooms 26/26".
2. Floor view of floor 2: Office A is **Room 101** (LIVE frame); the other rooms are numbered 102-126 and
   labelled simulated. Click a room: readings with "simulated" / "estimate" badges and the 30-min forecast.
3. Room view of a busy office: people, AC unit, airflow layer that follows the AC's cooling output.
4. Occupancy: the room panel's P(occupied) vs the simulated head count; Models & data tab: the learned fusion
   in shadow mode vs the live estimator, live forecast error, drift.
5. HVAC and lighting control: AI ON/OFF switch - both copies run the same minutes; the energy meter and KPI strip
   show AI vs conventional for exactly those minutes. Add people / heat in a room and watch the decision change.
6. Energy and comfort evaluation: experiments 1 and 5 tables (`experiments/results/exp05_control/summary.md`).
7. RL vs baseline: the PPO results and the registry's acceptance decision (`python -m ml.registry status`).
8. Live sensor integration: board connected -> LIVE ESP32 values; unplug or stop it -> NOT CONNECTED within 10 s,
   values disappear. Without the board: `scripts/start.sh harness` (labelled synthetic).
9. Fail-safe: `python experiments/run.py exp08_fault_tolerance` results - sensor dropout/stuck sensors and network
   outage handled by the fail-safe (F1 counts), a crashing controller falls back to the schedule, a corrupted model
   is refused; manual override from the API.
