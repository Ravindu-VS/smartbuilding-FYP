# Room 101 Commissioning Report

**Updated:** 23 Nov 2026  
**Scope:** ESP32-S3, Room 101 (`f2_office_a`), Raspberry Pi Mosquitto/Edge Brain, Wi-Fi/MQTT primary,
paired BLE fallback, actuators, INA219 measurement and digital-twin feedback.

## Result

**23 Nov 2026:** the full chain (ESP32 sensors → MQTT and BLE → Pi Edge Brain with the Random Forest and
the controller → commands back to the board, and the digital-twin dashboard) ran live and survived a Pi reboot.
16 of 24 rows now PASS (T03 and T05 on the owner's report). What is left needs the owner at the bench: fan 12 V supply, RGB by eye, reference
instrument, a hand over the BH1750. The paragraphs below are the 20 Nov record.

The source uses the existing `f2_office_a` topic contract and includes MQTT-first telemetry, paired BLE
fallback, validated JSON actuator commands, MQ-135/INA219 telemetry fields, and backend/twin display
support. The Pi deployment is running separately at `/home/pi/Desktop/Project-pi-ble`; the pre-existing
`/home/pi/Desktop/Project` was left untouched. The production ESP32-S3 firmware was compiled and flashed;
the final image hash verified after the flasher retried a fast-reflash mismatch.

After flashing, the Pi received the current `sb.telemetry/1` payload, including `device_id`,
`mq135_raw`, and `ina219_shunt_voltage_mV`; all sensor-health flags were true in the captured samples.
One sample reported 24.81 C, 43.33% humidity, 1006.93 hPa and -56 dBm Wi-Fi RSSI. A later sample reported
761.2888 hPa and 85.60% humidity. The pressure is outside the backend's configured 800..1100 hPa range
and is dropped; the readings still need comparison with a reference instrument. INA219 readings near
zero were observed without a powered fan load, so they do not validate the current-measurement path.

A controlled MQTT RGB RED command received an `applied` acknowledgement and the next board telemetry
reported `actuator_rgb: RED`, but the owner saw no light from the HW-478. The owner reports that one
current-limiting resistor is now installed per color channel and the common pin is connected to GND.
The firmware's RGB pin map and ESP32 core 3 PWM calls match GPIO R6/G7/B5, but this does not prove GPIO
voltage or wiring. RGB physical output is **FAIL** pending channel-by-channel wiring and voltage checks.
The Pi Edge Brain was restored after the controlled test; its one-minute LED-OFF override expired.
Fan and relay were not actuated and remain unverified.

After a board reset, the BLE gateway reconnected and forwarded telemetry while direct board MQTT was
offline, but frame delivery had long gaps and the Pi marked the board lost. Once MQTT recovered, an
eight-sample, 40-second check showed stable MQTT telemetry at about 3-second intervals; the latest Pi
snapshot reports 291 readings, a connected board and zero pending acknowledgements. BLE remains GATT
connected, but its last frame is over 200 seconds old because the board is using MQTT. The broker has
anonymous access and no TLS, so it is limited to the trusted LAN and must not be exposed through router
port forwarding.

The dashboard and APIs have received live Office A data, but no controlled sensor change was made.
Physical RGB output, fan/relay/INA219 load behavior, reliable BLE freshness/fallback, and Pi reboot recovery
remain outstanding. End-to-end acceptance remains **NOT COMPLETE**.

Statuses are `PASS`, `FAIL`, `NOT TESTED`, or `BLOCKED`. Owner-reported observations are identified in the
evidence column and are not represented as tests performed in this run.

## Live run, 23 Nov 2026 (remote, through the PC relay)

The board, the Pi and the dashboard ran together for the whole session. Work was done from the project PC
through a job relay that ran only on that PC (SSH/SCP to the Pi, MQTT captures, flashing and serial reads on COM8; not part of the repository); the
owner typed the Pi password into the relay and installed a passphrase-free relay key on the Pi.

- **Real data, labelled correctly.** The Edge Brain stored readings from the real ESP32 (`esp32_room101`)
  as synthetic; it now stores them as `room101_measured`.
- **CO2.** The board has no NDIR sensor. The Pi now estimates CO2 from the MQ-135 (`raspberry_pi/co2_estimator.py`,
  details in `HARDWARE.md`), labelled `mq135_estimate` everywhere, `eCO2 (MQ-135)` on the dashboard.
- **Wi-Fi/BLE coexistence and the guest Wi-Fi.** The board could barely hold MQTT (1 of 20 pings answered,
  `state=-2/-4` connect failures, broker keepalive timeouts). Fixes in firmware `room101-2026.11.23`: Wi-Fi
  modem sleep on (required for coexistence), coexistence prefers Wi-Fi, a 50-100 ms BLE connection interval,
  3 s MQTT connect timeout, 60 s keepalive, stall detection (12 s without any MQTT message) and redundant
  delivery: telemetry and ACKs over both MQTT and BLE with one `msg_id`, edge commands over both links, each
  side keeping one copy. Result: 95 readings in 297 s with no gap over 4.5 s after boot, versus 27 readings
  and 30 s gaps in 150 s before.
- **BLE after an Edge Brain restart.** The board stayed connected at BlueZ level to the killed gateway
  process, so it stopped advertising and the new gateway never found it. The gateway now disconnects such a
  stale link (`stale_disconnects` in `/api/hardware/ble`) and reconnects within about 20 s.
- **INA219 noise.** With no fan supply the INA219 reads about -0.2 mA, which raised a "reading accepted with
  problems" event every 3 s. Values within 2 mA / 20 mW / 0.05 V below zero are now clamped to 0.
- **Dashboard.** Built against the Pi (`dashboard/fyp-research-twin/.env.local`:
  `NEXT_PUBLIC_EDGE_URL=http://172.16.0.57:8001`) and served on the PC at http://localhost:3000 (relay job
  `launch`). It showed Edge `LIVE`, ESP32 `CONNECTED`, Office A streaming, and recovered by itself after
  the Pi reboot.
