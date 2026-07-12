"""
Window System for Solar Gain Calculation

Implements realistic window modeling including:
- Orientation-dependent solar gain
- Time-of-day sun position effects
- Shading and thermal properties
- Integration with thermal zone model

Phase 3: Advanced physics module for solar radiation effects.
"""

import math
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class WindowConfig:
    """Configuration for a window in a room."""
    window_id: int
    room_id: int
    width: float  # meters
    height: float  # meters
    azimuth: float  # degrees (0=N, 90=E, 180=S, 270=W)

    # Thermal properties
    u_value: float = 3.0  # W/m²K (typical double-glazed)
    solar_transmittance: float = 0.6  # Single transmittance (60% of incident radiation passes through)
    frame_fraction: float = 0.15  # 15% of window area is frame (non-transmitting)

    # Shading
    shading_factor: float = 0.0  # 0.0 = no shading, 1.0 = fully shaded

    @property
    def area(self) -> float:
        """Effective window area (m²)."""
        return self.width * self.height

    @property
    def effective_area(self) -> float:
        """Effective transmitting area (accounting for frame)."""
        return self.area * (1.0 - self.frame_fraction)


class Window:
    """
    Represents a single window in a building zone.

    Models:
    - Orientation (azimuth angle)
    - Solar transmittance properties
    - Time-dependent solar gain calculation
    - Shading effects
    """

    def __init__(self, config: WindowConfig):
        """
        Initialize window.

        Args:
            config: WindowConfig dataclass
        """
        self.config = config
        self.current_solar_gain = 0.0  # W (watts)

    def calculate_solar_gain(self, solar_irradiance: float,
                            sun_altitude: float, sun_azimuth: float) -> float:
        """
        Calculate solar gain through window based on sun position.

        Physics:
        - Incident angle depends on relative orientation of window vs sun
        - Solar gain = irradiance × cos(incident_angle) × transmittance × area × (1 - shading)

        Args:
            solar_irradiance: Direct solar radiation (W/m²) at horizontal plane
            sun_altitude: Solar altitude angle (degrees, 0-90)
            sun_azimuth: Solar azimuth angle (degrees, 0-360; 0=N, 90=E)

        Returns:
            Solar gain through window (W, can be 0 if sun is behind window)
        """
        # If sun is below horizon, no direct gain
        if sun_altitude <= 0:
            self.current_solar_gain = 0.0
            return 0.0

        # Convert to radians for calculation
        sun_alt_rad = math.radians(sun_altitude)
        sun_azi_rad = math.radians(sun_azimuth)
        win_azi_rad = math.radians(self.config.azimuth)

        # Calculate incident angle using spherical geometry
        # Incident angle depends on:
        # 1. Sun altitude (how high sun is)
        # 2. Relative azimuth (how much sun is off to the side)
        #
        # For a vertical window facing azimuth(win), incident angle is:
        # cos(theta) = sin(altitude) × cos(azimuth_difference)

        azimuth_diff = sun_azi_rad - win_azi_rad
        cos_incident_angle = math.sin(sun_alt_rad) * math.cos(azimuth_diff)

        # If cos < 0, sun is behind the window (facing away)
        if cos_incident_angle <= 0:
            self.current_solar_gain = 0.0
            return 0.0

        # Incident radiation on the window plane
        incident_irradiance = solar_irradiance * cos_incident_angle  # W/m²

        # Apply transmittance and shading
        effective_transmittance = self.config.solar_transmittance * (1.0 - self.config.shading_factor)

        # Transmitted radiation through window
        transmitted_irradiance = incident_irradiance * effective_transmittance  # W/m²

        # Solar gain (power) through window
        solar_gain = transmitted_irradiance * self.config.effective_area  # W

        self.current_solar_gain = max(0.0, solar_gain)
        return self.current_solar_gain

    def calculate_conduction_loss(self, t_indoor: float, t_outdoor: float) -> float:
        """
        Calculate conductive heat loss/gain through window.

        Q = U × A × ΔT

        Args:
            t_indoor: Indoor temperature (°C)
            t_outdoor: Outdoor temperature (°C)

        Returns:
            Heat flow (W, positive = heat loss from inside)
        """
        delta_t = t_indoor - t_outdoor
        conduction = self.config.u_value * self.config.effective_area * delta_t
        return conduction

    def update_shading(self, new_shading_factor: float):
        """
        Update shading factor (e.g., blinds/curtains).

        Args:
            new_shading_factor: 0.0 (fully open) to 1.0 (fully closed)
        """
        self.config.shading_factor = max(0.0, min(1.0, new_shading_factor))


