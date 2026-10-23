# Hardware, transport and the live room (Room 101)

Source of truth: `firmware/esp32_smart_building/esp32_smart_building.ino` (ESP32-S3) and
`raspberry_pi/edge_brain.py` (Raspberry Pi 4B edge brain).

## Status of the hardware integration

| Item | Status | Evidence |
|---|---|---|
| Firmware source (sensors, actuators, HTTP client, fail-safe) | implemented | firmware file; reviewed |
| Firmware compiled for the ESP32-S3 in this environment | **not done** - no Arduino/ESP32 toolchain reachable (GitHub release downloads refused by the network proxy) | - |
| Edge brain HTTP ingestion of the firmware's payload | implemented, tested | `raspberry_pi/test_edge_brain.py`, `tests/test_integration.py` |
| MQTT transport (edge side) with schema, dedupe, acks, status | implemented, tested with a local broker and a simulated board | `tests/test_store_mqtt.py`, experiment 10 |
| MQTT in the firmware | **not implemented** - the board posts HTTP; the edge accepts both | - |
| Physical verification with the board on the bench | **not performed in this work** (no board attached to this environment) | - |
| Wi-Fi credentials | in git-ignored `secrets.h` (template `secrets.example.h`) | `.gitignore` |

"Implemented" means the code exists and was reviewed; "tested" means an automated test exercised it;
"physically verified" is reserved for a run with the real board, which is still to be done.

## Room 101

Room 101 is Office A, room id `f2_office_a`, on floor 2 ("Operations") of the twin - the only room with
`data_source: "hardware"` in `twin/building_config.py`. The other 25 rooms (Rooms 102-126) are simulated.
Room numbers are labels for the report and the dashboard; the room ids are the keys everywhere in the code.

## Board pin map (from the firmware)

| Device | Function | ESP32-S3 pins |
|---|---|---|
| BME280 | temperature, humidity, pressure | I2C SDA 17 / SCL 18 (0x76/0x77) |
| BH1750 | illuminance | I2C SDA 17 / SCL 18 (0x23/0x5C) |
| SCD41 | CO2 (NDIR), temperature, humidity | I2C SDA 17 / SCL 18 (0x62) |
| INA226 | voltage, current, power of the board's loads | I2C SDA 17 / SCL 18 (0x40) |
| LD2410C | 24 GHz mmWave presence, distance | UART: board RX 16 <- TX, board TX 15 -> RX |
| MQ-2 | combustible gas (analog) | GPIO 1 (ADC) |
| HW-416-B PIR | motion | GPIO 4 |
| DC fan via MOSFET | stands in for the room's AC | GPIO 14 (PWM 25 kHz, 8 bit) |
| White LED | stands in for the room lighting | GPIO 12 (PWM 5 kHz, 8 bit) |
| SG90 servo | fresh-air damper | GPIO 13 (50 Hz) |
| RGB status LED | status | R 6, G 7, B 5 |
| Onboard LED | connection status | GPIO 38 |

**Difference from the master prompt.** The prompt lists an older design (DHT22 on GPIO 4, BH1750 on 8/9,
MQ135 on ADC1, PIR on GPIO 2, relay on GPIO 5, LED PWM on GPIO 6, MQTT every ~10 s). The firmware in the
repository uses the map above and posts every 3 s over HTTP. The firmware was not changed: altering
working pin assignments without the board to test on would be unsafe. The MQ-2 is a combustible-gas sensor;
its reading is stored as `mq2_raw` and is never used as CO2 (only the SCD41's NDIR value, `co2_source:
"scd41_ndir"`, is).

## Data path (sensor to twin)

```
sensor -> ESP32-S3 reads (missing sensor = field omitted, never a default value)
       -> HTTP POST /api/hardware/sensor-data  (or MQTT sb/v1/room/f2_office_a/telemetry)
       -> validation (_num: finite numbers only; MQTT: ranges, schema, msg_id, room/topic match)
       -> EdgeBrain.inject_hardware_data  (one ingestion function for both transports)
       -> SQLite store (readings, decisions; provenance room101_measured only for the real board)
       -> HardwareRoomController: PIR(+mmWave) + CO2 fusion -> multi-objective controller -> SafetyLayer
       -> reply / MQTT command -> board actuates fan, LED, damper
       -> state streamed to the dashboard (SSE) -> 3D twin and room panel
```

Failures are visible at each stage: a board that stops posting for `HW_TIMEOUT_S` (10 s) is shown as
"lost" with no values; a reading from the HTTP test sender or the MQTT harness is labelled
"TEST SENDER" / provenance `synthetic`; a value that fails validation is dropped and reported.

## Control path and fail-safe behaviour

Controller -> proposed action -> SafetyLayer (R1 valid values and set-point 22-27 C, R2 equipment rooms,
R3 heat-stress guard, R4 CO2 fresh-air rule) -> command to the board -> the next reading reports the
actuator state (`actuator_fan_speed`, `actuator_light_level`, `actuator_servo_angle`) -> event log.
Over MQTT the board also acknowledges each command (`sb.ack/1`); an unacknowledged command is marked
`timeout` after 10 s. When the board cannot reach the edge, the firmware itself switches the fan and LED
off (`apply_actuation("ECO", "OFF", 0, 0, -1)`) and shows a red status LED.

## MQTT topics and schemas

| Topic | Direction | QoS | Payload |
|---|---|---|---|
| `sb/v1/room/<room>/telemetry` | board -> edge | 1 | `sb.telemetry/1`: `room_id`, `msg_id` (1-64 chars, unique), optional `ts`, and the HTTP payload's fields |
| `sb/v1/room/<room>/command` | edge -> board | 1 | `sb.command/1`: `msg_id`, `in_reply_to`, `hvac_action`, `light_action`, `fan_speed`, `light_level`, `servo_angle`, `occupancy_probability`, `ttl_s` |
| `sb/v1/room/<room>/ack` | board -> edge | 1 | `sb.ack/1`: `msg_id` of the command, `status` applied/rejected, `applied` actuator states |
| `sb/v1/room/<room>/status` | board -> edge | 1, retained, last will | `{"state": "online" \| "offline"}` |
| `sb/v1/edge/status` | edge -> boards | 1, retained, last will | `{"state": "online" \| "offline"}` |

Credentials: `MQTT_USERNAME`, `MQTT_PASSWORD` (environment only, never logged), `MQTT_TLS=1` for TLS.
Enable the bridge with `MQTT_ENABLED=1` (`scripts/start.sh live`). One client per process; reconnect with
back-off 1-30 s. For a broker on the Pi, Mosquitto with `password_file` and `listener 1883 127.0.0.1` (or TLS
on 8883 for remote boards) is the intended set-up.

## Test harness (no board needed)

* `python raspberry_pi/esp32_test_sender.py` - HTTP, the firmware's payload with `source: "test_sender"`.
* `python raspberry_pi/mqtt_device_sim.py` - MQTT simulated board (first-order room model responding to its
  commands; options for duplicates, bad values, missing acks, going silent).
* `scripts/start.sh harness` - local broker + simulated board + edge brain + dashboard.
* Experiment 10 (`python experiments/run.py exp10_live_room`) runs both paths and checks ingestion,
  validation, dedupe, acknowledgements, status, staleness, storage and provenance.

Harness results are software tests; they are not a physical verification of the room.
