"""
Visual Actuator Effects

Translates control decisions into visual effects in the 3D scene.
- Lights: delegates to Room.set_light_state (no duplicate color control)
- HVAC: visual tint tracking
- Shading: window opacity
- Comfort: color feedback
"""

from panda3d.core import Vec3, Vec4
from panda3d_simulation.scene import Room
from typing import Dict, Optional
import math


class LightEffects:
    """Tracks light state — delegates actual rendering to Room/RoomLight."""

    def __init__(self, room: Room):
        self.room = room
        self.current_intensity = 0.0
        self.target_intensity = 0.0

    def update(self, light_on: bool, dt: float):
        """Track light intensity (Room handles actual brightness)."""
        self.target_intensity = 1.0 if light_on else 0.0

        # Smooth tracking for effect queries
        diff = self.target_intensity - self.current_intensity
        if abs(diff) > 0.01:
            speed = 4.0  # Match RoomLight ramp speed
            if self.current_intensity < self.target_intensity:
                self.current_intensity = min(self.target_intensity, self.current_intensity + speed * dt)
            else:
                self.current_intensity = max(self.target_intensity, self.current_intensity - speed * dt)
        else:
            self.current_intensity = self.target_intensity


class HVACEffects:
    """Manages visual HVAC effects based on control decisions."""

    def __init__(self, room: Room, render_node):
        self.room = room
        self.render_node = render_node
        self.hvac_mode = "off"
        self.hvac_speed = 0.0
        self.effect_intensity = 0.0
        self.target_intensity = 0.0

    def update(self, hvac_mode: str, hvac_speed: float, dt: float):
        self.hvac_mode = hvac_mode
        self.hvac_speed = max(0.0, min(1.0, hvac_speed))

        if hvac_mode == "off":
            self.target_intensity = 0.0
        else:
            self.target_intensity = 0.2 + 0.8 * self.hvac_speed

        diff = self.target_intensity - self.effect_intensity
        if abs(diff) > 0.01:
            self.effect_intensity += diff * 0.2 * min(dt, 0.1)
        else:
            self.effect_intensity = self.target_intensity
        self.effect_intensity = max(0.0, min(1.0, self.effect_intensity))

    def get_effect_color(self) -> Vec3:
        if self.hvac_mode == "heating":
            return Vec3(1.0, 0.4, 0.2) * self.effect_intensity
        elif self.hvac_mode == "cooling":
            return Vec3(0.2, 0.6, 1.0) * self.effect_intensity
        elif self.hvac_mode == "fan_only":
            return Vec3(0.6, 0.6, 0.7) * self.effect_intensity
        return Vec3(0, 0, 0)


class WindowShadingEffects:
    """Manages visual window shading effects."""

    def __init__(self, room: Room):
        self.room = room
        self.current_shading = 0.0
        self.target_shading = 0.0

    def update(self, shading_factor: float, dt: float):
        self.target_shading = max(0.0, min(1.0, shading_factor))
        diff = self.target_shading - self.current_shading
        if abs(diff) > 0.01:
            self.current_shading += diff * 0.3 * min(dt, 0.1)
        else:
            self.current_shading = self.target_shading
        self.current_shading = max(0.0, min(1.0, self.current_shading))

    def get_window_brightness(self) -> float:
        return 1.0 - self.current_shading * 0.7


class ComfortVisualization:
    """Visual feedback for comfort and energy metrics."""

    def __init__(self):
        self.comfort_index = 100.0
        self.energy_watts = 0.0
        self.trend = "stable"

    def update(self, comfort_index: float, energy_watts: float):
        old_comfort = self.comfort_index
        self.comfort_index = max(0.0, min(100.0, comfort_index))
        self.energy_watts = max(0.0, energy_watts)

        if self.comfort_index > old_comfort + 5:
            self.trend = "improving"
        elif self.comfort_index < old_comfort - 5:
            self.trend = "declining"
        else:
            self.trend = "stable"

    def get_comfort_color(self) -> Vec3:
        if self.comfort_index >= 80:
            return Vec3(0.0, 1.0, 0.0)
        elif self.comfort_index >= 60:
            return Vec3(0.5, 1.0, 0.0)
        elif self.comfort_index >= 40:
            return Vec3(1.0, 0.7, 0.0)
        return Vec3(1.0, 0.0, 0.0)


class ActuatorEffectsManager:
    """
    Manages all visual effects from actuator decisions.
    Bridges decision engine output to visual representation.
    """

    def __init__(self, scene, render_node):
        self.scene = scene
        self.render_node = render_node
        self.light_effects: Dict[int, LightEffects] = {}
        self.hvac_effects: Dict[int, HVACEffects] = {}
        self.shading_effects: Dict[int, WindowShadingEffects] = {}
        self.comfort_viz: Dict[int, ComfortVisualization] = {}

        for room_id, room in scene.rooms.items():
            self.light_effects[room_id] = LightEffects(room)
            self.hvac_effects[room_id] = HVACEffects(room, render_node)
            self.shading_effects[room_id] = WindowShadingEffects(room)
            self.comfort_viz[room_id] = ComfortVisualization()

    def update(self, simulation_state: dict, dt: float):
        if "rooms" not in simulation_state:
            return

        room_states = simulation_state["rooms"]
        for room_id, room_state in room_states.items():
            if room_id not in self.light_effects:
                continue

            light_on = room_state.get("light_on", False)
            self.light_effects[room_id].update(light_on, dt)

            hvac_mode = room_state.get("hvac_mode", "off")
            hvac_speed = room_state.get("hvac_speed", 0.0)
            self.hvac_effects[room_id].update(hvac_mode, hvac_speed, dt)

            shading_factor = room_state.get("shading_factor", 0.0)
            self.shading_effects[room_id].update(shading_factor, dt)

            comfort_index = room_state.get("comfort_index", 100.0)
            energy = room_state.get("energy_use", 0.0)
            self.comfort_viz[room_id].update(comfort_index, energy)

    def get_light_intensity(self, room_id: int) -> float:
        if room_id in self.light_effects:
            return self.light_effects[room_id].current_intensity
        return 0.0

    def get_hvac_effect_color(self, room_id: int) -> Vec3:
        if room_id in self.hvac_effects:
            return self.hvac_effects[room_id].get_effect_color()
        return Vec3(0, 0, 0)

    def get_shading_factor(self, room_id: int) -> float:
        if room_id in self.shading_effects:
            return self.shading_effects[room_id].current_shading
        return 0.0

    def get_comfort_color(self, room_id: int) -> Vec3:
        if room_id in self.comfort_viz:
            return self.comfort_viz[room_id].get_comfort_color()
        return Vec3(1, 1, 1)

    def get_hvac_status(self, room_id: int) -> tuple:
        if room_id not in self.hvac_effects:
            return ("off", 0.0, Vec3(0, 0, 0))
        hvac = self.hvac_effects[room_id]
        return (hvac.hvac_mode, hvac.hvac_speed, hvac.get_effect_color())
