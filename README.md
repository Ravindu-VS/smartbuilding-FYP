# Design and Implementation of an Edge Intelligence Based Energy Management and Optimization System for Smart Buildings

**Author:** Vinusha Rathnayaka · BSc (Hons) Computer Engineering, Final Year Project

This README describes the **live system**: the edge brain (`raspberry_pi/edge_brain.py`) with
its digital twin (`twin/`), the ESP32-S3 board in Office A (`firmware/esp32_smart_building/`)
and the Next.js dashboard with the 3D digital twin (`dashboard/fyp-research-twin/`).
Everything below was checked against the code on 20 October 2026; numbers come from the runs
listed in [Measured results](#measured-results).

---

## 1. What is real and what is simulated

| Part | Real or simulated | Notes |
|---|---|---|
| Office A (`f2_office_a`, level 2) | **Real**: ESP32-S3 with BME280, BH1750, SCD41, LD2410C, INA226, MQ-2, PIR | The one real room. Values are shown only while the board is sending; with no reading for 10 s the room is **NOT CONNECTED** and shows no values. |
| The other 25 rooms (5 floors) | **Simulated** by the digital twin `twin/live.py` | Per room: the thesis's ISO 13790 5R1C thermal model, CO2 and humidity balances, daylight, weather for Colombo, stochastic occupants, sensor models (PIR, CO2, temperature, lux) with noise. |
| Occupancy estimate (AI) | Thesis method: PIR + CO2 fusion estimator (`FusionEstimator`) | Selectable alternative: the project's original Random Forest with thresholds. The simulator's true occupancy is used only for scoring and for the 3D people. |
| Control (AI ON) | Multi-objective controller `J = αE + βC + γS` (α 1, β 3, γ 0.1) over AC and lighting options, then the safety layer (rules R1–R4) | After a 7-simulated-day learning week (the thesis method), cached in `output/twin_cache`. |
| Control (AI OFF) | Conventional schedule: lights on and AC at the room's design set-point during its operating hours, same safety layer | |
| Energy of simulated rooms | Computed by the physics (AC, lighting, plug loads) | Simulated, labelled as such. |
| Energy of Office A | Measured by the INA226 on the board, kept per AI on/off segment | "not measured" when the INA226 is absent. |
| Raspberry Pi GPIO outputs | Not wired yet | `PhysicalOutputController` records outputs only (`gpio_driving: false`). |

## 2. Run it (Windows)

**One click:** double-click `run_local.bat`. It checks the Python venv and the dashboard
packages (installs them if missing), starts the edge brain on port 8001 and the Next.js
dashboard on port 3000 in their own windows, waits until both answer, opens
http://localhost:3000 and prints this PC's IP address for the ESP32's `server_url`.
`run_local.bat test` also starts the test sender (shown as TEST SENDER, never as the board).
Close the two server windows to stop everything.

**Two terminals:**

```cmd
:: Terminal 1 — edge brain (digital twin + AI + API), port 8001
cd /d "G:\projects\Final Year Project Smart Building\Project"
.venv\Scripts\python.exe raspberry_pi\edge_brain.py

:: Terminal 2 — Next.js dashboard with the 3D digital twin, port 3000
cd /d "G:\projects\Final Year Project Smart Building\Project\dashboard\fyp-research-twin"
npm run dev
```

The first start runs the AI's learning week (a simulated week, run as fast as the PC allows;
the 3D view shows its progress) and caches it in `output/twin_cache`; later starts load the cache.

| URL | What |
|---|---|
| http://localhost:3000 | Dashboard with the 3D digital twin |
| http://localhost:3000/twin3d/index.html?standalone=1 | The 3D view on its own (reads the edge brain directly) |
| http://127.0.0.1:8001/health | Edge brain health |
| http://127.0.0.1:8001/api/stream | Live SSE stream (what the dashboard uses) |