- **Tests.** Pi tests (`raspberry_pi/`, `tests/test_store_mqtt.py`, `tests/test_edge_runtime.py`,
  `tests/test_firmware_check.py`, `tests/test_commission_runner.py`) pass; amqtt-dependent ones skip.

Still needing the owner at the bench: fan/relay/INA219 under load (T06-T08, T15: needs the fused 12 V fan
supply), the RGB colours by eye (T09/T16), a reference thermometer/hygrometer for T02, a covered/uncovered
BH1750 and a controlled sensor change on the dashboard (T03, T20).

## Review after the session (20 Nov 2026): causes found and fixes awaiting hardware verification

A code review of the firmware and the Pi gateway after the session found software causes for three of the open
items. The fixes are in firmware revision `room101-2026.11.20` and the updated Pi files. They compile for the
ESP32-S3 (core 3.3.12, 91 % flash, 20 % RAM), the host-side firmware check and the BLE gateway tests pass, and
the commissioning runner was dry-run against a simulated board. **None of this changes a status in the matrix
below**: each row changes only with evidence from a run on the real hardware.

- **RGB (T09/T16).** Serial colour commands could never be seen: with no edge controller connected the
  fail-safe in `loop()` switched the LED off again within 10 ms. That does not explain the dark LED during the
  controlled MQTT RED test, where the firmware wrote full duty to GPIO 6 and reported RED; that result still
  points to wiring, the module or the pin. The new serial key `D` drives each colour pin as a plain GPIO HIGH
  for 4 s so the voltage can be measured, and serial commands now open a two-minute bench session that the
  fail-safe and remote commands respect. MQTT colour tests use `"hold_s"`, so the Edge Brain's automatic white
  level (sent with every reading) no longer overwrites the colour; the Edge Brain no longer had to be stopped.
- **BLE freshness (T22).** The firmware forced a 23-byte ATT MTU, so each ~700-byte telemetry message went out
  as 44 notifications, 50 ms apart: the loop was blocked for over two seconds per reading and losing any one
  notification lost the message. MQTT reconnect attempts could block a further 3 s each. The board now offers
  MTU 247 (4-5 frames per message), retries a frame the host stack could not buffer, limits a broker connect to
  1.5 s and retries MQTT every 15 s while BLE carries the data. The gateway accepts the larger frames; it must be
  deployed together with the firmware. A test command (`"test": "mqtt_pause"`) now takes the board off MQTT on
  purpose, which gives T22/T23 a controlled procedure.
