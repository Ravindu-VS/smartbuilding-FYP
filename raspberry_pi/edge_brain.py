"""
Edge Intelligence Brain (Raspberry Pi 4B, or a laptop during development)
=========================================================================

One process that runs the whole live system:

    ESP32-S3 (Office A, real sensors) --HTTP POST every ~3 s--> this server
    This server:
        1. Accepts the board's readings (POST /api/hardware/sensor-data) and
           answers with the control decision for the board's actuators.
        2. Simulates the other 25 rooms (EdgeSimulator, 360x real time by default).
        3. Runs the Random Forest occupancy model on every room that has data.
        4. Turns each occupancy probability into a light/HVAC action (rule thresholds).
        5. Streams one combined building state to the Next.js digital twin over SSE
           (GET /api/stream), pushed on every tick and on every board reading.

What is real and what is simulated is carried in every room record:
    source = "hardware"   -> Office A (f2_office_a). Readings come only from the ESP32.
                             If no reading has arrived within HW_TIMEOUT_S seconds the
                             room is reported as NOT CONNECTED with no sensor values.
    source = "simulated"  -> the other 25 rooms.

Usage:
    python raspberry_pi/edge_brain.py

Environment variables:
    SPEED_FACTOR     simulation speed for the 25 simulated rooms (default 360)
    API_HOST/API_PORT  listen address (default 0.0.0.0:8001)
    HW_TIMEOUT_S     seconds without a board reading before Office A is shown as
                     not connected (default 10; the firmware posts every 3 s)
    HW_LED_LUX_FULL  lux that the board's own white LED adds at the BH1750 when it is
                     at full brightness (default 0 = not calibrated, nothing subtracted).
                     Used so the occupancy model does not mistake its own light for people.
"""

import os
import sys
import json
import time
import math
import random
import logging
import platform
import threading
from datetime import datetime
from typing import Dict, List, Any, Optional
from collections import deque
from dataclasses import dataclass

# ─── Flask API ───
from flask import Flask, request, jsonify, Response

# ─── Logging ───
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("EdgeBrain")

# Ensure project root is on path for model imports
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# =============================================================================
# BUILDING CONFIGURATION — Imported from the single source of truth
# =============================================================================
# The same room IDs are used by the Next.js digital twin (public/3d-twin/app.js).

from integration.building_config import get_all_rooms, get_room_schedule

ALL_ROOMS = []
for room in get_all_rooms():
    ALL_ROOMS.append({
        "room_id": room["room_id"],
        "type": room["type"],
        "display_name": room.get("name", room["room_id"]),
        "max_occ": room.get("max_occupancy", 10),
        "floor_id": room["floor_id"],
        "floor_name": room.get("floor_name", ""),
        "data_source": room.get("data_source", "simulation"),
    })

ROOM_IDS = [r["room_id"] for r in ALL_ROOMS]

# The hardware room is the one with data_source == "hardware" in building_config
HARDWARE_ROOM = next((r for r in ALL_ROOMS if r["data_source"] == "hardware"), None)
if HARDWARE_ROOM is None:
    raise RuntimeError("building_config.py has no room with data_source='hardware'")
HARDWARE_ROOM_ID = HARDWARE_ROOM["room_id"]

HW_TIMEOUT_S = float(os.environ.get("HW_TIMEOUT_S", "10"))
HW_LED_LUX_FULL = float(os.environ.get("HW_LED_LUX_FULL", "0"))

# Artificial light that a simulated room's own ceiling lights add at its lux sensor
SIM_LIGHT_LUX = 500.0


# =============================================================================
# OCCUPANCY SCHEDULES — Uses building_config.py's authoritative schedules
# =============================================================================
def get_occupancy_probability(room_type: str, hour: float) -> float:
    """Probability that a room is occupied at this hour (hourly schedule, interpolated)."""
    h = hour % 24
    schedule = get_room_schedule(room_type)  # 24-element list from building_config
    h_int = int(h) % 24
    h_frac = h - int(h)
    p_now = schedule[h_int]
    p_next = schedule[(h_int + 1) % 24]
    return p_now + (p_next - p_now) * h_frac


# =============================================================================
# ROOM STATE — Simulated room data container
# =============================================================================
@dataclass
class SimulatedRoom:
    """Live state for a single simulated room."""
    room_id: str
    room_type: str
    floor_id: int
    display_name: str
    max_occupancy: int

    temperature: float = 23.0
    humidity: float = 50.0
    co2_ppm: float = 400.0
    light_level: float = 0.0      # what a lux sensor in the room reads (daylight + own lights)
    daylight_lux: float = 0.0     # daylight part only
    occupancy: int = 0

    light_on: bool = False
    hvac_mode: str = "off"
    hvac_speed: float = 0.0


