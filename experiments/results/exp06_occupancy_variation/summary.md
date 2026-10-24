# Experiment 6 - Occupancy variation

Controllers: schedule, mo, ppo; seeds [1, 2, 3]; 7 measured days from 2026-03-02T00:00:00; warm-up {'schedule': 2.0, 'mo': 7.0, 'ppo': 2.0}. Values are means ± standard deviation over the seeds. Provenance: synthetic (simulator).

### low_occupancy

| controller | energy kWh | savings vs schedule % | HVAC kWh | lighting kWh | discomfort % of occupied time | PMV-hours over 0.5 | overheat room-min | IAQ room-min >1000 ppm | switches (light/AC) | AC on-off | fail-safe F1/F2/F3 | ms per decision |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| schedule | 10498 ± 76 | 0.0 ± 0.0 | 6494 | 2131 | 18.3 ± 0.5 | 93.7 | 6151 | 0 | 334/324 | 324 | 0/0/0 | 0.008 |
| mo | 9476 ± 100 | 9.7 ± 0.3 | 6507 | 1096 | 10.4 ± 1.8 | 18.3 | 922 | 0 | 1987/1230 | 720 | 0/0/0 | 0.460 |
| ppo | 8937 ± 82 | 14.9 ± 0.4 | 6186 | 878 | 5.3 ± 0.2 | 24.0 | 1872 | 0 | 864/862 | 724 | 0/0/0 | 0.052 |

### high_occupancy

| controller | energy kWh | savings vs schedule % | HVAC kWh | lighting kWh | discomfort % of occupied time | PMV-hours over 0.5 | overheat room-min | IAQ room-min >1000 ppm | switches (light/AC) | AC on-off | fail-safe F1/F2/F3 | ms per decision |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| schedule | 11228 ± 80 | 0.0 ± 0.0 | 6896 | 2131 | 22.5 ± 0.2 | 205.4 | 12350 | 0 | 334/324 | 324 | 0/0/0 | 0.008 |
| mo | 10425 ± 116 | 7.2 ± 0.4 | 7053 | 1170 | 14.7 ± 1.4 | 29.4 | 1579 | 0 | 2147/1045 | 642 | 0/0/0 | 0.456 |
| ppo | 10055 ± 104 | 10.4 ± 0.4 | 6859 | 995 | 5.8 ± 0.3 | 25.5 | 1573 | 0 | 938/912 | 771 | 0/0/0 | 0.043 |

### sudden_occupancy

| controller | energy kWh | savings vs schedule % | HVAC kWh | lighting kWh | discomfort % of occupied time | PMV-hours over 0.5 | overheat room-min | IAQ room-min >1000 ppm | switches (light/AC) | AC on-off | fail-safe F1/F2/F3 | ms per decision |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| schedule | 10993 ± 80 | 0.0 ± 0.0 | 6756 | 2131 | 22.7 ± 0.5 | 225.4 | 13264 | 67 | 334/324 | 324 | 0/0/0 | 0.007 |
| mo | 10240 ± 126 | 6.8 ± 0.5 | 6944 | 1190 | 13.8 ± 1.3 | 30.1 | 1702 | 0 | 2189/1082 | 663 | 0/0/0 | 0.343 |
| ppo | 9805 ± 114 | 10.8 ± 0.5 | 6718 | 981 | 5.4 ± 0.3 | 29.0 | 1813 | 0 | 951/956 | 810 | 0/0/0 | 0.051 |
