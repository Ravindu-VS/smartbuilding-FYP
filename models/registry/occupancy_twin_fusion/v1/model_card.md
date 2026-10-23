# Model card: occupancy_twin_fusion v1

- **Task**: occupancy of a simulated room from PIR and CO2 (learned fusion)
- **Features**: pir_2min, pir_10min, pir_20min, pir_log, CO2, CO2_d5, CO2_d15, CO2_std15, T_d15, HR_d15, hour_sin, hour_cos, weekday
- **Training data**: synthetic (twin seed 31, 231840 room-minutes)
- **Test**: twin seed 32 under a different controller

| method | f1 | precision | recall | roc_auc |
|---|---|---|---|---|
| learned_fusion_hist_gbt | 0.962 | 0.957 | 0.967 | 0.990 |
| handbuilt_fusion_estimator | 0.932 | 0.883 | 0.987 | 0.976 |
| pir_only_10min | 0.932 | 0.883 | 0.987 | 0.919 |

## Limitations

- Synthetic labels: it learns the simulator's occupant and sensor models; not valid for the real room without labelled real data.
- Light is deliberately not an input (the controller switches it).
