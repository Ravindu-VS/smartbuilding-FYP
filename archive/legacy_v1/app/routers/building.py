"""
Building Router — Building status, room states, and digital twin data.
"""
from fastapi import APIRouter, HTTPException
from datetime import datetime
from typing import Optional

from app.models.schemas import BuildingStatusResponse, RoomState

router = APIRouter(prefix="/building", tags=["Building"])

_state_manager = None
_building_config = None


def set_building_context(state_manager, building_config=None):
    global _state_manager, _building_config
    _state_manager = state_manager
    _building_config = building_config


@router.get("/status",
            summary="Full building status",
            description="Complete building state including all floors, rooms, sensors, and system metrics")
async def get_building_status():
    """Get the complete building state for monitoring and visualization."""
    now = datetime.now()

    if _state_manager is None:
        # Return structural info even without live data
        return {
            "timestamp": now.isoformat(),
            "building_name": "Smart Office Building",
            "total_floors": 5,
            "total_rooms": 26,
            "occupied_rooms": 0,
            "floors": [],
            "total_power_watts": 0.0,
            "total_cumulative_energy_wh": 0.0,
            "simulation_running": False,
            "outdoor_temperature": None,
        }

    try:
        summary = _state_manager.get_system_summary()
        rooms_data = _state_manager.get_all_room_states()

        # Organize rooms by floor
        floors = {}
        for room_id, state in rooms_data.items():
            floor_num = state.get("floor", 1)
            if floor_num not in floors:
                floors[floor_num] = {
                    "floor_number": floor_num,
                    "rooms": [],
                    "total_power_watts": 0.0,
                    "occupied_rooms": 0,
                }

            room_state = {
                "room_id": room_id,
                "room_name": state.get("name", room_id),
                "floor": floor_num,
                "room_type": state.get("type", "office"),
                "temperature": round(state.get("temperature", 22.0), 1),
                "humidity": round(state.get("humidity", 50.0), 1),
                "co2": round(state.get("co2", 400.0), 1),
                "lux": round(state.get("illumination", 0.0), 1),
                "occupancy": state.get("occupancy", 0),
                "occupancy_probability": state.get("occupancy_probability", 0.0),
                "hvac_setpoint": round(state.get("hvac_setpoint", 22.0), 1),
                "hvac_mode": state.get("hvac_mode", "auto"),
                "dimming_level": round(state.get("dimming_level", 0.5), 2),
                "power_watts": round(state.get("power_watts", 0.0), 1),
                "cumulative_energy_wh": round(state.get("cumulative_energy_wh", 0.0), 1),
                "data_source": state.get("source", "simulated"),
                "last_update": state.get("last_update"),
            }

            floors[floor_num]["rooms"].append(room_state)
            floors[floor_num]["total_power_watts"] += room_state["power_watts"]
            if room_state["occupancy"] > 0:
                floors[floor_num]["occupied_rooms"] += 1

        floor_list = [floors[k] for k in sorted(floors.keys())]

        return {
            "timestamp": now.isoformat(),
            "building_name": "Smart Office Building",
            "total_floors": len(floor_list),
            "total_rooms": summary.get("total_rooms", 26),
            "occupied_rooms": summary.get("occupied_rooms", 0),
            "floors": floor_list,
            "total_power_watts": summary.get("total_power_watts", 0.0),
            "total_cumulative_energy_wh": summary.get("total_cumulative_energy_wh", 0.0),
            "simulation_running": True,
            "outdoor_temperature": summary.get("outdoor_temperature"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rooms/{room_id}",
            summary="Individual room state",
            description="Get detailed state for a specific room")
async def get_room_state(room_id: str):
    """Get the current state of a specific room."""
    if _state_manager is None:
        raise HTTPException(status_code=503, detail="State manager not initialized")

    state = _state_manager.get_zone_state(room_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Room {room_id} not found")

    return {
        "room_id": room_id,
        "state": state,
        "timestamp": datetime.now().isoformat(),
    }


@router.get("/digital-twin",
            summary="Digital twin state",
            description="Optimized state payload for 3D visualization rendering")
async def get_digital_twin_state():
    """
    Get the building state optimized for 3D digital twin visualization.
    Returns compact room state data with visualization-relevant fields.
    """
    if _state_manager is None:
        return {"rooms": [], "timestamp": datetime.now().isoformat()}

    try:
        rooms_data = _state_manager.get_all_room_states()
        twin_rooms = []

        for room_id, state in rooms_data.items():
            twin_rooms.append({
                "id": room_id,
                "floor": state.get("floor", 1),
                "temp": round(state.get("temperature", 22.0), 1),
                "occ": state.get("occupancy", 0),
                "power": round(state.get("power_watts", 0.0), 0),
                "hvac": state.get("hvac_mode", "auto"),
                "light": round(state.get("dimming_level", 0.5), 2),
                "source": state.get("source", "simulated"),
            })

        return {
            "rooms": twin_rooms,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
