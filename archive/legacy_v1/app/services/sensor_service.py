"""
Sensor Data Service — Ingestion, validation, and state management bridge.
Wraps the existing hardware/sensor_gateway module with async FastAPI interface.
"""
import logging
from datetime import datetime
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class SensorService:
    """
    Service layer for sensor data ingestion and retrieval.
    Bridges ESP32 hardware / WSO2 MI payloads to the internal StateManager.
    """

    def __init__(self, state_manager=None, db_persistence=None):
        self.state_manager = state_manager
        self.db = db_persistence

    def ingest_telemetry(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process incoming sensor telemetry from WSO2 MI or direct HTTP POST.
        Validates ranges, updates state manager, and returns status.

        Args:
            payload: Dict with keys: room_id, telemetry (temp, humidity, co2, lux), source

        Returns:
            Dict with status, room_id, and optional occupancy prediction
        """
        # Extract fields
        room_id = payload.get("room_id")
        telemetry = payload.get("telemetry", {})
        source = payload.get("source", "hardware")
        timestamp = payload.get("timestamp", datetime.now().isoformat())

        if not room_id:
            # Try to parse room_id from MQTT topic
            topic = payload.get("topic", "")
            if topic:
                room_id = self._parse_room_id_from_topic(topic)

        if not room_id:
            raise ValueError("Missing room_id in sensor payload")

        # Validate sensor ranges
        validated = self._validate_readings(telemetry)

        # Build internal state update
        state_update = {
            "room_id": room_id,
            "temperature": validated.get("temperature", 22.0),
            "humidity": validated.get("humidity", 50.0),
            "co2": validated.get("co2", 400.0),
            "lux": validated.get("lux", 0.0),
            "source": source,
            "timestamp": timestamp,
        }

        # Update state manager if available
        occupancy_pred = None
        if self.state_manager:
            try:
                self.state_manager.update_hardware_room(room_id, state_update)
                logger.info(f"✓ Sensor data ingested for room {room_id} (source={source})")
            except Exception as e:
                logger.error(f"StateManager update failed for {room_id}: {e}")

        # Persist to database if available
        if self.db:
            try:
                self.db.log_sensor_reading(room_id, state_update)
            except Exception as e:
                logger.debug(f"DB logging skipped: {e}")

        return {
            "status": "success",
            "room_id": room_id,
            "message": f"Telemetry ingested for {room_id} via {source}",
            "occupancy_prediction": occupancy_pred,
        }

    def get_latest_reading(self, room_id: str) -> Optional[Dict[str, Any]]:
        """Get the most recent sensor reading for a room."""
        if self.state_manager:
            state = self.state_manager.get_zone_state(room_id)
            if state:
                return {
                    "room_id": room_id,
                    "temperature": state.get("temperature", 22.0),
                    "humidity": state.get("humidity", 50.0),
                    "co2": state.get("co2", 400.0),
                    "lux": state.get("illumination", 0.0),
                    "source": state.get("source", "simulated"),
                    "timestamp": datetime.now().isoformat(),
                }
        return None

    def _validate_readings(self, telemetry: Dict[str, float]) -> Dict[str, float]:
        """Validate sensor readings are within physical bounds."""
        validated = {}
        bounds = {
            "temperature": (-20.0, 60.0),
            "humidity": (0.0, 100.0),
            "co2": (0.0, 5000.0),
            "lux": (0.0, 100000.0),
        }
        for key, (lo, hi) in bounds.items():
            val = telemetry.get(key)
            if val is not None:
                val = float(val)
                if val < lo or val > hi:
                    logger.warning(f"Sensor {key}={val} out of bounds [{lo}, {hi}], clamping")
                    val = max(lo, min(hi, val))
                validated[key] = val
        return validated

    def _parse_room_id_from_topic(self, topic: str) -> Optional[str]:
        """
        Parse room_id from MQTT topic.
        Expected format: building/A/floor/1/room/101/sensor
        """
        parts = topic.strip("/").split("/")
        try:
            floor_idx = parts.index("floor")
            room_idx = parts.index("room")
            floor_num = parts[floor_idx + 1]
            room_num = parts[room_idx + 1]
            return f"f{floor_num}_room_{room_num}"
        except (ValueError, IndexError):
            return None
