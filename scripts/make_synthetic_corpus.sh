#!/usr/bin/env bash
# The synthetic corpus used to train and test the thermal and twin-energy models
# (ml/thermal.py, ml/energy.py).  Training and test use different seeds; the test set
# also has a scenario never seen in training (hvac_reduced).  ~15 min on 2 vCPUs.
set -euo pipefail
cd "$(dirname "$0")/.."
G="python3 scripts/generate_synthetic.py --every 5 --warmup-days 2"
# training
$G --scenario normal         --seed 11 --days 14 --controller mo
$G --scenario normal         --seed 12 --days 14 --controller schedule
$G --scenario hot_weather    --seed 13 --days 7  --controller mo
$G --scenario cool_weather   --seed 14 --days 7  --controller mo
$G --scenario high_occupancy --seed 15 --days 7  --controller mo
$G --scenario low_occupancy  --seed 16 --days 7  --controller schedule
# test (unseen seeds; hvac_reduced is an unseen scenario)
$G --scenario normal         --seed 21 --days 7  --controller mo
$G --scenario hot_weather    --seed 22 --days 7  --controller schedule
$G --scenario hvac_reduced   --seed 23 --days 7  --controller mo
# one-minute rows for the occupancy domain check (ml/occupancy.py --synthetic)
G1="python3 scripts/generate_synthetic.py --every 1 --warmup-days 2"
$G1 --scenario normal --seed 31 --days 7 --controller mo
$G1 --scenario normal --seed 32 --days 4 --controller schedule
