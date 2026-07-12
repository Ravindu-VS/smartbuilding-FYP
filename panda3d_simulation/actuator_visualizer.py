"""
Actuator Visual Effects Renderer

Applies actuator decisions (lights, HVAC, shading) to 3D room geometry.
Bridges ActuatorEffectsManager output to visual scene updates.
"""

from panda3d.core import Vec4
from panda3d_simulation.actuator_effects import ActuatorEffectsManager
from typing import Dict


class RoomVisualUpdater:
    """
    Updates room visual appearance based on actuator effects.

    Applies:
    - HVAC mode colors (red/blue/gray wall tint)
    - Window shading opacity
    - Light glow is handled by Room._update_light() directly
    """

    def __init__(self, room, effects_manager: ActuatorEffectsManager):
        self.room = room
        self.room_id = room.id
        self.effects_manager = effects_manager

        # Store original wall color for blending
        self.base_wall_color = Vec4(*room.wall_color)

    def update(self, dt: float):
        if self.room_id not in self.effects_manager.light_effects:
            return

        # Update HVAC color tint on walls
        self._update_hvac_color_tint()

        # Update window shading opacity
        self._update_window_shading()

    def _update_hvac_color_tint(self):
        """Apply subtle wall color tint based on HVAC mode."""
        hvac_mode, hvac_speed, _ = self.effects_manager.get_hvac_status(self.room_id)

        if hvac_mode == "off":
            return  # No tint

        # Tint intensity based on speed
        tint_factor = 0.05 + hvac_speed * 0.12  # Subtle: 5-17%

        if hvac_mode == "heating":
            tint = Vec4(tint_factor * 0.8, -tint_factor * 0.2, -tint_factor * 0.3, 0)
        elif hvac_mode == "cooling":
            tint = Vec4(-tint_factor * 0.2, tint_factor * 0.1, tint_factor * 0.8, 0)
        elif hvac_mode == "fan_only":
            tint = Vec4(tint_factor * 0.1, tint_factor * 0.1, tint_factor * 0.1, 0)
        else:
            return

        # Apply to walls via colorScale
        final = Vec4(
            max(0.0, min(1.0, 1.0 + tint.getX())),
            max(0.0, min(1.0, 1.0 + tint.getY())),
            max(0.0, min(1.0, 1.0 + tint.getZ())),
            1.0
        )
        self.room.set_wall_color(final)

    def _update_window_shading(self):
        """Update window tint based on shading factor."""
        if self.room_id not in self.effects_manager.shading_effects:
            return

        brightness = self.effects_manager.shading_effects[self.room_id].get_window_brightness()

        shaded_color = Vec4(
            0.7 * brightness,
            0.85 * brightness,
            1.0 * brightness,
            0.8
        )
        self.room.set_window_color(shaded_color)


class ActuatorVisualizerManager:
    """
    Manages visual updates for all rooms based on actuator effects.
    """

    def __init__(self, scene, effects_manager: ActuatorEffectsManager):
        self.scene = scene
        self.effects_manager = effects_manager
        self.room_updaters: Dict[int, RoomVisualUpdater] = {}

        for room_id, room in scene.rooms.items():
            self.room_updaters[room_id] = RoomVisualUpdater(room, effects_manager)

    def update(self, dt: float):
        for room_id, updater in self.room_updaters.items():
            updater.update(dt)
