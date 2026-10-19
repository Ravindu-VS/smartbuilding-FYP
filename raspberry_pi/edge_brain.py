"""
Raspberry Pi 4B Edge Intelligence Brain
========================================

Central edge intelligence system for the Smart Building prototype.
Runs on the Raspberry Pi 4B as the single edge computing node.

Architecture:
    ESP32-S3 (Room 101 Sensors) --HTTP POST--> Raspberry Pi 4B
    Raspberry Pi 4B:
        1. Receives real sensor data from ESP32 (Room 101)
        2. Runs MultiFloorSimulator for Rooms 102-308 (simulated)
        3. Merges real + simulated into a unified 26-room building state
        4. Runs Random Forest ML inference on ALL 26 rooms independently
        5. Makes independent HVAC/Lighting/Energy decisions per room
        6. Drives physical GPIO outputs (LEDs/motors) for demonstration
        7. Streams unified state via SSE to the Digital Twin dashboard

Usage (on the Raspberry Pi):
    python edge_brain.py

The Digital Twin dashboard runs on a laptop and connects to:
    http://<pi_ip>:8001/api/stream
"""

import os
import sys
import json
import time
import math
import random
import logging
import threading
from datetime import datetime
from typing import Dict, List, Any, Optional
from collections import deque
from dataclasses import dataclass, field

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
# This imports the EXACT same room IDs that the Digital Twin frontend uses.
# Any room added/removed in building_config.py is automatically reflected here.

from integration.building_config import (
    BUILDING_CONFIG, get_all_rooms, get_room_schedule,
    get_room_control_tuning, SCHEDULE_MAP,
)

# Build flat room list from building_config
ALL_ROOMS = []
for room in get_all_rooms():
    ALL_ROOMS.append({
        "room_id": room["room_id"],
        "type": room["type"],
        "display_name": room.get("name", room["room_id"]),
        "max_occ": room.get("max_occupancy", 10),
        "floor_id": room["floor_id"],
        "data_source": room.get("data_source", "simulation"),
    })

ROOM_IDS = [r["room_id"] for r in ALL_ROOMS]

# The hardware room is the one with data_source == "hardware" in building_config
HARDWARE_ROOM_ID = next(
    (r["room_id"] for r in ALL_ROOMS if r["data_source"] == "hardware"),
    "f2_office_a"  # Default fallback
)


# =============================================================================
# OCCUPANCY SCHEDULES — Uses building_config.py's authoritative schedules
# =============================================================================
def get_occupancy_probability(room_type: str, hour: float) -> float:
    """Return probability that a room is occupied at this hour.
    Uses the hourly schedule arrays from building_config.py."""
    h = hour % 24
    schedule = get_room_schedule(room_type)  # 24-element list from building_config
    h_int = int(h) % 24
    h_frac = h - int(h)
    # Linear interpolation between hourly bins
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
    light_level: float = 0.0
    occupancy: int = 0

    light_on: bool = False
    hvac_mode: str = "off"
    hvac_speed: float = 0.0