The dashboard and the 3D view need no internet: three.js is served from
`public/twin3d/vendor/three`, all textures are generated in the browser, and the page uses
system fonts. To open the dashboard from another device on the same network
(http://&lt;this PC's IP&gt;:3000), nothing is needed: this PC's addresses are allowed in
`next.config.ts`; other host names can be added with `NEXT_ALLOWED_DEV_ORIGINS=a,b`.

**Edge brain on a Raspberry Pi:** run `raspberry_pi/run_edge.sh` on the Pi, set the ESP32's
`server_url` to the Pi's address, and start the dashboard with
`set NEXT_PUBLIC_EDGE_URL=http://<pi-ip>:8001` then `npm run dev`.

Edge brain settings (environment variables): `SPEED_FACTOR` (simulated seconds per real second,
default 360), `TWIN_SEED` (7), `TWIN_WARMUP` (1 = learning week), `AI_DEFAULT`,
`TARIFF_LKR_PER_KWH` (50, an assumption), `API_HOST`/`API_PORT` (0.0.0.0:8001), `HW_TIMEOUT_S` (10),
`HW_LED_LUX_FULL`, `OUTDOOR_TEMP_C` (30, assumed for the real room).

## 3. The dashboard

- **Header:** simulated clock (pause, speed, fast-forward one hour, restart the scenario), the
  **AI CONTROL** master switch (every room, simulated and real, at once), the AI controller in use,
  edge brain and board status, and the **Viva demo** (guided scenarios).
- **KPI strip:** the building's energy meter, energy and cost with AI vs AI off, uncomfortable
  time, peak demand, lights on in empty rooms and occupancy-estimation accuracy — every figure
  for the same minutes under both modes.
- **3D digital twin** (centre) with three views — building, floor, room — described in
  [docs/twin3d.md](docs/twin3d.md): a modern five-storey building on a city site, floor
  cutaways with a card per room, and furnished room interiors with people, AC units, thermostat,
  a qualitative airflow layer, lighting and daylight, all driven by the edge brain's state.
  **Presentation** mode fills the screen; **Auto tour** flies through the building.
- **Building list** (left): floors and rooms with people, temperature, AI estimate, lights and AC.
  Click a room to select it, double-click to open it in 3D.
- **Room panel** (right): live readings, the AI's decision and why, AI on vs AI off for this room,
  scenario buttons (add people, empty it, add heat, CO2 source, open a window, overcast, heat wave).
- **Bottom panels:** the decision log, the energy meter (segments per switch position) and
  analytics. "Larger 3D view" folds them away.

## 4. AI ON vs AI OFF and the energy meter

Two copies of the simulated building run in lock-step with identical weather, occupants and
sensor noise. The **building** follows the switch; the **twin copy** always runs the other mode.
So every minute has an AI result and a conventional result for exactly the same conditions,
whatever the switch position. The meter keeps one segment per switch position (start, duration,
kWh used, what the other mode used over the same minutes, peak, discomfort). While AI is off it
keeps observing, and the room panel shows what it would do.

Office A follows the same switch: AI ON = the same estimator and controller on the board's real
readings; AI OFF = the schedule on real time. Its INA226 energy is kept per segment.

## 5. Board connection status

| Status | Rule |
|---|---|
| **CONNECTED** | A reading from the firmware (`"source": "sensor_node"`) arrived in the last `HW_TIMEOUT_S` seconds (10 s; the firmware posts every 3 s). |
| **TEST SENDER** | Same, but from `raspberry_pi/esp32_test_sender.py` (`"source": "test_sender"`). Never shown as the real board. |
| **NOT CONNECTED** | No reading since start, or the last one is older than the timeout. Office A then has no sensor values, no AI result and no decision; the 3D view shows the room empty with a red LIVE frame and "board not connected". |
| **EDGE BRAIN OFFLINE** | The dashboard is not receiving the stream (stopped or unreachable, or no message for 3 s). It reconnects by itself. |

Fields the board does not send are shown as "—"; nothing is filled in with default values.

## 6. How everything stays in sync

1. The ESP32 POSTs a reading to `/api/hardware/sensor-data`; the edge brain decides and replies
   with the actuator commands (fan PWM = AC, LED PWM = lights, servo = fresh-air damper). The same
   decision is what the dashboard shows for Office A.
2. The digital twin advances in 60-s control steps (physics step 15 s) at the chosen speed.
3. After every step and every board reading the edge brain pushes the full state on `/api/stream`.
4. The page holds **one** SSE connection. It feeds the panels and forwards each state, and once the
   building configuration, to the 3D view (`postMessage`). The 3D view has no connection of its own.
5. The 3D view reports how many of the backend's rooms it found ("3D rooms 26/26" in the footer).

## 7. Testing

```cmd
python -m pytest twin\tests raspberry_pi\test_edge_brain.py -q   :: 27 tests (pip install pytest)
python raspberry_pi\esp32_test_sender.py                         :: readings every 3 s, shown as TEST SENDER
python tests\e2e\twin_flows.py                                  :: 3D twin flows A-F in the running dashboard (Playwright)
```

Stop the test sender and Office A turns NOT CONNECTED about 10 s later.

## 8. API reference (API version 3)

| Method | Path | Use |
|---|---|---|
| POST | `/api/hardware/sensor-data` | Board reading in, decision out (only `f2_office_a`) |
| GET | `/api/hardware/status` | Board link status |
| POST | `/api/hardware/calibrate-led` | Measure the lux the board's LED adds at the BH1750 |
| GET / POST | `/api/ai` | Read / set the AI master switch `{"enabled": true}` |
| GET | `/api/meter` | Energy meter (segments, same-hour comparison, real room meter) |
| GET | `/api/stream` | SSE: full building state on every change |
| GET | `/api/rooms/current-state` | Same state, once |
| GET | `/api/building/config` | Floors and rooms (geometry used by the 3D view) |
| GET | `/api/rooms/history?room_id=…` | Recent states of a room |
| GET | `/api/timeline` | Decision log |
| GET | `/api/analytics` | AI vs AI-off results so far |
| GET | `/api/system/summary` | System part of the state |
| POST | `/api/simulation/control` | `pause`, `resume`, `speed {speed}`, `fast_forward {minutes | until, weekday}`, `reset`, `restart_comparison`, `watch` |
| POST | `/api/simulation/controller` | Choose the AI controller (`mo` or `threshold_rf`) |
| POST | `/api/scenario` | Apply / clear a demonstration scenario (applied to both copies) |
| GET | `/api/physical/outputs` | Output state per room (recorded only) |
| GET | `/health` | Health and platform |

## Measured results

From runs on 20 October 2026 on a Linux test machine (headless Chromium with software WebGL):

| What | Result |
|---|---|
| Backend tests (`twin/tests`, `raspberry_pi/test_edge_brain.py`) | 27 / 27 passed |
| One simulated weekday after the learning week (seed 7): energy, AI vs schedule | 1405 vs 1536 kWh (8.5 % less) |
| Same day: uncomfortable occupied time | 4.6 % vs 15.2 % |
| Same day: peak demand | 94 vs 147 kW |
| Same day: occupancy estimation accuracy, PIR+CO2 fusion vs Random Forest | 92 % vs 72 % |
| 3D twin interaction flows A–F of the redesign brief, automated in the real dashboard (`tests/e2e/twin_flows.py`) | 35 / 35 checks passed, no console errors or failed requests |
| Rooms matched between backend and 3D model | 26 / 26 |

Frame rates could not be measured meaningfully on the test machine (no GPU).

## 9. Known limitations

- **Simulated rooms are simulated.** Their physics follows the thesis model, but occupants,
  weather and equipment are models, not measurements; the dashboard labels them so.
- **3D furnishing and activities are a visual interpretation** of each room's type; numbers of
  people, light levels, AC states and temperatures come from the data. The airflow layer is
  qualitative (not CFD); see `docs/twin3d.md` §8.
- **Firmware changes are not compiled here.** Compile and flash in the Arduino IDE.
- **GPIO outputs on the Raspberry Pi are not wired** (`_drive_gpio` is empty).

## 10. Repository layout

| Path | What |
|---|---|
| `raspberry_pi/edge_brain.py` | Edge brain: board link, digital twin, AI switch, meter, API, SSE |
| `twin/` | Digital twin: physics (`physics.py`, `building.py`), climate, occupants, sensors, controllers, safety layer, live twin (`live.py`), the real room's controller (`hardware_room.py`); tests in `twin/tests` |
| `raspberry_pi/test_edge_brain.py` | Tests of the edge brain |
| `raspberry_pi/esp32_test_sender.py` | Test sender (not the real board) |
| `raspberry_pi/run_edge.sh`, `requirements.txt` | Running on a Raspberry Pi |
| `integration/building_config.py` | The 5 floors / 26 rooms and their geometry (single source) |
| `models/occupancy/co2/` | CO2 occupancy model used by the fusion estimator |
| `firmware/esp32_smart_building/` | ESP32-S3 firmware for Office A |
| `dashboard/fyp-research-twin/` | Next.js dashboard; `public/twin3d/` is the 3D digital twin ([docs/twin3d.md](docs/twin3d.md)); `public/3d-twin/` is the earlier 3D app, kept but no longer used |
| `run_local.bat` | Starts both on Windows |

Kept, but not used by the live system: the Docker / WSO2 / FastAPI stack (`docker-compose.yml`,
`Dockerfile`, `k8s/`, `wso2/`, `app/`, `auth/`, `edge_gateway/`, `ai/`), the older Flask server
`smart_building_api_flask.py` with `integration/*` and `hardware/`, the PPO research code
(`agents/`, `control/`, `sim/`, `main.py`), `experiments/`, and the model training and comparison
scripts (`train_*.py`, `compare_*.py`, `evaluate_*.py`).

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
