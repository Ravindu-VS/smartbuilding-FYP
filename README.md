
# Smart Building Energy Management System

**Two Components:**
1. **ML-Based Occupancy Detection & Control** (NEW - Production Ready) ← Start here!
2. **Simulation Framework** (Digital Twin for training/testing)

---

## ML System Quickstart (60 seconds)

### Start the Occupancy Detection API

```bash
python run_api_flask.py
```

API at: **http://127.0.0.1:8001**

### Test with curl

```bash
curl -X POST http://127.0.0.1:8001/control-decision \
  -H "Content-Type: application/json" \
  -d '{"Temperature": 21.5, "Humidity": 35.0, "Light": 450.0, "CO2": 700.0, "HumidityRatio": 0.0045}'
```

Response:
```json
{
  "control_mode": "OCCUPIED",
  "light_action": "ON",
  "hvac_action": "NORMAL"
}
```

### See the Documentation

- **README_ML_API.md** - ML system API reference
- **DEPLOYMENT_GUIDE.md** - Complete deployment guide
- **PIPELINE_TRAINING_COMPLETE.md** - Model performance details

---

## Simulation Framework

A Python-based simulation framework for smart building energy management systems. This digital twin enables offline training and testing of ML/optimization methods for building energy optimization before deploying to actual hardware.

## Project Overview

**Project Title:** Design and Implementation of an Edge Intelligence Based Energy Management and Optimization System for Smart Buildings

This simulation creates realistic time-series building sensor data and models HVAC, lighting, and plug loads. It includes controllers that minimize energy consumption while maintaining occupant comfort.

## Features

- **Thermal Modeling:** 2R2C (two-resistance, two-capacitance) thermal model for realistic zone temperature dynamics
- **HVAC System:** Heating/cooling with COP, capacity limits, and proportional control
- **Lighting System:** Dimming control with daylight harvesting
- **Occupancy Patterns:** Realistic office schedules, meeting room usage, and corridor traffic
- **Weather Generation:** Synthetic weather with seasonal/daily patterns
- **Plug Loads:** Occupancy-dependent electrical loads
- **Sensor Noise:** Realistic sensor imperfections and sampling
- **Controllers:**
  - Baseline rule-based controller
  - MPC-like look-ahead controller
- **Multi-objective Optimization:** Energy, comfort, and control smoothness

## Project Structure

```
Project/
├── config.yaml              # Configuration file
├── main.py                  # Entry point
├── README.md                # This file
├── requirements.txt         # Python dependencies
├── sim/                     # Simulation modules
│   ├── __init__.py
│   ├── building.py          # Building thermal model
│   ├── hvac.py              # HVAC system
│   ├── lighting.py          # Lighting with daylight harvesting
│   ├── occupancy.py         # Occupancy pattern generator
│   ├── weather.py           # Weather generator
│   ├── loads.py             # Plug load generator
│   ├── sensors.py           # Sensor noise simulation
│   └── energy_meter.py      # Energy tracking
├── control/                 # Controllers
│   ├── __init__.py
│   ├── baseline_rule_controller.py
│   ├── mpc_controller.py
│   └── optimizer.py         # Multi-objective scoring
├── data/                    # Data generation
│   ├── __init__.py
│   └── generator.py         # Dataset CSV generation
└── output/                  # Generated outputs
    ├── logs/                # CSV logs and summaries
    └── plots/               # Visualization plots
```

## Installation

### Requirements

- Python 3.8+
- Required packages:
  - numpy
  - pyyaml
  - matplotlib

### Setup

```bash
# Clone or download the project
cd "path/to/Project"

# Install dependencies
pip install numpy pyyaml matplotlib
```

Or create a virtual environment:

```bash
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # Linux/Mac

pip install numpy pyyaml matplotlib
```

## Quick Start

### Run with Baseline Controller (30 days)

```bash
python main.py --days 30 --controller baseline
```

### Run with MPC Controller (30 days)

```bash
python main.py --days 30 --controller mpc
```

### Run with Custom Configuration

```bash
python main.py --config custom_config.yaml --days 14 --controller mpc
```

### Command Line Options

```
usage: main.py [-h] [--days DAYS] [--controller {baseline,mpc}]
               [--config CONFIG] [--quiet]

Options:
  --days DAYS           Number of days to simulate (default: from config)
  --controller TYPE     Controller type: baseline or mpc (default: baseline)
  --config PATH         Path to configuration file (default: config.yaml)
  --quiet               Suppress progress output
```

## Configuration

Edit `config.yaml` to customize the simulation:

### Key Configuration Sections

#### Simulation Settings
```yaml
simulation:
  time_step_seconds: 60    # Simulation time step
  duration_days: 30        # Default duration
  random_seed: 42          # For reproducibility
```

#### Building Zones
```yaml
building:
  zones:
    - name: "Office"
      area_m2: 200
      occupancy_max: 25
      thermal:
        R_wall: 0.004      # Thermal resistance
        C_zone: 5000000    # Thermal capacitance
```

