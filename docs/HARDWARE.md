# Hardware, transport and the live room (Room 101)

Source of truth: `firmware/esp32_smart_building/esp32_smart_building.ino` (ESP32-S3) and
`raspberry_pi/edge_brain.py` (Raspberry Pi 4B edge brain).

## Status of the hardware integration

| Item | Status | Evidence |
|---|---|---|
| Firmware source (BME280, BH1750, MQ-135, PIR, INA219, relay/fan, RGB, MQTT and BLE fallback) | implemented | `firmware/esp32_smart_building/esp32_smart_building.ino` |
| Firmware compiled and flashed (previous revision) | **PASS** on the owner's PC, 20 Nov 2026 (T24) | `COMMISSIONING_REPORT.md` |
| Firmware revision `room101-2026.11.20` (BLE MTU, holds, bench mode, sensor retry/median) | compiled for ESP32-S3 with Arduino-ESP32 core 3.3.12: 1,200,328 B flash (91 %), 67,292 B RAM (20 %); **not yet flashed** | build log in this review; flash with the runner (`--flash`) |
| Host-side firmware syntax/core-stub check | passes for core 3.x and 2.x stubs | `firmware/tools/check_firmware.py`, `tests/test_firmware_check.py` |
| Commissioning runner (flash, deploy, every remaining test, evidence files) | implemented; dry-run against a simulated board and a local Mosquitto only | `scripts/commission_room101.py` |
| Virtual board (software simulation; UCI replay or simulated Office A) | implemented, tested | `raspberry_pi/virtual_board.py`, `tests/test_virtual_board.py`, experiment 11 |
| Edge brain HTTP ingestion | implemented, tested as a separate test path | `raspberry_pi/test_edge_brain.py`, `tests/test_integration.py` |
| MQTT transport (edge side) with schema, dedupe, acks, status | implemented, tested with a local broker and a simulated board | `tests/test_store_mqtt.py`, experiment 10 |
| MQTT in the firmware | live telemetry and command acknowledgements reached the Pi (T12, T13 PASS) | `COMMISSIONING_REPORT.md` |
| Paired BLE fallback | paired and GATT-connected (T21 PASS); sustained fallback freshness **FAIL** with the previous revision (T22) | `COMMISSIONING_REPORT.md` |
| Sensor bring-up | BME280, BH1750, MQ-135, PIR and INA219 I²C communication observed in live telemetry; reference and stimulus checks still open | `COMMISSIONING_REPORT.md` |
| RGB output | **FAIL** with the previous revision (acknowledged, owner saw no light); bench diagnostic `D` added | `COMMISSIONING_REPORT.md` |
| Fan branch / relay and INA219 load measurement | **NOT TESTED** (12 V branch not powered yet) | `COMMISSIONING_REPORT.md` |
| Wi-Fi credentials | in git-ignored `secrets.h` (template `secrets.example.h`) | `.gitignore` |

"Implemented" means the code exists; software tests do not establish physical operation. The owner-reported
sensor checks are distinguished from tests run in this environment in `COMMISSIONING_REPORT.md`.

## Active firmware and libraries

The active sketch uses Arduino-ESP32 Wi-Fi/BLE, PubSubClient, ArduinoJson, Adafruit BME280, BH1750,
Adafruit INA219, and Preferences. The old SCD41/LD2410/INA226 descriptions elsewhere in the research and
simulation documents describe earlier or simulated configurations, not the current physical firmware.
The revision `room101-2026.11.20` compiles with Arduino-ESP32 core 3.3.12 (NimBLE BLE stack on the
ESP32-S3); the board still runs the previously flashed revision until it is uploaded again.

Sensor handling in this revision: every reading cycle reads each sensor once and the same values go to the
Serial log and the telemetry. The BME280 is read three times 40 ms apart and the median is published only if
it is physically plausible (-40..85 C, 0..100 %RH, 800..1100 hPa); a rejected sample is left out of the
message and `sensor_health.bme280` is false for it, and repeated rejections re-initialise the sensor. This
addresses isolated outliers such as the 761 hPa / 85.6 %RH sample. A sensor that does not answer at power-up
is probed again every 30 s instead of staying unavailable until the next reboot.

