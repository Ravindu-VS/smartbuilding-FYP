# Model card: thermal_h15 v1

- **Task**: room air temperature 15 min ahead (simulated rooms)
- **Model**: histogram gradient-boosted trees on the temperature change
- **Features**: T, T_lag5, T_lag10, T_lag15, dT5, dT15, RH, CO2, CO2_d15, pir_recent, ac_on, ac_low, setpoint_gap, ac_power_frac, min_since_hvac_change, light_level, vent, t_out, t_out_gap, ghi, hour_sin, hour_cos, area_m2, ac_w_per_m3, window_m2
- **Training data**: synthetic twin corpus (402750 rows; provenance synthetic)
- **Test**: unseen seeds and an unseen scenario; ground truth = simulator air temperature

| method | MAE | RMSE | unseen hvac_reduced MAE |
|---|---|---|---|
| persistence | 0.226 | 0.605 | 0.232 |
| greybox_1r1c | 0.214 | 0.493 | 0.266 |
| ridge | 0.204 | 0.513 | 0.253 |
| hist_gbt | 0.158 | 0.413 | 0.193 |

## Limitations

- Trained on simulator output only: it learns the 5R1C model's behaviour, not a real building's. Its real-data check on the UCI office (no HVAC data there) is in docs/results/thermal.md.
- Assumes the AC command at time t is held for the horizon.