#### Comfort Constraints
```yaml
comfort:
  temp_target_min: 22.0    # °C
  temp_target_max: 24.0    # °C
  lux_target_min: 300      # lux
  lux_target_max: 500      # lux
```

#### Controller Settings
```yaml
controller:
  baseline:
    comfort_setpoint: 23.0
    
  mpc:
    horizon_steps: 30
    candidate_setpoints: [20, 22, 23, 24, 26]
```

## Output

### CSV Log File

The simulation generates a detailed log file with columns:

| Column | Description |
|--------|-------------|
| timestamp | ISO format timestamp |
| zone_name | Zone identifier |
| zone_temperature | Measured temperature (°C) |
| outdoor_temperature | Outdoor temperature (°C) |
| occupancy | Number of occupants |
| hvac_power_w | HVAC electrical power (W) |
| lighting_power_w | Lighting power (W) |
| plug_power_w | Plug load power (W) |
| total_power_w | Total power (W) |
| hvac_setpoint | HVAC setpoint (°C) |
| dimming_level | Lighting dimming (0-1) |
| comfort_violation | Comfort penalty score |

### Summary Metrics (JSON)

```json
{
  "total_kwh": 1250.5,
  "peak_kw": 15.2,
  "comfort_violation_hours": 12.3,
  "control_switch_count": 145,
  "simulation": {
    "duration_days": 30,
    "controller_type": "baseline"
  }
}
```

### Generated Plots

- `{zone}_temperature.png` - Temperature profile with setpoints
- `{zone}_lighting.png` - Illumination and dimming control
- `building_summary.png` - Building-wide power consumption

## Building Zones

The default configuration includes three zones:

| Zone | Area | Max Occupancy | Type |
|------|------|---------------|------|
| Office | 200 m² | 25 | Open office |
| MeetingRoom | 50 m² | 12 | Conference room |
| Corridor | 80 m² | 5 | Transient space |

## Controllers

### Baseline Rule Controller

Simple rule-based control:
- **Occupied:** Maintain 23°C, 400 lux
- **Unoccupied:** Setback to 26°C (cooling) / 18°C (heating), lights off

### MPC Controller

Model Predictive Control with look-ahead:
- Simulates future building response over prediction horizon
- Evaluates discrete action candidates
- Selects actions minimizing total cost (energy + comfort + switching)

## Extending the Simulation

### Adding a New Controller

1. Create a new file in `control/`:
```python
from control.baseline_rule_controller import ControlAction

class MyController:
    def compute_all_actions(self, zone_states, outdoor_temp, daylight_lux):
        actions = {}
        for zone_name, state in zone_states.items():
            actions[zone_name] = ControlAction(
                hvac_setpoint=23.0,
                fan_on=True,
                dimming_level=0.5
            )
        return actions
```

2. Import in `main.py` and add to `setup_controller()`

### Adding a New Zone Type

1. Add zone configuration in `config.yaml`:
```yaml
zones:
  - name: "Laboratory"
    area_m2: 100
    occupancy_max: 10
    lighting_baseline_watts: 800
```

2. Define zone-specific behavior in `occupancy.py`

### Using Custom Weather Data

1. Prepare a CSV file with columns: `timestamp, temperature, solar_irradiance, humidity`
2. Update `config.yaml`:
```yaml
weather:
  mode: "csv"
  csv_path: "data/weather_data.csv"
```

## Performance

Typical runtime on a standard laptop:
- 30 days @ 60s step: ~30-60 seconds (baseline)
- 30 days @ 60s step: ~2-3 minutes (MPC)

## Use Cases

1. **ML Model Training:** Generate labeled datasets for supervised learning
2. **Reinforcement Learning:** Use as environment for RL agent training
3. **Control Algorithm Testing:** Compare different control strategies
4. **Energy Analysis:** Analyze building energy patterns
5. **Sensitivity Studies:** Test impact of parameter changes

## Example Results

### Baseline Controller (30 days)
```
Total Energy: 1250.45 kWh
Peak Power: 12.50 kW
Comfort Violation Hours: 45.2
Control Switches: 2880
```

### MPC Controller (30 days)
```
Total Energy: 1105.32 kWh (11.6% reduction)
Peak Power: 11.20 kW
Comfort Violation Hours: 18.5
Control Switches: 1420
```

## Troubleshooting

### ImportError: No module named 'yaml'
```bash
pip install pyyaml
```

### matplotlib display issues
The simulation uses a non-interactive backend by default. Plots are saved as PNG files.

### Memory issues with long simulations
For very long simulations (>365 days), consider:
- Increasing time step
- Reducing output verbosity
- Processing data in chunks

## Contributing

Feel free to extend this framework for your research:
- Add new building types
- Implement different control algorithms
- Integrate real weather data
- Add more detailed HVAC models

## License

This project is developed for educational purposes as part of a Final Year Project.

## References

- RC thermal network modeling for buildings
- Model Predictive Control for building energy systems
- Daylight harvesting strategies
- Occupancy-based demand control

---

**Author:** Final Year Project - Smart Building Energy Management  
**Date:** 2024

For questions or issues, please refer to your project supervisor.

