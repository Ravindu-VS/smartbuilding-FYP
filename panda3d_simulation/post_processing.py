"""
Post-Processing System (Lightweight)

Provides time-of-day color grading via scene colorScale.
Bloom/SSAO stubs removed — they were skeleton code with no actual shader programs.
This approach is reliable and has zero performance cost.
"""

from panda3d.core import Vec4, Vec3
from panda3d_simulation.actuator_effects import ActuatorEffectsManager
from typing import Dict
import math


class ColorGrading:
    """
    Time-of-day color grading via render node colorScale.
    Adjusts scene warmth, exposure, and saturation based on sun position.
    """

    def __init__(self):
        self.enabled = True
        self.current_scale = Vec4(1, 1, 1, 1)

    def adapt_to_time(self, sun_altitude: float) -> Vec4:
        """
        Compute scene color scale for time of day.

        Args:
            sun_altitude: Sun altitude angle (-90 to 90)

        Returns:
            Vec4 color scale to apply to render node
        """
        if not self.enabled:
            return Vec4(1, 1, 1, 1)

        if sun_altitude < -18:
            # Deep night — rich moonlight blue
            self.current_scale = Vec4(0.20, 0.25, 0.50, 1.0)
        elif sun_altitude < -6:
            # Twilight — gradual transition
            t = (sun_altitude + 18) / 12.0
            self.current_scale = Vec4(
                0.20 + t * 0.55,  # 0.20 → 0.75
                0.25 + t * 0.45,  # 0.25 → 0.70
                0.50 + t * 0.25,  # 0.50 → 0.75
                1.0
            )
        elif sun_altitude < 0:
            # Dawn/dusk — vibrant golden hour orange
            t = (sun_altitude + 6) / 6.0
            self.current_scale = Vec4(
                0.75 + t * 0.35,  # 0.75 → 1.10 (slight bloom)
                0.70 + t * 0.20,  # 0.70 → 0.90
                0.75 - t * 0.10,  # 0.75 → 0.65 (reduces blue)
                1.0
            )
        elif sun_altitude < 15:
            # Morning/late afternoon — softening warmth
            t = sun_altitude / 15.0
            self.current_scale = Vec4(
                1.10 - t * 0.10,  # 1.10 → 1.00
                0.90 + t * 0.10,  # 0.90 → 1.00
                0.65 + t * 0.35,  # 0.65 → 1.00
                1.0
            )
        else:
            # Full daytime — neutral
            self.current_scale = Vec4(1.0, 1.0, 1.0, 1.0)

        return self.current_scale


class PostProcessingPipeline:
    """
    Lightweight post-processing: only color grading.
    Applied as render node colorScale (no shaders needed).
    """

    def __init__(self, app, effects_manager: ActuatorEffectsManager):
        self.app = app
        self.effects_manager = effects_manager
        self.color_grading = ColorGrading()
        self.enabled = True

    def update(self, simulation_state: dict, dt: float):
        if not self.enabled:
            return

        sun_altitude = simulation_state.get("sun_altitude", 0)
        scale = self.color_grading.adapt_to_time(sun_altitude)

        # Apply color grading as scene-wide color scale
        self.app.render.setColorScale(scale)

    def enable_all(self, enabled: bool):
        self.enabled = enabled
        if not enabled:
            self.app.render.setColorScale(Vec4(1, 1, 1, 1))


class AdvancedRenderingConfig:
    """Configuration presets (simplified)."""

    @staticmethod
    def apply_preset(pipeline: PostProcessingPipeline, preset_name: str):
        if preset_name == "performance":
            pipeline.color_grading.enabled = False
        else:
            pipeline.color_grading.enabled = True
