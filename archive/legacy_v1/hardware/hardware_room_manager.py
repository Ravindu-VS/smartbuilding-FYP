"""
Hardware Room Manager

Maintains the state of physical rooms (rooms with data_source = 'hardware').
This acts as a memory cache for incoming sensor data from ESP32/IoT devices.
"""
import time
import logging

logger = logging.getLogger("HardwareRoomManager")

class HardwareRoomManager:
    def __init__(self):
        # Maps room_id -> dict of sensor values
        self._physical_states = {}
        
    def update_sensors(self, room_id: str, sensors: dict):
        """Update the current physical state for a room."""
        if room_id not in self._physical_states:
            self._physical_states[room_id] = {
                "id": room_id,
                "source": "hardware",
                "last_update": 0
            }
        
        # Update with new values
        for k, v in sensors.items():
            self._physical_states[room_id][k] = v
            
        self._physical_states[room_id]["last_update"] = time.time()
        logger.debug(f"Hardware room {room_id} updated: {sensors}")

    def get_room_state(self, room_id: str):
        """Retrieve the latest physical state for a room, or None if not hardware."""
        return self._physical_states.get(room_id, None)

    def is_hardware_room(self, room_id: str) -> bool:
        """Check if we have physical data for this room."""
        return room_id in self._physical_states

    def get_all_hardware_states(self) -> dict:
        """Get all physical room states."""
        return self._physical_states

# Singleton instance
hardware_manager = HardwareRoomManager()