# =============================================================================
# EDGE BUILDING SIMULATOR — Generates simulated data for rooms 102-308
# =============================================================================
class EdgeSimulator:
    """
    Lightweight building simulator that runs on the Raspberry Pi.
    Generates realistic sensor data for the 25 simulated rooms.
    Room 101's state comes from the ESP32 hardware.
    """

    def __init__(self, speed_factor: float = 360.0, seed: int = 42):
        self._rng = random.Random(seed)
        self._speed_factor = speed_factor
        self._sim_seconds = 6 * 3600  # Start at 06:00
        self._day_count = 0

        # Initialize all simulated rooms (excluding hardware room)
        self._rooms: Dict[str, SimulatedRoom] = {}
        for room_cfg in ALL_ROOMS:
            rid = room_cfg["room_id"]
            if rid == HARDWARE_ROOM_ID:
                continue  # Room 101 comes from ESP32
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

        # Outdoor weather (simple sinusoidal model)
        self._outdoor_temp = 28.0
        self._outdoor_humidity = 65.0

        logger.info(f"EdgeSimulator initialized: {len(self._rooms)} simulated rooms, speed={speed_factor}x")

    @property
    def sim_hour(self) -> float:
        return (self._sim_seconds / 3600) % 24

    def get_time_string(self) -> str:
        h = int(self.sim_hour)
        m = int((self._sim_seconds % 3600) // 60)
        return f"{h:02d}:{m:02d}:00"

    def step(self, dt_real: float):
        """Advance simulation by dt_real real-world seconds."""
        dt_sim = dt_real * self._speed_factor
        self._sim_seconds += dt_sim

        # Day rollover
        if self._sim_seconds >= 24 * 3600:
            while self._sim_seconds >= 24 * 3600:
                self._sim_seconds -= 24 * 3600
                self._day_count += 1

        hour = self.sim_hour

        # Update outdoor conditions (sinusoidal day/night)
        self._outdoor_temp = 26.0 + 6.0 * math.sin((hour - 6) * math.pi / 12)
        self._outdoor_humidity = 60.0 + 10.0 * math.cos((hour - 14) * math.pi / 12)

        # Update each simulated room
        for room in self._rooms.values():
            self._step_room(room, hour, dt_sim)

    def _step_room(self, room: SimulatedRoom, hour: float, dt_sim: float):
        """Step a single room's physics forward."""
        # 1. Stochastic occupancy from schedule
        occ_prob = get_occupancy_probability(room.room_type, hour)
        if self._rng.random() < 0.1:  # 10% chance of change per tick
            room.occupancy = sum(
                1 for _ in range(room.max_occupancy)
                if self._rng.random() < occ_prob
            )

        # 2. Light level (natural + artificial)
        sun_factor = max(0, math.sin((hour - 6) * math.pi / 12)) if 6 <= hour <= 18 else 0
        natural_light = sun_factor * 400.0
        artificial_light = 500.0 if room.light_on else 0.0
        room.light_level = natural_light + artificial_light + self._rng.uniform(-10, 10)

        # 3. Temperature (simplified thermal model)
        target_temp = 22.0 if room.hvac_mode in ["cooling", "normal"] else self._outdoor_temp
        heat_from_people = room.occupancy * 0.3
        room.temperature += (target_temp - room.temperature) * 0.01 * (dt_sim / 60.0)
        room.temperature += heat_from_people * 0.005 * (dt_sim / 60.0)
        room.temperature += self._rng.uniform(-0.1, 0.1)
        room.temperature = max(15, min(40, room.temperature))

        # 4. Humidity
        room.humidity += (self._outdoor_humidity - room.humidity) * 0.002 * (dt_sim / 60.0)
        room.humidity += room.occupancy * 0.01
        room.humidity += self._rng.uniform(-0.2, 0.2)
        room.humidity = max(30, min(90, room.humidity))

        # 5. CO2
        co2_gen = room.occupancy * 0.005 * 1e6 / max(1, room.max_occupancy * 35 * 1000)
        ventilation = 0.5 if room.hvac_mode != "off" else 0.15
        co2_removal = (ventilation / 3600) * (room.co2_ppm - 400.0)
        room.co2_ppm += (co2_gen - co2_removal) * dt_sim + self._rng.uniform(-2, 2)
        room.co2_ppm = max(400, min(2000, room.co2_ppm))

    def get_all_simulated_states(self) -> List[Dict[str, Any]]:
        """Return all simulated room states as dicts."""
        states = []
        for room in self._rooms.values():
            hr = self._compute_humidity_ratio(room.temperature, room.humidity)
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
        """Apply AI control decisions back into the simulation."""
        if room_id in self._rooms:
            room = self._rooms[room_id]
            room.light_on = light_on
            room.hvac_mode = hvac_mode
            room.hvac_speed = hvac_speed

    @staticmethod
    def _compute_humidity_ratio(temp_c: float, rh_pct: float) -> float:
        a, b = 17.27, 237.7
        p_sat = 610.78 * math.exp((a * temp_c) / (b + temp_c))
        rh_frac = max(0, min(1, rh_pct / 100))
        p_w = rh_frac * p_sat
        denom = 101325 - p_w
        if denom <= 0:
            return 0.01
        return 0.622 * p_w / denom


# =============================================================================
# ML INFERENCE ENGINE — Loads and runs the Random Forest model
# =============================================================================
class EdgeMLEngine:
    """
    Edge ML inference engine running on the Raspberry Pi.
    Loads the full Random Forest occupancy pipeline and makes
    independent predictions for all 26 rooms.
    """

    FEATURES = ['Temperature', 'Humidity', 'Light', 'CO2', 'HumidityRatio']

    def __init__(self):
        self.model = None
        self._load_model()

    def _load_model(self):
        """Load the trained sklearn pipeline."""
        import joblib
        model_path = os.path.join(PROJECT_ROOT, "models", "final_unified_occupancy_pipeline.pkl")
        try:
            self.model = joblib.load(model_path)
            logger.info(f"✓ ML Model loaded from {model_path}")
        except Exception as e:
            logger.error(f"✗ Failed to load ML model: {e}")
            logger.info("  Falling back to heuristic inference")
            self.model = None

    def predict(self, sensor_data: Dict[str, float]) -> Dict[str, Any]:
        """
        Run occupancy prediction on a single room's sensor data.
        Returns: {occupancy_probability, predicted_occupancy, confidence}
        """
        if self.model is None:
            return self._heuristic_predict(sensor_data)

        try:
            import numpy as np
            import pandas as pd

            # Build feature vector
            features = {}
            for f in self.FEATURES:
                val = sensor_data.get(f)
                if val is None:
                    # Try lowercase/titlecase variants
                    val = sensor_data.get(f.lower(), sensor_data.get(f.title()))
                features[f] = float(val) if val is not None else np.nan

            df = pd.DataFrame([features])
            prob = self.model.predict_proba(df)[0]
            occ_prob = float(prob[1]) if len(prob) > 1 else float(prob[0])
            prediction = 1 if occ_prob >= 0.5 else 0
            confidence = max(float(prob[0]), float(prob[1])) if len(prob) > 1 else float(prob[0])

            return {
                "occupancy_probability": round(occ_prob, 4),
                "predicted_occupancy": prediction,
                "confidence": round(confidence, 4),
            }
        except Exception as e:
            logger.warning(f"ML prediction failed: {e}, using heuristic")
            return self._heuristic_predict(sensor_data)

    def _heuristic_predict(self, sensor_data: Dict[str, float]) -> Dict[str, Any]:
        """Simple heuristic fallback if ML model is unavailable."""
        co2 = sensor_data.get("CO2", sensor_data.get("co2", 400))
        light = sensor_data.get("Light", sensor_data.get("lux", 0))
        temp = sensor_data.get("Temperature", sensor_data.get("temperature", 22))

        score = 0.0
        if co2 > 500: score += 0.3
        if co2 > 700: score += 0.2
        if light > 200: score += 0.2
        if temp > 24: score += 0.1

        return {
            "occupancy_probability": round(min(score, 0.95), 4),
            "predicted_occupancy": 1 if score >= 0.5 else 0,
            "confidence": round(max(score, 1 - score), 4),
        }


# =============================================================================
# AI CONTROL DECISION ENGINE
# =============================================================================
class ControlEngine:
    """Makes independent HVAC/Lighting/Energy decisions per room."""

    # Room-type-specific thresholds
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

    # Power estimates (watts)
    POWER = {
        "light": {"ON": 60, "DIM": 25, "OFF": 0},
        "hvac": {"NORMAL": 2500, "LOW": 1200, "ECO": 200, "OFF": 0},
    }

    # PWM mapping for v2.0 actuators
    FAN_PWM = {"NORMAL": 180, "LOW": 100, "ECO": 0, "OFF": 0, "HIGH": 255, "MEDIUM": 180}
    LED_PWM = {"ON": 255, "DIM": 80, "OFF": 0, "LOW": 64, "MEDIUM": 160, "HIGH": 255}

    def decide(self, room_type: str, ai_result: Dict, room_state: Dict = None) -> Dict[str, Any]:
        """Make control decision based on AI prediction.
        
        v2.0: Also returns fan_speed (0-255), light_level (0-255),
        and servo_angle (0-180) for PWM-capable actuators.
        """
        thresholds = self.TUNING.get(room_type, {"empty": 0.20, "occupied": 0.60})
        prob = ai_result["occupancy_probability"]

        if prob < thresholds["empty"]:
            light_action = "OFF"
            hvac_action = "ECO"
            control_mode = "EMPTY"
        elif prob < thresholds["occupied"]:
            light_action = "DIM"
            hvac_action = "LOW"
            control_mode = "STANDBY"
        else:
            light_action = "ON"
            hvac_action = "NORMAL"
            control_mode = "OCCUPIED"

        # Power estimation
        power_w = self.POWER["light"][light_action] + self.POWER["hvac"][hvac_action]

        # v2.0: PWM-level control values for ESP32 actuators
        fan_speed = self.FAN_PWM.get(hvac_action, 0)
        light_level = self.LED_PWM.get(light_action, 0)

        # Servo ventilation angle: open damper when CO2 is elevated and
        # temperature is acceptable for natural ventilation
        servo_angle = 0  # default: closed
        if room_state:
            co2 = room_state.get("sensors", {}).get("CO2", 400)
            temp = room_state.get("sensors", {}).get("Temperature", 24)
            if co2 > 800 and 18 <= temp <= 28 and prob >= thresholds["occupied"]:
                # Proportional: 800→0°, 1200+→90°
                servo_angle = min(90, max(0, int((co2 - 800) * 90 / 400)))
                # If ventilating naturally, reduce fan
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
    """Tracks cumulative energy consumption per room."""

    def __init__(self):
        self._cumulative_wh: Dict[str, float] = {}

    def update(self, room_id: str, power_watts: float, dt_sim_seconds: float):
        if room_id not in self._cumulative_wh:
            self._cumulative_wh[room_id] = 0.0
        self._cumulative_wh[room_id] += power_watts * (dt_sim_seconds / 3600.0)

    def get(self, room_id: str) -> float:
        return self._cumulative_wh.get(room_id, 0.0)

    def get_total(self) -> float:
        return sum(self._cumulative_wh.values())

    def reset(self):
        self._cumulative_wh.clear()


# =============================================================================
# PHYSICAL OUTPUT CONTROLLER (GPIO)
# =============================================================================
class PhysicalOutputController:
    """
    Controls physical GPIO outputs on the Raspberry Pi.
    Drives LEDs, motors, and indicators to demonstrate AI decisions.

    When running on a non-Pi system (development), this operates
    in simulation mode and just logs the output states.
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
            logger.info("✓ Raspberry Pi GPIO initialized")
        except (ImportError, RuntimeError):
            logger.info("ℹ Not running on Raspberry Pi — GPIO in simulation mode")

    def update_room(self, room_id: str, control: Dict[str, Any]):
        """Update the physical output state for a room."""
        self._output_states[room_id] = {
            "light": control.get("light_action", "OFF"),
            "hvac": control.get("hvac_action", "ECO"),
            "mode": control.get("control_mode", "EMPTY"),
            "power": control.get("estimated_power_watts", 0),
        }

        # On actual Pi, drive GPIO pins here
        # For now, this is extensible — you add pin mappings per room
        if self._is_pi:
            self._drive_gpio(room_id, control)

    def _drive_gpio(self, room_id: str, control: Dict):
        """Drive actual GPIO pins. Override this with your wiring map."""
        # Example: Room 101 uses specific pins
        # This would be expanded with PCA9685 for 26-room output
        pass

    def get_all_states(self) -> Dict[str, Dict]:
        return dict(self._output_states)

    def cleanup(self):
        if self._is_pi and self._gpio:
            self._gpio.cleanup()


# =============================================================================
# MAIN EDGE BRAIN — Orchestrator
# =============================================================================
class EdgeBrain:
    """
    Main orchestrator for the Raspberry Pi Edge Intelligence system.

    Manages:
    - EdgeSimulator (25 virtual rooms)
    - EdgeMLEngine (Random Forest inference)
    - ControlEngine (per-room decisions)
    - EnergyTracker (cumulative energy)
    - PhysicalOutputController (GPIO outputs)
    - Hardware room state (Room 101 from ESP32)
    - Flask API + SSE streaming
    """

    def __init__(self, speed_factor: float = 360.0):
        self._lock = threading.Lock()

        # Core components
        self.simulator = EdgeSimulator(speed_factor=speed_factor)
        self.ml_engine = EdgeMLEngine()
        self.control_engine = ControlEngine()
        self.energy_tracker = EnergyTracker()
        self.physical_output = PhysicalOutputController()

        # Hardware room state (received from ESP32 via HTTP)
        self._hardware_state: Optional[Dict[str, Any]] = None
        self._hardware_last_update: Optional[str] = None

        # Complete building state (26 rooms, updated each tick)
        self._building_state: Dict[str, Dict[str, Any]] = {}

        # History for charts
        self._history: Dict[str, deque] = {}
        self._max_history = 200

        # Tick counter
        self._tick_count = 0
        self._update_interval = 0.5  # seconds between ticks
        self._speed_factor = speed_factor

        logger.info("✓ EdgeBrain initialized")
        logger.info(f"  Speed factor: {speed_factor}x")
        logger.info(f"  Rooms: 1 physical + {len(self.simulator._rooms)} simulated = {len(ALL_ROOMS)} total")

    def inject_hardware_data(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Receive real sensor data from ESP32 v2.0 (Room 101).
        Handles expanded telemetry: SCD41, LD2410C, INA226, sensor health.
        Returns the AI control decision including PWM-level actuator values.
        """
        with self._lock:
            temp = float(payload.get("temperature", 24.0))
            hum = float(payload.get("humidity", 50.0))
            co2 = float(payload.get("co2", 400.0))
            lux = float(payload.get("lux", 0.0))
            motion = payload.get("motion_detected", False)

            # v2.0 expanded sensor fields
            pressure_hpa = float(payload.get("pressure_hpa", 1013.25))
            co2_source = payload.get("co2_source", "mq2_estimate")
            mq2_raw = int(payload.get("mq2_raw", 0))

            # SCD41 NDIR supplementary readings
            scd41_temp = payload.get("scd41_temp")
            scd41_hum = payload.get("scd41_humidity")

            # LD2410C mmWave presence
            mmwave_presence = payload.get("mmwave_presence", False)
            mmwave_moving = payload.get("mmwave_moving", False)
            mmwave_stationary = payload.get("mmwave_stationary", False)
            mmwave_distance = int(payload.get("mmwave_distance_cm", 0))
            presence = payload.get("presence", motion)  # fused presence
            presence_source = payload.get("presence_source", "pir")

            # INA226 real power measurement
            measured_voltage = payload.get("measured_voltage_v")
            measured_current = payload.get("measured_current_mA")
            measured_power = payload.get("measured_power_mW")

            # Actuator feedback from ESP32
            actuator_fan = int(payload.get("actuator_fan_speed", 0))
            actuator_light = int(payload.get("actuator_light_level", 0))
            actuator_servo = int(payload.get("actuator_servo_angle", 0))

            # Sensor health status
            sensor_health = payload.get("sensor_health", {})

            # Compute humidity ratio
            es = 6.112 * math.exp((17.67 * temp) / (temp + 243.5))
            e = (hum / 100.0) * es
            hr = (0.622 * e) / (1013.25 - e) if (1013.25 - e) > 0 else 0.004

            self._hardware_state = {
                "room_id": HARDWARE_ROOM_ID,
                "room_type": "office",
                "floor_id": 1,
                "display_name": "Room 101 (Hardware)",
                "source": "physical",
                "sensors": {
                    "Temperature": round(temp, 2),
                    "Humidity": round(hum, 2),
                    "Light": round(lux, 1),
                    "CO2": round(co2, 1),
                    "CO2_source": co2_source,
                    "HumidityRatio": round(hr, 6),
                    "Pressure_hPa": round(pressure_hpa, 1),
                    "MQ2_raw": mq2_raw,
                },
                "presence": {
                    "pir_motion": motion,
                    "mmwave_presence": mmwave_presence,
                    "mmwave_moving": mmwave_moving,
                    "mmwave_stationary": mmwave_stationary,
                    "mmwave_distance_cm": mmwave_distance,
                    "fused_presence": presence,
                    "source": presence_source,
                },
                "ground_truth": {
                    "true_occupancy": 1 if presence else 0,
                    "max_occupancy": 10,
                },
                "device_state": {
                    "light_on": actuator_light > 0,
                    "hvac_mode": "on" if actuator_fan > 0 else "off",
                    "hvac_speed": actuator_fan,
                    "light_level": actuator_light,
                    "servo_angle": actuator_servo,
                },
                "power_measurement": {
                    "voltage_v": measured_voltage,
                    "current_mA": measured_current,
                    "power_mW": measured_power,
                    "available": measured_power is not None,
                },
                "sensor_health": sensor_health,
            }

            # Add SCD41 supplementary if available
            if scd41_temp is not None:
                self._hardware_state["sensors"]["SCD41_Temperature"] = round(scd41_temp, 2)
            if scd41_hum is not None:
                self._hardware_state["sensors"]["SCD41_Humidity"] = round(scd41_hum, 2)

            self._hardware_last_update = datetime.now().isoformat()

        # Run ML prediction for Room 101 immediately and return decision
        ai_result = self.ml_engine.predict(self._hardware_state["sensors"])
        control = self.control_engine.decide("office", ai_result, self._hardware_state)

        logger.info(
            f"HARDWARE Room 101: T={temp:.1f}C Lux={lux:.0f} CO2={co2:.0f}({co2_source}) "
            f"Pres={presence}({presence_source}) "
            f"-> OccProb={ai_result['occupancy_probability']:.2f} "
            f"-> {control['control_mode']} (Fan={control['fan_speed']} Light={control['light_level']} Servo={control['servo_angle']})"
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

    def tick(self):
        """
        Execute one full update cycle:
        1. Step simulator
        2. Merge real + simulated states
        3. Run ML on all 26 rooms
        4. Make control decisions
        5. Apply to simulator & physical outputs
        6. Update building state for SSE streaming
        """
        self._tick_count += 1
        dt = self._update_interval
        dt_sim = dt * self._speed_factor

        # 1. Step simulation forward
        self.simulator.step(dt)

        # 2. Collect all room states
        sim_states = self.simulator.get_all_simulated_states()
        all_room_states = list(sim_states)  # 25 simulated rooms

        # Insert Room 101 hardware state (or generate a placeholder if no ESP32 data)
        with self._lock:
            if self._hardware_state:
                all_room_states.append(dict(self._hardware_state))
            else:
                # No ESP32 data yet — generate simulated Room 101 as placeholder
                all_room_states.append(self._generate_placeholder_room101())

        # 3. Run ML + Control on ALL 26 rooms
        for room_state in all_room_states:
            room_id = room_state["room_id"]
            room_type = room_state["room_type"]
            sensors = room_state["sensors"]

            # ML prediction
            ai_result = self.ml_engine.predict(sensors)
            room_state["ai"] = ai_result

            # Control decision
            control = self.control_engine.decide(room_type, ai_result)
            room_state["control"] = control

            # Energy tracking
            self.energy_tracker.update(room_id, control["estimated_power_watts"], dt_sim)
            room_state["energy"] = {
                "estimated_power_watts": control["estimated_power_watts"],
                "cumulative_energy_wh": round(self.energy_tracker.get(room_id), 2),
            }

            # Apply control back to simulator (closes the loop)
            if room_id != HARDWARE_ROOM_ID:
                light_on = control["light_action"] != "OFF"
                hvac_map = {"NORMAL": "cooling", "LOW": "fan_only", "ECO": "off", "OFF": "off"}
                hvac_mode = hvac_map.get(control["hvac_action"], "off")
                self.simulator.apply_control(room_id, light_on, hvac_mode)

            # Update physical outputs
            self.physical_output.update_room(room_id, control)

            # Timestamp
            room_state["timestamp"] = self.simulator.get_time_string()

            # Status
            room_state["status"] = {
                "api_online": True,
                "model_loaded": self.ml_engine.model is not None,
                "simulation_running": True,
            }

            # Store
            with self._lock:
                self._building_state[room_id] = room_state

                # History
                if room_id not in self._history:
                    self._history[room_id] = deque(maxlen=self._max_history)
                self._history[room_id].append({
                    "timestamp": room_state["timestamp"],
                    "occupancy_probability": ai_result["occupancy_probability"],
                    "predicted_occupancy": ai_result["predicted_occupancy"],
                    "true_occupancy": room_state.get("ground_truth", {}).get("true_occupancy", 0),
                    "power_watts": control["estimated_power_watts"],
                    "temperature": sensors.get("Temperature", 22),
                })

        # Periodic log
        if self._tick_count % 30 == 0:
            total_power = sum(
                rs.get("energy", {}).get("estimated_power_watts", 0)
                for rs in self._building_state.values()
            )
            occupied = sum(
                1 for rs in self._building_state.values()
                if rs.get("ai", {}).get("predicted_occupancy", 0) == 1
            )
            logger.info(
                f"Tick #{self._tick_count} | "
                f"Time: {self.simulator.get_time_string()} | "
                f"Rooms: {len(self._building_state)} | "
                f"Occupied: {occupied} | "
                f"Power: {total_power:.0f}W | "
                f"Energy: {self.energy_tracker.get_total():.1f}Wh"
            )

    def _generate_placeholder_room101(self) -> Dict[str, Any]:
        """Generate a simulated placeholder for Room 101 when ESP32 is offline."""
        hour = self.simulator.sim_hour
        occ_prob = get_occupancy_probability("office", hour)
        occ = 1 if random.random() < occ_prob else 0
        sun = max(0, math.sin((hour - 6) * math.pi / 12)) if 6 <= hour <= 18 else 0

        return {
            "room_id": HARDWARE_ROOM_ID,
            "room_type": "office",
            "floor_id": 1,
            "display_name": "Room 101 (Simulated Fallback)",
            "source": "simulated",
            "sensors": {
                "Temperature": round(22.0 + random.uniform(-1, 3), 2),
                "Humidity": round(50.0 + random.uniform(-5, 10), 2),
                "Light": round(sun * 400 + random.uniform(-10, 10), 1),
                "CO2": round(400.0 + occ * 100 + random.uniform(-10, 10), 1),
                "HumidityRatio": 0.004,
            },
            "ground_truth": {"true_occupancy": occ, "max_occupancy": 10},
            "device_state": {"light_on": False, "hvac_mode": "off", "hvac_speed": 0},
        }

    def get_current_state(self) -> Dict[str, Any]:
        """Get the complete building state for SSE streaming."""
        with self._lock:
            rooms = list(self._building_state.values())

        # System summary
        total_power = sum(r.get("energy", {}).get("estimated_power_watts", 0) for r in rooms)
        occupied = sum(1 for r in rooms if r.get("ai", {}).get("predicted_occupancy", 0) == 1)
        total_energy = self.energy_tracker.get_total()

        return {
            "timestamp": datetime.now().isoformat(),
            "rooms": rooms,
            "system": {
                "total_rooms": len(rooms),
                "occupied_rooms": occupied,
                "empty_rooms": len(rooms) - occupied,
                "total_power_watts": round(total_power, 1),
                "total_cumulative_energy_wh": round(total_energy, 2),
                "model_loaded": self.ml_engine.model is not None,
                "api_online": True,
                "simulation_running": True,
                "simulation_connected": True,
                "simulation_time": self.simulator.get_time_string(),
                "simulation_speed_factor": self._speed_factor,
                "data_stale": False,
                "last_update": datetime.now().isoformat(),
                "update_interval": self._update_interval,
                "simulation_paused": False,
                "day_count": self.simulator._day_count,
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
        "message": "Raspberry Pi Edge Intelligence Brain",
        "model_loaded": brain.ml_engine.model is not None if brain else False,
        "simulation_active": True,
        "platform": "Raspberry Pi 4B",
    })


@app.route('/api/hardware/sensor-data', methods=['POST'])
def receive_sensor_data():
    """ESP32 POSTs raw sensor data here. Pi returns control decision."""
    try:
        payload = request.get_json(force=True)
        if not payload:
            return jsonify({"error": "No JSON payload"}), 400

        decision = brain.inject_hardware_data(payload)

        return jsonify({
            "status": "ok",
            "message": "Sensor data accepted, edge decision made",
            "room_id": HARDWARE_ROOM_ID,
            "source": "edge_ai_pi",
            "hvac_action": decision["hvac_action"],
            "light_action": decision["light_action"],
            "control_mode": decision["control_mode"],
            "occupancy_probability": decision["occupancy_probability"],
            # v2.0: PWM-level actuator control values
            "fan_speed": decision.get("fan_speed", -1),
            "light_level": decision.get("light_level", -1),
            "servo_angle": decision.get("servo_angle", -1),
            "timestamp": datetime.now().isoformat(),
        }), 200

    except Exception as e:
        logger.error(f"Hardware endpoint error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/rooms/current-state', methods=['GET'])
def get_current_state():
    return jsonify(brain.get_current_state())


@app.route('/api/stream', methods=['GET'])
def sse_stream():
    """Server-Sent Events stream for the Digital Twin dashboard."""
    def generate():
        while True:
            try:
                state = brain.get_current_state()
                data = json.dumps(state, default=str)
                yield f"data: {data}\n\n"
                time.sleep(brain._update_interval)
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
    state = brain.get_current_state()
    return jsonify(state.get("system", {}))


@app.route('/api/rooms/history', methods=['GET'])
def room_history():
    room_id = request.args.get('room_id')
    if room_id:
        return jsonify({room_id: brain.get_room_history(room_id)})
    # Return all histories
    result = {}
    for rid in ROOM_IDS:
        result[rid] = brain.get_room_history(rid)
    return jsonify(result)


@app.route('/api/simulation/control', methods=['POST'])
def simulation_control():
    """Control simulation (pause/resume/reset-energy)."""
    data = request.get_json(force=True)
    action = data.get("action", "")

    if action == "reset-energy":
        brain.energy_tracker.reset()
        return jsonify({"status": "ok", "message": "Energy counters reset"})

    return jsonify({"status": "ok", "message": f"Action '{action}' noted"})


@app.route('/api/physical/outputs', methods=['GET'])
def physical_outputs():
    """Get current physical output states for all rooms."""
    return jsonify(brain.physical_output.get_all_states())


# =============================================================================
# BACKGROUND TICK LOOP
# =============================================================================
def run_tick_loop(brain_instance: EdgeBrain, stop_event: threading.Event):
    """Background thread that runs the simulation + ML + control loop."""
    logger.info("[>] Edge Brain tick loop started")
    while not stop_event.is_set():
        try:
            brain_instance.tick()
        except Exception as e:
            logger.error(f"Tick error: {e}", exc_info=True)
        stop_event.wait(brain_instance._update_interval)
    logger.info("[■] Edge Brain tick loop stopped")


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================
def main():
    global brain

    logger.info("═══════════════════════════════════════════════════")
    logger.info("  RASPBERRY PI 4B — EDGE INTELLIGENCE BRAIN")
    logger.info("  Smart Building Hybrid Cyber-Physical System")
    logger.info("═══════════════════════════════════════════════════")

    # Initialize the edge brain
    speed = float(os.environ.get("SPEED_FACTOR", "360"))
    brain = EdgeBrain(speed_factor=speed)

    # Start background tick loop
    stop_event = threading.Event()
    tick_thread = threading.Thread(
        target=run_tick_loop,
        args=(brain, stop_event),
        daemon=True,
        name="EdgeBrainTickLoop",
    )
    tick_thread.start()

    # Start Flask API
    port = int(os.environ.get("API_PORT", "8001"))
    host = os.environ.get("API_HOST", "0.0.0.0")

    logger.info(f"Starting API on {host}:{port}")
    logger.info(f"  ESP32 endpoint: POST http://<pi_ip>:{port}/api/hardware/sensor-data")
    logger.info(f"  SSE stream:     GET  http://<pi_ip>:{port}/api/stream")
    logger.info(f"  Health check:   GET  http://<pi_ip>:{port}/health")

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