## Virtual board for software-only testing

`raspberry_pi/virtual_board.py` stands in for the ESP32-S3 on the HTTP test path: the same HTTP POST every 3 s with
the digital twin's payload fields, the same handling
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

## Bring-up and commissioning

1. In Arduino IDE 2 install *esp32 by Espressif Systems* and select *ESP32S3 Dev Module*. Enable USB CDC
   On Boot when using the native USB connector.
2. Install *PubSubClient*, *ArduinoJson*, *Adafruit BME280 Library* (with Unified Sensor and BusIO),
   *BH1750*, and *Adafruit INA219*. BLE, Preferences and Wi-Fi are provided by the ESP32 Arduino core.
3. Keep credentials in the git-ignored `secrets.h` copied from `secrets.example.h`. Set the board's
   `MQTT_BROKER_IP` to the Pi's current LAN IP (not `127.0.0.1`); the Pi gateway's local broker host can
   remain `127.0.0.1`. Ensure the Wi-Fi network permits ESP32-to-Pi TCP access on port 1883; guest or
   client-isolated networks may block it. Do not configure router port forwarding or paste credentials
   into source or logs.
4. Confirm the installed wiring against the pin table below. The HW-478 photo shows no visible on-board
   current-limiting resistors, so install one series resistor (220-330 ohm) on each R/G/B channel before
   connecting it to the ESP32. Confirm the RGB polarity and relay active level before actuator tests;
   firmware polarity flags are configuration, not proof. The INA219 logic VCC is not connected to the
   12 V fan supply. Set the MT3608 boost to 12.0 V with a meter before connecting the fan branch.
5. Compile and flash the production `.ino` in Arduino IDE; Serial Monitor is 115200 baud. After flashing,
   record the boot log, sensor presence, Wi-Fi IP/RSSI and MQTT connection. A verified flash and valid
   telemetry do not prove that physical actuator wiring works.
6. On the Pi install `requirements/edge.txt`, ensure Mosquitto and BlueZ are running, then start
   `raspberry_pi/run_edge.sh`. Confirm `/health`, `/api/hardware/mqtt`, and `/api/hardware/ble` actually answer.
7. Pair the BLE gateway using the passkey printed by the ESP32, then confirm `connected` in
   `/api/hardware/ble`. Advertising alone is not a successful BLE connection.
8. Observe `sb/v1/room/f2_office_a/#` on Mosquitto. Verify telemetry and status first; then send a
   validated `sb.command/1` JSON command on the existing command topic and verify its acknowledgement.
   The BLE gateway uses the same topics when the board's direct MQTT status is offline.
9. Run the tests in `docs/COMMISSIONING_REPORT.md`, including fan current measurement, all RGB colors,
   command acknowledgement, transport recovery and Pi reboot. Record evidence and never mark an
   unobserved hardware test PASS. `scripts/commission_room101.py` does all of this from the PC (see
   "Commissioning runner" below) and writes the evidence to `docs/commissioning_runs/`.

## Commissioning runner

Run from the project folder on the Windows PC (ESP32 on USB, Pi on the LAN, Arduino Serial Monitor closed):

```powershell
.venv\Scripts\python.exe scripts\commission_room101.py --deploy-pi --flash      # first run
.venv\Scripts\python.exe scripts\commission_room101.py --only T09,T16           # repeat some tests
.venv\Scripts\python.exe scripts\commission_room101.py --skip-reboot            # everything but T18
```

`--deploy-pi` backs up and replaces `ble_gateway.py`, `mqtt_bridge.py` and `edge_brain.py` in
`/home/pi/Desktop/Project-pi-ble` and restarts the Edge Brain; deploy it together with the new firmware,
because the old gateway rejects the larger BLE frames. `--flash` compiles and uploads with the Arduino IDE's
bundled `arduino-cli` (`--port COM8` by default). The runner then measures what it can (telemetry intervals,
acknowledgements, INA219 current, BLE gaps, recovery times) and asks the operator only for what it cannot
see: a reference thermometer reading, covering the light sensor, breathing on the MQ-135, waving at the PIR,
the LED colour, the relay click and the fan. Mosquitto restart (T17) and Pi reboot (T18) use `sudo` over SSH,
so the Pi password is typed into the terminal. Results go to `docs/commissioning_runs/run_<time>.md/.json`;
a test is PASS only when the measurement and the operator's observation agree.