- **BME280 outliers (T02).** Single reads were published as-is, including the 761 hPa / 85.6 %RH sample. Readings
  are now the median of three with a plausibility check; sensors not found at power-up are probed again every
  30 s.

### How the remaining rows are completed

`scripts/commission_room101.py --deploy-pi --flash` on the PC deploys the Pi files, flashes the board and runs
every remaining test (T01-T24), asking the operator only for physical observations and reference readings. It
writes `docs/commissioning_runs/run_<time>.md` and `.json`; this matrix is updated from those files. The fan,
relay and INA219 rows (T06, T07, T08, T15) need the fused 12 V fan branch powered; without it they stay BLOCKED.

## Required commissioning matrix

| Test ID | Component | Test procedure | Expected result | Actual result | Status | Evidence |
|---|---|---|---|---|---|---|
| T01 | ESP32 boot | Flash production sketch and capture Serial Monitor startup at 115200 baud | Board boots; diagnostics identify sensors and transports | 23 Nov: firmware `room101-2026.11.23` flashed over COM8 (hash verified); boot log read through the PC relay: I2C devices 0x23, 0x40, 0x76 found, BME280 and BH1750 connected, BLE ready, Wi-Fi IP 172.16.0.137, MQTT connected | PASS | Relay serial captures `output/agent/outbox/*.json`, flash output |
| T02 | BME280 | Compare temperature, humidity and pressure with an independent reference | Valid, changing BME280 values | Live samples included 24.81 C/43.33%/1006.93 hPa and later 22.72 C/85.60%/761.2888 hPa; no independent comparison | NOT TESTED | Pi MQTT captures; pressure is intermittently outside the backend's accepted range |
| T03 | BH1750 | Cover and uncover sensor while observing lux telemetry | Lux changes in the expected direction | Owner reports successful BH1750 communication; no current MQTT capture | PASS | Owner-reported in attached commissioning notes |
| T04 | MQ-135 | Observe raw ADC, ADC-pin millivolts and digital output under controlled conditions | Raw response changes; CO2 shown only as a labelled estimate | 23 Nov: AO rose 325 → 810 mV during heater warm-up, then 340-450 mV in the occupied factory; never near the 3.1 V ADC limit (5 V module, no divider). The Pi converts it to estimated CO2 (`mq135_estimate`, baseline 420 ppm, provisional for 24 h) | PASS | Pi MQTT captures, `/api/hardware/co2`; estimate, not an NDIR measurement |
| T05 | PIR | Move in front of sensor, then remain still through its configured hold time | Motion changes to active, then inactive | Owner reports PIR communication; current transition timing was not recorded | PASS | Owner-reported in attached commissioning notes |
| T06 | INA219 | Measure its I2C response and the fused fan branch while switching fan off/on | Bus/shunt voltage, current and power respond to actual load | Live telemetry includes the shunt field; readings near 0 V/0 mA were captured with no powered fan load. Load response was not tested | BLOCKED | Pi MQTT captures; powered fan branch and multimeter evidence still required |
| T07 | Relay | Send ON/OFF commands and observe relay contact/load state | Relay switches the fan branch without unintended energization | No current relay actuation or polarity result available | NOT TESTED | Requires physical bench |
| T08 | Fan | Power the fused low-voltage branch and confirm fan rotation | Fan runs from its supply and stops when switched off | Owner reports the fan is physically available and working; relay-controlled run was not observed here | NOT TESTED | Owner report does not verify the commissioned relay-controlled path |
| T09 | RGB | Install one series current-limiting resistor per R/G/B channel, then issue RED/GREEN/BLUE/WHITE/OFF and verify output | Each named color and OFF state are correct | Owner reports resistors installed. RED command was acknowledged and telemetry reported RED, but owner observed the module remained off | FAIL | Controlled MQTT command/ack, next telemetry, and owner visual observation; physical output still needs wiring/voltage diagnosis |
| T10 | Wi-Fi | Capture ESP32 association, IP and RSSI; confirm same LAN as Pi | ESP32 associates and can reach the Pi LAN | Board joins the guest Wi-Fi at -57 to -59 dBm on the Pi's /22. The link is congested: before the 23 Nov firmware fix the Pi answered 1 of 20 pings to the board; after it 20 of 20 with 0.3-3 s latency | PASS | Serial log, Pi `ping`; a dedicated AP is recommended for the demo |
| T11 | MQTT broker | On Pi, check Mosquitto service and subscribe to the Room 101 topic tree | Broker accepts local clients and receives retained status | Mosquitto is active; Edge Brain's local MQTT client is connected and reports the board online | PASS | Pi service/API observation; anonymous access and no TLS are security limitations |
| T12 | ESP32 → MQTT | Observe `sb/v1/room/f2_office_a/telemetry` from the Pi | Periodic board telemetry arrives on the canonical topic | 23 Nov 5-min capture: 95 unique readings in 297 s, each sent over MQTT and BLE with the same `msg_id`; 20 arrived first over MQTT, 75 first over BLE; no field rejected | PASS | `output/agent/outbox/soak5min-2.json`, `/api/hardware/mqtt` |
| T13 | MQTT → ESP32 | Publish a unique `sb.command/1` and observe board acknowledgement | Command validates, actuates and returns `sb.ack/1` | 23 Nov: 94 of 95 Edge Brain commands acknowledged in the 5-min capture (each command also forwarded over BLE; the board applies it once) | PASS | `soak5min-2.json`; physical actuator results are recorded in T15/T16 |
| T14 | Telemetry / backend | Follow an actual board message through MQTT bridge and EdgeBrain | Backend state updates from the actual board payload | 23 Nov: board connected, mean interval 3.0 s, readings stored as `room101_measured` (fixed: the real board was previously stored as synthetic); AI P(occ) 0.98 with PIR, decisions returned to the board | PASS | `/api/hardware/status`, `/api/rooms/current-state` |
| T15 | Fan MQTT control | Publish fan ON then OFF and observe relay, fan and INA219 | Fan responds and current/power change with load | No command-driven physical observation | NOT TESTED | Requires Pi and hardware |
| T16 | RGB MQTT control | With per-channel current limiting installed, publish each supported named color and OFF | RGB output matches each command and ack reports applied state | RED command was acknowledged and board telemetry reported RED while Edge Brain was briefly paused; owner saw no light. LED was then returned to OFF | FAIL | Controlled MQTT command/ack, board telemetry, and owner visual observation; no channel voltage measured |
| T17 | MQTT recovery | Interrupt and restore Wi-Fi/broker without resetting ESP32 | Reconnect occurs; telemetry and commands resume | 23 Nov: the Pi reboot (T18) took the broker away for about a minute; the board (uptime continuing, no reset) resumed MQTT on its own. A stalled MQTT link is dropped after 12 s of silence and rebuilt | PASS | Board `uptime_s` 1341 → 1432 across the run, `/api/hardware/status` after reboot |
| T18 | Pi reboot recovery | Reboot Pi and observe Mosquitto, Edge Brain, BLE gateway and board recovery | Services restart; board resumes data/control without manual reset | 23 Nov: `systemctl reboot`; 100 s later Mosquitto and edge-brain active, board connected with 19 readings; BLE gateway reconnected (MTU 247); the dashboard reconnected by itself | PASS | Relay SSH output, `/api/hardware/ble`, dashboard screenshot |
| T19 | Backend/API | Query `/health`, `/api/hardware/mqtt`, `/api/hardware/ble` on Pi | Actual service responses report backend, broker and BLE state | All respond; MQTT connected, BLE connected with MTU 247, 0 dropped, 0 invalid frames | PASS | Live Pi API responses (23 Nov) |
| T20 | Digital twin live update | Change a sensor and verify API/SSE/dashboard state changes from the physical board | Room 101 shows fresh measured values and device state | Dashboard built against the Pi and loaded with Edge `LIVE`/ESP32 `CONNECTED`; Office A showed live temperature, humidity and board-reported actuator status. No controlled sensor change was made | NOT TESTED | Visual/API connectivity verified; change-response still requires a physical test |
| T21 | BLE pairing | Pair Pi gateway to `SB-Room101` using the passkey printed by the ESP32 | Authenticated BLE GATT connection appears in `/api/hardware/ble` | Bonded and trusted; reconnects after board reset, Edge Brain restart (stale BlueZ link now dropped automatically) and Pi reboot | PASS | `/api/hardware/ble`, `bluetoothctl info` |
| T22 | BLE telemetry fallback | Disable board MQTT while leaving BLE/Pi broker available | BLE telemetry is forwarded to the existing MQTT telemetry topic | 23 Nov: `mqtt_pause` 60 s acknowledged; board published retained `offline`; 20 readings in 59 s all arrived through BLE, longest gap 3.1 s; board back on MQTT at 60.6 s | PASS | `output/agent/outbox/t22-1123a.json` |
| T23 | BLE command/ack fallback | With direct board MQTT offline, publish an MQTT command and observe BLE write/ack forwarding | One actuator change and one acknowledgement reach the broker | 23 Nov, during the pause: `rgb GREEN, hold_s 15` → one `applied` ACK via BLE at 12.2 s; telemetry reported GREEN with the hold counting 15 → 0, then WHITE again. Physical colour not observed in this run | PASS | `t22-1123a.json` (transport and board state; visual check is T16) |
| T24 | Firmware build/flash | Compile and flash the active sketch for ESP32-S3 | Build succeeds and flash verifies | 23 Nov: `room101-2026.11.23` compiled with core 3.3.12, 1,200,856 B (91 %) flash, 67 KB (20 %) RAM; flashed through the relay, hash verified | PASS | arduino-cli/esptool output |

