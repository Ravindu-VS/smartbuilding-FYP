"""
Decision Display — Integrated

Decision reasoning is now embedded in the main dashboard panel (ui.py).
This module provides the update logic for decision-related fields
while keeping the display integrated (no separate overlay).
"""

from panda3d.core import TextNode, Point2
from typing import Dict, Optional


class DecisionDisplay:
    """
    Updates decision-related fields in the integrated dashboard.
    No longer creates its own text elements — uses the HUD's elements.
    """

    def __init__(self, app):
        """
        Initialize decision display.

        Args:
            app: ShowBase application instance
        """
        self.app = app
        self.decision_history = {}

    def update(self, simulation_state: dict, selected_room_id: int):
        """
        Update decision fields in the HUD.

        Args:
            simulation_state: Current simulation state
            selected_room_id: Currently selected room
        """
        if "rooms" not in simulation_state or selected_room_id not in simulation_state["rooms"]:
            return

        room_state = simulation_state["rooms"][selected_room_id]
        hud = self.app.hud

        # Determine trend
        comfort = room_state.get("comfort_index", 100.0)
        energy = room_state.get("energy_use", 0.0)
        room_key = f"room_{selected_room_id}_comfort"
        old_comfort = self.decision_history.get(room_key, comfort)
        self.decision_history[room_key] = comfort

        if comfort > old_comfort + 2:
            trend_text = "Trend: improving ↗"
            trend_color = (0.3, 1.0, 0.5, 1.0)
        elif comfort < old_comfort - 2:
            trend_text = "Trend: declining ↘"
            trend_color = (1.0, 0.4, 0.4, 1.0)
        else:
            trend_text = "Trend: stable →"
            trend_color = (0.7, 0.7, 0.4, 1.0)

        hud._set_text("decision_trend", trend_text, trend_color)

        # Effectiveness
        if comfort > 85 and energy < 400:
            status = "Excellent ✓"
            status_color = (0.3, 1.0, 0.5, 1.0)
        elif comfort > 70 and energy < 500:
            status = "Good ✓"
            status_color = (0.5, 0.9, 0.4, 1.0)
        elif comfort > 50:
            status = "Fair"
            status_color = (1.0, 0.75, 0.2, 1.0)
        else:
            status = "Needs attention ⚠"
            status_color = (1.0, 0.4, 0.3, 1.0)

        # Balance score
        c_score = min(10, comfort / 10)
        e_score = max(0, 10 - (energy / 100))
        balance = int((c_score + e_score) / 2)

        hud._set_text("decision_effectiveness",
                       f"{status} | Balance: {balance}/10",
                       status_color)