# =============================================================================
# EDGE BUILDING SIMULATOR — Generates data for the 25 simulated rooms
# =============================================================================
class EdgeSimulator:
    """
    Lightweight building simulator. Generates sensor data for the 25 simulated rooms.
    Office A (the hardware room) is never simulated: its data comes only from the ESP32.

    The model is deliberately simple (first-order temperature drift, a CO2 mass balance,
    a sinusoidal day): it exists to give the dashboard 25 plausible rooms, not to
    predict a real building.
    """

    TICK_REF_S = 180.0  # simulated seconds per tick at the default settings (0.5 s x 360)

    def __init__(self, speed_factor: float = 360.0, seed: int = 42):
        self._rng = random.Random(seed)
        self._speed_factor = speed_factor
        self._sim_seconds = 6 * 3600  # Start at 06:00
        self._day_count = 0

        self._rooms: Dict[str, SimulatedRoom] = {}
        for room_cfg in ALL_ROOMS:
            rid = room_cfg["room_id"]
            if rid == HARDWARE_ROOM_ID:
                continue
            self._rooms[rid] = SimulatedRoom(
                room_id=rid,
                room_type=room_cfg["type"],
                floor_id=room_cfg["floor_id"],
                display_name=room_cfg["display_name"],
                max_occupancy=room_cfg["max_occ"],
                temperature=20.0 + self._rng.uniform(0, 4),
                humidity=45.0 + self._rng.uniform(0, 15),
                co2_ppm=400.0 + self._rng.uniform(0, 50),
            )

        self.outdoor_temp = 28.0
        self.outdoor_humidity = 65.0

        logger.info(f"EdgeSimulator initialized: {len(self._rooms)} simulated rooms, speed={speed_factor}x")

    @property
    def sim_hour(self) -> float:
        return (self._sim_seconds / 3600) % 24

    @property
    def day_count(self) -> int:
        return self._day_count

    def get_time_string(self) -> str:
        h = int(self.sim_hour)
        m = int((self._sim_seconds % 3600) // 60)
        return f"{h:02d}:{m:02d}:00"

    def step(self, dt_real: float):
        """Advance simulation by dt_real real-world seconds."""
        dt_sim = dt_real * self._speed_factor
        self._sim_seconds += dt_sim
        while self._sim_seconds >= 24 * 3600:
            self._sim_seconds -= 24 * 3600
            self._day_count += 1

        hour = self.sim_hour
        self.outdoor_temp = 26.0 + 6.0 * math.sin((hour - 6) * math.pi / 12)
        self.outdoor_humidity = 60.0 + 10.0 * math.cos((hour - 14) * math.pi / 12)

        for room in self._rooms.values():
            self._step_room(room, hour, dt_sim)

    def _step_room(self, room: SimulatedRoom, hour: float, dt_sim: float):
        """Step a single room's physics forward (rates scaled so any speed gives the same dynamics)."""
        k = dt_sim / self.TICK_REF_S
        noise = math.sqrt(max(k, 0.0))

        # 1. Stochastic occupancy from schedule (on average one redraw every 10 ticks at default speed)
        occ_prob = get_occupancy_probability(room.room_type, hour)
        if self._rng.random() < 1.0 - 0.9 ** k:
            room.occupancy = sum(
                1 for _ in range(room.max_occupancy)
                if self._rng.random() < occ_prob
            )

        # 2. Light level: daylight + the room's own ceiling lights
        sun_factor = max(0, math.sin((hour - 6) * math.pi / 12)) if 6 <= hour <= 18 else 0
        room.daylight_lux = max(0.0, sun_factor * 400.0 + self._rng.uniform(-10, 10))
        artificial_light = SIM_LIGHT_LUX if room.light_on else 0.0
        room.light_level = room.daylight_lux + artificial_light

        # 3. Temperature (first-order drift to the HVAC target or to outdoors, plus people)
        target_temp = 22.0 if room.hvac_mode in ["cooling", "normal"] else self.outdoor_temp
        heat_from_people = room.occupancy * 0.3
        room.temperature += (target_temp - room.temperature) * 0.01 * (dt_sim / 60.0)
        room.temperature += heat_from_people * 0.005 * (dt_sim / 60.0)
        room.temperature += self._rng.uniform(-0.1, 0.1) * noise
        room.temperature = max(15, min(40, room.temperature))

        # 4. Humidity
        room.humidity += (self.outdoor_humidity - room.humidity) * 0.002 * (dt_sim / 60.0)
        room.humidity += room.occupancy * 0.01 * k
        room.humidity += self._rng.uniform(-0.2, 0.2) * noise
        room.humidity = max(30, min(90, room.humidity))

        # 5. CO2 mass balance
        co2_gen = room.occupancy * 0.005 * 1e6 / max(1, room.max_occupancy * 35 * 1000)
        ventilation = 0.5 if room.hvac_mode != "off" else 0.15
        co2_removal = (ventilation / 3600) * (room.co2_ppm - 400.0)
        room.co2_ppm += (co2_gen - co2_removal) * dt_sim + self._rng.uniform(-2, 2) * noise
        room.co2_ppm = max(400, min(2000, room.co2_ppm))

    def get_all_simulated_states(self) -> List[Dict[str, Any]]:
        """Return all simulated room states as dicts."""
        states = []
        for room in self._rooms.values():
            hr = humidity_ratio(room.temperature, room.humidity)
            states.append({
                "room_id": room.room_id,
                "room_type": room.room_type,
                "floor_id": room.floor_id,
                "display_name": room.display_name,
                "source": "simulated",
                "sensors": {
                    "Temperature": round(room.temperature, 2),
                    "Humidity": round(room.humidity, 2),
                    "Light": round(room.light_level, 1),
                    "CO2": round(room.co2_ppm, 1),
                    "HumidityRatio": round(hr, 6),
                },
                # What the occupancy model is given: the lux sensor reading without the
                # room's own lights (the controller knows that part). Feeding the model
                # its own lights would make "lights on -> occupied -> lights on" a loop.
                "model_input": {
                    "Temperature": round(room.temperature, 2),
                    "Humidity": round(room.humidity, 2),
                    "Light": round(room.daylight_lux, 1),
                    "CO2": round(room.co2_ppm, 1),
                    "HumidityRatio": round(hr, 6),
                },
                "ground_truth": {
                    "true_occupancy": room.occupancy,
                    "max_occupancy": room.max_occupancy,
                },
                "device_state": {
                    "light_on": room.light_on,
                    "hvac_mode": room.hvac_mode,
                    "hvac_speed": room.hvac_speed,
                },
            })
        return states

    def apply_control(self, room_id: str, light_on: bool, hvac_mode: str, hvac_speed: float = 0.5):
        """Apply control decisions back into the simulation (closes the loop)."""
        if room_id in self._rooms:
            room = self._rooms[room_id]
            room.light_on = light_on
            room.hvac_mode = hvac_mode
            room.hvac_speed = hvac_speed


def humidity_ratio(temp_c: Optional[float], rh_pct: Optional[float]) -> Optional[float]:
    """Humidity ratio (kg water / kg dry air) from temperature and RH; None if either is missing."""
    if temp_c is None or rh_pct is None:
        return None
    p_sat = 610.78 * math.exp((17.27 * temp_c) / (237.7 + temp_c))
    p_w = max(0.0, min(1.0, rh_pct / 100.0)) * p_sat
    denom = 101325.0 - p_w
    if denom <= 0:
        return None
    return 0.622 * p_w / denom


# =============================================================================
# ML INFERENCE ENGINE — Loads and runs the Random Forest model
# =============================================================================
class EdgeMLEngine:
    """
    Occupancy inference with the trained sklearn pipeline
    (models/final_unified_occupancy_pipeline.pkl: median imputer, scaler, Random Forest).
    Missing inputs are passed as NaN and filled by the pipeline's imputer.
    """

    FEATURES = ['Temperature', 'Humidity', 'Light', 'CO2', 'HumidityRatio']
    MODEL_FILE = "final_unified_occupancy_pipeline.pkl"

    def __init__(self):
        self.model = None
        self.model_name = None
        self._load_model()

    def _load_model(self):
        import joblib
        model_path = os.path.join(PROJECT_ROOT, "models", self.MODEL_FILE)
        try:
            self.model = joblib.load(model_path)
            self.model_name = self.MODEL_FILE
            logger.info(f"✓ ML Model loaded from {model_path}")
        except Exception as e:
            logger.error(f"✗ Failed to load ML model: {e}")
            logger.info("  Falling back to heuristic inference (reported as model_loaded=false)")
            self.model = None

    @staticmethod
    def _value(sensor_data: Dict[str, Any], feature: str):
        val = sensor_data.get(feature)
        if val is None:
            val = sensor_data.get(feature.lower())
        if isinstance(val, bool) or val is None:
            return None
        try:
            v = float(val)
        except (TypeError, ValueError):
            return None
        return v if math.isfinite(v) else None

    def predict(self, sensor_data: Dict[str, Any]) -> Dict[str, Any]:
        return self.predict_batch([sensor_data])[0]

    def predict_batch(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Predict for several rooms in one call (one sklearn call per tick, not one per room)."""
        if not rows:
            return []
        if self.model is None:
            return [self._heuristic_predict(r) for r in rows]
        try:
            import numpy as np
            import pandas as pd
            table = [{f: (self._value(r, f) if self._value(r, f) is not None else np.nan)
                      for f in self.FEATURES} for r in rows]
            probs = self.model.predict_proba(pd.DataFrame(table, columns=self.FEATURES))
            out = []
            for p in probs:
                occ_prob = float(p[1]) if len(p) > 1 else float(p[0])
                out.append({
                    "occupancy_probability": round(occ_prob, 4),
                    "predicted_occupancy": 1 if occ_prob >= 0.5 else 0,
                    "confidence": round(max(occ_prob, 1.0 - occ_prob), 4),
                    "method": "random_forest",
                })
            return out
        except Exception as e:
            logger.warning(f"ML prediction failed: {e}, using heuristic")
            return [self._heuristic_predict(r) for r in rows]

    def _heuristic_predict(self, sensor_data: Dict[str, Any]) -> Dict[str, Any]:
        """Simple heuristic fallback if the ML model is unavailable."""
        co2 = self._value(sensor_data, "CO2")
        light = self._value(sensor_data, "Light")
        temp = self._value(sensor_data, "Temperature")
        score = 0.0
        if co2 is not None and co2 > 500: score += 0.3
        if co2 is not None and co2 > 700: score += 0.2
        if light is not None and light > 200: score += 0.2
        if temp is not None and temp > 24: score += 0.1
        return {
            "occupancy_probability": round(min(score, 0.95), 4),
            "predicted_occupancy": 1 if score >= 0.5 else 0,
            "confidence": round(max(score, 1 - score), 4),
            "method": "heuristic_fallback",
        }


# =============================================================================
# AI CONTROL DECISION ENGINE
# =============================================================================
class ControlEngine:
    """Turns an occupancy probability into light/HVAC actions with per-room-type thresholds."""

    TUNING = {
        "office":    {"empty": 0.20, "occupied": 0.60},
        "meeting":   {"empty": 0.15, "occupied": 0.55},
        "kitchen":   {"empty": 0.25, "occupied": 0.65},
        "lobby":     {"empty": 0.15, "occupied": 0.50},
        "server":    {"empty": 0.30, "occupied": 0.70},
        "executive": {"empty": 0.20, "occupied": 0.55},
        "lounge":    {"empty": 0.20, "occupied": 0.60},
        "gym":       {"empty": 0.25, "occupied": 0.65},
    }

    # Assumed power per action (watts) for the simulated rooms; not measured.
    POWER = {
        "light": {"ON": 60, "DIM": 25, "OFF": 0},
        "hvac": {"NORMAL": 2500, "LOW": 1200, "ECO": 200, "OFF": 0},
    }

    # PWM mapping for the ESP32 actuators
    FAN_PWM = {"NORMAL": 180, "LOW": 100, "ECO": 0, "OFF": 0, "HIGH": 255, "MEDIUM": 180}
    LED_PWM = {"ON": 255, "DIM": 80, "OFF": 0, "LOW": 64, "MEDIUM": 160, "HIGH": 255}

    def decide(self, room_type: str, ai_result: Dict, room_state: Dict = None) -> Dict[str, Any]:
        thresholds = self.TUNING.get(room_type, {"empty": 0.20, "occupied": 0.60})
        prob = ai_result["occupancy_probability"]

        if prob < thresholds["empty"]:
            light_action, hvac_action, control_mode = "OFF", "ECO", "EMPTY"
        elif prob < thresholds["occupied"]:
            light_action, hvac_action, control_mode = "DIM", "LOW", "STANDBY"
        else:
            light_action, hvac_action, control_mode = "ON", "NORMAL", "OCCUPIED"

        power_w = self.POWER["light"][light_action] + self.POWER["hvac"][hvac_action]
        fan_speed = self.FAN_PWM.get(hvac_action, 0)
        light_level = self.LED_PWM.get(light_action, 0)

        # Servo ventilation damper: open when CO2 is high, the room is occupied and
        # the temperature allows natural ventilation (only with a real CO2 reading).
        servo_angle = 0
        if room_state:
            sensors = room_state.get("sensors", {})
            co2 = sensors.get("CO2")
            temp = sensors.get("Temperature")
            if co2 is not None and temp is not None and co2 > 800 and 18 <= temp <= 28 \
                    and prob >= thresholds["occupied"]:
                servo_angle = min(90, max(0, int((co2 - 800) * 90 / 400)))
                if servo_angle > 30:
                    fan_speed = max(0, fan_speed - 60)

        return {
            "light_action": light_action,
            "hvac_action": hvac_action,
            "control_mode": control_mode,
            "estimated_power_watts": power_w,
            "fan_speed": fan_speed,
            "light_level": light_level,
            "servo_angle": servo_angle,
        }


# =============================================================================
# ENERGY TRACKER
# =============================================================================
class EnergyTracker:
    """Cumulative energy per room (Wh)."""

    def __init__(self):
        self._cumulative_wh: Dict[str, float] = {}

    def update(self, room_id: str, power_watts: float, dt_seconds: float):
        self._cumulative_wh[room_id] = self._cumulative_wh.get(room_id, 0.0) + power_watts * (dt_seconds / 3600.0)

    def get(self, room_id: str) -> float:
        return self._cumulative_wh.get(room_id, 0.0)

    def get_total(self, exclude: Optional[str] = None) -> float:
        return sum(v for k, v in self._cumulative_wh.items() if k != exclude)

    def reset(self):
        self._cumulative_wh.clear()


# =============================================================================
# PHYSICAL OUTPUT CONTROLLER (GPIO)
# =============================================================================
class PhysicalOutputController:
    """
    Records the output state per room. On a Raspberry Pi with RPi.GPIO installed it
    sets up GPIO, but no pin mapping is configured yet (_drive_gpio is empty), so no
    pin is driven: this is reported as gpio_driving=false.
    """

    def __init__(self):
        self._is_pi = False
        self._gpio = None
        self._output_states: Dict[str, Dict[str, Any]] = {}
        try:
            import RPi.GPIO as GPIO
            self._gpio = GPIO
            self._gpio.setmode(GPIO.BCM)
            self._gpio.setwarnings(False)
            self._is_pi = True
            logger.info("ℹ RPi.GPIO available, but no pin mapping is configured: outputs are recorded only")
        except (ImportError, RuntimeError):
            logger.info("ℹ Not running on a Raspberry Pi: outputs are recorded only")

    @property
    def gpio_driving(self) -> bool:
        return False  # set True once _drive_gpio has a real wiring map

    def update_room(self, room_id: str, control: Dict[str, Any]):
        self._output_states[room_id] = {
            "light": control.get("light_action", "OFF"),
            "hvac": control.get("hvac_action", "ECO"),
            "mode": control.get("control_mode", "EMPTY"),
            "power": control.get("estimated_power_watts", 0),
        }
        if self._is_pi:
            self._drive_gpio(room_id, control)

    def clear_room(self, room_id: str):
        self._output_states.pop(room_id, None)

    def _drive_gpio(self, room_id: str, control: Dict):
        """Drive actual GPIO pins. Add your wiring map here (see physical_output.py)."""
        pass

    def get_all_states(self) -> Dict[str, Dict]:
        return dict(self._output_states)

    def cleanup(self):
        if self._is_pi and self._gpio:
            self._gpio.cleanup()


# =============================================================================
# HARDWARE PAYLOAD PARSING
# =============================================================================
def _num(payload: Dict[str, Any], key: str) -> Optional[float]:
    """A finite number from the payload, or None if missing/invalid (never a default value)."""
    val = payload.get(key)
    if val is None or isinstance(val, bool):
        return None
    try:
        v = float(val)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _int(payload: Dict[str, Any], key: str) -> Optional[int]:
    v = _num(payload, key)
    return int(round(v)) if v is not None else None


def _bool(payload: Dict[str, Any], key: str) -> Optional[bool]:
    val = payload.get(key)
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)) and val in (0, 1):
        return bool(val)
    return None


def _round(v: Optional[float], nd: int) -> Optional[float]:
    return round(v, nd) if v is not None else None


# =============================================================================
# MAIN EDGE BRAIN — Orchestrator
# =============================================================================
class EdgeBrain:
    """
    Orchestrates the simulator, the model, the controller, the energy tracker, the
    board link (Office A) and the state that is streamed to the dashboard.
    """

    def __init__(self, speed_factor: float = 360.0):
        self._lock = threading.Lock()
        self._changed = threading.Condition()   # notified on every tick and board reading
        self._seq = 0
        self._started_mono = time.monotonic()
        self._started_iso = datetime.now().isoformat(timespec="seconds")

        self.simulator = EdgeSimulator(speed_factor=speed_factor)
        self.ml_engine = EdgeMLEngine()
        self.control_engine = ControlEngine()
        self.energy_tracker = EnergyTracker()
        self.physical_output = PhysicalOutputController()

        # Board link (Office A)
        self._hw_last_rx_mono: Optional[float] = None
        self._hw_last_rx_iso: Optional[str] = None
        self._hw_rx_count = 0
        self._hw_intervals: deque = deque(maxlen=20)
        self._hw_reading: Optional[Dict[str, Any]] = None   # last parsed reading + decision
        self._hw_sender: Optional[str] = None               # payload "source" of the last reading
        self._hw_last_power_w: Optional[float] = None

        # Building state (26 rooms) and history
        self._building_state: Dict[str, Dict[str, Any]] = {}
        self._history: Dict[str, deque] = {}
        self._max_history = 200

        # Model accuracy against the simulator's true occupancy (simulated rooms only)
        self._acc_correct = 0
        self._acc_total = 0

        self._tick_count = 0
        self._last_tick_mono: Optional[float] = None
        self._update_interval = 0.5  # seconds between ticks
        self._speed_factor = speed_factor

        logger.info("✓ EdgeBrain initialized")
        logger.info(f"  Speed factor: {speed_factor}x  |  board timeout: {HW_TIMEOUT_S:.0f} s")
        logger.info(f"  Rooms: 1 hardware ({HARDWARE_ROOM_ID}) + {len(self.simulator._rooms)} simulated = {len(ALL_ROOMS)}")

    # ─── change notification (SSE) ───
    @property
    def seq(self) -> int:
        return self._seq

    def _notify(self):
        with self._changed:
            self._seq += 1
            self._changed.notify_all()

    def wait_for_change(self, last_seq: int, timeout: float) -> int:
        with self._changed:
            self._changed.wait_for(lambda: self._seq != last_seq, timeout=timeout)
            return self._seq

    # ─── board link ───
    def hardware_status(self, now_mono: Optional[float] = None) -> Dict[str, Any]:
        now_mono = time.monotonic() if now_mono is None else now_mono
        if self._hw_last_rx_mono is None:
            state, age = "never_connected", None
        else:
            age = now_mono - self._hw_last_rx_mono
            state = "connected" if age <= HW_TIMEOUT_S else "lost"
        mean_interval = (sum(self._hw_intervals) / len(self._hw_intervals)) if self._hw_intervals else None
        if self._hw_sender is None:
            sender = None
        elif self._hw_sender == "sensor_node":
            sender = "esp32_board"           # what the firmware sends as "source"
        else:
            sender = str(self._hw_sender)    # e.g. "test_sender": not the real board
        return {
            "room_id": HARDWARE_ROOM_ID,
            "connected": state == "connected",
            "state": state,
            "sender": sender,
            "real_board": sender == "esp32_board",
            "last_seen": self._hw_last_rx_iso,
            "age_s": round(age, 2) if age is not None else None,
            "timeout_s": HW_TIMEOUT_S,
            "readings_received": self._hw_rx_count,
            "mean_interval_s": round(mean_interval, 2) if mean_interval is not None else None,
        }

    def inject_hardware_data(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Accept one reading from the ESP32 (Office A) and return the control decision.
        The same decision object is what the dashboard shows for Office A.
        Fields that the board did not send stay None (shown as missing), never a default.
        """
        now_mono = time.monotonic()
        now_iso = datetime.now().isoformat(timespec="milliseconds")

        temp = _num(payload, "temperature")
        hum = _num(payload, "humidity")
        co2 = _num(payload, "co2")
        lux = _num(payload, "lux")
        pressure_hpa = _num(payload, "pressure_hpa")
        co2_source = payload.get("co2_source") if co2 is not None else None
        pir = _bool(payload, "motion_detected")
        presence = _bool(payload, "presence")
        if presence is None:
            presence = pir
        actuator_fan = _int(payload, "actuator_fan_speed")
        actuator_light = _int(payload, "actuator_light_level")
        actuator_servo = _int(payload, "actuator_servo_angle")
        power_mw = _num(payload, "measured_power_mW")
        power_w = power_mw / 1000.0 if power_mw is not None else None

        hr = humidity_ratio(temp, hum)
        sensors = {
            "Temperature": _round(temp, 2),
            "Humidity": _round(hum, 2),
            "Light": _round(lux, 1),
            "CO2": _round(co2, 1),
            "HumidityRatio": _round(hr, 6),
            "CO2_source": co2_source,
            "Pressure_hPa": _round(pressure_hpa, 1),
            "MQ2_raw": _int(payload, "mq2_raw"),
        }
        scd41_temp = _num(payload, "scd41_temp")
        scd41_hum = _num(payload, "scd41_humidity")
        if scd41_temp is not None:
            sensors["SCD41_Temperature"] = round(scd41_temp, 2)
        if scd41_hum is not None:
            sensors["SCD41_Humidity"] = round(scd41_hum, 2)

        # Model input: the lux reading minus what the board's own LED adds (if calibrated)
        model_lux = lux
        if lux is not None and HW_LED_LUX_FULL > 0 and actuator_light is not None:
            model_lux = max(0.0, lux - HW_LED_LUX_FULL * max(0, min(255, actuator_light)) / 255.0)
        model_input = {"Temperature": temp, "Humidity": hum, "Light": model_lux, "CO2": co2, "HumidityRatio": hr}

        ai_result = self.ml_engine.predict(model_input)
        control = self.control_engine.decide(HARDWARE_ROOM["type"], ai_result, {"sensors": sensors})
        control["estimated_power_watts"] = None   # the board's power is measured, not estimated

        reading = {
            "received_at": now_iso,
            "sensors": sensors,
            "model_input": {k: _round(v, 6 if k == "HumidityRatio" else 1) for k, v in model_input.items()},
            "presence": {
                "pir_motion": pir,
                "mmwave_presence": _bool(payload, "mmwave_presence"),
                "mmwave_moving": _bool(payload, "mmwave_moving"),
                "mmwave_stationary": _bool(payload, "mmwave_stationary"),
                "mmwave_distance_cm": _int(payload, "mmwave_distance_cm"),
                "fused_presence": presence,
                "source": payload.get("presence_source"),
            },
            # What the board reports it is currently doing (applied before this reading)
            "device_state": {
                "light_on": (actuator_light > 0) if actuator_light is not None else None,
                "hvac_mode": ("on" if actuator_fan > 0 else "off") if actuator_fan is not None else None,
                "hvac_speed": actuator_fan,
                "light_level": actuator_light,
                "servo_angle": actuator_servo,
            },
            "power_measurement": {
                "voltage_v": _num(payload, "measured_voltage_v"),
                "current_mA": _num(payload, "measured_current_mA"),
                "power_mW": power_mw,
                "available": power_mw is not None,
            },
            "sensor_health": payload.get("sensor_health") if isinstance(payload.get("sensor_health"), dict) else {},
            "ai": ai_result,
            "control": control,
        }

        with self._lock:
            if self._hw_last_rx_mono is not None:
                gap = now_mono - self._hw_last_rx_mono
                self._hw_intervals.append(gap)
                # Measured energy: trapezoid between consecutive readings (real time)
                if gap <= HW_TIMEOUT_S and power_w is not None and self._hw_last_power_w is not None:
                    self.energy_tracker.update(HARDWARE_ROOM_ID, (power_w + self._hw_last_power_w) / 2.0, gap)
            self._hw_last_power_w = power_w
            self._hw_last_rx_mono = now_mono
            self._hw_last_rx_iso = now_iso
            self._hw_rx_count += 1
            self._hw_sender = payload.get("source") if isinstance(payload.get("source"), str) else "unknown"
            self._hw_reading = reading
            room_state = self._hardware_room_state(now_mono)
            self._building_state[HARDWARE_ROOM_ID] = room_state
            self._append_history(HARDWARE_ROOM_ID, room_state)
        self.physical_output.update_room(HARDWARE_ROOM_ID, control)
        self._notify()

        logger.info(
            f"HARDWARE {HARDWARE_ROOM_ID}: T={temp} Lux={lux} CO2={co2}({co2_source}) Pres={presence} "
            f"-> OccProb={ai_result['occupancy_probability']:.2f} -> {control['control_mode']} "
            f"(Fan={control['fan_speed']} Light={control['light_level']} Servo={control['servo_angle']})"
        )

        return {
            "hvac_action": control["hvac_action"],
            "light_action": control["light_action"],
            "control_mode": control["control_mode"],
            "occupancy_probability": ai_result["occupancy_probability"],
            "fan_speed": control["fan_speed"],
            "light_level": control["light_level"],
            "servo_angle": control["servo_angle"],
        }

    def _hardware_room_state(self, now_mono: Optional[float] = None) -> Dict[str, Any]:
        """Office A as the dashboard should show it: live values only while the board is connected."""
        status = self.hardware_status(now_mono)
        base = {
            "room_id": HARDWARE_ROOM_ID,
            "room_type": HARDWARE_ROOM["type"],
            "floor_id": HARDWARE_ROOM["floor_id"],
            "display_name": HARDWARE_ROOM["display_name"],
            "source": "hardware",
            "hardware": status,
            "timestamp": self._hw_last_rx_iso,
        }
        r = self._hw_reading
        if not status["connected"] or r is None:
            base.update({
                "sensors": {k: None for k in ("Temperature", "Humidity", "Light", "CO2", "HumidityRatio")},
                "ai": None,
                "control": None,
                "device_state": None,
                "energy": None,
                "presence": None,
                "power_measurement": None,
                "sensor_health": None,
                "ground_truth": None,
            })
            return base
        pm = r["power_measurement"]
        base.update({
            "sensors": dict(r["sensors"]),
            "model_input": dict(r["model_input"]),
            "presence": dict(r["presence"]),
            "device_state": dict(r["device_state"]),
            "power_measurement": dict(pm),
            "sensor_health": dict(r["sensor_health"]),
            "ai": dict(r["ai"]),
            "control": dict(r["control"]),
            "energy": {
                "measured_power_watts": round(pm["power_mW"] / 1000.0, 3) if pm["available"] else None,
                "cumulative_energy_wh": round(self.energy_tracker.get(HARDWARE_ROOM_ID), 4) if pm["available"] else None,
                "estimated_power_watts": None,
            },
            "ground_truth": None,   # a real room has no ground truth; presence is a sensor reading
        })
        return base

    def _append_history(self, room_id: str, room_state: Dict[str, Any]):
        if room_id not in self._history:
            self._history[room_id] = deque(maxlen=self._max_history)
        ai = room_state.get("ai") or {}
        energy = room_state.get("energy") or {}
        self._history[room_id].append({
            "timestamp": room_state.get("timestamp"),
            "occupancy_probability": ai.get("occupancy_probability"),
            "predicted_occupancy": ai.get("predicted_occupancy"),
            "true_occupancy": (room_state.get("ground_truth") or {}).get("true_occupancy"),
            "power_watts": energy.get("estimated_power_watts", energy.get("measured_power_watts")),
            "temperature": (room_state.get("sensors") or {}).get("Temperature"),
        })

    # ─── simulation tick ───
    def tick(self):
        """
        One update cycle: step the 25 simulated rooms, predict occupancy (one batch call),
        decide, apply the decisions back to the simulator, refresh Office A's link status,
        then notify the stream.
        """
        self._tick_count += 1
        dt = self._update_interval
        dt_sim = dt * self._speed_factor

        self.simulator.step(dt)
        sim_states = self.simulator.get_all_simulated_states()
        ai_results = self.ml_engine.predict_batch([s["model_input"] for s in sim_states])
        sim_time = self.simulator.get_time_string()

        new_states = {}
        for room_state, ai_result in zip(sim_states, ai_results):
            room_id = room_state["room_id"]
            control = self.control_engine.decide(room_state["room_type"], ai_result)
            room_state["ai"] = ai_result
            room_state["control"] = control

            self.energy_tracker.update(room_id, control["estimated_power_watts"], dt_sim)
            room_state["energy"] = {
                "estimated_power_watts": control["estimated_power_watts"],
                "cumulative_energy_wh": round(self.energy_tracker.get(room_id), 2),
            }

            light_on = control["light_action"] != "OFF"
            hvac_map = {"NORMAL": "cooling", "LOW": "fan_only", "ECO": "off", "OFF": "off"}
            self.simulator.apply_control(room_id, light_on, hvac_map.get(control["hvac_action"], "off"))
            self.physical_output.update_room(room_id, control)

            truth = room_state["ground_truth"]["true_occupancy"] > 0
            self._acc_total += 1
            self._acc_correct += int(truth == (ai_result["predicted_occupancy"] == 1))

            room_state["timestamp"] = sim_time
            new_states[room_id] = room_state

        now_mono = time.monotonic()
        with self._lock:
            for room_id, room_state in new_states.items():
                self._building_state[room_id] = room_state
                self._append_history(room_id, room_state)
            hw_state = self._hardware_room_state(now_mono)
            self._building_state[HARDWARE_ROOM_ID] = hw_state
            self._last_tick_mono = now_mono
        if not hw_state["hardware"]["connected"]:
            self.physical_output.clear_room(HARDWARE_ROOM_ID)
        self._notify()

        if self._tick_count % 30 == 0:
            s = self.get_current_state()["system"]
            logger.info(
                f"Tick #{self._tick_count} | Sim time: {sim_time} | "
                f"Predicted occupied: {s['occupied_rooms']}/{s['rooms_with_data']} | "
                f"Sim power (est.): {s['sim_estimated_power_watts']:.0f} W | "
                f"Board: {s['hardware']['state']}"
            )

    def get_current_state(self) -> Dict[str, Any]:
        """The complete building state streamed to the dashboard."""
        now_mono = time.monotonic()
        with self._lock:
            # Refresh Office A so a board that stopped posting shows as not connected at once
            self._building_state[HARDWARE_ROOM_ID] = self._hardware_room_state(now_mono)
            rooms = [dict(r) for r in self._building_state.values()]
            last_tick = self._last_tick_mono
        hw = self.hardware_status(now_mono)

        sim_rooms = [r for r in rooms if r.get("source") == "simulated"]
        with_data = [r for r in rooms if r.get("ai")]
        occupied = sum(1 for r in with_data if r["ai"].get("predicted_occupancy") == 1)
        sim_power = sum((r.get("energy") or {}).get("estimated_power_watts") or 0 for r in sim_rooms)
        hw_room = next((r for r in rooms if r.get("room_id") == HARDWARE_ROOM_ID), None)
        hw_power = ((hw_room or {}).get("energy") or {}).get("measured_power_watts")
        tick_age = (now_mono - last_tick) if last_tick is not None else None

        return {
            "timestamp": datetime.now().isoformat(timespec="milliseconds"),
            "seq": self._seq,
            "rooms": rooms,
            "hardware": hw,
            "system": {
                "total_rooms": len(ALL_ROOMS),
                "simulated_rooms": len(self.simulator._rooms),
                "hardware_room_id": HARDWARE_ROOM_ID,
                "rooms_with_data": len(with_data),
                "occupied_rooms": occupied,
                "empty_rooms": len(with_data) - occupied,
                "sim_estimated_power_watts": round(sim_power, 1),
                "sim_cumulative_energy_wh": round(self.energy_tracker.get_total(exclude=HARDWARE_ROOM_ID), 2),
                "hardware_measured_power_watts": hw_power,
                "model_loaded": self.ml_engine.model is not None,
                "model_name": self.ml_engine.model_name,
                "controller": "rule thresholds on the model's occupancy probability",
                "ai_accuracy_simulated": {
                    "accuracy": round(self._acc_correct / self._acc_total, 4) if self._acc_total else None,
                    "room_ticks": self._acc_total,
                    "reference": "simulator true occupancy (simulated rooms only)",
                },
                "simulation_running": tick_age is not None and tick_age <= 3 * self._update_interval,
                "simulation_time": self.simulator.get_time_string() if last_tick is not None else None,
                "simulation_speed_factor": self._speed_factor,
                "day_count": self.simulator.day_count,
                "outdoor_temp_c": round(self.simulator.outdoor_temp, 1),
                "outdoor_humidity": round(self.simulator.outdoor_humidity, 1),
                "update_interval": self._update_interval,
                "last_tick_age_s": round(tick_age, 3) if tick_age is not None else None,
                "data_stale": tick_age is None or tick_age > 3 * self._update_interval,
                "gpio_driving": self.physical_output.gpio_driving,
                "started_at": self._started_iso,
                "hardware": hw,
            },
            "physical_outputs": self.physical_output.get_all_states(),
        }

    def get_room_history(self, room_id: str) -> List[Dict]:
        with self._lock:
            if room_id in self._history:
                return list(self._history[room_id])
        return []


# =============================================================================
# FLASK API — Serves both ESP32 hardware and Digital Twin dashboard
# =============================================================================
app = Flask(__name__)
brain: Optional[EdgeBrain] = None


@app.after_request
def add_cors(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS'
    return response


@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status": "healthy",
        "message": "Edge Intelligence Brain",
        "model_loaded": brain.ml_engine.model is not None if brain else False,
        "simulation_running": bool(brain and brain.get_current_state()["system"]["simulation_running"]),
        "hardware": brain.hardware_status() if brain else None,
        "platform": f"{platform.system()} {platform.machine()} (Python {platform.python_version()})",
        "host": platform.node(),
    })


@app.route('/api/hardware/sensor-data', methods=['POST'])
def receive_sensor_data():
    """ESP32 POSTs its readings here and gets the control decision back."""
    try:
        payload = request.get_json(force=True, silent=True)
        if not isinstance(payload, dict) or not payload:
            return jsonify({"error": "Expected a JSON object"}), 400
        room_id = payload.get("room_id")
        if room_id is not None and room_id != HARDWARE_ROOM_ID:
            return jsonify({"error": f"This server takes readings for room '{HARDWARE_ROOM_ID}', got '{room_id}'"}), 400

        decision = brain.inject_hardware_data(payload)

        # Keep this reply small: the firmware parses it into a 384-byte ArduinoJson document.
        return jsonify({
            "status": "ok",
            "room_id": HARDWARE_ROOM_ID,
            "hvac_action": decision["hvac_action"],
            "light_action": decision["light_action"],
            "control_mode": decision["control_mode"],
            "occupancy_probability": decision["occupancy_probability"],
            "fan_speed": decision["fan_speed"],
            "light_level": decision["light_level"],
            "servo_angle": decision["servo_angle"],
        }), 200

    except Exception as e:
        logger.error(f"Hardware endpoint error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/api/hardware/status', methods=['GET'])
def hardware_status():
    return jsonify(brain.hardware_status())


@app.route('/api/rooms/current-state', methods=['GET'])
def get_current_state():
    return jsonify(brain.get_current_state())


@app.route('/api/stream', methods=['GET'])
def sse_stream():
    """
    Server-Sent Events stream for the digital twin. A full state is pushed as soon
    as anything changes (every simulation tick and every board reading), with a
    comment line every 5 s when nothing changes so dead connections are noticed.
    """
    def generate():
        last_seq = -1
        while True:
            try:
                seq = brain.wait_for_change(last_seq, timeout=5.0)
                if seq == last_seq:
                    yield ": keepalive\n\n"
                    continue
                last_seq = seq
                data = json.dumps(brain.get_current_state(), default=str)
                yield f"id: {seq}\ndata: {data}\n\n"
            except GeneratorExit:
                break
            except Exception as e:
                logger.error(f"SSE error: {e}")
                time.sleep(1)

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
        }
    )