## Serial bench commands (Arduino Serial Monitor, 115200 baud)

| Key | Action |
|---|---|
| `1` / `0` | relay and fan ON / OFF |
| `R` `G` `B` `W` `K` | RGB red / green / blue / white / off (PWM) |
| `D` | RGB channel diagnostic: each colour pin driven as a plain GPIO HIGH for 4 s (GPIO 6, then 7, then 5) |
| `S` | read and print all sensors |
| `I` | scan the I²C bus |
| `X` | end the bench session now (relay and LED OFF) |
| `H` | help |

A serial command starts a two-minute bench session: the edge fail-safe and remote commands do not override
the operator's setting meanwhile, and everything returns to OFF when it ends. Previously the fail-safe
switched the outputs off within 10 ms whenever no edge controller was connected, so serial colour tests
always looked dark. For the `D` diagnostic measure each GPIO to GND with a multimeter: about 3.3 V while the
LED stays dark points to the module, its series resistor or the common-pin connection; 0 V points to the
pin or the board.

## Room 101

Room 101 is Office A, room id `f2_office_a`, on floor 2 ("Operations") of the twin - the only room with
`data_source: "hardware"` in `twin/building_config.py`. The other 25 rooms (Rooms 102-126) are simulated.
Room numbers are labels for the report and the dashboard; the room ids are the keys everywhere in the code.

## Board pin map (from the firmware)

Full circuit with every module's printed pin order and the exact header positions: [wiring/room101-wiring.html](wiring/room101-wiring.html).

| Device | Function | ESP32-S3 pins |
|---|---|---|
| BME280 | temperature, humidity, pressure | I2C SDA 9 / SCL 8 |
| BH1750 | illuminance | I2C SDA 9 / SCL 8 |
| INA219 | bus/shunt voltage, current, power | I2C SDA 9 / SCL 8 |
| 0.96" OLED JMD0.96A-2 (SSD1306, 0x3C) | energy meter: power, voltage, current, Wh since boot, fan, mode, temperature (refreshed every 1 s) | I2C SDA 9 / SCL 8, VCC 3.3 V |
| MQ-135 AO / DO | raw environmental response / comparator output | AO → R1 10k → GPIO 1 (J3-4), R2 15k to GND / DO → R3 10k → GPIO 2 (J3-5), R4 22k to GND |
| HC-SR501 PIR | motion (VCC 5 V, OUT 3.3 V) | OUT → GPIO 4 (J1-4) |
| CW-020 5 V relay module (IN, VCC, GND) | fan switching | low-level input: GPIO 10 (J1-16) → R5 1k → BC547 Q1 base, R6 10k base to GND; Q1 collector → relay IN, emitter → GND. High-level input: GPIO 10 → IN direct. The relay test in the circuit page picks one. GPIO 10 HIGH = fan ON; fan + on NO |
| 12 V two-wire fan | load, switched by relay | relay contacts; 12 V from the MT3608 boost |
| Light LED (HW-478 RGB) | the AI's lighting decision, PWM white OFF / DIM / ON | R 6 / G 7 / B 5 through 150 / 68 / 68 ohm; common (-) to GND |
| AC indicator RGB LED | what the AC would do: ECO green, LOW cyan, COOL blue, MAX magenta | R 11 / G 12 / B 13 through 150 / 68 / 68 ohm (on/off, no PWM) |
| Status RGB LED | AI blue, schedule green, manual yellow, warning red, test white; blinking red = no controller | R 14 / G 15 / B 16 through 150 / 68 / 68 ohm (on/off, no PWM) |
| Onboard RGB LED | Wi-Fi/MQTT connection indication | GPIO 48 (J3-16) on the DevKitC-1 v1.0 used here (GPIO 38 on v1.1 boards) |

