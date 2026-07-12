"""
Graphics Effects

Visual effects for weather conditions (rain, wind, etc.).
Uses Panda3D particles and geometry for weather visualization.
"""

from panda3d.core import Point3, Vec3


class GraphicsEffects:
    """
    Manages weather visual effects in the 3D scene.
    Handles rain, wind, and other atmospheric effects.
    """

    def __init__(self, parent_node):
        """
        Initialize graphics effects system.

        Args:
            parent_node: Panda3D parent node to attach effects to
        """
        self.parent_node = parent_node
        self.rain_effect_active = False
        self.rain_intensity = 0.0
        self.wind_effect_active = False
        self.wind_strength = 0.0

        # For Phase 2, we keep effects simple (text indicators)
        # Phase 2.5 can add particle systems
        print("[OK] Graphics effects system initialized (Phase 2+)")

    def update(self, precipitation: float, wind_speed: float, cloud_cover: float):
        """
        Update weather effects based on conditions.

        Args:
            precipitation: Precipitation rate (mm/hour)
            wind_speed: Wind speed (m/s)
            cloud_cover: Cloud coverage (0.0 to 1.0)
        """
        # Update rain effect
        if precipitation > 0.5:
            self.rain_intensity = min(1.0, precipitation / 20.0)  # Scale to 0-1
            self.rain_effect_active = True
        else:
            self.rain_effect_active = False
            self.rain_intensity = 0.0

        # Update wind effect
        if wind_speed > 2.0:
            self.wind_strength = min(1.0, wind_speed / 15.0)  # Scale to 0-1
            self.wind_effect_active = True
        else:
            self.wind_effect_active = False
            self.wind_strength = 0.0

    def get_rain_intensity(self) -> float:
        """Get current rain intensity (0.0 to 1.0)."""
        return self.rain_intensity if self.rain_effect_active else 0.0

    def get_wind_strength(self) -> float:
        """Get current wind strength (0.0 to 1.0)."""
        return self.wind_strength if self.wind_effect_active else 0.0

    def is_raining(self) -> bool:
        """Check if it's raining."""
        return self.rain_effect_active

    def is_windy(self) -> bool:
        """Check if it's windy."""
        return self.wind_effect_active

    # Note: Particle system implementation for Phase 2.5+
    # Would include:
    # - ParticlePool for rain drops
    # - Wind effect on particle drift
    # - Dynamic particle count based on intensity
    # - Collision detection with geometry
