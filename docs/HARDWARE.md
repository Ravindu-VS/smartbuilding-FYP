# Hardware, transport and the live room (Room 101)

Source of truth: `firmware/esp32_smart_building/esp32_smart_building.ino` (ESP32-S3) and
`raspberry_pi/edge_brain.py` (Raspberry Pi 4B edge brain).

## Status of the hardware integration

| Item | Status | Evidence |
|---|---|---|
| Firmware source (sensors, actuators, HTTP client, fail-safe) | implemented | firmware file; reviewed |
| Firmware compiled for the ESP32-S3 in this environment | **not done** - no Arduino/ESP32 toolchain reachable (GitHub release downloads refused by the network proxy) | - |
| Firmware syntax and library-API check (host g++, stub core headers, real library headers) | passes for SCD4x 1.x / 0.x / absent x INA226 Tillaart / INA226Lib / absent x core 3.x / 2.x | `firmware/tools/check_firmware.py`, `tests/test_firmware_check.py` |
| Bench-check script for the real room | implemented, tested against the HTTP test sender and rehearsed against the virtual board (labelled a software check) | `scripts/check_hardware.py`, `tests/test_check_hardware.py`, `experiments/results/exp11_real_room_replay/bench_rehearsal/` |
| Virtual board (firmware-identical payload; UCI replay or simulated Office A) | implemented, tested | `raspberry_pi/virtual_board.py`, `tests/test_virtual_board.py`, experiment 11 |
| Edge brain HTTP ingestion of the firmware's payload | implemented, tested | `raspberry_pi/test_edge_brain.py`, `tests/test_integration.py` |
| MQTT transport (edge side) with schema, dedupe, acks, status | implemented, tested with a local broker and a simulated board | `tests/test_store_mqtt.py`, experiment 10 |
| MQTT in the firmware | **not implemented** - the board posts HTTP; the edge accepts both | - |
| Physical verification with the board on the bench | **not performed in this work** (no board attached to this environment) | - |
| Wi-Fi credentials | in git-ignored `secrets.h` (template `secrets.example.h`) | `.gitignore` |

"Implemented" means the code exists and was reviewed; "tested" means an automated test exercised it;
"physically verified" is reserved for a run with the real board, which is still to be done.

## Library fixes found by the API check (24 Oct 2026)

The firmware had never been compiled in this work, so its library calls were checked against the libraries'
published headers (`firmware/tools/check_firmware.py`). Two problems were found and fixed; pins, timing and
logic are unchanged:

1. **SCD41 silently disabled with the current library.** Sensirion I2C SCD4x 1.x renamed the header and class
   (`SensirionI2cScd4x`) and changed `begin()` / the data-ready call. The sketch only looked for the old header,
   so with 1.x installed it compiled but never read CO2. It now supports 1.x and 0.4.x.
2. **INA226 did not compile with any INA226 library.** The sketch mixed two APIs (constructor of Rob Tillaart's
   library, methods of the Jarzebski/INA226Lib library). It now supports both libraries.

This is a syntax and API check with stubbed core headers, not an ESP32 compile: compile and flash in the Arduino
IDE as below.

## Until the hardware arrives: the virtual board

`raspberry_pi/virtual_board.py` stands in for the ESP32-S3 on the wire: the same HTTP POST every 3 s with
exactly the firmware's JSON fields (checked by `tests/test_virtual_board.py` against the `.ino`), the same handling
of the edge brain's reply (fan / LED / damper, reported back in the next reading) and the same fail-safe (fan
and LED off when the edge brain cannot be reached). Two data sources:

| Source | Temperature, humidity, light, CO2 | Occupancy | Reacts to the actuators |
|---|---|---|---|
| `--source uci` (default) | **recorded** values of the UCI office dataset (tracked copies in `Dataset/UCI/`) | recorded label drives the PIR / mmWave models | LED light at the BH1750 and the INA226 current (modelled); temperature does not |
| `--source twin` | Office A simulated by the twin's 5R1C physics, synthetic Colombo weather | twin occupants and PIR model | yes: the fan command runs the simulated AC, the LED the lights, the damper the boost fan |

PIR (HW-416-B), LD2410C, MQ-2 and INA226 values come from sensor models; `--noisy-sensors` raises the PIR /
mmWave false-trigger rates, `--drop scd41,...` removes sensors, `--stop-after N` goes silent. Its readings carry
`"source": "virtual_board"`: the dashboard shows **VIRTUAL BOARD · UCI REPLAY** (or ROOM MODEL), never LIVE ESP32,
and the store keeps them as `synthetic`. Start it with `run_local.bat virtual` / `virtual-twin` or
`scripts/start.sh virtual` / `virtual-twin`; stop it when the real board is connected - nothing else changes.

