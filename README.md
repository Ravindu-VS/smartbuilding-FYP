# Design and Implementation of an Edge Intelligence Based Energy Management and Optimization System for Smart Buildings

**Author:** Vinusha Rathnayaka · BSc (Hons) Computer Engineering, Final Year Project

This README describes the **live system**: the edge brain (`raspberry_pi/edge_brain.py`),
the ESP32-S3 board in Office A (`firmware/esp32_smart_building/`) and the Next.js 3D
digital twin (`dashboard/fyp-research-twin/`). Everything below was checked against the
code on 19 October 2026; numbers are from the test runs listed in
[Measured results](#measured-results).

---

## 1. What is real and what is simulated

| Part | Real or simulated | Notes |
|---|---|---|
| Office A (`f2_office_a`, floor 3) | **Real**: ESP32-S3 with BME280, BH1750, SCD41, LD2410C, INA226, MQ-2, PIR | Values are shown only while the board is sending. With no reading for 10 s the room is shown as **NOT CONNECTED** with no values. |
| The other 25 rooms (5 floors) | **Simulated** by `EdgeSimulator` in the edge brain, 360× real time by default | Simple model: temperature drifts to the HVAC target or outdoors, a CO2 mass balance, a sinusoidal day. It gives the dashboard plausible rooms; it is not a calibrated building model. |
| Occupancy AI | Random Forest pipeline `models/final_unified_occupancy_pipeline.pkl` (median imputer, scaler, RF) | Runs on all rooms that have data, in one batch call per tick. |
| Control | Rule thresholds on the AI probability (EMPTY / STANDBY / OCCUPIED → light OFF/DIM/ON, HVAC ECO/LOW/NORMAL) | Per room-type thresholds in `ControlEngine`. |
| Power of simulated rooms | **Assumed** watts per action (e.g. HVAC NORMAL 2500 W, light ON 60 W) | Estimates, not measurements. |
| Power of Office A | Measured by the INA226 on the board, if fitted | Shown as "not measured" otherwise. |
| Raspberry Pi GPIO outputs | Not wired yet | `PhysicalOutputController` records outputs only (`gpio_driving: false`). |

## 2. Run it (Windows)

**One click:** double-click `run_local.bat` in this folder. It starts the edge brain on
port 8001, the Next.js twin on port 3000, and opens http://localhost:3000.

**Two terminals:**

```cmd
:: Terminal 1 — edge brain (simulator + AI + API), port 8001
cd /d "G:\projects\Final Year Project Smart Building\Project"
.\.venv\Scripts\activate
python raspberry_pi\edge_brain.py

:: Terminal 2 — Next.js 3D digital twin, port 3000
cd /d "G:\projects\Final Year Project Smart Building\Project\dashboard\fyp-research-twin"
npm run dev
```

| URL | What |
|---|---|
| http://localhost:3000 | 3D digital twin dashboard |
| http://127.0.0.1:8001/health | Edge brain health (model loaded, board status, platform) |
| http://127.0.0.1:8001/api/hardware/status | Board link status only |
| http://127.0.0.1:8001/api/stream | Live SSE stream (what the dashboard uses) |
| http://127.0.0.1:8001/api/system/summary | Building summary |

The dashboard and the 3D view need no internet: three.js is served from
`public/3d-twin/vendor/three` and the page uses system fonts.

**Edge brain on a Raspberry Pi:** run `raspberry_pi/run_edge.sh` on the Pi, set the ESP32's
`server_url` to the Pi's address, and start the dashboard with the Pi's address:
`set NEXT_PUBLIC_EDGE_URL=http://<pi-ip>:8001` then `npm run dev`.

Settings (environment variables of the edge brain): `SPEED_FACTOR` (default 360),
`API_PORT` (8001), `API_HOST` (0.0.0.0), `HW_TIMEOUT_S` (10), `HW_LED_LUX_FULL` (0, see §5).

## 3. Board connection status

The edge brain decides the status from the time of the last reading:

| Status on the dashboard | Rule |
|---|---|
| **CONNECTED** | A reading from the firmware (`"source": "sensor_node"`) arrived in the last `HW_TIMEOUT_S` seconds (10 s; the firmware posts every 3 s). |
| **TEST SENDER** | Same, but the readings came from `raspberry_pi/esp32_test_sender.py` (`"source": "test_sender"`). Shown in amber with a warning; never shown as the real board. |
| **NOT CONNECTED** | No reading since the edge brain started, or the last one is older than the timeout. Office A then has no sensor values, no AI result and no decision; the dashboard shows when the last reading arrived. |
| **EDGE BRAIN OFFLINE** | The dashboard is not receiving the stream (edge brain stopped or unreachable, or no message for 3 s). The 3D view shows a "not live" banner. It reconnects by itself. |

Fields the board does not send (e.g. no BME280 fitted) are shown as "—"; nothing is filled in
with default values, neither in the firmware nor in the edge brain.

## 4. How everything stays in sync

1. The ESP32 POSTs a reading to `/api/hardware/sensor-data`. The edge brain runs the model,
   decides, and replies with the decision (fan PWM, LED PWM, servo angle). The **same decision
   object** is what the dashboard shows for Office A.
2. The simulator ticks every 0.5 s (one batch model call for the 25 simulated rooms).
3. After every tick and every board reading the edge brain pushes the full state on
   `/api/stream` (SSE). A comment line is sent every 5 s when nothing changes.
4. The Next.js page holds **one** SSE connection. It feeds the side panels and forwards each
   payload to the 3D view (`postMessage`). The 3D view has no connection of its own.
5. The 3D view reports how many of the backend's rooms it found in its model; the dashboard
   shows it as "Rooms found in 3D model" (26 / 26 when the room IDs match `integration/building_config.py`).

## 5. AI and control details

- **Inputs:** Temperature, Humidity, Light, CO2, HumidityRatio (missing values are filled by the
  pipeline's median imputer).
- **No light feedback loop:** for the simulated rooms the model is given the lux the room would
  have with its own lights off (the controller knows that part). Before this change the model saw
  its own lights, predicted "occupied" and kept the lights on: in a 2-day run every simulated
  room was predicted occupied 100% of the night (true occupancy 36%).
- **Office A:** the BH1750 also sees the board's white LED. Set `HW_LED_LUX_FULL` to the lux the
  LED adds at the sensor at full brightness (measure in a dark room: LED at 255 minus LED off)
  and the edge brain subtracts it before running the model. With the default 0 nothing is
  subtracted, so keep the sensor shielded from the LED.
- **CO2 on the board:** the SCD41 (NDIR) is used when present. Without it the firmware sends an
  MQ-2 estimate (`350 + 400 × voltage`), which is not a CO2 measurement; the dashboard labels it
  "CO₂ est. (MQ-2, uncalibrated)".
- **Presence (PIR + mmWave)** is shown on the dashboard and drives the avatar in Office A, but it
  is not an input of the Random Forest.

## 6. Testing without the board

```cmd
python -m pytest raspberry_pi\test_edge_brain.py -q          :: 10 tests (pip install pytest)
python raspberry_pi\esp32_test_sender.py                      :: readings every 3 s, shown as TEST SENDER
```

Stop the test sender and Office A turns NOT CONNECTED about 10 s later.

## 7. API reference

| Method | Path | Use |
|---|---|---|
| POST | `/api/hardware/sensor-data` | Board reading in, decision out. Rejects a `room_id` other than `f2_office_a` (400). |
| GET | `/api/stream` | SSE: full building state on every change |
| GET | `/api/rooms/current-state` | Same state, once |
| GET | `/api/system/summary` | `system` part of the state |
| GET | `/api/hardware/status` | Board link status |
| GET | `/api/rooms/history?room_id=…` | Last 200 states of a room |
| POST | `/api/simulation/control` | `{"action": "reset-energy"}` (other actions return 400) |
| GET | `/api/physical/outputs` | Output state per room (recorded only) |
| GET | `/health` | Model loaded, board status, real platform name |

Board reading (what the firmware sends; all sensor fields optional):

```json
{"room_id": "f2_office_a", "source": "sensor_node",
 "temperature": 27.4, "humidity": 66.0, "pressure_hpa": 1009.0,
 "co2": 812.0, "co2_source": "scd41_ndir", "lux": 140.0, "mq2_raw": 1210,
 "motion_detected": true, "presence": true, "presence_source": "pir+mmwave",
 "measured_power_mW": 1500.0,
 "actuator_fan_speed": 0, "actuator_light_level": 80, "actuator_servo_angle": 0,
 "sensor_health": {"bme280": true, "bh1750": true, "scd41": true, "ina226": true, "ld2410c": false, "servo": true}}
```

Reply (kept under 300 bytes because the firmware parses it into a 384-byte ArduinoJson document):

```json
{"status": "ok", "room_id": "f2_office_a", "control_mode": "STANDBY",
 "occupancy_probability": 0.31, "hvac_action": "LOW", "light_action": "DIM",
 "fan_speed": 100, "light_level": 80, "servo_angle": 0}
```

## Measured results

From test runs on 19 October 2026 (Linux test machine, headless Chromium; commands in §6 and
`raspberry_pi/test_edge_brain.py`):

| What | Result |
|---|---|
| End-to-end check (no board → board → board stops → test sender → edge brain stops → restarts) | 27 / 27 checks passed |
| Board POST → SSE message with the new value | median 15 ms, max 18 ms (10 readings) |
| Board POST → value on the dashboard panel | median 22 ms, max 63 ms (10 readings; 3D view not loaded, because the test machine renders WebGL in software at ~0.2 frames/s) |
| Last reading → dashboard shows NOT CONNECTED | 10.3 s (timeout 10 s + up to one 0.5 s tick) |
| Edge brain stopped → dashboard shows EDGE BRAIN OFFLINE | under 0.1 s |
| Rooms matched between backend and 3D model | 26 / 26 |
| Edge brain tick (25 simulated rooms, one batch model call) | median 8.7 ms, 95th percentile 13.7 ms |
| AI accuracy against the simulator's true occupancy (2 simulated days, 25 rooms) | 70.1 % |

The dashboard also shows the AI accuracy live ("AI accuracy (sim. rooms)").

## 8. Known limitations

- **The Random Forest does not fit the simulated rooms well.** It was trained on UCI office data,
  where light is the strongest sign of people. In the simulator, daylight alone makes it predict
  "occupied" (87 % of daytime room-ticks predicted occupied vs 65 % truly occupied), and at night
  its probability for empty rooms sits between the thresholds, so rooms are in STANDBY (DIM light,
  LOW HVAC) about 92 % of the night. Accuracy is 70 % (base rate 64–65 %).
- **No energy-saving figure** is computed in the live demo: there is no baseline, and the
  simulated rooms' power is a fixed lookup per action, not physics.
- **The simulator is simple** (§1); outdoor weather is a sine curve, not measured weather.
- **Firmware changes are not compiled here.** The edits to `esp32_smart_building.ino` (no fallback
  values) were reviewed but not built for the board; compile and flash in the Arduino IDE.
- **Wi-Fi name and password are written in the firmware source.** Do not publish them.
- **GPIO outputs on the Raspberry Pi are not wired** (`_drive_gpio` is empty).

## 9. Repository layout

Live system:

| Path | What |
|---|---|
| `raspberry_pi/edge_brain.py` | Edge brain: simulator, model, controller, board link, API, SSE |
| `raspberry_pi/test_edge_brain.py` | Tests of the edge brain |
| `raspberry_pi/esp32_test_sender.py` | Test sender (not the real board) |
| `raspberry_pi/run_edge.sh`, `requirements.txt` | Running on a Raspberry Pi |
| `integration/building_config.py` | The 5 floors / 26 rooms (single source of room IDs) |
| `models/final_unified_occupancy_pipeline.pkl` | The model used live |
| `firmware/esp32_smart_building/` | ESP32-S3 firmware for Office A |
| `dashboard/fyp-research-twin/` | Next.js dashboard; `public/3d-twin/` is the Three.js building |
| `run_local.bat` | Starts both on Windows |

Kept, but not used by the live system: the Docker / WSO2 / FastAPI stack (`docker-compose.yml`,
`Dockerfile`, `k8s/`, `wso2/`, `app/`, `auth/`, `edge_gateway/`, `ai/`), the older Flask server
`smart_building_api_flask.py` with `integration/*` and `hardware/` (started by docker-compose),
the PPO research code (`agents/`, `control/`, `sim/`, `main.py`), `experiments/`, and the model
training and comparison scripts (`train_*.py`, `compare_*.py`, `evaluate_*.py`). The
`dashboard/3d-twin` folder that docker-compose builds no longer exists.

### Removed on 19 October 2026 (old simulations)

Panda3D app (`panda3d_simulation/`), its launcher `run_system.py`, the old simulation engine
(`simulation/`, `sensors/`, `decisions/`, `models/__init__.py`), `smart_building_api.py`,
`simulation_control_evaluator.py`, `validate_demo_readiness.py`, tests of the old stack
(`test_system.py`, `test_synchronization.py`, `test_integration.py`, `test_api.py`,
`test_evaluator.py`), the old static dashboard (`dashboard/index.html`, `style.css`,
`dashboard/archive/`), the build leftovers in `dashboard-next/`, and unused Next.js files
(`src/lib/SmartBuildingTwin.js`, the "Viva Demo Mode" that injected made-up values,
`app_backup_before_sync_rebuild.js`, template SVGs). Everything that was tracked by git is in
the commit "Snapshot of G: working tree as found on 2026-10-19" and can be restored with
`git checkout <that commit> -- <path>`.