The production firmware uses Room 101's canonical id `f2_office_a`, publishes to the project's existing
`sb/v1/room/f2_office_a/...` topics, and sends telemetry every 3 s over MQTT and BLE. The board itself does
not compute CO2; the Pi estimates it from the ADC millivolts (see "CO2 from the MQ-135" below).

Indicator LEDs (firmware `room101-2026.11.23b`): every Edge Brain command carries `ac_led`
(OFF/ECO/LOW/COOL/MAX, from the AC decision) and `status_led` (AI/RULE/MANUAL/WARNING/TEST); the board reports
what they show as `actuator_ac_led` / `actuator_status_led`. WARNING means a safety note, room temperature
>= 30 C, CO2 >= 1200 ppm or a sensor not responding. The board overrides the status LED locally: blinking red
when no controller is reachable (fail-safe), white during a serial bench session. The indicator LEDs switch
colours on/off because the S3 has 8 LEDC channels and the light LED uses three for dimming. The retained
status topic now also carries `detail`: booting (first 60 s), running, or error with `failed` sensors.
Pin numbers differ from the requirements document (SDA 8 / SCL 9, RGB 5/6/7); the owner chose to keep the
wired and tested board as the reference (23 Nov 2026). The full wiring page with the INA219/relay/fan branch
is `docs/wiring/room101-wiring.html` (final circuit with the OLED, C1/C2 470 uF, C3 100 nF, LED resistors red 150 ohm /
green and blue 68 ohm, parts list with part numbers; PNG: `docs/wiring/room101-final-circuit.png`).

Power (revision F, 28 Nov 2026): the whole system runs from one Baseus Adaman Metal 22.5 W 20000 mAh power bank
(PPADM205). With two ports in use it gives 5 V and 3 A in total, so everything runs at 5 V:

| Bank port | Goes to | Load |
|---|---|---|
| USB 1 (A) | J1 USB-A plug (VBUS, GND; D-/D+ open) -> F1 PTC 1.6 A -> +5 V rail (C1 470 uF) | ESP32 via D3, MQ-135, PIR, relay, MT3608 boost (12.0 V, C2 470 uF) -> INA219 -> relay -> fan; ~0.4 A typical, ~1.3 A peak |
| USB 2 (A) | USB-A to USB-C cable (3 A, <= 1 m) -> Raspberry Pi 4B | ~0.6 A typical, ~1.3 A busy |
| USB-C | recharging the bank only, not during a demo | - |

The 12 V adapter, D1 1N5822 and the LM2596 are no longer used. Plug both cables in before pressing the bank's
button (a running bank may reset its outputs when a second device is connected), and check
`vcgencmd get_throttled` on the Pi reads `0x0`. Runtime is about 7-8 h at the typical load.
Firmware `room101-2026.11.24` (OLED energy page; relay driven through Q1, GPIO 10 active-HIGH); a missing OLED is probed again every 30 s like the sensors.

## Data path (sensor to twin)

```
sensor -> ESP32-S3 reads (unavailable sensor fields omitted; sensor_health reports availability)
       -> MQTT sb/v1/room/f2_office_a/telemetry
          or paired BLE -> Pi BleGateway -> the same MQTT topic
       -> validation (_num: finite numbers only; MQTT: ranges, schema, msg_id, room/topic match)
       -> EdgeBrain.inject_hardware_data  (one ingestion function for both transports)
       -> SQLite store (readings, decisions; provenance room101_measured only for the real board)
       -> HardwareRoomController: PIR(+mmWave) + CO2 fusion -> multi-objective controller -> SafetyLayer
       -> sb.command/1 over MQTT or BLE -> board switches relay/fan and RGB
       -> state streamed to the dashboard (SSE) -> 3D twin and room panel
```

Failures are visible at each stage: a board that stops posting for `HW_TIMEOUT_S` (10 s) is shown as
"lost" with no values; a reading from the HTTP test sender or the MQTT harness is labelled
"TEST SENDER" / provenance `synthetic`; a value that fails validation is dropped and reported.

