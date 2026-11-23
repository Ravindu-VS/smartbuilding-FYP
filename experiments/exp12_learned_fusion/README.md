# Experiment 12: learned PIR+CO2 fusion in the AI controller (simulated rooms)

Run 2026-11-23 with `experiments/exp12_learned_fusion/run_exp12.py` (twin/runner.py, the same decision path, guard and safety layer as the experiments 1-9). Scenario `normal`, seeds 1-3, 7 measured days after a 7-day warm-up; both controllers see identical weather, occupants and sensor noise per seed. Occupancy accuracy: the controller's P(occupied) >= 0.5 against the simulator's true head count > 0, every room and control minute.

| controller | energy kWh (7 d) | discomfort (share of occupied time) | AC on/off cycles | light switches | occupancy accuracy, all 25 rooms | F1 | precision | recall | accuracy, rooms people stay in |
|---|---|---|---|---|---|---|---|---|---|
| Multi-objective, hand-built fusion (Oct) | 10120 ± 89 | 13.6 % ± 1.0 | 640 | 2020 | 92.5 % | 0.932 | 0.878 | 0.994 | 97.9 % |
| Multi-objective, learned fusion (Nov) | 10033 ± 84 | 13.0 % ± 1.4 | 639 | 2142 | 96.9 % | 0.970 | 0.965 | 0.976 | 98.9 % |

The hand-built configuration reproduces the recorded experiment 5 result (10120 kWh, 13.6 %), so the harness matches. With the learned fusion the controller used 0.9 % less energy, people were uncomfortable for a slightly smaller share of the occupied time, and the occupancy estimate was right in 96.9 % of room-minutes instead of 92.5 % (precision 0.965 instead of 0.878: far fewer minutes treated as occupied after people had left). Decision adopted for the live system (twin/live.py, FUSION_LEARNED=1); FUSION_LEARNED=0 restores the October configuration.

Scope: synthetic labels, simulated rooms only. Room 101 keeps the hand-built estimator (no ground-truth labels for the real room).
