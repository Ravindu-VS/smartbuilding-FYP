"""
Integration Configuration

Central configuration for the real-time integration layer.
Contains room mappings, energy parameters, control tuning, and system defaults.
"""

from typing import Dict, Any
import math
import os

# =============================================================================
# ENVIRONMENT CONFIGURATION
# =============================================================================
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_USER = os.getenv("POSTGRES_USER", "admin")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "adminpassword")
POSTGRES_DB = os.getenv("POSTGRES_DB", "smartbuilding")

WSO2_AM_URL = os.getenv("WSO2_AM_URL", "https://localhost:8243")
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")

# =============================================================================
# ROOM MAPPING
# =============================================================================
# Maps simulation engine integer room IDs to dashboard-friendly string IDs.
# The simulation engine (simulation/engine.py) uses int IDs from room_config.json.

ROOM_ID_MAP: Dict[int, str] = {
    0: "office_1",
    1: "kitchen_1",
    2: "meeting_room_1",
    3: "bathroom_1",
}

# Reverse mapping: string ID -> int ID
ROOM_ID_REVERSE: Dict[str, int] = {v: k for k, v in ROOM_ID_MAP.items()}

# Room type mapping (from simulation zone_type to dashboard room_type)
ROOM_TYPE_MAP: Dict[str, str] = {
    "office": "office",
    "kitchen": "kitchen",
    "meeting": "meeting_room",
    "bathroom": "bathroom",
}

# Display names for dashboard
ROOM_DISPLAY_NAMES: Dict[str, str] = {
    "office_1": "Office A",
    "kitchen_1": "Kitchen",
    "meeting_room_1": "Meeting Room",
    "bathroom_1": "Bathroom",
}

# =============================================================================
# ENERGY ESTIMATION PARAMETERS (Watts)
# =============================================================================

ENERGY_PARAMS: Dict[str, Dict[str, float]] = {
    # Lighting power by action state
    "lights": {
        "OFF": 5.0,       # Standby power (indicator LEDs, etc.)
        "DIM": 80.0,      # Dimmed lighting
        "ON": 200.0,      # Full lighting
    },
    # HVAC power by action state
    "hvac": {
        "ECO": 50.0,      # Eco / minimal ventilation
        "OFF": 10.0,      # Standby
        "LOW": 150.0,     # Low-speed conditioning
        "NORMAL": 350.0,  # Full conditioning
    },
    # Base plug loads per room type (always-on equipment)
    "base_load": {
        "office": 80.0,       # Computers, monitors
        "kitchen": 120.0,     # Refrigerator, etc.
        "meeting_room": 50.0, # Projector standby, etc.
        "bathroom": 30.0,     # Exhaust fan, etc.
    },
}

# Room-type energy multipliers (some rooms use more energy than others)
ROOM_ENERGY_MULTIPLIER: Dict[str, float] = {
    "office": 1.0,
    "kitchen": 1.2,       # Kitchen appliances add overhead
    "meeting_room": 0.9,  # Usually simpler setup
    "bathroom": 0.6,      # Smaller space, less equipment
}

# =============================================================================
# CONTROL TUNING (Room-aware thresholds)
# =============================================================================
# These modify the SmartBuildingController thresholds per room type.
# The base controller uses: EMPTY < 0.20, STANDBY [0.20, 0.60), OCCUPIED >= 0.60

ROOM_CONTROL_TUNING: Dict[str, Dict[str, Any]] = {
    "office": {
        "empty_threshold": 0.20,
        "occupied_threshold": 0.60,
        "description": "Balanced comfort and energy savings",
    },
    "kitchen": {
        "empty_threshold": 0.15,     # More tolerant of irregular occupancy
        "occupied_threshold": 0.50,
        "description": "Tolerates irregular occupancy patterns",
    },
    "meeting_room": {
        "empty_threshold": 0.25,     # React strongly to occupied periods
        "occupied_threshold": 0.55,
        "description": "Strong reaction to occupied periods",
    },
    "bathroom": {
        "empty_threshold": 0.10,     # Prioritize short occupancy events
        "occupied_threshold": 0.40,
        "description": "Prioritizes short occupancy events and lights",
    },
}

# =============================================================================
# BATHROOM OCCUPANCY SCHEDULE
# =============================================================================
# Custom schedule parameters for bathrooms (short, intermittent events)
BATHROOM_OCCUPANCY_SCHEDULE = {
    "start_hour": 7,
    "peak_hour": 10,
    "end_hour": 19,
    "evening_start": 19,
    "evening_peak": 0.05,
    "peak_occupancy": 0.25,  # Bathrooms are rarely fully occupied
}

# Kitchen occupancy schedule (irregular bursts around meal times)
KITCHEN_OCCUPANCY_SCHEDULE = {
    "start_hour": 7,
    "peak_hour": 12,      # Lunch peak
    "end_hour": 14,
    "evening_start": 18,
    "evening_peak": 0.1,
    "peak_occupancy": 0.7,
}

