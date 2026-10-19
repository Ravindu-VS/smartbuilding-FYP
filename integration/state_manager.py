"""
State Manager

Central live state store for the real-time integration layer.
Holds the latest state for all 4 rooms, runs the full pipeline
(sensor data → ML inference → control decision → energy estimation),
and maintains per-room history buffers.

Thread-safe: all state access is protected by a threading.Lock().
"""

import sys
import os
import logging
import threading
import time
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import asdict
from collections import deque

try:
    import redis
    import json
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

# Ensure project root is on path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from integration.config import (
    ROOM_ID_MAP, MAX_HISTORY_POINTS,
    MODEL_PATH, ROOM_DISPLAY_NAMES,
)
from integration.building_config import BUILDING_CONFIG, get_room_control_tuning
from integration.energy_estimator import EnergyEstimator
from integration.energy_optimizer import EnergyOptimizer
from integration.logger import SystemLogger

logger = logging.getLogger(__name__)


class StateManager:
    """
    Central live state store for the smart building integration.

    Holds:
    - Latest room state for all 4 rooms (dict keyed by room_id string)
    - Per-room history buffers (deques)
    - System health flags
    - Building-wide summary

    Runs the pipeline: sensor data → ML inference → control decision → energy
    """

    def __init__(self):
        """Initialize state manager and load ML model."""
        self._lock = threading.Lock()

        # Current room states
        self._rooms: Dict[str, Dict[str, Any]] = {}

        # Per-room history
        self._history: Dict[str, deque] = {}

        # System health - SINGLE SOURCE OF TRUTH FOR ALL LIVE DATA
        # Backend coordinator pattern: StateManager is the ONLY authoritative source
        self._health = {
            # API/Connection Status
            "api_online": True,                     # Backend API running

            # Simulation Status (from bridge, stored here as source of truth)
            "simulation_running": False,             # Is simulation engine active?
            "simulation_connected": False,           # Is simulation bridge connected?
            "simulation_time": None,                 # AUTHORITATIVE: Current sim time (from bridge)
            "simulation_speed_factor": 60.0,         # Simulation speed multiplier
            "last_simulation_update_time": None,     # When did we last get sim data?

            # Data Quality
            "data_stale": False,                     # Data older than threshold?
            "stale_threshold_seconds": 5.0,          # Staleness threshold

            # Model Status
            "model_loaded": False,                   # ML model ready?

            # Update Tracking
            "last_api_update": None,                 # When was state last updated?
            "update_interval": 2.0,                  # Current update interval
        }

        # Energy estimator (per-room power + cumulative)
        self._energy = EnergyEstimator()

        # Energy optimizer (baseline vs AI comparison)
        self._optimizer = EnergyOptimizer()

        # Centralized event logger
        self._sys_logger = SystemLogger.get_instance()

        # ML inference service and controller (loaded once)
        self._inference_service = None
        self._controller = None
        
        # Optimization weights for multi-objective cost (alpha, beta, gamma)
        self.optimization_weights = {"alpha": 1.0, "beta": 5.0, "gamma": 0.5}
        
        # Multi-Floor Agent Hierarchy
        from agents.building_agent import BuildingAgent
        self._building_agent = BuildingAgent(BUILDING_CONFIG, self._inference_service)

        # Reference to simulation bridge for closed-loop feedback
        self._bridge = None

        # Load model
        self._load_model()

        # Initialize Redis client if configured
        self.redis_client = None
        redis_host = os.environ.get("REDIS_HOST")
        if redis_host and REDIS_AVAILABLE:
            try:
                self.redis_client = redis.Redis(host=redis_host, port=6379, db=0, socket_timeout=1.0)
                logger.info(f"✓ StateManager connected to Redis cache at {redis_host}")
            except Exception as e:
                logger.warning(f"StateManager failed to connect to Redis: {e}")

        self._sys_logger.log_system("StateManager initialized", sim_time=self._health.get("simulation_time"))
        logger.info("✓ StateManager initialized")

    def set_bridge(self, bridge):
        """
        Set the simulation bridge reference for closed-loop feedback.

        When set, control decisions from the ML pipeline are applied back
        into the simulation engine, closing the real-time loop.

        Args:
            bridge: SimulationBridge instance
        """
        self._bridge = bridge
        logger.info("✓ Closed-loop feedback enabled (StateManager → SimulationBridge)")

    def _load_model(self):
        """Load the occupancy inference service and controller."""
        try:
            from occupancy_inference_service import OccupancyInferenceService
            from smart_building_controller import SmartBuildingController

            model_path = os.path.join(PROJECT_ROOT, MODEL_PATH)

            self._inference_service = OccupancyInferenceService(
                model_path, threshold=0.5
            )

            # Use default thresholds; room-specific tuning applied in pipeline
            self._controller = SmartBuildingController(
                model_path,
                empty_threshold=0.20,
                occupied_threshold=0.60,
            )

            self._health["model_loaded"] = True
            self._sys_logger.log_model("ML model loaded successfully", sim_time=self._health.get("simulation_time"))
            logger.info("✓ ML model loaded successfully")

        except Exception as e:
            logger.error(f"Failed to load ML model: {e}")
            self._sys_logger.log_model(f"ML model load FAILED: {e}", "ERROR", sim_time=self._health.get("simulation_time"))
            self._health["model_loaded"] = False

    def process_room_states(self, raw_rooms: List[Dict[str, Any]], sim_time: Optional[str] = None, dt: float = 2.0):
        """
        Process raw room states from the simulation bridge.

        CRITICAL: This is where simulation state becomes the backend's
        authoritative source. Once data enters here, StateManager OWNS it.

        For each room:
        1. Run ML inference to predict occupancy
        2. Apply room-aware control decision
        3. Estimate energy
        4. Update state store and history

        Args:
            raw_rooms: List of room state dicts from SimulationBridge
            sim_time: Current simulation time (STORED AS AUTHORITATIVE)
        """
        # STEP 1: Update simulation status with AUTHORITATIVE time
        # Once stored here, this is the ONLY source of truth for sim_time
        if sim_time:
            with self._lock:
                self._health["simulation_running"] = True
                self._health["simulation_connected"] = True
                self._health["simulation_time"] = sim_time  # STORE AS SOURCE OF TRUTH
                self._health["last_simulation_update_time"] = datetime.now().isoformat()
                self._health["data_stale"] = False  # Fresh data just arrived
                logger.debug(f"StateManager: Received simulation time = {sim_time}")

        from hardware.hardware_room_manager import hardware_manager

        # Prepare building_sensor_data for BuildingAgent
        building_sensor_data = {}
        for raw in raw_rooms:
            f_id = raw.get("floor_id", 0)
            r_id = raw["room_id"]
            if f_id not in building_sensor_data:
                building_sensor_data[f_id] = {}
            
            # --- HARDWARE INJECTION ---
            hw_state = hardware_manager.get_room_state(r_id)
            if hw_state:
                # Override simulation sensors with physical reality
                for k, v in hw_state.items():
                    if k not in ["id", "source", "last_update", "occupancy_probability"]:
                        # Handle titlecase variations
                        if k.title() in raw["sensors"]:
                            raw["sensors"][k.title()] = v
                        else:
                            raw["sensors"][k] = v
                
                # Specifically extract edge AI prediction if it exists
                if "occupancy_probability" in hw_state:
                    raw["sensors"]["edge_occupancy_probability"] = hw_state["occupancy_probability"]
                
                raw["source"] = "hardware"
            
            # Fix ML causal confusion: remove artificial light before passing to ML
            sensors_for_model = raw["sensors"].copy()
            if raw.get("device_state", {}).get("light_on", False):
                sensors_for_model["Light"] = max(0, sensors_for_model["Light"] - 400.0)
                
            building_sensor_data[f_id][r_id] = sensors_for_model
            
        # Run BuildingAgent to get all decisions
        agent_decisions = self._building_agent.step(building_sensor_data)
        decision_map = {d["room_id"]: d for d in agent_decisions}

        total_power = 0.0

        for raw in raw_rooms:
            try:
                room_id = raw["room_id"]
                room_type = raw["room_type"]

                # Ensure room is registered for energy tracking
                self._energy.register_room(room_id, room_type)
                self._optimizer.register_room(room_id, room_type)

                agent_decision = decision_map.get(room_id)
                if agent_decision:
                    ai_result = agent_decision["ai"]
                    control_result = agent_decision["control"]
                else:
                    ai_result = {"predicted_occupancy": 0, "occupancy_probability": 0.0}
                    control_result = {"light_action": "ON", "hvac_action": "NORMAL", "control_mode": "FALLBACK"}

                # 2b. CLOSED-LOOP FEEDBACK: Apply control back to simulation
                if self._bridge is not None:
                    self._bridge.apply_control_actions(room_id, control_result)

                # 2c. RESOLVE ACTUAL ACTIONS (What the simulation is actually doing right now)
                device_state = raw.get("device_state", {})
                actual_light_on = device_state.get("light_on", False)
                actual_hvac_mode = device_state.get("hvac_mode", "off")

                rec_light = control_result.get("light_action", "ON")
                if not actual_light_on:
                    actual_light_act = "OFF"
                else:
                    actual_light_act = rec_light if rec_light in ["ON", "DIM"] else "ON"

                rec_hvac = control_result.get("hvac_action", "ECO")
                if actual_hvac_mode in ["off", ""]:
                    actual_hvac_act = "ECO" if rec_hvac == "ECO" else "OFF"
                elif actual_hvac_mode == "fan_only":
                    actual_hvac_act = "LOW"
                else:
                    actual_hvac_act = "NORMAL"

                # 2d. CALCULATE SIMULATION DT
                speed = self._health.get("simulation_speed_factor", 60.0)
                dt_sim = dt * speed

                # 3. Energy Estimation (actual power + cumulative using ACTUAL actions)
                energy_result = self._energy.estimate_room_energy(
                    room_id, actual_light_act, actual_hvac_act, dt_sim
                )
                total_power += energy_result["estimated_power_watts"]

                # 4. Energy Optimization (baseline vs AI comparison using ACTUAL actions)
                opt_result = self._optimizer.update_room(
                    room_id, actual_light_act, actual_hvac_act, dt=dt_sim
                )
                energy_result["optimization"] = opt_result

                # 5. Log ACTUAL control decision applied
                ctrl_mode = control_result.get("control_mode", "EMPTY")
                self._sys_logger.log_control(
                    raw.get("display_name", room_id),
                    ctrl_mode,
                    f"Lights {actual_light_act}, HVAC {actual_hvac_act}",
                    sim_time=sim_time
                )

                # Build complete room state
                room_state = {
                    "room_id": room_id,
                    "room_type": room_type,
                    "floor_id": raw.get("floor_id", 2),
                    "source": raw.get("source", "simulation"),
                    "display_name": raw.get("display_name", room_id),
                    "timestamp": sim_time if sim_time else raw.get("timestamp", ""),
                    "sensors": raw["sensors"],
                    "ground_truth": raw.get("ground_truth", {}),
                    "ai": ai_result,
                    "control": control_result,
                    "actual_action": {
                        "light_action": actual_light_act,
                        "hvac_action": actual_hvac_act
                    },
                    "energy": energy_result,
                    "device_state": device_state,
                    "status": {
                        "api_online": self._health.get("api_online", True),
                        "model_loaded": self._health.get("model_loaded", False),
                        "simulation_running": self._health.get("simulation_running", False),
                    },
                }

                # Thread-safe update
                with self._lock:
                    self._rooms[room_id] = room_state

                    # Update history
                    if room_id not in self._history:
                        self._history[room_id] = deque(
                            maxlen=MAX_HISTORY_POINTS
                        )
                    self._history[room_id].append({
                        "timestamp": room_state["timestamp"],
                        "occupancy_probability": ai_result.get(
                            "occupancy_probability", 0.0
                        ),
                        "predicted_occupancy": ai_result.get(
                            "predicted_occupancy", 0
                        ),
                        "true_occupancy": raw.get("ground_truth", {}).get(
                            "true_occupancy", 0
                        ),
                        "control_mode": ctrl_mode,
                        "co2": raw["sensors"].get("CO2", 400.0),
                        "temperature": raw["sensors"].get("Temperature", 20.0),
                        "power_watts": energy_result["estimated_power_watts"],
                        "cumulative_wh": energy_result["cumulative_energy_wh"],
                    })

            except Exception as e:
                logger.warning(
                    f"Failed to process room {raw.get('room_id', '?')}: {e}"
                )
                continue

        # Update health
        with self._lock:
            self._health["last_update"] = datetime.now().isoformat()
            self._health["simulation_active"] = True
            self._health["total_power_watts"] = round(total_power, 1)

            # Sync to Redis cache if active
            if self.redis_client:
                try:
                    for r_id, r_state in self._rooms.items():
                        self.redis_client.set(f"room:{r_id}", json.dumps(r_state))
                    self.redis_client.set("health", json.dumps(self._health))
                    self.redis_client.set("system_summary", json.dumps(self._get_system_summary_internal()))
                except Exception as ex:
                    logger.warning(f"StateManager: Redis sync failed: {ex}")

    def _run_inference(self, sensors: Dict[str, float]) -> Dict[str, Any]:
        """
        Run ML inference on sensor data.

        Args:
            sensors: Dict with Temperature, Humidity, Light, CO2, HumidityRatio

        Returns:
            Dict with occupancy_probability, predicted_occupancy, confidence
        """
        if self._inference_service is None:
            return {
                "occupancy_probability": 0.0,
                "predicted_occupancy": 0,
                "confidence": 0.0,
            }

        try:
            result = self._inference_service.predict(sensors)
            return {
                "occupancy_probability": round(result.occupancy_probability, 4),
                "predicted_occupancy": int(result.occupancy_prediction),
                "confidence": round(result.confidence, 4),
            }
        except Exception as e:
            logger.warning(f"Inference failed: {e}")
            return {
                "occupancy_probability": 0.0,
                "predicted_occupancy": 0,
                "confidence": 0.0,
            }

    def _run_control(
        self,
        sensors: Dict[str, float],
        room_type: str,
        ai_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Generate control decision using room-aware thresholds.

        Args:
            sensors: Sensor data dict
            room_type: Room type string
            ai_result: AI inference result

        Returns:
            Dict with control_mode, light_action, hvac_action, energy_mode
        """
        prob = ai_result.get("occupancy_probability", 0.0)

        # Get room-specific thresholds
        tuning = get_room_control_tuning(room_type)
        empty_thresh = tuning["empty_threshold"]
        occupied_thresh = tuning["occupied_threshold"]

        # Determine control mode
        if prob < empty_thresh:
            control_mode = "EMPTY"
            light_action = "OFF"
            hvac_action = "ECO"
            energy_mode = "MAXIMUM_SAVINGS"
        elif prob < occupied_thresh:
            control_mode = "STANDBY"
            light_action = "DIM"
            hvac_action = "LOW"
            energy_mode = "COMFORT_SAVINGS"
        else:
            control_mode = "OCCUPIED"
            light_action = "ON"
            hvac_action = "NORMAL"
            energy_mode = "COMFORT"

        return {
            "control_mode": control_mode,
            "light_action": light_action,
            "hvac_action": hvac_action,
            "energy_mode": energy_mode,
        }

    def get_current_state(self) -> Dict[str, Any]:
        """
        Get current state of all rooms.

        Returns:
            Dict with floors list and timestamp.
        """
        with self._lock:
            # Group rooms by floor
            floors = []
            for floor_config in BUILDING_CONFIG["floors"]:
                floor_data = {
                    "floor_id": floor_config["floor_id"],
                    "name": floor_config["name"],
                    "rooms": []
                }
                for room_cfg in floor_config["rooms"]:
                    if room_cfg["room_id"] in self._rooms:
                        floor_data["rooms"].append(self._rooms[room_cfg["room_id"]])
                
                # Compute floor-level energy
                floor_power = sum(r.get("energy", {}).get("estimated_power_watts", 0.0) for r in floor_data["rooms"])
                floor_data["total_power_watts"] = round(floor_power, 1)
                
                floors.append(floor_data)
                
            return {
                "timestamp": self._health.get("last_update", ""),
                "floors": floors,
                "system": self._get_system_summary_internal(),
            }

    def get_room_history(self, room_id: str) -> List[Dict]:
        """
        Get history buffer for a specific room.

        Args:
            room_id: Room identifier string

        Returns:
            List of historical data points
        """
        with self._lock:
            history = self._history.get(room_id, deque())
            return list(history)

    def get_all_history(self) -> Dict[str, List[Dict]]:
        """Get history for all rooms."""
        with self._lock:
            return {
                room_id: list(hist)
                for room_id, hist in self._history.items()
            }

    def get_system_summary(self) -> Dict[str, Any]:
        """Get building-wide system summary."""
        with self._lock:
            return self._get_system_summary_internal()

    def _get_system_summary_internal(self) -> Dict[str, Any]:
        """Internal method for system summary (caller must hold lock)."""
        total_rooms = len(self._rooms)
        occupied_rooms = sum(
            1 for r in self._rooms.values()
            if r.get("ai", {}).get("predicted_occupancy", 0) == 1
        )
        empty_rooms = total_rooms - occupied_rooms

        # Total energy
        total_power = sum(
            r.get("energy", {}).get("estimated_power_watts", 0.0)
            for r in self._rooms.values()
        )
        total_energy = sum(
            r.get("energy", {}).get("cumulative_energy_wh", 0.0)
            for r in self._rooms.values()
        )

        # Check stale data
        self._check_stale_data()

        # Get energy optimization summary (baseline vs AI)
        opt_summary = self._optimizer.get_building_summary()

        return {
            "total_rooms": total_rooms,
            "occupied_rooms": occupied_rooms,
            "empty_rooms": empty_rooms,
            "total_power_watts": round(total_power, 1),
            "total_cumulative_energy_wh": round(total_energy, 2),
            "model_loaded": self._health.get("model_loaded", False),
            "api_online": self._health.get("api_online", True),
            "simulation_running": self._health.get("simulation_running", False),
            "simulation_connected": self._health.get("simulation_connected", False),
            "simulation_time": self._health.get("simulation_time"),  # AUTHORITATIVE - from StateManager only
            "data_stale": self._health.get("data_stale", False),
            "last_update": self._health.get("last_api_update", ""),
            # Energy optimization (baseline vs AI)
            "baseline_power_watts": opt_summary.get("baseline_power_watts", 0),
            "ai_power_watts": opt_summary.get("ai_power_watts", 0),
            "baseline_energy_wh": opt_summary.get("baseline_energy_wh", 0),
            "ai_energy_wh": opt_summary.get("ai_energy_wh", 0),
            "energy_saved_wh": opt_summary.get("energy_saved_wh", 0),
            "percentage_saved": opt_summary.get("percentage_saved", 0),
        }

    def set_simulation_active(self, active: bool):
        """Set simulation active status."""
        with self._lock:
            self._health["simulation_active"] = active

    def reset_energy(self):
        """Reset all energy counters."""
        self._energy.reset_all()
        self._optimizer.reset_all()
        self._sys_logger.log_energy("All energy counters reset", sim_time=self._health.get("simulation_time"))
        logger.info("Energy counters reset via StateManager")

    def set_simulation_status(
        self,
        active: bool,
        connected: bool,
        sim_time: Optional[str] = None,
        speed_factor: float = 60.0,
    ):
        """
        Update simulation connection and status.

        Call this at the start of each simulation update cycle to track:
        - Whether simulation is running
        - Whether simulation is connected
        - Current simulation time (for real-time sync)
        - Simulation speed factor

        Args:
            active: Simulation is active/running
            connected: Simulation data source is connected
            sim_time: Current simulation time (ISO format or --:--:--)
            speed_factor: Simulation speed multiplier
        """
        with self._lock:
            self._health["simulation_active"] = active
            self._health["simulation_connected"] = connected
            self._health["simulation_time"] = sim_time
            self._health["simulation_speed_factor"] = speed_factor

            if connected and active:
                self._health["last_simulation_update"] = datetime.now().isoformat()
                self._check_stale_data()  # Reset stale flag on update

            logger.debug(
                f"Simulation status: active={active}, connected={connected}, time={sim_time}"
            )

    def _check_stale_data(self):
        """Check if data is stale (no update within threshold)."""
        threshold = self._health.get("stale_threshold_seconds", 5.0)
        last_update = self._health.get("last_simulation_update")

        if last_update is None:
            self._health["data_stale"] = True
            return

        try:
            last_dt = datetime.fromisoformat(last_update)
            now = datetime.now()
            age_seconds = (now - last_dt).total_seconds()
            self._health["data_stale"] = age_seconds > threshold
        except Exception:
            self._health["data_stale"] = True

    def get_simulation_status(self) -> Dict[str, Any]:
        """
        Get comprehensive simulation status.

        Returns:
            Dict with active, connected, time, stale flag, speed, last update
        """
        with self._lock:
            self._check_stale_data()  # Ensure stale flag is current
            return {
                "active": self._health.get("simulation_active", False),
                "connected": self._health.get("simulation_connected", False),
                "time": self._health.get("simulation_time", None),
                "speed_factor": self._health.get("simulation_speed_factor", 60.0),
                "stale": self._health.get("data_stale", False),
                "last_update": self._health.get("last_simulation_update", None),
            }

    def get_optimization_weights(self) -> Dict[str, float]:
        """Retrieve current optimization weights (alpha, beta, gamma)."""
        with self._lock:
            return self.optimization_weights.copy()

    def set_optimization_weights(self, alpha: Optional[float], beta: Optional[float], gamma: Optional[float]):
        """Update optimization weights dynamically."""
        with self._lock:
            if alpha is not None:
                self.optimization_weights["alpha"] = float(alpha)
            if beta is not None:
                self.optimization_weights["beta"] = float(beta)
            if gamma is not None:
                self.optimization_weights["gamma"] = float(gamma)
            logger.info(f"Optimization weights updated: {self.optimization_weights}")