@app.route('/api/system/summary', methods=['GET'])
def system_summary():
    return jsonify(brain.get_current_state().get("system", {}))


@app.route('/api/rooms/history', methods=['GET'])
def room_history():
    room_id = request.args.get('room_id')
    if room_id:
        return jsonify({room_id: brain.get_room_history(room_id)})
    return jsonify({rid: brain.get_room_history(rid) for rid in ROOM_IDS})


@app.route('/api/simulation/control', methods=['POST'])
def simulation_control():
    """Simulation control. Only 'reset-energy' is supported."""
    data = request.get_json(force=True, silent=True) or {}
    action = data.get("action", "")
    if action == "reset-energy":
        brain.energy_tracker.reset()
        return jsonify({"status": "ok", "message": "Energy counters reset"})
    return jsonify({"status": "error", "message": f"Unsupported action '{action}' (supported: reset-energy)"}), 400


@app.route('/api/physical/outputs', methods=['GET'])
def physical_outputs():
    """Output state per room (recorded; see gpio_driving in /api/system/summary)."""
    return jsonify(brain.physical_output.get_all_states())


# =============================================================================
# BACKGROUND TICK LOOP
# =============================================================================
def run_tick_loop(brain_instance: EdgeBrain, stop_event: threading.Event):
    """Runs the simulation + ML + control loop at a fixed rate."""
    logger.info("[>] Edge Brain tick loop started")
    next_t = time.monotonic()
    while not stop_event.is_set():
        try:
            brain_instance.tick()
        except Exception as e:
            logger.error(f"Tick error: {e}", exc_info=True)
        next_t += brain_instance._update_interval
        delay = next_t - time.monotonic()
        if delay < 0:          # running behind (slow machine): don't try to catch up
            next_t = time.monotonic()
            delay = 0
        stop_event.wait(delay)
    logger.info("[■] Edge Brain tick loop stopped")


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================
def main():
    global brain

    logger.info("═══════════════════════════════════════════════════")
    logger.info("  EDGE INTELLIGENCE BRAIN")
    logger.info(f"  Running on {platform.system()} {platform.machine()}")
    logger.info("═══════════════════════════════════════════════════")

    speed = float(os.environ.get("SPEED_FACTOR", "360"))
    brain = EdgeBrain(speed_factor=speed)

    stop_event = threading.Event()
    tick_thread = threading.Thread(
        target=run_tick_loop,
        args=(brain, stop_event),
        daemon=True,
        name="EdgeBrainTickLoop",
    )
    tick_thread.start()

    port = int(os.environ.get("API_PORT", "8001"))
    host = os.environ.get("API_HOST", "0.0.0.0")

    logger.info(f"Starting API on {host}:{port}")
    logger.info(f"  ESP32 endpoint: POST http://<this machine's IP>:{port}/api/hardware/sensor-data")
    logger.info(f"  SSE stream:     GET  http://<this machine's IP>:{port}/api/stream")
    logger.info(f"  Health check:   GET  http://<this machine's IP>:{port}/health")

    try:
        app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        brain.physical_output.cleanup()
        logger.info("Edge Brain shutdown complete.")


if __name__ == "__main__":
    main()
