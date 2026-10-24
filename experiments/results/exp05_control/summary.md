# Experiment 5 - Optimized control vs baseline

Controllers: schedule, threshold_rf, mo, ppo; seeds [1, 2, 3]; 7 measured days from 2026-03-02T00:00:00; warm-up {'schedule': 2.0, 'threshold_rf': 2.0, 'mo': 7.0, 'ppo': 2.0}. Values are means ± standard deviation over the seeds. Provenance: synthetic (simulator).

### normal

| controller | energy kWh | savings vs schedule % | HVAC kWh | lighting kWh | discomfort % of occupied time | PMV-hours over 0.5 | overheat room-min | IAQ room-min >1000 ppm | switches (light/AC) | AC on-off | fail-safe F1/F2/F3 | ms per decision |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| schedule | 10964 ± 76 | 0.0 ± 0.0 | 6743 | 2131 | 21.7 ± 0.2 | 197.9 | 12153 | 0 | 334/324 | 324 | 0/0/0 | 0.006 |
| threshold_rf | 11836 ± 113 | -7.9 ± 0.3 | 7265 | 2481 | 36.9 ± 3.1 | 153.9 | 45509 | 0 | 1567/1567 | 0 | 0/0/0 | 0.010 |
| mo | 10120 ± 109 | 7.7 ± 0.4 | 6874 | 1155 | 13.6 ± 1.3 | 28.6 | 1552 | 0 | 2020/1040 | 640 | 0/0/0 | 0.381 |
| ppo | 9721 ± 92 | 11.3 ± 0.3 | 6666 | 965 | 5.2 ± 0.3 | 26.6 | 1654 | 0 | 911/912 | 771 | 0/0/0 | 0.049 |

## Additional checks

- **ppo_seed_variability**: best policy of each training run on normal/seeds 1-3 - v2_seed0: 9721 kWh, discomfort 5.2 %; v2_seed1: 9770 kWh, discomfort 6.1 %
- **ppo_confirmation_new_seeds**: ppo_policy v2 on normal / seeds 4-6 (not used in the reward redesign) - schedule: 10892 kWh (+0.0 % vs schedule), discomfort 22.2 %, AC cycles 324; mo: 10031 kWh (+7.9 % vs schedule), discomfort 11.2 %, AC cycles 621; ppo: 9683 kWh (+11.1 % vs schedule), discomfort 4.6 %, AC cycles 772
