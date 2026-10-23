# Reinforcement learning (PPO) and controller comparison

## What was there and what changed

The repository had a stable-baselines3 PPO agent (`archive/legacy_v1/agents/`, `control/ppo_controller.py`,
`models/ppo_building_controller.zip`) trained on the first simulator. It could not be run: the simulator it
was trained on is superseded, and PyTorch/SB3 cannot be installed here (no CPU wheel index reachable). The
algorithm is kept - PPO - and re-implemented in numpy (`rl/ppo.py`), which also keeps the Raspberry Pi free
of PyTorch. No second RL framework was added.

Correctness of the implementation: analytic gradients equal finite differences (`tests/test_rl.py`), GAE on
known values, and CartPole-v1 solved (deterministic evaluation 500/500 steps on 3 seeds;
`experiments/results/ppo_cartpole.json`, `python -m rl.cartpole_check`).

## Environment (`rl/env.py`)

The 25 simulated rooms of the twin (ISO 13790 physics, synthetic Colombo weather, stochastic occupants and
sensors). One policy is shared by all rooms (each room is one sample per step; parameter sharing). This is a
per-room controller, not a multi-agent system: there is no communication or coordinator, and it is not
described as one. `RoomControlEnv` is the gymnasium view of one room (passes gymnasium's env checker).

* **Decision interval** 5 min; each decision is held for five 1-min control steps; at every step the held
  command passes the SafetyLayer (R1-R4) exactly as in deployment.
* **Observation (24 values)** - only what the controller has at decision time: measured temperature error
  to the design set-point, humidity, CO2 (+ missing flag) and its 15-min trend, the live PIR + CO2 fusion
  estimate, PIR in the last 2/10 min, inside operating hours, time of day, weekday, outdoor temperature,
  daylight estimate, current light level, AC mode and set-point, AC sub-meter power, minutes since the AC
  command changed, room area, capacity and activity level (`rl/policy.py`).
* **Actions (12)** - light {OFF, DIM, ON} x AC {ECO, LOW (27 C), NORMAL at design + 1 C, NORMAL at design};
  set-points 22-27 C only; the AC command may change at most once per 10 min. No actuator the building does
  not have (the fresh-air fan stays under the safety rule R4).
* **Reward** per room and decision, all terms dimensionless:
  `r = -(1.0 E/E_max + 3.0 D + 1.0 V + 1.0 Q + 0.05 S)` with E = AC + boost fan + lighting energy over the
  5 min, E_max = the room's maximum AC + lighting energy over 5 min; D = mean over occupied minutes of
  max(0, |PMV| - 0.5); V = mean over occupied minutes of max(0, 300 lux - illuminance)/300; Q = mean over
  occupied minutes of max(0, CO2 - 1000 ppm)/500; S = number of command changes. Comfort terms are zero in
  empty rooms and in transit rooms (corridors). The reward uses the simulator's true state; the policy sees
  only the observation. Weights mirror the multi-objective controller's (comfort weighted 3 x energy).
* **Episodes** 1 simulated day after a 12-h warm-up under the schedule; truncated (not terminated) at the
  horizon, so the last state is bootstrapped. Training scenarios: normal, hot, cool, high, low and sudden
  occupancy, unusual demand; random start dates in 2026; simulator seeds 1000 + 1000 x run + episode
  (evaluation seeds 1-3 are never used for training). Faults (sensor dropout, outages, AC failures) are kept
  for evaluation only.

## Training (`python -m rl.train --seed k`)

PPO: clipped surrogate (0.2), GAE (gamma 0.99, lambda 0.95), Adam lr 1e-3 decaying, 10 epochs, minibatch
512, entropy 0.005 -> 0.001, value coefficient 0.5, gradient-norm clip 0.5, actor and critic 64-64 tanh.
160 one-day episodes per run (1.15 M room-decisions). Every 5 episodes the deterministic policy is scored on
a fixed validation day (seed 999); the best is kept (`models/ppo_runs/seed<k>/policy_best.json`, training
log `train_log.csv`).

## Deployment

`PPOController` (numpy only) decides every 5 min per room, holds in between, enforces the AC dwell, and runs
behind `GuardedController` (fail-safe to the schedule on missing / stuck / stale inputs, an exception or an
invalid action) and the SafetyLayer. It controls simulated rooms only; the real room keeps the
multi-objective controller. It is selectable in the live twin (`POST /api/simulation/controller
{"controller": "ppo"}`) only after the `ppo_policy` registry version passed its acceptance tests.

## Comparison protocol (`python -m rl.evaluate`, experiments 1 and 5-8)

Controllers: conventional schedule (lights on + AC at design set-point during operating hours), the
project's original rule (thresholds on the Random Forest probability), the multi-objective optimiser
(30-min look-ahead over the AC options: the MPC-like controller), PPO. Same building, weather, occupants,
sensor noise and faults for a given seed; same 7 measured days; seeds 1-3; warm-up 7 days for the
optimiser (its learning week) and 2 days for the others. Reported: HVAC, lighting and total energy,
savings vs the schedule (negative if more), discomfort share and PMV-hours, overheating minutes,
temperature error, IAQ minutes, switching and AC cycles, fail-safe counts, decision time. Results:
`experiments/results/exp05_control/summary.md` and the scenario experiments.
