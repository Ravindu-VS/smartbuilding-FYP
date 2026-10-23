import logging
from typing import Dict, Any, List
from .floor_agent import FloorAgent

logger = logging.getLogger(__name__)

class BuildingAgent:
    """
    Building Agent manages the entire building.
    It orchestrates FloorAgents and can make building-wide decisions 
    (e.g., demand response, global HVAC optimization).
    """
    
    def __init__(self, building_config: Dict[str, Any], inference_service=None):
        self.building_id = building_config.get("building_id", "building_1")
        self.name = building_config.get("name", "Smart Building")
        
        # Initialize floor agents
        self.floor_agents = {}
        for floor_cfg in building_config.get("floors", []):
            f_id = floor_cfg["floor_id"]
            self.floor_agents[f_id] = FloorAgent(
                floor_id=f_id,
                floor_config=floor_cfg,
                inference_service=inference_service
            )
            
    def step(self, building_sensor_data: Dict[int, Dict[str, Dict[str, float]]]) -> List[Dict[str, Any]]:
        """
        Process sensor data for the entire building.
        building_sensor_data: dict of floor_id -> {room_id -> sensor data dict}
        Returns a flat list of room state deltas for the entire building.
        """
        building_deltas = []
        for floor_id, floor_sensor_data in building_sensor_data.items():
            if floor_id in self.floor_agents:
                agent = self.floor_agents[floor_id]
                deltas = agent.step(floor_sensor_data)
                building_deltas.extend(deltas)
            else:
                logger.warning(f"Building: No agent for floor {floor_id}")
                
        return building_deltas
