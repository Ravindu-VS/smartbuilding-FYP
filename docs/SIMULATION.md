# Building simulation (digital twin)

Code: `twin/physics.py` (room model), `twin/building.py` (25 rooms, partitions), `twin/climate.py` (weather),
`twin/occupancy.py` (people), `twin/sensors.py` (sensor models), `twin/spec.py` + `twin/building_config.py`
(geometry and per-type parameters), `twin/scenarios.py` (scenarios and faults), `twin/runner.py` (episodes),
`twin/validation.py` (plausibility checks). It is a simplified thermal model for control studies, not a
validated whole-building or CFD simulation.

## Building

Five floors (0 Retail & Lobby, 1 Health & Recreation, 2 Operations, 3 Residential, 4 Penthouse), 26 rooms.
Room 101 (Office A, `f2_office_a`) is the real room and is not simulated; the other 25 rooms (Rooms 102-126)
each have their own geometry, exposure, window area, AC size, lighting, plug loads, occupancy profile and
activity level (`twin/spec.py` TYPE_PARAMS). Heat flows between neighbouring rooms on the same floor through
shared partitions (U = 2.0 W/m2K); floor slabs are treated as adiabatic.

## Thermal model: ISO 13790 5R1C, explicit Euler, 15 s step

Nodes: air temperature `T_air`, surface (star) temperature `T_s`, thermal mass `T_m`. Per step (dt = 15 s):

```
phi_ia = 0.5 Q_int                                   convective internal gains (people, lighting, plug)
phi_rad = 0.5 Q_int + Q_sol                          radiant gains;  Q_sol = A_win SHGC I_win (1 - 0.7 shading)
phi_m  = (A_m / A_t) phi_rad
phi_st = max(0, 1 - A_m/A_t - H_win/(9.1 A_t)) phi_rad
T_s    = (H_is T_air + H_ms T_m + H_win T_out + phi_st) / (H_is + H_ms + H_win)
Q_air  = H_is (T_s - T_air) + H_ve (T_out - T_air) + Q_neighbours + phi_ia + Q_hvac      [W]
Q_mass = H_ms (T_s - T_m) + H_roof (T_sa,roof - T_m) + H_wall (T_sa,wall - T_m) + phi_m [W]
T_air += Q_air / C_air dt          C_air = rho c_p V x 3 (furniture)      [J/K]
T_m   += Q_mass / C_m dt           C_m = 165 kJ/(m2 K) x floor area       [J/K]
H_ve  = rho c_p ACH V / 3600       ACH = 0.5 infiltration + 1.0 with the AC (fresh air) + 2.0 boost fan
```
Sol-air temperatures add absorbed solar radiation and sky radiation losses to `T_out`. Units: W, J/K, K, s.
Stability: results at dt = 5, 15 and 30 s differ by < 0.3 K after 1 h (`tests/test_simulation.py`).

## Air conditioner (split unit) and energy

Proportional thermostat around the set-point (band 1 K): cooling fraction
`f = clip(0.5 + (T_air - T_sp)/band, 0, 1)`; `Q_hvac = -capacity x capacity_factor x f`
(capacity 146.5 W per m2 of floor, from the thesis's 5.275 kW unit for 36 m2; `capacity_factor` < 1 models a
degraded unit, 0 a failed compressor). Latent load: coil with sensible heat ratio 0.75 while the air is
wetter than the coil (0.0095 kg/kg); condensation of supersaturated air is removed and its latent heat
charged to the AC. Electricity: `P_AC = (|Q_hvac| + Q_latent) / COP + P_fan`, COP 3.2, fan 0.76 % of
capacity, fan only while the AC is on (also when the compressor has failed). The fresh-air boost fan uses
0.3 W per m3/h. Thermal and electrical energy are never mixed: meters integrate electrical power only.
Modes: ECO (off), LOW (27 C set-back), NORMAL (comfort set-point 22-27 C, room design 22-24 C).

## Lighting and daylight

Three levels: OFF, DIM (40 %), ON; power = installed W/m2 (5-14 by type) x area x level; 400 lux at the desk
at full output. Daylight at the sensor = outdoor illuminance x daylight factor (scaled by window-to-floor
ratio, at most 5 %). Visual-comfort target 300 lux (multi-objective controller and RL reward).

## Comfort and indoor air

PMV/PPD (ISO 7730) on the true air and surface temperatures, humidity, air speed 0.1 m/s, clothing 0.5 clo,
activity 1.0-1.6 met by room type; |PMV| <= 0.5 is ISO 7730 category B. CO2: exact solution of the
single-zone mass balance (outdoor 420 ppm, 0.0052 L/s per person). The safety layer's R4 rule switches the
fresh-air fan above 1000 ppm (off below 800). In the real room only the SCD41's NDIR CO2 is used; the MQ-2
is not a CO2 instrument.

## Weather, occupants, sensors

* Weather: synthetic Colombo climate from monthly normals (not measured; see docs/DATASETS.md), clear-sky
  (Haurwitz) and cloud (Kasten-Czeplak) irradiance, deterministic per seed and date.
* Occupants: per-type stochastic daily profiles from the hourly schedules in `twin/building_config.py`,
  seeded; the thesis's office, meeting-room and kitchen models for those types.
* Sensors: Gaussian noise (0.1 K, 1 %RH, 2 % light, 10 ppm + 1 % CO2) and 60 s first-order lag; PIR as a
  Poisson process (one detectable movement per occupant per minute, false trigger once per 10 h).

## Scenarios and faults (`twin/scenarios.py`)

| Scenario | What changes |
|---|---|
| normal | nothing |
| high_occupancy / low_occupancy | head counts x 1.5 (capped at capacity) / x 0.4, stochastic rounding |
| hot_weather / cool_weather | outdoor +3 K / -2.5 K and 40 % daylight |
| sudden_occupancy | 6 rooms get unscheduled full-capacity occupancy (Poisson, 2 per day, 60 min) |
| hvac_failure | AC of 4 rooms fails 09:00-15:00 on days 1 and 3 |
| hvac_reduced | every AC at 60 % capacity |
| sensor_dropout | 10 % of sensor values missing; 2 rooms' temperature sensors stuck |
| network_outage | no readings reach the controller 10:00-10:45 and 15:00-15:30 daily |
| unusual_demand | 4 rooms draw an extra 1.5 kW 10:00-16:00 on weekdays |
| conflicting_objectives | +3 K, 1.3 x occupancy, AC at 80 %: comfort costs energy |

Rooms affected are chosen from the seed. Faults in readings change only what the controller sees; the
`InputGuard` holds a missing value for at most 3 min, flags implausible, stuck (unchanged 30 min) and stale
(> 5 min) data, and the `GuardedController` then falls back to the rule-based schedule (F1), as it does when
a controller raises (F2) or returns an invalid action (F3).

## Validation checks (`twin/validation.py`)

Ranges (air 10-50 C, RH 0-100 %, CO2 >= 380 ppm, illuminance and powers >= 0, occupants 0..capacity),
equipment consistency (no AC power when off, lighting power = installed x level, total = AC + lighting +
plug), time (strictly increasing, regular interval), inertia (< 1.5 K per minute) and non-decreasing
cumulative energy. Every generated file is checked; experiment 9 checks room, floor, end-use and building
energy totals.
