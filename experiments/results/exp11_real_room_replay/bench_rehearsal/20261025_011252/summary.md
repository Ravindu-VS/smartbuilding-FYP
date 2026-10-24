# Hardware bench check - 2026-10-25 01:12

**PASS** - software check (not the real board); room `f2_office_a`; 21 readings.

| group | check | status | detail |
|---|---|---|---|
| link | board connected | PASS | sender virtual_board |
| link | readings come from the real board | INFO | sender is 'virtual_board' - this run is a software check, not a physical verification |
| link | readings received | PASS | 21 distinct readings; mean interval 3.0 s |
| link | report interval about 3 s | PASS | 3.0 s |
| BME280 | temperature (C) | PASS | 21.73-21.88, mean 21.78, 11 distinct of 21 |
| BME280 | humidity (%) | PASS | 31.09-31.74, mean 31.32, 18 distinct of 21 |
| BME280 | pressure (hPa) | PASS | 1007.5-1007.7, mean 1007.65, 3 distinct of 21 |
| BH1750 | illuminance (lux) | PASS | 434.5-451.1, mean 441.43, 20 distinct of 21 |
| SCD41 | CO2 (ppm, NDIR) | PASS | 1050-1077, mean 1058.57, 8 distinct of 21 |
| SCD41 | temperature (C) | PASS | 22.39-22.85, mean 22.58, 9 distinct of 21 |
| PIR | motion (bool) | PASS | values seen: ['False', 'True'] |
| LD2410C | presence (bool) | PASS | values seen: ['True'] |
| LD2410C | distance (cm) | PASS | 89-399, mean 258.10, 21 distinct of 21 |
| INA226 | bus voltage (V) | PASS | 4.999-5.015, mean 5.01, 11 distinct of 21 |
| INA226 | current (mA) | PASS | 101.8-114.9, mean 109.43, 18 distinct of 21 |
| MQ-2 | raw ADC (gas, never used as CO2) | PASS | 837-881, mean 858.29, 17 distinct of 21 |
| firmware | sensor_health reported by the board | INFO | all detected |
| edge | occupancy estimate produced | PASS | {'occupancy_probability': 0.9964} |
| edge | provenance of the room's values | INFO | {'ai': 'prediction', 'energy': 'synthetic (INA226)', 'sensors': 'synthetic'} |
| actuators | fan PWM reported by the board | PASS | 255 (commanded 255) |
| actuators | LED PWM reported by the board | PASS | 255 (commanded 255) |
| actuators | damper angle reported by the board | PASS | 90 (commanded 90) |
| actuators | edge verified the previous command | PASS | True |
| actuators | LED seen by the BH1750 | PASS | +167 lux (off 441, on 608) |
| actuators | INA226 current with fan+LED on vs off | INFO | 113 -> 384 mA |
| actuators | fan and LED off again | PASS | fan 0, LED 0 |
