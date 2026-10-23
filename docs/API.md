# Edge brain API (v3)

Base URL `http://<edge>:8001`. JSON everywhere; units are stated in field names (`_c` degC, `_pct` %,
`_w` W, `_wh` Wh, `_kwh` kWh, `_ppm`, `_s` seconds) or in a `units` object. Errors: HTTP 400 with
`{"error": "..."}` for invalid input, 403 when an admin token is required, 409 when a model fails its
acceptance tests, 503 when an optional service (the store) is not configured. Set `ADMIN_TOKEN` to require
`X-Admin-Token` on model promotion and rollback.

## State and streaming

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | liveness, version, host |
| GET | `/api/stream` | Server-Sent Events: the full building state on every change (`seq` increases) |
| GET | `/api/rooms/current-state` | the same state once |
| GET | `/api/system/summary` | system block of the state |
| GET | `/api/building/config` | floors, 26 rooms (geometry, `room_number`, data source), controllers with availability, scenarios |

Room objects in the state carry `room_number` (101-126), `source` (`simulated` / `hardware`), `provenance`
(per value group: `synthetic`, `room101_measured`, `prediction`, `unavailable`), `prediction`
(`temperature_30min` from the thermal model, simulated rooms) and, for the real room, `hardware`
(connected / lost / never_connected, age, timeout) and `freshness`. A disconnected board's room has every
sensor value `null` - never a default.

## Simulation control

| Method | Path | Body |
|---|---|---|
| POST | `/api/simulation/control` | `{"action": "pause" \| "resume" \| "speed" (speed) \| "fast_forward" (minutes or until "HH:MM") \| "reset" (seed?, controller?) \| "restart_comparison" \| "watch" (room_id)}` |
| POST | `/api/simulation/controller` | `{"controller": "mo" \| "threshold_rf" \| "ppo"}` - `ppo` only once an approved policy exists |
| POST | `/api/ai` | `{"enabled": true \| false}` the AI master switch (GET reads it) |
| POST | `/api/scenario` | `{"kind": occupancy \| heat_gain \| co2 \| window \| heat_wave \| overcast, "room_id", "value", "minutes"}` or `{"action": "clear"}` |
| GET | `/api/meter` | same-period energy meter (AI vs conventional) |
| GET | `/api/analytics` | comparison, series, meter |
| GET | `/api/timeline` | `?after&room_id&limit&kinds` decision/event timeline (in memory) |
| GET | `/api/rooms/history` | `?room_id` recent in-memory history |

## Hardware

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/hardware/sensor-data` | a board's reading (firmware payload, see docs/HARDWARE.md); reply = that room's decision (< 300 bytes for the firmware's JSON buffer) |
| GET | `/api/hardware/status` | link status of every real room |
| POST | `/api/hardware/calibrate-led` | measure the LED's lux contribution |
| GET | `/api/hardware/mqtt` | MQTT bridge status (connected, counters, pending acks, rejections) or `{"enabled": false}` |
| GET | `/api/physical/outputs` | GPIO output state on the Pi |

## Persistence, provenance, models, experiments

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/history` | `?room_id&since&until&limit&table=room_snapshots\|readings\|decisions\|predictions` persisted history (SQLite) |
| GET | `/api/events` | `?limit&kind` persisted events (falls back to the in-memory timeline without a store) |
| GET | `/api/provenance` | provenance classes, each room's data source, weather source, store counts by provenance, datasets |
| GET | `/api/datasets` | `data/manifest.json` |
| GET | `/api/models` | registry status (active versions, candidates, last event), live models (shadow / active), shadow comparison, live thermal MAE, drift reports, controller availability |
| POST | `/api/models/promote` | `{"task", "version"}` - runs the acceptance tests; 409 with the report if they fail |
| POST | `/api/models/rollback` | `{"task", "reason"?}` - back to the previously active version |
| GET | `/api/experiments` | experiments with their `status.json` |
