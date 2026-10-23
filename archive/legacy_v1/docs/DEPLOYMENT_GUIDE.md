# Smart Building Digital Twin — Complete System Guide

## Overview

A production-ready real-time digital twin system combining simulation, machine learning, REST API, and interactive dashboard for smart building automation.

**Architecture**: Simulation → Sensors → ML Model → Controller → Feedback → API → Dashboard

## Quick Start (One Command)

```bash
python run_system.py
```

Opens dashboard at: http://127.0.0.1:8001/dashboard

## What's Running

| Component | Port | Function |
|-----------|------|----------|
| **Flask API** | 8001 | Serves live data and control endpoints |
| **Dashboard** | 8001 | Interactive web UI (real-time charts) |
| **Simulation** | - | Headless building simulation (4 rooms) |
| **ML Pipeline** | - | Occupancy inference (background thread) |
| **State Manager** | - | Runs ML→control→energy pipeline continuously |

## System Architecture

```
┌─────────────────────────────────────────────────────┐
│                   SIMULATION ENGINE                  │
│  • 4 rooms: office, kitchen, meeting room, bathroom │
│  • Thermal model (2R2C physics)                      │
│  • Sensor simulation (temp, humidity, CO2, light)    │
│  • Occupancy schedule injection                      │
│  • 60x time acceleration                             │
└┬────────────────────────────────────────────────────┘
 │ Room states + sensor data every tick
 ▼
┌─────────────────────────────────────────────────────┐
│                   STATE MANAGER                      │
│  • ML Inference (occupancy probability)              │
│  • Control Decision (3-zone: EMPTY/STANDBY/OCCUPIED)│
│  • Energy Estimation (per-room + building total)    │
│  • Metrics & Analytics Tracking                      │
│  • Database Persistence                             │
└┬────────────────────────────────────────────────────┘
 │ Decisions apply back to simulation (closed-loop)
 ▼
┌─────────────────────────────────────────────────────┐
│                   FLASK REST API                     │
│  • /api/system/live - current state (rooms + system)│
│  • /api/metrics - performance metrics               │
│  • /api/analytics - accuracy & anomalies            │
│  • /api/data/export - historical export (CSV)       │
│  • /api/stream (SSE) - live updates to dashboard    │
└┬────────────────────────────────────────────────────┘
 │ WebSocket/Polling
 ▼
┌─────────────────────────────────────────────────────┐
│                WEB DASHBOARD                         │
│  • Building overview (occupied, power, energy)       │
│  • Room cards (sensors, predictions, controls)       │
│  • Live charts (occupancy, CO2, power, energy)      │
│  • System status (model loaded, API, simulation)    │
│  • Controls (pause/resume, interval, reset)         │
└─────────────────────────────────────────────────────┘
```

## Core Technologies

- **Backend**: Flask (Python)
- **Simulation**: SimulationEngine (thermal + occupancy)
- **ML Model**: Scikit-learn (logistic regression pipeline)
- **Frontend**: HTML5 + JavaScript + Chart.js
- **Data**: SQLite (persistent storage)

## Configuration

All settings in `integration/config.py`:

```python
# Room mapping
ROOM_ID_MAP = {0: "office_1", 1: "kitchen_1", ...}

# Control thresholds (room-aware)
ROOM_CONTROL_TUNING = {
    "office": {"empty_threshold": 0.20, "occupied_threshold": 0.60},
    "kitchen": {"empty_threshold": 0.15, "occupied_threshold": 0.50},
    ...
}

# Energy parameters (Watts)
ENERGY_PARAMS = {
    "lights": {"OFF": 5.0, "DIM": 80.0, "ON": 200.0},
    "hvac": {"ECO": 50.0, "LOW": 150.0, "NORMAL": 350.0},
}

DEFAULT_UPDATE_INTERVAL = 2.0  # seconds
API_PORT = 8001
API_HOST = "127.0.0.1"
```

## Command-Line Options

```bash
python run_system.py [OPTIONS]

Options:
  --port PORT              API server port (default: 8001)
  --interval SECS          Update interval (default: 2.0)
  --no-browser             Don't auto-open dashboard
  --no-csv                 Disable CSV logging
```

Examples:
```bash
# Custom port
python run_system.py --port 9000

# Faster updates (1 second)
python run_system.py --interval 1.0

# Silent mode (no browser)
python run_system.py --no-browser
```

## API Endpoints