## Control path and fail-safe behaviour

Controller -> proposed action -> SafetyLayer (R1 valid values and set-point 22-27 C, R2 equipment rooms,
R3 heat-stress guard, R4 CO2 fresh-air rule) -> command to the board -> the next reading reports the
actuator state (`actuator_fan_speed`, `actuator_light_level`, `actuator_servo_angle`) -> event log.
Over MQTT or BLE the board acknowledges each command (`sb.ack/1`); an unacknowledged command is marked
`timeout` after 10 s. Each reading's reported actuator levels are compared with the previous command
(`control.previous_command_verified`, stored as `decisions.verified`); three mismatches in a row raise an event.
Manual control: `POST /api/hardware/override` sets bounded fan/LED levels for 1-240 min. When neither MQTT
nor BLE is available, or the edge command timeout expires, firmware switches the relay and RGB off.

## MQTT topics and schemas

| Topic | Direction | QoS | Payload |
|---|---|---|---|
| `sb/v1/room/<room>/telemetry` | board -> edge | 1 | `sb.telemetry/1`: `room_id`, `msg_id`, sensor fields, MQ-135 raw/ADC reading, INA219 measurements and actuator state |
| `sb/v1/room/<room>/command` | edge -> board | 1 | `sb.command/1`: backend `fan_speed`/`light_level`, or validated `fan`/`relay`/`rgb` manual fields |
| `sb/v1/room/<room>/ack` | board -> edge | 1 | `sb.ack/1`: `msg_id` of the command, `status` applied/rejected, `applied` actuator states |
| `sb/v1/room/<room>/status` | board -> edge | 1, retained, last will | `{"state": "online" \| "offline"}` |
| `sb/v1/edge/status` | edge -> boards | 1, retained, last will | `{"state": "online" \| "offline"}` |

The relay switches the fan, so `relay` and `fan` are alternate command names for the same output, not
independent actuators. Each command needs a unique string `msg_id`. Examples for a local Pi broker:

```sh
mosquitto_pub -h 127.0.0.1 -t sb/v1/room/f2_office_a/command \
  -m '{"schema":"sb.command/1","msg_id":"manual-fan-001","fan":"ON"}'
mosquitto_pub -h 127.0.0.1 -t sb/v1/room/f2_office_a/command \
  -m '{"schema":"sb.command/1","msg_id":"manual-rgb-001","rgb":"RED"}'
```

Use `fan` or `relay` with `ON`, `OFF`, or `TOGGLE`; `rgb` supports `RED`, `GREEN`, `BLUE`, `WHITE`, or
`OFF`. Each valid command is acknowledged on the existing `ack` topic; commands sent through BLE use the
same JSON and acknowledgement schemas.

The Edge Brain answers every reading with an automatic `fan_speed`/`light_level` command, and the RGB module
is the room light, so a plain `rgb` colour is replaced by the automatic white level within about three
seconds. Manual and test commands therefore carry `"hold_s"` (1-600): the actuators they set keep that state
and automatic commands leave them alone until the hold ends; `"hold_s": 0` releases a hold at once. Holds are
reported in telemetry and acknowledgements (`rgb_hold_s`, `fan_hold_s`), the Edge Brain does not count a held
actuator as a verification mismatch, and the edge fail-safe still clears every hold.

```sh
mosquitto_pub -h 127.0.0.1 -t sb/v1/room/f2_office_a/command \
  -m '{"schema":"sb.command/1","msg_id":"manual-rgb-002","rgb":"RED","hold_s":30}'
mosquitto_pub -h 127.0.0.1 -t sb/v1/room/f2_office_a/command \
  -m '{"schema":"sb.command/1","msg_id":"ble-test-001","test":"mqtt_pause","seconds":60}'
```

`"test": "mqtt_pause"` (10-300 s, accepted only while the BLE gateway is connected) makes the board publish a
retained `offline` status, leave MQTT and carry telemetry and commands over BLE until the pause ends. It is
the controlled way to commission the BLE fallback without touching the network. Telemetry states the path it
took in `transport` (`mqtt` or `ble`) and the firmware revision in `fw_version`.

