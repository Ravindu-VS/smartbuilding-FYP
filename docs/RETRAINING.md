# Safe self-learning: data collection, retraining, promotion, rollback

Learning never means exploring on the real room. Models are trained offline (public data and the
simulator), evaluated on held-out data, versioned, run in shadow mode, and promoted only through
acceptance tests; the safety layer stays in front of every controller at all times.

## Stages and where each is implemented

| Stage | Implementation |
|---|---|
| 1. Train on public + simulator data | `ml/occupancy.py` (UCI), `ml/thermal.py` (twin corpus), `ml/energy.py` (BDG2), `rl/train.py` (twin) |
| 2. Validate on held-out real data | chronological UCI test week; BDG2 2017 months and unseen buildings |
| 3. Evaluate in unseen simulator scenarios | test seeds 21-23/32, scenario `hvac_reduced` unseen in training; PPO evaluated on seeds 1-3 (training seeds >= 1000) |
| 4. Save and version | `models/registry/<task>/<version>/` (model.json, model.joblib, metadata.json, model_card.md) - never overwritten |
| 5. Shadow mode | `ml/serving.py`: the newest `occupancy_twin_fusion` runs beside the live estimator in every simulated room; scored against simulated truth; never applied |
| 6. Compare with observations and the safe controller | shadow F1 vs the live estimator, agreement; live 30-min forecast MAE (`/api/models`) |
| 7. Collect observations with provenance | SQLite store: readings (room101_measured only from the real board), decisions (proposed and applied action, safety notes, model version, mode), predictions (role active/shadow), commands and acks, events |
| 8. Drift, missing inputs, sensor faults | `ml/drift.py` PSI per feature vs training deciles (real-room inputs vs the RF's training data); `twin/safety.py` InputGuard (missing, implausible, stuck, stale) |
| 9. Retrain offline | re-run the training script with the new data added (below) |
| 10. Evaluate candidate vs approved | `python -m ml.registry evaluate <task> <version>` (also run by promote) |
| 11. Promote only after acceptance tests | `python -m ml.registry promote <task> <version>` or `POST /api/models/promote` |
| 12. Roll back | `python -m ml.registry rollback <task>` or `POST /api/models/rollback`; history kept in `registry.json` |
| 13. Continual learning (since 23 Nov 2026) | `ml/online_learning.py`: the simulated rooms' occupancy model retrains itself while the system runs (below) |

## Acceptance tests (ml/registry.py)

Every candidate: files intact (SHA-256 = metadata), portable model self-test, feature list = metadata,
finite outputs on perturbed inputs with 5 % missing, probabilities in [0, 1], single-row latency < 5 ms,
rejects a wrong feature count, portable output = scikit-learn output. Then the task's rule:

| Task | Rule |
|---|---|
| occupancy_rf, occupancy_best | held-out week F1 >= 0.80 and not worse than the active version by > 0.01 |
| occupancy_co2_temporal | must beat the deployed CO2 decision tree on the held-out week (F1 0.5296) |
| occupancy_twin_fusion | must beat the hand-built PIR+CO2 fusion on the same synthetic test seed |
| thermal_h15, thermal_h30 | MAE below persistence on unseen simulator seeds |
| energy_dayahead | CV(RMSE) below the seasonal-naive baseline on the 2017 test months |
| ppo_policy | on the held-out evaluation: no controller errors, discomfort not worse than the schedule by > 2 percentage points of occupied time, lower energy |

A rejected promotion is recorded with its report (`promotion_rejected`) and the active version stays.

## Retraining with the real room's data

Labels for the real room do not exist yet (no ground-truth head count). Predictions are never used as
labels. To fine-tune the occupancy model on Room 101: record ground truth (e.g. a manual log or a camera
count with consent) next to the stored readings, export `readings` for the period from
`output/edge_store.sqlite3`, add them as a third data source with provenance `room101_measured` in
`ml/occupancy.py`, keep a later week as the test set, retrain, then `ml.registry evaluate` and `promote`.
Until then, the real room keeps the rule-based fusion estimator and the multi-objective controller.

## Continual learning while the system runs (simulated rooms)

Since 23 Nov 2026 the approved learned fusion (`occupancy_twin_fusion`) drives the AI's P(occupied) in the 25
simulated rooms (`ml/learned_fusion.py`; experiment 12: occupancy accuracy 96.9 % vs 92.5 %, 0.9 % less energy,
slightly better comfort), and it keeps learning:

1. Every control step, each simulated room adds one row: the model's 13 features, the simulator's true label
   (head count > 0), the hand-built estimate and the approved model's estimate (buffer: the last 5 simulated days).
2. Every 24 simulated hours (once at least one day is collected) a background thread trains a new
   gradient-boosted model on the older 80 % of the buffer and tests it on the newest 20 % (forward in time).
3. It goes live only if its F1 on those rows beats the approved model's by at least 0.002 **and** beats the
   hand-built estimator, **and** it passes the registry's acceptance tests (self-test, latency, finite outputs,
   feature list). It is then registered as a new version with its data window and metrics, promoted, and the live
   estimators switch to it at the next control step. Otherwise the round is recorded and the approved model stays.
4. Status and the last rounds: `GET /api/models` (`live.online_learning`) and the dashboard's Models & data tab.
   Roll back: `python -m ml.registry rollback occupancy_twin_fusion`. Switch off: `ONLINE_LEARNING=0`;
   October configuration (hand-built estimator, learned model in shadow): `FUSION_LEARNED=0`.

Not learned online, on purpose: Room 101's occupancy (no ground-truth labels; training on the model's own
predictions would reinforce its mistakes) and the PPO policy (reinforcement learning explores, which is done in
the simulator, `rl/train.py`, and deployed through its acceptance test). The multi-objective controller's
per-room occupancy prior keeps adapting online, as before.