class WindowSystem:
    """
    Manages all windows in a zone or building.

    Coordinates solar gain calculations across multiple windows,
    tracks total solar input to the zone.
    """

    def __init__(self):
        """Initialize window system."""
        self.windows: Dict[int, Window] = {}
        self.total_solar_gain = 0.0  # W

    def add_window(self, config: WindowConfig) -> Window:
        """
        Add a window to the system.

        Args:
            config: WindowConfig dataclass

        Returns:
            Window instance
        """
        window = Window(config)
        self.windows[config.window_id] = window
        return window

    def remove_window(self, window_id: int) -> bool:
        """
        Remove a window from the system.

        Args:
            window_id: Window identifier

        Returns:
            True if window was removed, False if not found
        """
        if window_id in self.windows:
            del self.windows[window_id]
            return True
        return False

    def update_solar_gain(self, solar_irradiance: float,
                         sun_altitude: float, sun_azimuth: float) -> float:
        """
        Update solar gain for all windows.

        Args:
            solar_irradiance: Direct solar radiation (W/m²)
            sun_altitude: Solar altitude (degrees)
            sun_azimuth: Solar azimuth (degrees)

        Returns:
            Total solar gain through all windows (W)
        """
        total_gain = 0.0

        for window in self.windows.values():
            gain = window.calculate_solar_gain(
                solar_irradiance, sun_altitude, sun_azimuth
            )
            total_gain += gain

        self.total_solar_gain = total_gain
        return total_gain

    def get_window(self, window_id: int) -> Optional[Window]:
        """
        Get window by ID.

        Args:
            window_id: Window identifier

        Returns:
            Window instance or None if not found
        """
        return self.windows.get(window_id)

    def get_total_solar_gain(self) -> float:
        """
        Get total solar gain from all windows.

        Returns:
            Total solar gain (W)
        """
        return self.total_solar_gain

    def get_window_count(self) -> int:
        """Get number of windows in system."""
        return len(self.windows)

    def get_total_window_area(self) -> float:
        """Get total effective window area (m²)."""
        return sum(w.config.effective_area for w in self.windows.values())


class RoomWindowConfig:
    """Helper class for managing windows in a specific room."""

    def __init__(self, room_id: int):
        """
        Initialize room window configuration.

        Args:
            room_id: Room identifier
        """
        self.room_id = room_id
        self.window_system = WindowSystem()

    def add_window(self, width: float, height: float, azimuth: float,
                   u_value: float = 3.0, solar_transmittance: float = 0.6,
                   frame_fraction: float = 0.15, shading_factor: float = 0.0) -> Window:
        """
        Convenience method to add a window to this room.

        Args:
            width: Window width (m)
            height: Window height (m)
            azimuth: Window orientation (degrees, 0=N, 90=E, 180=S, 270=W)
            u_value: U-value (W/m²K)
            solar_transmittance: Solar transmittance (0-1)
            frame_fraction: Frame area fraction (0-1)
            shading_factor: Shading factor (0-1)

        Returns:
            Window instance
        """
        window_id = len(self.window_system.windows)
        config = WindowConfig(
            window_id=window_id,
            room_id=self.room_id,
            width=width,
            height=height,
            azimuth=azimuth,
            u_value=u_value,
            solar_transmittance=solar_transmittance,
            frame_fraction=frame_fraction,
            shading_factor=shading_factor
        )
        return self.window_system.add_window(config)

    def add_standard_window(self, count: int = 1, azimuth: float = 180.0) -> None:
        """
        Add standard window(s) to room.

        Standard window: 1.0m × 1.2m (typical office window)

        Args:
            count: Number of windows to add
            azimuth: Window orientation (degrees)
        """
        for _ in range(count):
            self.add_window(
                width=1.0,
                height=1.2,
                azimuth=azimuth,
                u_value=3.0,
                solar_transmittance=0.6,
                frame_fraction=0.15
            )

    def get_total_solar_gain(self) -> float:
        """Get total solar gain from all windows in this room."""
        return self.window_system.get_total_solar_gain()