# =============================================================================
# SYSTEM DEFAULTS & DEMO MODE
# =============================================================================

# Enable fast-day visualization mode
DEMO_MODE = False

# Simulation speed factor (how fast simulation time advances)
# Normal: 60.0 means 1 real second = 1 simulation minute
# Demo: 720.0 means 1 real second = 12 simulation minutes (2 min per day)
SIMULATION_SPEED_FACTOR = 720.0 if DEMO_MODE else 60.0

# Update interval in seconds for the live loop
# Faster in demo mode to keep UI feeling smooth
DEFAULT_UPDATE_INTERVAL = 0.5 if DEMO_MODE else 2.0

# Maximum history buffer size per room (number of data points to keep in memory)
MAX_HISTORY_POINTS = 300

# Flask API port
API_PORT = 8001

# API host (0.0.0.0 allows incoming connections from ESP32 on WiFi network)
API_HOST = "0.0.0.0"

# Model path (relative to project root)
MODEL_PATH = "models/final_unified_occupancy_pipeline.pkl"

# CSV log directory for persistence
OUTPUT_DIR = "output"
LOG_DIR = "output/integration_logs"

# Auto-open the dashboard in the default browser on startup
AUTO_OPEN_BROWSER = False

# Dashboard URL (computed from host/port)
DASHBOARD_URL = f"http://{API_HOST}:{API_PORT}/3d-twin"

# =============================================================================
# TWO-WAY IPC CONFIGURATION (Panda3D ↔ Backend)
# =============================================================================

# Direction 1: Simulation → Backend (Panda3D writes engine state)
SHARED_STATE_FILE = "output/.sim_state.json"

# Direction 2: Backend → Simulation (Backend writes control actions)
SHARED_CONTROL_FILE = "output/.control_actions.json"

# Stale timeout: how old a shared file can be before it's considered disconnected
SHARED_STATE_STALE_TIMEOUT = 5.0  # seconds

# Reconnection interval: how often the backend retries reading a missing state file
RECONNECT_INTERVAL = 3.0  # seconds

# Panda3D write throttle: minimum interval between state file writes
SIM_STATE_WRITE_INTERVAL = 0.1  # seconds (10 Hz max write rate)

# =============================================================================
# ENERGY OPTIMIZER — BASELINE vs AI COMPARISON
# =============================================================================
# Baseline mode = "always on" worst case (lights ON, HVAC NORMAL for every room)
BASELINE_LIGHT_ACTION = "ON"
BASELINE_HVAC_ACTION = "NORMAL"

# =============================================================================
# CENTRALIZED LOGGING
# =============================================================================
SYSTEM_LOG_FILE = "output/logs/system.log"
EVENT_LOG_MAX_SIZE = 200  # ring buffer capacity for dashboard event panel

# =============================================================================
# CONTROL FEEDBACK MAPPING (ML Controller → Simulation Engine)
# =============================================================================
# Maps ML controller light_action to simulation engine light_on state
LIGHT_ACTION_TO_SIM: Dict[str, bool] = {
    "ON": True,
    "DIM": True,      # DIM still means lights are on (at reduced level)
    "OFF": False,
}

# Maps ML controller hvac_action to simulation engine hvac_mode + hvac_speed
HVAC_ACTION_TO_SIM: Dict[str, Dict[str, Any]] = {
    "NORMAL": {"hvac_mode": "heating", "hvac_speed": 0.8},
    "LOW":    {"hvac_mode": "fan_only", "hvac_speed": 0.3},
    "ECO":    {"hvac_mode": "off", "hvac_speed": 0.0},
    "OFF":    {"hvac_mode": "off", "hvac_speed": 0.0},
}

# =============================================================================
# HUMIDITY RATIO COMPUTATION
# =============================================================================

def compute_humidity_ratio(temperature_c: float, relative_humidity_pct: float,
                           pressure_pa: float = 101325.0) -> float:
    """
    Compute humidity ratio (kg water / kg dry air) from temperature and
    relative humidity using the simulation's humidity sensor data.

    Uses the Magnus formula for saturation vapor pressure.

    Args:
        temperature_c: Air temperature in Celsius
        relative_humidity_pct: Relative humidity in percent (0-100)
        pressure_pa: Atmospheric pressure in Pascals (default: 101325 Pa)

    Returns:
        Humidity ratio (dimensionless, typically 0.001 - 0.02)
    """
    # Magnus formula coefficients
    a = 17.27
    b = 237.7  # °C

    # Saturation vapor pressure (Pa)
    p_sat = 610.78 * math.exp((a * temperature_c) / (b + temperature_c))

    # Actual vapor pressure
    rh_fraction = max(0.0, min(1.0, relative_humidity_pct / 100.0))
    p_w = rh_fraction * p_sat

    # Humidity ratio: W = 0.622 * Pw / (P - Pw)
    denominator = pressure_pa - p_w
    if denominator <= 0:
        return 0.01  # Fallback for edge cases

    humidity_ratio = 0.622 * p_w / denominator
    return round(humidity_ratio, 6)
