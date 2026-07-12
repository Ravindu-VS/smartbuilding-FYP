"""
Models and Data Structures

Defines clean, simulation-agnostic data models for building state, sensors, and decisions.
Phase 2 additions: thermal properties, historical data, weather state, room configuration.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime


# ============================================================================
# PHASE 1 MODELS (MAINTAINED)
# ============================================================================

@dataclass
class SensorData:
    """
    Sensor readings for a single room.
    This is simulation-agnostic and can accept real sensor data later.
    """
    timestamp: datetime
    temperature: float  # Celsius
    humidity: float     # Relative humidity (%)
    light_level: float  # Lux (0-1000+)
    co2: float         # CO2 level (ppm)
    occupancy: int     # Number of people (0+)
    energy_use: float  # Current power consumption (Watts)

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "temperature": self.temperature,
            "humidity": self.humidity,
            "light_level": self.light_level,
            "co2": self.co2,
            "occupancy": self.occupancy,
            "energy_use": self.energy_use,
        }


@dataclass
class ActuatorState:
    """
    Control state for actuators in a room.
    Extended for Phase 2 with more HVAC modes.
    Extended for Phase 4 with window shading control.
    """
    light_on: bool = False
    hvac_mode: str = "off"  # "off", "heating", "cooling", "fan_only", "auto"
    hvac_setpoint: float = 21.0  # Target temperature (Celsius)
    hvac_speed: float = 0.0  # 0.0 to 1.0 (compressor speed)
    shading_factor: float = 0.0  # 0.0 (open) to 1.0 (fully shaded) - Phase 4

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "light_on": self.light_on,
            "hvac_mode": self.hvac_mode,
            "hvac_setpoint": self.hvac_setpoint,
            "hvac_speed": self.hvac_speed,
            "shading_factor": self.shading_factor,
        }


@dataclass
class RoomState:
    """
    Complete state of a single room at a point in time.
    """
    room_id: int
    sensors: SensorData
    actuators: ActuatorState
    occupancy_schedule: List[int] = field(default_factory=list)  # Occupancy per hour
    is_occupied: bool = False

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "room_id": self.room_id,
            "sensors": self.sensors.to_dict(),
            "actuators": self.actuators.to_dict(),
            "is_occupied": self.is_occupied,
        }


# ============================================================================
# PHASE 2 NEW MODELS
# ============================================================================

@dataclass
class ThermalProperties:
    """
    Thermal characteristics of a room/zone.
    Used for advanced thermal simulation in Phase 2+.
    """
    thermal_mass_j_k: float = 50000.0  # Thermal mass (Joules/Kelvin)
    u_value_w_m2k: float = 0.3  # Overall heat transfer coefficient
    infiltration_rate_ach: float = 0.5  # Air changes per hour (ACH)
    solar_gain_factor: float = 0.3  # Fraction of solar radiation through windows

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "thermal_mass_j_k": self.thermal_mass_j_k,
            "u_value_w_m2k": self.u_value_w_m2k,
            "infiltration_rate_ach": self.infiltration_rate_ach,
            "solar_gain_factor": self.solar_gain_factor,
        }


@dataclass
class RoomConfig:
    """
    Room configuration and metadata.
    Describes static room properties loaded from config file.
    """
    room_id: int
    name: str  # e.g., "Office A"
    zone_type: str  # "office", "meeting", "corridor", "lobby", "storage"
    position: Dict[str, float]  # {"x": 0, "y": 0, "z": 0}
    dimensions: Dict[str, float]  # {"width": 6, "depth": 6, "height": 3}
    max_occupancy: int = 4
    thermal_properties: ThermalProperties = field(default_factory=ThermalProperties)
    doors: Dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "room_id": self.room_id,
            "name": self.name,
            "zone_type": self.zone_type,
            "position": self.position,
            "dimensions": self.dimensions,
            "max_occupancy": self.max_occupancy,
            "thermal_properties": self.thermal_properties.to_dict(),
        }


@dataclass
class HistoricalData:
    """
    Historical data tracking for visualization and analysis.
    Stores time series data for charts and trends.
    """
    max_points: int = 300  # Maximum number of data points to keep (prevent memory bloat)
    temperature_history: List[float] = field(default_factory=list)
    occupancy_history: List[float] = field(default_factory=list)
    energy_history: List[float] = field(default_factory=list)
    humidity_history: List[float] = field(default_factory=list)
    light_history: List[float] = field(default_factory=list)

    def add_point(self, temperature: float = None, occupancy: float = None,
                  energy: float = None, humidity: float = None, light: float = None):
        """Add a data point to history, dropping oldest if at max."""
        if temperature is not None:
            self.temperature_history.append(temperature)
            if len(self.temperature_history) > self.max_points:
                self.temperature_history.pop(0)
        if occupancy is not None:
            self.occupancy_history.append(occupancy)
            if len(self.occupancy_history) > self.max_points:
                self.occupancy_history.pop(0)
        if energy is not None:
            self.energy_history.append(energy)
            if len(self.energy_history) > self.max_points:
                self.energy_history.pop(0)
        if humidity is not None:
            self.humidity_history.append(humidity)
            if len(self.humidity_history) > self.max_points:
                self.humidity_history.pop(0)
        if light is not None:
            self.light_history.append(light)
            if len(self.light_history) > self.max_points:
                self.light_history.pop(0)


@dataclass
class WeatherState:
    """
    Environmental/weather conditions (extends BuildingState).
    Describes outdoor conditions that affect the building.
    """
    cloud_cover: float = 0.0  # 0.0 (clear) to 1.0 (overcast)
    precipitation: float = 0.0  # mm/hour
    wind_speed: float = 0.0  # m/s
    wind_direction: float = 0.0  # degrees (0-360)
    solar_irradiance: float = 0.0  # W/m^2 (varies with sun position and clouds)

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "cloud_cover": self.cloud_cover,
            "precipitation": self.precipitation,
            "wind_speed": self.wind_speed,
            "wind_direction": self.wind_direction,
            "solar_irradiance": self.solar_irradiance,
        }


@dataclass
class BuildingState:
    """
    Complete state of the entire building at a point in time.
    Extended for Phase 2 with weather and expanded room data.
    """
    timestamp: datetime
    outdoor_temperature: float  # Celsius
    outdoor_humidity: float     # %
    outdoor_light: float        # Lux
    sun_altitude: float        # Degrees (-90 to 90)
    sun_azimuth: float         # Degrees (0 to 360)
    rooms: Dict[int, RoomState] = field(default_factory=dict)
    weather: WeatherState = field(default_factory=WeatherState)

    # Optional historical data for charting (populated by rendering layer)
    history: Optional[HistoricalData] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "outdoor_temperature": self.outdoor_temperature,
            "outdoor_humidity": self.outdoor_humidity,
            "outdoor_light": self.outdoor_light,
            "sun_altitude": self.sun_altitude,
            "sun_azimuth": self.sun_azimuth,
            "weather": self.weather.to_dict(),
            "rooms": {rid: s.to_dict() for rid, s in self.rooms.items()},
        }
