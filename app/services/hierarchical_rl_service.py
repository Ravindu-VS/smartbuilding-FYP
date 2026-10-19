import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class RoomAgent:
    def __init__(self, room_id: str):
        self.room_id = room_id
        # In the future, loads specific PPO weights for this room
        
    def optimize(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """ Optimize individual room comfort and energy """
        logger.info(f"[RoomAgent-{self.room_id}] Optimizing based on local state: {state}")
        # Default fallback logic
        return {"hvac_setpoint": 24.0, "lighting": 50, "power_requested": 1.2}

class FloorAgent:
    def __init__(self, floor_id: str):
        self.floor_id = floor_id
        self.room_agents = {}
        
    def add_room(self, room_id: str):
        self.room_agents[room_id] = RoomAgent(room_id)
        
    def optimize(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """ Aggregate room requests and optimize floor-level constraints """
        logger.info(f"[FloorAgent-{self.floor_id}] Balancing floor energy loads.")
        room_actions = {}
        total_power = 0
        
        for room_id, agent in self.room_agents.items():
            action = agent.optimize(state.get(room_id, {}))
            room_actions[room_id] = action
            total_power += action.get("power_requested", 0)
            
        return {"total_floor_power": total_power, "room_actions": room_actions}

class BuildingAgent:
    def __init__(self, building_id: str):
        self.building_id = building_id
        self.floor_agents = {}
        
    def add_floor(self, floor_id: str):
        self.floor_agents[floor_id] = FloorAgent(floor_id)
        
    def optimize(self, global_state: Dict[str, Any]) -> Dict[str, Any]:
        """ Peak shaving, demand response, and global constraints """
        logger.info(f"[BuildingAgent-{self.building_id}] Enforcing peak demand constraints.")
        
        floor_results = {}
        total_building_power = 0
        
        for floor_id, agent in self.floor_agents.items():
            result = agent.optimize(global_state.get(floor_id, {}))
            floor_results[floor_id] = result
            total_building_power += result.get("total_floor_power", 0)
            
        # Example peak shaving logic
        peak_limit = global_state.get("peak_limit", 50.0)
        if total_building_power > peak_limit:
            logger.warning(f"Total power {total_building_power}kW exceeds peak limit {peak_limit}kW! Throttling.")
            
        return {
            "status": "optimized",
            "total_power_kw": total_building_power,
            "peak_limit_enforced": peak_limit,
            "allocations": floor_results
        }

class HierarchicalRLService:
    def __init__(self):
        self.building_agent = BuildingAgent("B1")
        # Initialize 5 floors as per master prompt
        for i in range(1, 6):
            self.building_agent.add_floor(f"Floor_{i}")
            
    def get_optimal_actions(self, global_state: Dict[str, Any]) -> Dict[str, Any]:
        return self.building_agent.optimize(global_state)