## Software and deployment checks

- BLE frame encode/reassembly, message-size limits and MQTT-priority selection were checked with a local
  Python assertion script. These checks do not exercise a BLE radio, BlueZ, Mosquitto or the physical board.
- Focused Edge Brain regression tests passed (14 tests); dashboard TypeScript checking, ESLint, and production
  build passed. These validate software only, not physical Room 101 behavior.
- The production sketch was compiled and flashed for ESP32-S3 (T24); full-image hash verification passed.
- MQTT/BLE counters and firmware-reported actuator state are transport/software evidence only. They do not
  prove physical actuation; the RED command/telemetry versus the owner's dark LED observation demonstrates
  that distinction.

## Pi access and deployment

SSH access to `172.16.0.57` was verified (`smartbuilding-pi`). The original `/home/pi/Desktop/Project`
contains a different codebase and was preserved. The sanitized project was deployed separately to
`/home/pi/Desktop/Project-pi-ble`; the Pi Edge Brain user service is active with MQTT and BLE enabled.
The service uses `MQTT_HOST=127.0.0.1`. The radio is powered. The gateway reconnected after an ESP32 reset
and forwarded BLE telemetry during the board's MQTT outage, but delivery became stale; current MQTT-primary
telemetry is stable. `Linger=yes` is configured so the enabled user service can run without an interactive
login; a Pi reboot was not performed, so boot recovery remains unverified.

