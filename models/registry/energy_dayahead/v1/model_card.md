# Model card: energy_dayahead v1

- **Task**: day-ahead hourly electricity of an office building
- **Data**: BDG2 Panther site offices (Orlando FL area by metadata coordinates; humid subtropical), 18 training buildings, 153704 rows, provenance public_real
- **Model**: histogram gradient-boosted trees; features: hour_sin, hour_cos, dow_sin, dow_cos, weekend, holiday, month_sin, month_cos, airTemperature, dewTemperature, cloudCoverage, windSpeed, lag24, lag48, lag168, lag336, same_hour_4wk, mean_prev_day, mean_prev_week, temp_mean24

| method | CV(RMSE) % seen | NMBE % seen | MAE kWh seen | CV(RMSE) % unseen | MAE kWh unseen |
|---|---|---|---|---|---|
| seasonal_naive_lag168 | 22.509 | 0.194 | 8.420 | 20.458 | 7.017 |
| persistence_lag24 | 22.568 | 0.093 | 8.244 | 13.954 | 4.704 |
| ridge_lags | 16.600 | -0.191 | 6.908 | 14.138 | 5.039 |
| ridge_weather_calendar | 31.503 | 9.130 | 17.607 | 27.226 | 11.250 |
| hist_gbt_lags | 15.372 | 0.118 | 5.969 | 13.472 | 4.579 |
| hist_gbt_weather_calendar | 31.752 | 7.497 | 17.470 | 28.542 | 11.963 |

## Limitations

- Observed weather used as if it were a perfect forecast.
- University office buildings in one US site; not the project's building (the twin's rooms are simulated in Colombo).
- Predicts consumption; savings must be measured separately (experiments 1 and 5).
