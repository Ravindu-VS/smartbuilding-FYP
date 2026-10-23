# Model card: ppo_policy v2

- PPO policy for the 25 simulated rooms (one shared per-room policy)
- Trained offline in the digital twin only; deployed behind InputGuard/GuardedController and the SafetyLayer
- Observation 24 values, 12 discrete actions (rl/policy.py)

## Evaluation (synthetic)

### normal

| controller | energy kWh | savings vs schedule % | HVAC kWh | lighting kWh | discomfort % of occupied time | PMV-hours over 0.5 | overheat room-min | IAQ room-min >1000 ppm | switches (light/AC) | AC on-off | fail-safe F1/F2/F3 | ms per decision |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| schedule | 10964 ± 76 | 0.0 ± 0.0 | 6743 | 2131 | 21.7 ± 0.2 | 197.9 | 12153 | 0 | 334/324 | 324 | 0/0/0 | 0.006 |
| ppo | 9721 ± 92 | 11.3 ± 0.3 | 6666 | 965 | 5.2 ± 0.3 | 26.6 | 1654 | 0 | 911/912 | 771 | 0/0/0 | 0.049 |

### hot_weather

| controller | energy kWh | savings vs schedule % | HVAC kWh | lighting kWh | discomfort % of occupied time | PMV-hours over 0.5 | overheat room-min | IAQ room-min >1000 ppm | switches (light/AC) | AC on-off | fail-safe F1/F2/F3 | ms per decision |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| schedule | 12242 ± 78 | 0.0 ± 0.0 | 8021 | 2131 | 27.0 ± 0.6 | 264.8 | 13426 | 0 | 334/324 | 324 | 0/0/0 | 0.005 |
| ppo | 11384 ± 86 | 7.0 ± 0.3 | 8241 | 1053 | 9.5 ± 0.2 | 40.2 | 1741 | 0 | 1198/1160 | 978 | 0/0/0 | 0.050 |

### high_occupancy

| controller | energy kWh | savings vs schedule % | HVAC kWh | lighting kWh | discomfort % of occupied time | PMV-hours over 0.5 | overheat room-min | IAQ room-min >1000 ppm | switches (light/AC) | AC on-off | fail-safe F1/F2/F3 | ms per decision |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| schedule | 11228 ± 80 | 0.0 ± 0.0 | 6896 | 2131 | 22.5 ± 0.2 | 205.4 | 12350 | 0 | 334/324 | 324 | 0/0/0 | 0.008 |
| ppo | 10055 ± 104 | 10.4 ± 0.4 | 6859 | 995 | 5.8 ± 0.3 | 25.5 | 1573 | 0 | 938/912 | 771 | 0/0/0 | 0.043 |

## Limitations

- Learned in the simulator; not validated on a real building. The real room keeps the rule-based / multi-objective controller.
- One policy shared by all rooms (not a multi-agent system).