### System & Monitoring

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | System health check |
| GET | `/api/system/live` | Current state (rooms + summary) |
| GET | `/api/system/summary` | Building summary (power, energy, occupancy) |
| GET | `/api/metrics` | Performance metrics (timing, accuracy) |
| GET | `/api/anomalies` | Detected system anomalies |
| GET | `/api/analytics` | Full analytics report |

### Rooms & History

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/rooms/current-state` | All 4 rooms with full state |
| GET | `/api/rooms/history?room_id=office_1` | History buffer for room |

### ML Inference & Control

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/predict-occupancy` | Get occupancy probability from sensor data |
| POST | `/control-decision` | Get control action from sensor data |
| POST | `/batch-occupancy` | Batch predictions |
| POST | `/batch-control` | Batch control decisions |

### Data & Admin

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/data/export` | Export data to CSV |
| POST | `/api/simulation/control` | Pause/resume/reset simulation |
| GET | `/api/database/stats` | Database statistics |

### Streaming

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/stream` | Server-Sent Events (real-time data Push) |

## Dashboard Features

### Building Overview
- Total rooms and occupancy count
- Total power (Watts)
- Cumulative energy (Wh / kWh)
- AI model and API status

### Room Cards (x4)
Each room shows:
- Room name and type
- Occupancy probability gauge
- Predicted vs. true occupancy
- Control mode badge (EMPTY / STANDBY / OCCUPIED)
- Light & HVAC actions
- Sensor readings:
  - Temperature (°C)
  - Humidity (%)
  - CO₂ (ppm)
  - Light (lux)
  - Humidity ratio
- Power (W) and cumulative energy (Wh)

### Live Charts
- **Occupancy Probability**: All 4 rooms over time
- **CO₂ Levels**: All 4 rooms
- **Power Usage**: Per-room power consumption
- **Cumulative Energy**: Building-wide energy

### System Status
- AI model health
- API status
- Simulation running
- Connection status
- Last update time

###Controls
- **Pause / Resume**: Stop/start simulation
- **Update Interval Slider**: 0.5s - 10s
- **Data Source Toggle**: SSE stream vs. polling
- **Reset Energy**: Clear cumulative counters

## Data Flow Example

```
Tick 1:
1. Simulation steps 2 seconds forward
2. Four rooms read sensors:
   - office_1:   T=21.5°C, H=35%, Light=450lux, CO2=700ppm
   - kitchen_1:  T=22.0°C, H=45%, Light=350lux, CO2=650ppm
   - meeting_1:  T=20.8°C, H=38%, Light=300lux, CO2=600ppm
   - bathroom_1: T=21.2°C, H=52%, Light=150lux, CO2=580ppm

3. State manager processes each room:
   a. Occupancy inference:
      - office_1: probability=0.78 → OCCUPIED
      - kitchen_1: probability=0.45 → STANDBY
      - meeting_1: probability=0.32 → STANDBY
      - bathroom_1: probability=0.15 → EMPTY

   b. Control decisions (room-aware):
      - office_1: OCCUPIED → Light=ON, HVAC=NORMAL
      - kitchen_1: STANDBY → Light=DIM, HVAC=LOW
      - meeting_1: STANDBY → Light=DIM, HVAC=LOW
      - bathroom_1: EMPTY → Light=OFF, HVAC=ECO

   c. Feedback applied to simulation:
      - office_1: light_on=True, hvac_mode="heating"
      - kitchen_1: light_on=True(dim), hvac_mode="fan_only"
      - meeting_1: light_on=True(dim), hvac_mode="fan_only"
      - bathroom_1: light_on=False, hvac_mode="off"

   d. Energy estimation:
      - office_1: 630W (lights 200W + HVAC 350W + base 80W)
      - kitchen_1: 255W (lights 80W + HVAC 150W + base 25W)
      - meeting_1: 230W (lights 80W + HVAC 150W + base 0W)
      - bathroom_1: 95W (lights 5W + HVAC 10W + base 80W)
      - TOTAL: 1210W

4. State saved to database and API:
   - State: {"rooms": [...], "system": {"total_power_watts": 1210, ...}}

5. Dashboard updated:
   - Charts add new data point
   - Room cards refresh
   - Power gauge updates to 1210W
```

## Testing

### Offline (No Server)
```bash
python test_system.py
```
Verifies: ML, controller, simulation bridge, state manager, closed-loop feedback, energy

