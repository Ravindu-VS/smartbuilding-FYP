import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class RoomAgent:
    """
    Room Agent is responsible for managing a single room's environment.
    It reads sensor data, infers occupancy, and makes HVAC/lighting decisions.
    """
    
    def __init__(self, room_id: str, room_type: str, inference_service=None):
        self.room_id = room_id
        self.room_type = room_type
        self.inference_service = inference_service
        from integration.building_config import get_room_control_tuning
        self.tuning = get_room_control_tuning(self.room_type)
        
    def step(self, sensor_data: Dict[str, float]) -> Dict[str, Any]:
        """
        Process the current sensor data, decide on actions, and return the room's state delta.
        """
        occupancy_prob = 0.0
        prediction = 0
        
        # 1. Infer Occupancy
        # Respect edge computing: If the physical node (e.g., Room 101) already ran inference, use it!
        if "edge_occupancy_probability" in sensor_data:
            occupancy_prob = sensor_data["edge_occupancy_probability"]
            prediction = 1 if occupancy_prob >= 0.5 else 0
            logger.debug(f"Room {self.room_id} using edge AI prediction: {occupancy_prob}")
        elif self.inference_service:
            try:
                # inference_service takes dict of sensors
                result = self.inference_service.predict(sensor_data)
                occupancy_prob = result.occupancy_probability
                prediction = result.occupancy_prediction
            except Exception as e:
                logger.error(f"Error inferring occupancy for {self.room_id}: {e}")
        
        # 2. Control Decision
        # Using tuning thresholds for this room type
        if occupancy_prob < self.tuning["empty_threshold"]:
            light_action = "OFF"
            hvac_action = "ECO"
            control_mode = "EMPTY"
        elif occupancy_prob < self.tuning["occupied_threshold"]:
            light_action = "DIM"
            hvac_action = "LOW"
            control_mode = "STANDBY"
        else:
            light_action = "ON"
            hvac_action = "NORMAL"
            control_mode = "OCCUPIED"
            
        # Returning state payload format matching StateManager's needs
        return {
            "room_id": self.room_id,
            "ai": {
                "predicted_occupancy": prediction,
                "occupancy_probability": occupancy_prob
            },
            "control": {
                "light_action": light_action,
                "hvac_action": hvac_action,
                "control_mode": control_mode
            }
        }
