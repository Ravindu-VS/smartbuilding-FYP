# Experiment 11 - Room 101 pipeline on replayed real data (virtual board)

Room 101's pipeline (PIR(+mmWave)+CO2 fusion -> multi-objective controller -> safety layer, `twin/hardware_room.py`) fed by the virtual board (`raspberry_pi/virtual_board.py`) replaying the UCI office measurements of 2015-02-11 - 2015-02-18 (held out from every UCI-trained model) every 3 s of dataset time. Temperature, humidity, light and CO2 are the recorded values; PIR, mmWave, MQ-2 and INA226 come from sensor models driven by the recorded occupancy, so the presence variants measure the pipeline under those models, and only the CO2-only variant uses recorded inputs alone. Sensor models per 3-s sample: quiet = PIR high 45 % of occupied samples, false trigger 0.03 %; LD2410C presence 97 %, false 0.05 %; noisy = false triggers 0.3 % (PIR) and 1 % (LD2410C). **Not a measurement of Room 101 and not a physical verification.**

| pipeline | minutes | F1 | precision | recall | accuracy | F1 without vacancy rule | lights on when empty | lights on when occupied | AC on when empty | damper open |
|---|---|---|---|---|---|---|---|---|---|---|
| full board: PIR + mmWave + CO2 (quiet sensors) | 9752 | 0.790 | 0.653 | 1.000 | 0.888 | 0.627 | 22.1 % | 0.4 % | 0.0 % | 23.1 % |
| full board, noisy sensors (10x false triggers) | 9752 | 0.354 | 0.215 | 1.000 | 0.232 | 0.351 | 96.2 % | 1.0 % | 0.0 % | 23.2 % |
| PIR + CO2, no LD2410C (quiet) | 9752 | 0.884 | 0.793 | 1.000 | 0.945 | 0.678 | 9.8 % | 0.3 % | 0.0 % | 23.2 % |
| PIR + CO2, no LD2410C (noisy) | 9752 | 0.516 | 0.347 | 1.000 | 0.605 | 0.471 | 57.2 % | 0.9 % | 0.0 % | 23.2 % |
| CO2 only (recorded inputs only) | 9752 | 0.529 | 0.444 | 0.654 | 0.755 | 0.529 | 91.4 % | 0.9 % | 0.0 % | 23.2 % |
| occupancy_rf v1 (registry; T, RH, light, CO2 from the same minutes) | 9752 | 0.973 | 0.952 | 0.996 | 0.989 | - | - | - | - | - |

F1 etc.: the pipeline's occupancy decision (estimator >= 0.5 and not vacant); 'without vacancy rule' = the PIR+CO2 fusion estimator alone. AC / lights on when empty = share of unoccupied minutes with the AC (fan) not in ECO / the lights not OFF; lights on when occupied = share of occupied minutes with lights not OFF (they may correctly stay off in daylight). The UCI office was 19-24 C (Belgian winter), so the AC rarely runs; lighting decisions see the office's own recorded lighting in the light reading.

## End to end through the edge brain API

| check | result |
|---|---|
| uci_replay: 200 readings accepted, a decision returned for each | PASS |
| uci_replay: actuator levels reported by the board match the commands | PASS |
| uci_replay: shown as VIRTUAL BOARD (virtual_board/uci_replay), not the real board | PASS |
| uci_replay: every field the firmware sends is present | PASS |
| room_model: 200 readings accepted, a decision returned for each | PASS |
| room_model: actuator levels reported by the board match the commands | PASS |
| room_model: shown as VIRTUAL BOARD (virtual_board/room_model), not the real board | PASS |
| room_model: every field the firmware sends is present | PASS |
| all virtual-board readings stored as synthetic, none as room101_measured | PASS |

Room-model source (closed loop): mean temperature 26.40 C in readings with the AC (fan) commanded on vs 31.35 C with it off.
