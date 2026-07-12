"""
Sky System

Dynamic sky rendering with day/night cycle color gradients.
Simulates realistic sky colors based on sun position and weather.
Phase 10: Enhanced with more vivid sunset/evening colors and smooth transitions.
"""

from panda3d.core import Vec4
import math


class SkySystem:
    """
    Manages sky color and visual appearance based on sun position.
    Implements realistic atmospheric color gradients with smooth transitions.

    Features:
    - Bright blue daytime sky
    - Vivid orange/pink sunset (evening)
    - Dark blue/purple twilight
    - Nearly black night sky
    - Smooth color transitions between times
    """

    def __init__(self, parent_node=None):
        """
        Initialize sky system.

        Args:
            parent_node: Panda3D node (for future sky dome geometry)
        """
        self.parent_node = parent_node
        self.current_color = Vec4(0.5, 0.7, 0.95, 1.0)  # Default daytime blue

        # Color palette for different times - ENHANCED with vivid sunset colors
        self.night_color = Vec4(0.05, 0.10, 0.20, 1.0)         # Dark blue (night)
        self.pre_dawn_color = Vec4(0.15, 0.15, 0.30, 1.0)       # Dark blue before dawn
        self.dawn_color = Vec4(0.40, 0.30, 0.50, 1.0)           # Pink/Purple dawn
        self.sunrise_color = Vec4(0.90, 0.50, 0.40, 1.0)        # Orange/Pink sunrise
        self.morning_color = Vec4(0.60, 0.80, 1.00, 1.0)         # Bright blue morning
        self.noon_color = Vec4(0.40, 0.70, 1.00, 1.0)           # Bright sky blue
        self.afternoon_color = Vec4(0.45, 0.75, 1.00, 1.0)      # Afternoon blue
        self.golden_hour = Vec4(1.00, 0.60, 0.45, 1.0)           # Golden hour (orange/pink)
        self.sunset_color = Vec4(0.95, 0.35, 0.40, 1.0)          # Vivid pink/orange sunset
        self.dusk_color = Vec4(0.40, 0.20, 0.40, 1.0)           # Purple dusk
        self.late_dusk_color = Vec4(0.10, 0.15, 0.25, 1.0)      # Dark blue before night

    def update(self, sun_altitude: float, cloud_cover: float = 0.0) -> Vec4:
        """
        Update sky color based on sun position and weather.
        Smooth transitions throughout the day cycle.

        Args:
            sun_altitude: Sun altitude angle (-90 to 90 degrees)
            cloud_cover: Cloud coverage (0.0 to 1.0)

        Returns:
            Sky color as Vec4 (RGBA)
        """
        # Smooth color transitions based on sun altitude
        if sun_altitude < -18:
            color = self.night_color
        elif sun_altitude < -15:
            progress = (sun_altitude + 18) / 3
            color = self._lerp(self.night_color, self.pre_dawn_color, progress)
        elif sun_altitude < -10:
            progress = (sun_altitude + 15) / 5
            color = self._lerp(self.pre_dawn_color, self.dawn_color, progress)
        elif sun_altitude < -5:
            progress = (sun_altitude + 10) / 5
            color = self._lerp(self.dawn_color, self.sunrise_color, progress)
        elif sun_altitude < 0:
            progress = (sun_altitude + 5) / 5
            color = self._lerp(self.sunrise_color, self.morning_color, progress)
        elif sun_altitude < 5:
            progress = sun_altitude / 5
            color = self._lerp(self.morning_color, self.noon_color, progress)
        elif sun_altitude < 45:
            # Daytime: stable blue
            color = self.noon_color
        elif sun_altitude < 60:
            # Descending toward horizon
            progress = (sun_altitude - 45) / 15
            color = self._lerp(self.noon_color, self.golden_hour, progress)
        else:
            # Sun very high (rare)
            color = self.noon_color

        # Apply cloud cover effect (darker when cloudy)
        if cloud_cover > 0.0:
            cloud_factor = 1.0 - cloud_cover * 0.4  # Up to 40% darker when fully overcast
            color = Vec4(
                color.getX() * cloud_factor,
                color.getY() * cloud_factor,
                color.getZ() * cloud_factor,
                color.getW()
            )

        self.current_color = color
        return color

    def get_sky_color(self) -> Vec4:
        """
        Get current sky color.

        Returns:
            Sky color as Vec4 (RGBA)
        """
        return self.current_color

    @staticmethod
    def _lerp(color1: Vec4, color2: Vec4, t: float) -> Vec4:
        """
        Linear interpolation between two colors.

        Args:
            color1: First color
            color2: Second color
            t: Interpolation factor (0 = color1, 1 = color2)

        Returns:
            Interpolated color
        """
        t = max(0.0, min(1.0, t))  # Clamp to 0-1
        return Vec4(
            color1.getX() + (color2.getX() - color1.getX()) * t,
            color1.getY() + (color2.getY() - color1.getY()) * t,
            color1.getZ() + (color2.getZ() - color1.getZ()) * t,
            color1.getW() + (color2.getW() - color1.getW()) * t,
        )

    def get_ambient_light_intensity(self, sun_altitude: float) -> float:
        """
        Get ambient light intensity based on sun position.
        Used to brighten/darken the scene.

        Args:
            sun_altitude: Sun altitude angle

        Returns:
            Ambient light intensity (0.0 to 1.0)
        """
        if sun_altitude < -20:
            # Night: very dark
            return 0.35
        elif sun_altitude < -10:
            # Early morning/late evening
            return 0.45 + (sun_altitude + 20) / 10 * 0.25
        elif sun_altitude < 0:
            # Sunrise/sunset
            return 0.7 + sun_altitude / 20 * 0.3
        else:
            # Daytime
            return min(1.0, 0.75 + sun_altitude / 90)

    def get_sun_direction_angle(self, sun_altitude: float, sun_azimuth: float) -> tuple:
        """
        Convert altitude/azimuth to direction angles for light source.

        Args:
            sun_altitude: Sun altitude (-90 to 90)
            sun_azimuth: Sun azimuth (0 to 360)

        Returns:
            Tuple of (heading, pitch) for Panda3D light direction
        """
        # Convert azimuth to Panda3D heading (0 = +Y, 90 = +X)
        heading = (sun_azimuth - 90) % 360

        # Pitch is simply negative altitude (down is positive in Panda3D)
        pitch = -sun_altitude

        return (heading, pitch)
