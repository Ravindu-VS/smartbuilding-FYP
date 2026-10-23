#!/usr/bin/env bash
# Rebuild every dataset, model and result from scratch (offline; development PC, ~3-4 h on 2 vCPUs).
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
"$PY" scripts/fetch_datasets.py                 # public data (needs internet), checksums verified
"$PY" scripts/preprocess_datasets.py            # data/processed/
scripts/make_synthetic_corpus.sh                # data/synthetic/ (simulator)
"$PY" -m ml.occupancy                           # models/registry/occupancy_*
"$PY" -m ml.thermal                             # models/registry/thermal_h15, thermal_h30
"$PY" -m ml.energy                              # models/registry/energy_dayahead
"$PY" -m ml.registry init                       # activate what passes its acceptance tests
"$PY" -m rl.cartpole_check                      # PPO implementation check
for s in 0 1 2; do "$PY" -m rl.train --seed "$s"; done
echo "Next: pick the best run and register it after the comparison, e.g."
echo "  $PY -m rl.evaluate --policy models/ppo_runs/seed0/policy_best.json --scenarios normal --register"
echo "then: $PY experiments/run.py --all"