Credentials: `MQTT_USERNAME`, `MQTT_PASSWORD` (environment only, never logged), `MQTT_TLS=1` for TLS.
Enable the bridge with `MQTT_ENABLED=1` (`scripts/start.sh live`). One client per process; reconnect with
back-off 1-30 s. For a broker on the Pi, Mosquitto with `password_file` and `listener 1883 127.0.0.1` (or TLS
on 8883 for remote boards) is the intended set-up.

## Paired BLE fallback

MQTT remains the preferred board transport. When the ESP32 cannot connect to MQTT but the Pi gateway is
available, the board advertises `SB-Room101` over BLE. The Pi's `BleGateway` forwards telemetry and
acknowledgements to the same MQTT topics and sends MQTT commands back over BLE. BLE uses the same schemas,
with a four-byte frame header; the message limit is 1024 bytes. The ESP32 offers an ATT MTU of 247 and BlueZ
negotiates it on connect, so each notification carries up to 240 data bytes and a telemetry message needs
four or five frames (sixteen-byte frames, about sixty of them, only if the MTU stays at 23). A notification the
host stack cannot buffer is retried up to three times before the message counts as dropped. The previous
revision forced a 23-byte MTU and sent 44 frames 50 ms apart per message, which blocked the loop for over two
seconds every reading and lost whole messages when one frame was dropped; that matches the gaps seen in T22.
Pi gateway and firmware must be updated together: the old gateway rejects frames longer than 20 bytes. The paired BLE
link is an alternate route to the MQTT broker, not a replacement for Mosquitto.
**Redundant delivery (since 23 Nov 2026).** On the factory guest Wi-Fi the board's MQTT link was unreliable:
the Pi answered 1 of 20 pings to the board, TCP stalled for tens of seconds while PubSubClient still counted
as connected, and writes into the stalled socket blocked the loop for up to 10 s each. BLE, measured at the
same time, delivered every frame. The system therefore uses both links at once while both are up:

- the board publishes each reading over MQTT and, while the gateway is connected, over BLE too, with the
  same `msg_id` (`transport` says which copy it is). The MQTT bridge keeps the first copy and counts the
  other as a duplicate, so each reading is processed and answered once;