Experiment 11 replays the held-out UCI week through Room 101's own pipeline and drives the edge brain end to
end with both sources (`experiments/results/exp11_real_room_replay/`). The bench check was rehearsed against the
virtual board: 22 pass, 0 fail, 0 missing, labelled a software check
(`experiments/results/exp11_real_room_replay/bench_rehearsal/`).

**Finding and fix - vacancy rule.** Replaying real office data showed that CO2 stays high for hours after people
leave: before the fix the pipeline kept the lights on in 92 % of the empty minutes (quiet sensors, with or
without the LD2410C; 91 % with CO2 alone), because the CO2 evidence alone was enough to switch them on in the dark. Room 101's
controller now applies a vacancy rule when presence sensors are fitted: no PIR / mmWave detection for 15 min ->
lights OFF and AC ECO (ASHRAE 90.1-2016 allows occupancy-sensor timeouts of at most 20 min). With quiet sensors this cut
lights-on-when-empty to 10 % (PIR + CO2) and 22 % (PIR + mmWave + CO2); with 10x false triggers it stays at
57-96 %, because every false trigger restarts the 15 min. The real false-trigger rates are therefore worth
measuring: `python3 scripts/check_hardware.py --empty-room --seconds 1800` with nobody in the room. The simulated
rooms are unchanged (their controller is not affected).

## Bring-up (when the hardware is connected)

1. **Arduino IDE 2** - Boards Manager: *esp32 by Espressif Systems* (core 2.x or 3.x; both PWM APIs are handled).
   Board: *ESP32S3 Dev Module* (if you use the board's native USB port, set *USB CDC On Boot: Enabled* to see the
   serial log).
2. **Libraries** (Library Manager): *ArduinoJson* (Benoit Blanchon), *Adafruit BME280 Library* (accept *Adafruit
   Unified Sensor* and *Adafruit BusIO*), *BH1750* (Christopher Laws), *Sensirion I2C SCD4x*, *INA226* (Rob
   Tillaart; *INA226Lib* also works), *ld2410* (Nick Reynolds), *ESP32Servo* (Kevin Harrington). A missing
   optional library disables that sensor (the serial log says "library not available") and the bench check
   reports it as MISSING.
3. Copy `secrets.example.h` to `secrets.h` (git-ignored) and set Wi-Fi name, password and `EDGE_SERVER_URL` =
   `http://<Pi or PC IP>:8001/api/hardware/sensor-data` (`run_local.bat` prints the PC's IP). Allow port 8001
   through the PC's firewall.
4. Optional before flashing: `python3 firmware/tools/check_firmware.py`.
5. Compile and upload; Serial Monitor at 115200 baud. Each sensor prints `+ ... ACTIVE` or why not (`i ... not
   found`); fix wiring/addresses until the sensors you fitted are active.
6. Start the edge brain (`scripts/start.sh edge` on the Pi, `run_local.bat` or `scripts/start.sh dev` on the PC)
   and open the dashboard: Room 101 should turn LIVE (ESP32) within a few seconds.
7. Stop the virtual board if it is running. Bench check: `python3 scripts/check_hardware.py --actuators --ask`
   (reads 60 s of data, drives fan, LED and
   damper through a short manual override, asks you to confirm what you see, clears the override). Result:
   `experiments/results/hardware_bench/<date_time>/summary.md`. It is a physical verification only when the
   sender is the real board (`esp32_board`).
8. Disconnect test: unplug the board - Room 101 must show NOT CONNECTED within 10 s and its values disappear.
9. Empty-room false triggers: `python3 scripts/check_hardware.py --empty-room --seconds 1800` with nobody in
   the room (PIR / mmWave detections per hour; each one keeps the lights on for up to 15 min).
10. LED calibration: the button in Room 101's panel (or `POST /api/hardware/calibrate-led`) measures what the LED
   adds at the BH1750, so the AI does not mistake its own light for daylight.
11. Record the results: update the status table above and `docs/ACCEPTANCE_GATE.md` (section F) with the bench
    check's folder as evidence.

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
`timeout` after 10 s. Each reading's reported actuator levels are compared with the previous command
(`control.previous_command_verified`, stored as `decisions.verified`); three mismatches in a row raise an event.
Manual control: `POST /api/hardware/override` sets bounded fan/LED/damper levels for 1-240 min (the AI is bypassed,
the room shows MANUAL OVERRIDE, the override ends by itself or with `clear`). The AI switch (AI OFF) returns
every room to the conventional schedule. When the board cannot reach the edge, the firmware itself switches the fan and LED
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
