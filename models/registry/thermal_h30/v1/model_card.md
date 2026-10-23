# Model card: thermal_h30 v1

- **Task**: room air temperature 30 min ahead (simulated rooms)
- **Model**: histogram gradient-boosted trees on the temperature change
- **Features**: T, T_lag5, T_lag10, T_lag15, dT5, dT15, RH, CO2, CO2_d15, pir_recent, ac_on, ac_low, setpoint_gap, ac_power_frac, min_since_hvac_change, light_level, vent, t_out, t_out_gap, ghi, hour_sin, hour_cos, area_m2, ac_w_per_m3, window_m2
- **Training data**: synthetic twin corpus (402300 rows; provenance synthetic)
- **Test**: unseen seeds and an unseen scenario; ground truth = simulator air temperature

| method | MAE | RMSE | unseen hvac_reduced MAE |
|---|---|---|---|
| persistence | 0.341 | 0.907 | 0.333 |
| greybox_1r1c | 0.332 | 0.772 | 0.372 |
| ridge | 0.354 | 0.823 | 0.373 |
| hist_gbt | 0.267 | 0.641 | 0.292 |

## Limitations

- Trained on simulator output only: it learns the 5R1C model's behaviour, not a real building's. Its real-data check on the UCI office (no HVAC data there) is in docs/results/thermal.md.
- Assumes the AC command at time t is held for the horizon.
