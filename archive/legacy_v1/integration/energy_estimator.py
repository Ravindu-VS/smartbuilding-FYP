"""
Energy Estimator

Computes per-room instantaneous power (W) and cumulative energy (Wh)
based on control actions (lights, HVAC) and room type.

Also provides building-wide totals.
"""

import logging
import time
from typing import Dict, Any, Optional
from integration.config import ENERGY_PARAMS, ROOM_ENERGY_MULTIPLIER

logger = logging.getLogger(__name__)


class RoomEnergyTracker:
    """Tracks energy for a single room."""

    def __init__(self, room_id: str, room_type: str):
        self.room_id = room_id
        self.room_type = room_type
        self.cumulative_energy_wh = 0.0
        self._last_update_time: Optional[float] = None

    def compute_power(self, light_action: str, hvac_action: str) -> float:
        """
        Compute instantaneous power draw for this room.

        Args:
            light_action: "OFF", "DIM", or "ON"
            hvac_action: "ECO", "OFF", "LOW", or "NORMAL"

        Returns:
            Power in watts
        """
        # Light power
        light_power = ENERGY_PARAMS["lights"].get(light_action, 5.0)

        # HVAC power
        hvac_power = ENERGY_PARAMS["hvac"].get(hvac_action, 10.0)

        # Base load for this room type
        base_load = ENERGY_PARAMS["base_load"].get(self.room_type, 50.0)

        # Room-type multiplier
        multiplier = ROOM_ENERGY_MULTIPLIER.get(self.room_type, 1.0)

        total_power = (light_power + hvac_power + base_load) * multiplier
        return round(total_power, 1)

    def update_cumulative(self, power_watts: float, dt: Optional[float] = None):
        """
        Update cumulative energy based on power and elapsed time.

        Args:
            power_watts: Current instantaneous power in watts
            dt: Delta time elapsed in seconds (e.g. from simulation). If None, falls back to wall clock.
        """
        if dt is not None:
            elapsed_hours = dt / 3600.0
            self.cumulative_energy_wh += power_watts * elapsed_hours
            self._last_update_time = time.time()
        else:
            now = time.time()
            if self._last_update_time is not None:
                elapsed_hours = (now - self._last_update_time) / 3600.0
                self.cumulative_energy_wh += power_watts * elapsed_hours
            self._last_update_time = now

    def reset(self):
        """Reset cumulative energy counter."""
        self.cumulative_energy_wh = 0.0
        self._last_update_time = time.time()
        logger.info(f"Energy counter reset for {self.room_id}")


class EnergyEstimator:
    """
    Building-wide energy estimation.

    Manages per-room energy trackers and provides building totals.
    """

    def __init__(self):
        self._trackers: Dict[str, RoomEnergyTracker] = {}
        logger.info("✓ EnergyEstimator initialized")

    def register_room(self, room_id: str, room_type: str):
        """Register a room for energy tracking."""
        if room_id not in self._trackers:
            self._trackers[room_id] = RoomEnergyTracker(room_id, room_type)

    def estimate_room_energy(
        self, room_id: str, light_action: str, hvac_action: str, dt: Optional[float] = None
    ) -> Dict[str, float]:
        """
        Compute power and update cumulative energy for a room.

        Args:
            room_id: Room identifier (e.g., "office_1")
            light_action: Current light action ("OFF", "DIM", "ON")
            hvac_action: Current HVAC action ("ECO", "OFF", "LOW", "NORMAL")
            dt: Optional elapsed simulation time in seconds

        Returns:
            Dict with estimated_power_watts and cumulative_energy_wh
        """
        tracker = self._trackers.get(room_id)
        if tracker is None:
            return {"estimated_power_watts": 0.0, "cumulative_energy_wh": 0.0}

        power = tracker.compute_power(light_action, hvac_action)
        tracker.update_cumulative(power, dt)

        return {
            "estimated_power_watts": power,
            "cumulative_energy_wh": round(tracker.cumulative_energy_wh, 2),
        }

    def get_building_totals(self) -> Dict[str, float]:
        """
        Get building-wide energy totals.

        Returns:
            Dict with total_power_watts and total_cumulative_energy_wh
        """
        total_power = 0.0
        total_energy = 0.0

        for tracker in self._trackers.values():
            # Use last known power (re-compute would need current state)
            total_energy += tracker.cumulative_energy_wh

        return {
            "total_power_watts": total_power,  # Updated by caller
            "total_cumulative_energy_wh": round(total_energy, 2),
        }

    def reset_all(self):
        """Reset all energy counters."""
        for tracker in self._trackers.values():
            tracker.reset()
        logger.info("All energy counters reset")