- ACKs go over both links; the edge matches them by command `msg_id`;
- the gateway forwards every edge command over BLE as well (`BLE_REDUNDANT=1`, the default; set `0` for the
  old behaviour of forwarding only when the board's MQTT status is offline). The board de-duplicates by
  command `msg_id` and does not re-acknowledge the second copy within 10 s;
- the board drops an MQTT link that has delivered nothing for 12 s (the edge answers every reading, so
  silence means a stall) and reconnects, instead of blocking on it;
- Wi-Fi modem sleep is on (ESP-IDF requires it for Wi-Fi/BLE coexistence), coexistence prefers Wi-Fi, and
  the board asks the Pi for a 50-100 ms BLE connection interval so BLE leaves air time for Wi-Fi.

Measured on 23 Nov 2026 (5-minute MQTT capture on the Pi broker, firmware `room101-2026.11.23`): 95 unique
readings in 297 s (one every 3.1 s), the only gap longer than 4.5 s was the 16 s Wi-Fi/MQTT connect after
boot, 94 of 95 commands acknowledged. 75 readings arrived first over BLE and 20 first over MQTT. Before the
change, a 150 s capture had 27 readings and gaps of up to 30 s. A dedicated access point or phone hotspot
for the Pi and the board will make the MQTT half far better than the shared guest network.

On the Pi, install `requirements/edge.txt` and run `raspberry_pi/run_edge.sh` with Mosquitto available.
That launcher enables MQTT and BLE by default. For direct startup, set both `MQTT_ENABLED=1` and
`BLE_ENABLED=1`. The gateway scans for the configured device and exposes its state at
`GET /api/hardware/ble` (`connected`, `mqtt_connected`, `last_error`, and transfer counters). BLE status
is also published on `sb/v1/room/f2_office_a/ble_status`; the existing MQTT bridge uses it only when the
board's direct MQTT status is not online.

For first pairing, open the ESP32 Serial Monitor at 115200 baud and note the six-digit passkey printed
during startup. Keep it private. The Pi gateway requests pairing when it connects. If BlueZ requires an
interactive pairing agent, stop the gateway, use `bluetoothctl` with a keyboard/display agent to pair the
advertised device using that passkey, trust the device, then restart the gateway. Confirm the result in
`/api/hardware/ble`; do not treat advertising alone as a completed connection. A new passkey is generated
only if the ESP32's stored Preferences value is invalid.

While BLE carries the data the firmware retries MQTT every 15 s instead of 5 s, and a TCP connect to a
missing broker is limited to 3 s (raised from 1.5 s, which was too short on the congested guest Wi-Fi).

## CO2 from the MQ-135 (estimated, `co2_source = "mq135_estimate"`)

The board has no NDIR CO2 sensor, so the Edge Brain estimates CO2 from the MQ-135
(`raspberry_pi/co2_estimator.py`). The board sends the AO voltage (`mq135_adc_mv`); the Pi converts it:

    Vout = Vadc x divider        Rs = RL (Vcc - Vout) / Vout          (RL = 1 kOhm on the module, Vcc = 5 V)
    Rs_c = Rs / f(T, RH)         temperature/humidity correction from the datasheet curve, BME280 values
    ppm  = 116.6020682 (Rs_c / R0)^-2.769034857

R0 comes from automatic baseline correction (ABC): the cleanest hour in the last 7 days (highest corrected
Rs) is taken as fresh air, 420 ppm. For the first 24 h the value is labelled `provisional`; the first 30 min
after a board boot are `warming_up` and give no value. The result is the median of the last five readings,
clamped to 350..10000 ppm. It appears as `CO2` with `CO2_source = mq135_estimate`, `CO2_estimate_state` and
`MQ135_Rs_kohm` in the room sensors, and the dashboard labels it `eCO2 (MQ-135)`. A measured NDIR value
(`scd41_ndir`) always wins if a board sends one. Status: `GET /api/hardware/co2`.

Final wiring: the module runs from 5 V and AO reaches GPIO1 through a 10k/15k divider (R1 10 k from AO to
GPIO1, R2 15 k from GPIO1 to GND), so GPIO1 never sees more than 3.0 V. The Edge Brain's default
`MQ135_DIVIDER` is 25/15 = 1.667 for this circuit (set it to `1.0` only for a board without the divider).
The ESP32-S3 ADC reads up to about 3.1 V; readings at or above 3100 mV are reported `adc_saturated` and not
used. A calibration saved for a different supply, load resistor or divider is set aside automatically and
the baseline starts again (it is kept in `discarded_calibration` of `GET /api/hardware/co2`). Better calibration: put the board outdoors for 20-30 min, then
`POST /api/hardware/co2/calibrate {"reference_ppm": 420}` (manual R0, kept until
`{"release": true}`). The MQ-135 also reacts to alcohol, ammonia and VOCs, so this is an estimate, not a
measurement; the thesis should say so.

If both transports are unavailable, the firmware turns the fan and RGB outputs off. A valid command over
either MQTT or BLE refreshes the command timeout; BLE connection by itself does not bypass the timeout.

## Test harness (no board needed)

* `python raspberry_pi/esp32_test_sender.py` - HTTP, the firmware's payload with `source: "test_sender"`.
* `python raspberry_pi/mqtt_device_sim.py` - MQTT simulated board (first-order room model responding to its
  commands; options for duplicates, bad values, missing acks, going silent).
* `scripts/start.sh harness` - local broker + simulated board + edge brain + dashboard.
* Experiment 10 (`python experiments/run.py exp10_live_room`) runs both paths and checks ingestion,
  validation, dedupe, acknowledgements, status, staleness, storage and provenance.

Harness results are software tests; they are not a physical verification of the room.
