import logging
from typing import Dict, Any, List
from .room_agent import RoomAgent

logger = logging.getLogger(__name__)

class FloorAgent:
    """
    Floor Agent manages all rooms on a specific floor.
    It orchestrates RoomAgents and aggregates floor-level metrics.
    """
    
    def __init__(self, floor_id: int, floor_config: Dict[str, Any], inference_service=None):
        self.floor_id = floor_id
        self.name = floor_config.get("name", f"Floor {floor_id}")
        self.floor_type = floor_config.get("floor_type", "unknown")
        
        # Initialize room agents
        self.room_agents = {}
        for room_cfg in floor_config.get("rooms", []):
            r_id = room_cfg["room_id"]
            self.room_agents[r_id] = RoomAgent(
                room_id=r_id,
                room_type=room_cfg["type"],
                inference_service=inference_service
            )
            
    def step(self, floor_sensor_data: Dict[str, Dict[str, float]]) -> List[Dict[str, Any]]:
        """
        Process sensor data for all rooms on the floor.
        floor_sensor_data: dict of room_id -> sensor data dict
        Returns a list of room state deltas for this floor.
        """
        floor_deltas = []
        for room_id, sensor_data in floor_sensor_data.items():
            if room_id in self.room_agents:
                agent = self.room_agents[room_id]
                delta = agent.step(sensor_data)
                floor_deltas.append(delta)
            else:
                logger.warning(f"Floor {self.floor_id}: No agent for room {room_id}")
                
        return floor_deltas