### Online (With Server)
```bash
# Terminal 1
python run_system.py

# Terminal 2
python test_system.py --with-api
```
Verifies: All above + API endpoints + dashboard serving

## Performance Expectations

| Metric | Target | Typical |
|--------|--------|---------|
| Tick cycle | <100ms | 20-50ms |
| ML inference | <50ms per room | 10-20ms |
| API response | <50ms | 10-30ms |
| Dashboard update | ~2s (configurable) | <1s |
| Occupancy accuracy | >80% (trained) | 75-95% |

## Database

Auto-created SQLite database at `output/smart_building.db` stores:
- **metrics**: Per-tick performance data
- **occupancy_records**: Predictions vs. ground truth
- **energy_records**: Power and cumulative energy
- **system_events**: Startup/shutdown events
- **anomalies**: Detected anomalies

Access via API endpoint: `GET /api/database/stats`

## File Structure

```
project/
├── run_system.py                      # Main launcher
├── integration/
│   ├── config.py                      # Central configuration
│   ├── state_manager.py              # ML pipeline executor
│   ├── simulation_bridge.py           # Sim → JSON adapter
│   ├── live_update_service.py         # Background loop
│   ├── energy_estimator.py            # Power calculations
│   ├── metrics_tracker.py             # Performance monitoring
│   ├── advanced_analytics.py          # Analytics & anomalies
│   └── database_persistence.py        # SQLite storage
├── smart_building_api_flask.py        # Flask REST API
├── smart_building_controller.py       # 3-zone controller
├── occupancy_inference_service.py     # ML wrapper
├── simulation/
│   └── engine.py                      # Headless simulation
├── dashboard/
│   ├── index.html                     # Dashboard UI (SSE/polling)
│   ├── app.js                        # Real-time client logic
│   └── style.css                     # Dark theme styling
├── models/
│   └── domain_adapted_occupancy_pipeline.pkl  # Trained model
├── test_system.py                     # Verification tests
└── docs/
    ├── openapi_generator.py           # OpenAPI spec
    └── DEPLOYMENT_GUIDE.md            # This file
```

## Troubleshooting

### System won't start
```bash
python test_system.py  # Check offline tests first
```

### Low dashboard update rate
```bash
python run_system.py --interval 0.5  # Faster updates (more CPU)
```

### High CPU usage
```bash
python run_system.py --interval 5.0  # Slower updates (less CPU)
```

### Dashboard not reflecting sim changes
- Check API health: `curl http://127.0.0.1:8001/health`
- Check live data: `curl http://127.0.0.1:8001/api/system/live`
- Check browser console for errors (F12)

### ML predictions seem wrong
```bash
# Test model directly
curl -X POST http://127.0.0.1:8001/predict-occupancy \
  -H "Content-Type: application/json" \
  -d '{"Temperature": 21.5, "Humidity": 35, "Light": 450, "CO2": 700, "HumidityRatio": 0.0045}'
```

## Production Deployment

For production use, consider:

1. **WSGI Server**: Use Gunicorn instead of Flask development server
   ```bash
   gunicorn -w 4 -b 0.0.0.0:8001 smart_building_api_flask:app
   ```

2. **Database Backup**: Regular SQLite backups
   ```bash
   cp output/smart_building.db output/smart_building_$(date +%Y%m%d).db
   ```

3. **Monitoring**: Export metrics and ingest into Prometheus/Grafana

4. **SSL**: Use Nginx reverse proxy with SSL/TLS

5. **API Rate Limiting**: Implement per-client rate limits

6. **Logging**: Send logs to centralized ELK or Splunk

## Advanced Features

### Room-Specific Control Tuning
Edit `ROOM_CONTROL_TUNING` in `config.py` to adjust thresholds per room type

### Custom Energy Model
Override `EnergyEstimator` in `energy_estimator.py` for actual device specs

### Predictive Analytics
Use data exported via `/api/data/export` to train forecasting models

### Multi-Building Deployment
Modify `run_system.py` to instantiate multiple SimulationBridge instances

## Support & Documentation

- **API Spec**: /api/ (index) or use OpenAPI generator
- **Dashboard Help**: (F1 in dashboard when built out)
- **Test Suite**: `python test_system.py --with-api`

## License & Attribution

Final Year Project - Smart Building Digital Twin
Based on domain-adapted ML model and Panda3D simulation engine.