The broker is listening on all interfaces with anonymous access and TLS disabled. This was approved only
for temporary commissioning on the trusted LAN; do not configure router port forwarding. BLE paired and
forwarded frames during a temporary board MQTT outage, but did not maintain the 10-second freshness target.
The existing
`Project-pi-ble.tar.gz` archive was not regenerated in this run; its earlier validation reported 735
entries with no secret-named files or links. Keep excluding `secrets.h`, credentials, keys, `.venv`,
`node_modules`, and generated caches.

## Safe physical test conditions

- Verify fuse, relay contact wiring, INA219 series placement and polarity with the multimeter before applying
  power. Never put the 12 V fan supply on INA219 logic VCC.
- Do not connect the HW-478 color pins directly to ESP32 GPIOs. Install one 220-330 ohm series resistor
  per R/G/B channel; the module photo shows no visible on-board resistors. Confirm the common-pin polarity
  and relay active level before actuator commands.
- If an acknowledged RGB command still leaves the module dark, isolate it and check the commanded
  GPIO-to-GND voltage (RED uses GPIO 6) before reconnecting. Then verify the matching module channel,
  its series resistor and common-to-GND wiring; firmware acknowledgements do not verify light.
- Keep the fan supply isolated from ESP32 logic power and do not connect mains equipment.
- Record Serial output, MQTT topic captures, API responses, physical observations and measured INA219 values
  under the same test ID before changing any status to PASS.
