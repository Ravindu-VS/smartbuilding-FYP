"""
Occupancy Prediction Service — Wraps the existing ML inference pipeline.
"""
import os
import sys
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Add project root for imports
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class OccupancyService:
    """
    Async-compatible wrapper around the existing OccupancyInferenceService.
    Provides single and batch occupancy predictions from sensor data.
    """

    def __init__(self, model_path: str = None, threshold: float = 0.20):
        self.model_path = model_path or "models/final_unified_occupancy_pipeline.pkl"
        self.threshold = threshold
        self._service = None
        self._load_model()

    def _load_model(self):
        """Load the occupancy inference pipeline."""
        try:
            from occupancy_inference_service import OccupancyInferenceService
            full_path = os.path.join(PROJECT_ROOT, self.model_path)
            self._service = OccupancyInferenceService(full_path, threshold=self.threshold)
            logger.info(f"✓ Occupancy model loaded from {self.model_path}")
        except Exception as e:
            logger.warning(f"Failed to load occupancy model: {e}. Service will return defaults.")
            self._service = None

    def predict(self, sensor_data: Dict[str, float]) -> Dict[str, Any]:
        """
        Predict occupancy from sensor readings.

        Args:
            sensor_data: Dict with keys Temperature, Humidity, Light, CO2, HumidityRatio

        Returns:
            Dict with probability, prediction, confidence
        """
        if self._service is None:
            return {
                "occupancy_probability": 0.5,
                "occupancy_prediction": 0,
                "confidence": 0.0,
                "model_type": "fallback",
            }

        try:
            result = self._service.predict(sensor_data)
            return {
                "occupancy_probability": float(result.occupancy_probability),
                "occupancy_prediction": int(result.occupancy_prediction),
                "confidence": float(result.confidence),
                "model_type": "LogisticRegression",
            }
        except Exception as e:
            logger.error(f"Occupancy prediction error: {e}")
            return {
                "occupancy_probability": 0.5,
                "occupancy_prediction": 0,
                "confidence": 0.0,
                "model_type": "error_fallback",
            }

    def predict_for_room(self, room_id: str, state_manager=None) -> Dict[str, Any]:
        """
        Predict occupancy for a specific room using its current sensor state.
        """
        if state_manager is None:
            return self.predict({})

        state = state_manager.get_zone_state(room_id)
        if not state:
            return self.predict({})

        sensor_data = {
            "Temperature": state.get("temperature", 22.0),
            "Humidity": state.get("humidity", 50.0),
            "Light": state.get("illumination", 0.0),
            "CO2": state.get("co2", 400.0),
        }
        result = self.predict(sensor_data)
        result["room_id"] = room_id
        return result

    @property
    def is_loaded(self) -> bool:
        return self._service is not None
