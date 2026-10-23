# Model card: ppo_policy v1

- PPO policy for the 25 simulated rooms (one shared per-room policy)
- Trained offline in the digital twin only; deployed behind InputGuard/GuardedController and the SafetyLayer
- Observation 24 values, 12 discrete actions (rl/policy.py)

## Evaluation (synthetic)

### normal

| controller | energy kWh | savings vs schedule % | HVAC kWh | lighting kWh | discomfort % of occupied time | PMV-hours over 0.5 | overheat room-min | IAQ room-min >1000 ppm | switches (light/AC) | AC on-off | fail-safe F1/F2/F3 | ms per decision |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| schedule | 10964 ± 76 | 0.0 ± 0.0 | 6743 | 2131 | 21.7 ± 0.2 | 197.9 | 12153 | 0 | 334/324 | 324 | 0/0/0 | 0.003 |
| ppo | 9207 ± 100 | 16.0 ± 0.3 | 6193 | 924 | 25.5 ± 3.7 | 52.4 | 22789 | 0 | 1425/2819 | 2066 | 0/0/0 | 0.050 |

### hot_weather

| controller | energy kWh | savings vs schedule % | HVAC kWh | lighting kWh | discomfort % of occupied time | PMV-hours over 0.5 | overheat room-min | IAQ room-min >1000 ppm | switches (light/AC) | AC on-off | fail-safe F1/F2/F3 | ms per decision |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| schedule | 12242 ± 78 | 0.0 ± 0.0 | 8021 | 2131 | 27.0 ± 0.6 | 264.8 | 13426 | 0 | 334/324 | 324 | 0/0/0 | 0.004 |
| ppo | 10940 ± 104 | 10.6 ± 0.3 | 7820 | 1030 | 32.8 ± 2.5 | 72.1 | 19645 | 0 | 1526/2901 | 2059 | 0/0/0 | 0.051 |

### high_occupancy

| controller | energy kWh | savings vs schedule % | HVAC kWh | lighting kWh | discomfort % of occupied time | PMV-hours over 0.5 | overheat room-min | IAQ room-min >1000 ppm | switches (light/AC) | AC on-off | fail-safe F1/F2/F3 | ms per decision |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| schedule | 11228 ± 80 | 0.0 ± 0.0 | 6896 | 2131 | 22.5 ± 0.2 | 205.4 | 12350 | 0 | 334/324 | 324 | 0/0/0 | 0.004 |
| ppo | 9586 ± 113 | 14.6 ± 0.4 | 6421 | 963 | 26.1 ± 3.6 | 49.3 | 22148 | 0 | 1401/2794 | 2047 | 0/0/0 | 0.044 |

## Limitations

- Learned in the simulator; not validated on a real building. The real room keeps the rule-based / multi-objective controller.
- One policy shared by all rooms (not a multi-agent system).
