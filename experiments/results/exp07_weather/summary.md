# Experiment 7 - Weather variation

Controllers: schedule, mo, ppo; seeds [1, 2, 3]; 7 measured days from 2026-03-02T00:00:00; warm-up {'schedule': 2.0, 'mo': 7.0, 'ppo': 2.0}. Values are means ± standard deviation over the seeds. Provenance: synthetic (simulator).

### hot_weather

| controller | energy kWh | savings vs schedule % | HVAC kWh | lighting kWh | discomfort % of occupied time | PMV-hours over 0.5 | overheat room-min | IAQ room-min >1000 ppm | switches (light/AC) | AC on-off | fail-safe F1/F2/F3 | ms per decision |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| schedule | 12242 ± 78 | 0.0 ± 0.0 | 8021 | 2131 | 27.0 ± 0.6 | 264.8 | 13426 | 0 | 334/324 | 324 | 0/0/0 | 0.005 |
| mo | 11670 ± 116 | 4.7 ± 0.4 | 8424 | 1155 | 21.7 ± 0.7 | 50.1 | 3147 | 0 | 2008/1046 | 690 | 0/0/0 | 0.315 |
| ppo | 11384 ± 86 | 7.0 ± 0.3 | 8241 | 1053 | 9.5 ± 0.2 | 40.2 | 1741 | 0 | 1198/1160 | 978 | 0/0/0 | 0.050 |

### cool_weather

| controller | energy kWh | savings vs schedule % | HVAC kWh | lighting kWh | discomfort % of occupied time | PMV-hours over 0.5 | overheat room-min | IAQ room-min >1000 ppm | switches (light/AC) | AC on-off | fail-safe F1/F2/F3 | ms per decision |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| schedule | 8504 ± 66 | 0.0 ± 0.0 | 4283 | 2131 | 20.6 ± 1.1 | 44.0 | 6784 | 0 | 334/324 | 324 | 0/0/0 | 0.005 |
| mo | 7489 ± 90 | 11.9 ± 0.4 | 4091 | 1308 | 0.7 ± 0.1 | 1.8 | 295 | 0 | 2378/447 | 323 | 0/0/0 | 0.177 |
| ppo | 6715 ± 70 | 21.0 ± 0.2 | 3684 | 941 | 5.1 ± 0.4 | 27.2 | 4598 | 0 | 471/352 | 316 | 0/0/0 | 0.052 |
