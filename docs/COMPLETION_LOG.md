# Completion log

Persistent log for the final master prompt (started 23 Oct 2026). Each entry: what was done, files changed,
evidence (command + result), and the next action. Resume from the last "Next" line.

## 2026-10-23 — Phase 0: audit

- Audited the repository (see [`COMPLETION_MATRIX.md`](COMPLETION_MATRIX.md)).
- Baseline tests: `python3 -m pytest -q twin/tests raspberry_pi/test_edge_brain.py` → **27 passed** (37.5 s).
- Simulation speed: 25 rooms, 1 simulated day at 60 s control steps = 2.7 s on the dev container (2 vCPU).
- Network from this environment: `raw.githubusercontent.com` and `media.githubusercontent.com` reachable;
  `archive.ics.uci.edu`, `archive-api.open-meteo.com`, `power.larc.nasa.gov`, `bulk.meteostat.net`,
  `zenodo.org`, `huggingface.co`, `kaggle.com`, `download.pytorch.org` refused by the egress proxy (HTTP 403 on
  CONNECT). The linked PC's shell has the same allow-list (tested: UCI, Open-Meteo, NASA POWER refused).
- Next: datasets (verify UCI copies against the author's repository, fetch BDG2 subset), then generator.

## 2026-10-23 — Phase 1: datasets, generator, ML, RL, integration, tests, clean-up

- Datasets: UCI occupancy downloaded from the author's repository; SHA-256 equal to the tracked `Dataset/UCI`
  copies and to the "Kaggle" copies (finding: the Kaggle files are UCI re-uploads; the legacy RF was trained
  on its own test rows). BDG2 metadata/weather/cleaned electricity downloaded (195 MB, git-ignored);
  Panther offices selected (23 buildings). Files: `scripts/fetch_datasets.py`, `scripts/preprocess_datasets.py`,
  `data/manifest.json`, `docs/DATASETS.md`. Colombo measured weather: BLOCKED (hosts refused by proxy).
- Simulation: `twin/scenarios.py` (12 scenarios incl. faults), `twin/runner.py`, `twin/validation.py`,
  physics hooks (AC capacity factor, extra plug load), InputGuard + GuardedController (`twin/safety.py`),
  room numbers 101-126 (`twin/spec.py`). All 12 scenarios generated and validated (0 problems).
- ML: `ml/` (occupancy 5 families x 6 feature sets, thermal 15/30 min, energy day-ahead, portable JSON
  export with parity < 1e-13, registry with acceptance/promotion/rollback, drift, shadow mode, numpy-only
  `ml/online.py`). Parity tests found a pandas-3 bug in a thermal feature (fixed).
- RL: numpy PPO (`rl/ppo.py`) gradient-checked and CartPole-v1 solved on 3 seeds (500/500);
  `rl/env.py` (passes gymnasium check_env), `rl/policy.py` (PPOController), `rl/train.py`, `rl/evaluate.py`.
  First training settings learned too slowly (lr 3e-4, minibatch 2048): stopped after 16 episodes and
  restarted with lr 1e-3, minibatch 512, 10 epochs, one-day episodes.
- Integration: SQLite store with migrations (`raspberry_pi/store.py`), MQTT bridge + device harness,
  edge-brain routes `/api/models`, `/api/models/promote|rollback`, `/api/history`, `/api/events`,
  `/api/provenance`, `/api/datasets`, `/api/experiments`, `/api/hardware/mqtt`; provenance, room numbers,
  thermal forecast and freshness in the room state; PPO selectable once approved.
- Dashboard: room numbers, provenance badges, 30-min forecast badge, PPO in the controller list (disabled
  until approved), "Models & data" tab. `npx tsc --noEmit` and `npx eslint src` clean.
- Clean-up: superseded architecture moved to `archive/legacy_v1/` with git mv; `twin/building_config.py`;
  tests consolidated in `tests/`; requirements split (`requirements/edge|train|dev.txt`);
  `tests/test_edge_runtime.py` proves the edge runs without pandas/scikit-learn/scipy/joblib/gymnasium.
- Experiments 9 and 10 run: PASS (consistency; live room via HTTP + MQTT harness).
- Tests: `python3 -m pytest -q` 90 passed after the clean-up (before the new export/runtime tests).
- Next: finish PPO training (seeds 0, 1; then 2), retrain ML into a fresh registry (feature references),
  `ml.registry init`, register the selected PPO policy, run experiments 1-8, full test run, browser flows,
  README / final report / acceptance gate, commit, apply to G:.
