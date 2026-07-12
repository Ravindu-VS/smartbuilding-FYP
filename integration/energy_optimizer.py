"""
Energy Optimizer — Baseline vs AI Energy Comparison

Tracks energy consumption in two parallel modes:

A. BASELINE MODE:
   - Lights always ON, HVAC always NORMAL for every room
   - Represents worst-case "no intelligence" energy usage

B. AI MODE:
   - Uses actual ML controller decisions (EMPTY/STANDBY/OCCUPIED)
   - Represents real energy usage with AI optimization

Computes:
   - energy_baseline   (Wh) — what we WOULD have used without AI
   - energy_ai         (Wh) — what we ACTUALLY used with AI
   - energy_saved      (Wh) — difference
   - percentage_saved  (%) — savings percentage

Thread-safe. Per-room and building-wide tracking.
"""

import time
import logging
import threading
from typing import Dict, Any, Optional

from integration.config import (
    ENERGY_PARAMS, ROOM_ENERGY_MULTIPLIER,
    BASELINE_LIGHT_ACTION, BASELINE_HVAC_ACTION,
)

logger = logging.getLogger(__name__)


class RoomEnergyOptimizer:
    """Tracks baseline and AI energy for a single room."""

    def __init__(self, room_id: str, room_type: str):
        self.room_id = room_id
        self.room_type = room_type

        # Cumulative energy counters
        self.baseline_energy_wh = 0.0
        self.ai_energy_wh = 0.0

        # Last power readings (for display)
        self.baseline_power_watts = 0.0
        self.ai_power_watts = 0.0

        # Timing
        # We no longer use time.time() directly; we use deterministic `dt` from the simulation loop.

    def _compute_power(self, light_action: str, hvac_action: str) -> float:
        """Compute instantaneous power for given actions."""
        light_power = ENERGY_PARAMS["lights"].get(light_action, 5.0)
        hvac_power = ENERGY_PARAMS["hvac"].get(hvac_action, 10.0)
        base_load = ENERGY_PARAMS["base_load"].get(self.room_type, 50.0)
        multiplier = ROOM_ENERGY_MULTIPLIER.get(self.room_type, 1.0)
        return (light_power + hvac_power + base_load) * multiplier

    def update(self, ai_light_action: str, ai_hvac_action: str, dt: float = 2.0):
        """
        Update both baseline and AI energy with current actions based on simulation delta time.

        Args:
            ai_light_action: Actual ML controller light action (OFF/DIM/ON)
            ai_hvac_action: Actual ML controller HVAC action (ECO/LOW/NORMAL)
            dt: Delta time elapsed in seconds (e.g. 2.0 for 2-second simulation tick)
        """
        # Compute power for both modes
        self.baseline_power_watts = self._compute_power(
            BASELINE_LIGHT_ACTION, BASELINE_HVAC_ACTION
        )
        self.ai_power_watts = self._compute_power(
            ai_light_action, ai_hvac_action
        )

        # Accumulate energy (Wh) deterministically based on simulation time tick
        elapsed_hours = dt / 3600.0
        self.baseline_energy_wh += self.baseline_power_watts * elapsed_hours
        self.ai_energy_wh += self.ai_power_watts * elapsed_hours

    @property
    def energy_saved_wh(self) -> float:
        """Energy saved by AI vs baseline."""
        return max(0.0, self.baseline_energy_wh - self.ai_energy_wh)

    @property
    def percentage_saved(self) -> float:
        """Percentage of energy saved vs baseline."""
        if self.baseline_energy_wh <= 0:
            return 0.0
        return (self.energy_saved_wh / self.baseline_energy_wh) * 100.0

    def get_summary(self) -> Dict[str, float]:
        """Get room energy optimization summary."""
        return {
            "baseline_power_watts": round(self.baseline_power_watts, 1),
            "ai_power_watts": round(self.ai_power_watts, 1),
            "baseline_energy_wh": round(self.baseline_energy_wh, 2),
            "ai_energy_wh": round(self.ai_energy_wh, 2),
            "energy_saved_wh": round(self.energy_saved_wh, 2),
            "percentage_saved": round(self.percentage_saved, 1),
        }

    def reset(self):
        """Reset all counters."""
        self.baseline_energy_wh = 0.0
        self.ai_energy_wh = 0.0
        self.baseline_power_watts = 0.0
        self.ai_power_watts = 0.0


class EnergyOptimizer:
    """
    Building-wide energy optimization tracker.

    Manages per-room optimizers and provides building-wide totals
    comparing baseline (always-on) vs AI-controlled energy usage.

    Usage:
        optimizer = EnergyOptimizer()
        optimizer.register_room("office_1", "office")
        optimizer.update_room("office_1", "OFF", "ECO")
        summary = optimizer.get_building_summary()
    """

    def __init__(self):
        self._rooms: Dict[str, RoomEnergyOptimizer] = {}
        self._lock = threading.Lock()
        logger.info("✓ EnergyOptimizer initialized (baseline vs AI tracking)")

    def register_room(self, room_id: str, room_type: str):
        """Register a room for optimization tracking."""
        with self._lock:
            if room_id not in self._rooms:
                self._rooms[room_id] = RoomEnergyOptimizer(room_id, room_type)

    def update_room(
        self, room_id: str, ai_light_action: str, ai_hvac_action: str, dt: float = 2.0
    ) -> Dict[str, float]:
        """
        Update energy for a room with current AI control actions.

        Args:
            room_id: Room identifier
            ai_light_action: ML controller light action
            ai_hvac_action: ML controller HVAC action
            dt: Delta time elapsed in seconds

        Returns:
            Room optimization summary dict
        """
        with self._lock:
            tracker = self._rooms.get(room_id)
            if tracker is None:
                return {}
            tracker.update(ai_light_action, ai_hvac_action, dt=dt)
            return tracker.get_summary()

    def get_room_summary(self, room_id: str) -> Dict[str, float]:
        """Get optimization summary for a specific room."""
        with self._lock:
            tracker = self._rooms.get(room_id)
            if tracker is None:
                return {}
            return tracker.get_summary()

    def get_building_summary(self) -> Dict[str, Any]:
        """
        Get building-wide optimization summary.

        Returns:
            Dict with total baseline, AI, saved, percentage for all rooms.
        """
        with self._lock:
            total_baseline_power = 0.0
            total_ai_power = 0.0
            total_baseline_energy = 0.0
            total_ai_energy = 0.0
            per_room = {}

            for room_id, tracker in self._rooms.items():
                summary = tracker.get_summary()
                per_room[room_id] = summary
                total_baseline_power += summary["baseline_power_watts"]
                total_ai_power += summary["ai_power_watts"]
                total_baseline_energy += summary["baseline_energy_wh"]
                total_ai_energy += summary["ai_energy_wh"]

            total_saved = max(0.0, total_baseline_energy - total_ai_energy)
            pct_saved = (
                (total_saved / total_baseline_energy * 100.0)
                if total_baseline_energy > 0
                else 0.0
            )

            return {
                "baseline_power_watts": round(total_baseline_power, 1),
                "ai_power_watts": round(total_ai_power, 1),
                "baseline_energy_wh": round(total_baseline_energy, 2),
                "ai_energy_wh": round(total_ai_energy, 2),
                "energy_saved_wh": round(total_saved, 2),
                "percentage_saved": round(pct_saved, 1),
                "per_room": per_room,
            }

    def reset_all(self):
        """Reset all room energy counters."""
        with self._lock:
            for tracker in self._rooms.values():
                tracker.reset()
        logger.info("EnergyOptimizer: All counters reset")
