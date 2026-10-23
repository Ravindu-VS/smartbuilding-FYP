"""
Building Thermal Model Module

Implements a 2R2C (two-resistance, two-capacitance) thermal model for each zone.
This models the thermal dynamics of walls and interior air separately.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import numpy as np


@dataclass
class ZoneState:
    """Current state of a building zone."""
    temperature: float  # Indoor air temperature (°C)
    wall_temperature: float  # Wall temperature (°C)
    humidity: float = 50.0  # Relative humidity (%)
    co2_ppm: float = 400.0  # CO2 concentration (ppm)
    illumination: float = 0.0  # Current illumination (lux)
    occupancy: int = 0  # Number of occupants
    
    def copy(self) -> 'ZoneState':
        """Create a copy of the state."""
        return ZoneState(
            temperature=self.temperature,
            wall_temperature=self.wall_temperature,
            humidity=self.humidity,
            co2_ppm=self.co2_ppm,
            illumination=self.illumination,
            occupancy=self.occupancy
        )


@dataclass
class ZoneConfig:
    """Configuration for a building zone."""
    name: str
    area_m2: float
    volume_m3: float
    occupancy_max: int
    lighting_baseline_watts: float
    plug_load_baseline_watts: float
    R_wall: float  # Thermal resistance wall-outdoor (K/W)
    R_internal: float  # Thermal resistance wall-indoor (K/W)
    C_zone: float  # Thermal capacitance of zone air (J/K)
    C_wall: float  # Thermal capacitance of wall (J/K)


@dataclass
class Zone:
    """
    Represents a thermal zone in the building.
    
    Uses 2R2C model:
    - R_wall: resistance from wall to outdoor
    - R_internal: resistance from wall to indoor air
    - C_wall: wall thermal mass
    - C_zone: indoor air thermal mass
    """
    config: ZoneConfig
    state: ZoneState = field(default_factory=lambda: ZoneState(22.0, 20.0))
    
    # Heat gain parameters
    HEAT_PER_PERSON_W: float = 100.0  # Sensible heat per person
    SOLAR_GAIN_FACTOR: float = 0.15  # Fraction of solar radiation entering zone
    
    def __post_init__(self):
        """Initialize default state if needed."""
        if self.state is None:
            self.state = ZoneState(22.0, 20.0)
    
    @property
    def name(self) -> str:
        return self.config.name
    
    def compute_heat_gains(
        self,
        occupancy: int,
        plug_load_watts: float,
        lighting_watts: float,
        solar_irradiance: float
    ) -> float:
        """
        Compute total internal heat gains.
        
        Args:
            occupancy: Number of occupants
            plug_load_watts: Current plug load power
            lighting_watts: Current lighting power
            solar_irradiance: Solar irradiance (W/m²)
            
        Returns:
            Total heat gain in watts
        """
        # Occupant heat
        Q_occupants = occupancy * self.HEAT_PER_PERSON_W
        
        # Equipment heat (assume 80% becomes heat)
        Q_plug = plug_load_watts * 0.8
        
        # Lighting heat (assume 70% becomes heat for LED)
        Q_lighting = lighting_watts * 0.7
        
        # Solar heat gain through windows
        # Assume window area is 20% of floor area
        window_area = self.config.area_m2 * 0.2
        Q_solar = solar_irradiance * window_area * self.SOLAR_GAIN_FACTOR
        
        return Q_occupants + Q_plug + Q_lighting + Q_solar
    
    def update_temperature(
        self,
        outdoor_temp: float,
        hvac_power: float,
        internal_gains: float,
        dt: float
    ) -> float:
        """
        Update zone temperature using 2R2C thermal model.
        
        The 2R2C model equations:
        dT_wall/dt = (1/C_wall) * [(T_out - T_wall)/R_wall + (T_zone - T_wall)/R_internal]
        dT_zone/dt = (1/C_zone) * [(T_wall - T_zone)/R_internal + Q_hvac + Q_internal]
        
        Args:
            outdoor_temp: Outdoor temperature (°C)
            hvac_power: HVAC thermal power (+ heating, - cooling) (W)
            internal_gains: Internal heat gains (W)
            dt: Time step (seconds)
            
        Returns:
            New zone temperature
        """
        cfg = self.config
        T_zone = self.state.temperature
        T_wall = self.state.wall_temperature
        T_out = outdoor_temp
        
        # Heat flow through wall to outdoor
        Q_wall_out = (T_out - T_wall) / cfg.R_wall
        
        # Heat flow from wall to zone
        Q_wall_zone = (T_zone - T_wall) / cfg.R_internal
        
        # Wall temperature update
        dT_wall = (Q_wall_out - Q_wall_zone) / cfg.C_wall * dt
        T_wall_new = T_wall + dT_wall
        
        # Zone temperature update
        Q_zone_net = -Q_wall_zone + hvac_power + internal_gains
        dT_zone = Q_zone_net / cfg.C_zone * dt
        T_zone_new = T_zone + dT_zone
        
        # Update state
        self.state.wall_temperature = T_wall_new
        self.state.temperature = T_zone_new
        
        return T_zone_new
    
    def update_co2(self, occupancy: int, ventilation_rate: float, dt: float) -> float:
        """
        Update CO2 concentration based on occupancy and ventilation.
        
        Args:
            occupancy: Number of occupants
            ventilation_rate: Air changes per hour
            dt: Time step (seconds)
            
        Returns:
            New CO2 concentration (ppm)
        """
        OUTDOOR_CO2 = 400.0  # ppm
        CO2_PER_PERSON = 0.005  # L/s per person (CO2 generation)
        
        # Convert to ppm/s
        volume_liters = self.config.volume_m3 * 1000
        generation_rate = (occupancy * CO2_PER_PERSON * 1e6) / volume_liters
        
        # Ventilation removal
        ach_per_second = ventilation_rate / 3600
        removal_rate = ach_per_second * (self.state.co2_ppm - OUTDOOR_CO2)
        
        # Update CO2
        dCO2 = (generation_rate - removal_rate) * dt
        self.state.co2_ppm = max(OUTDOOR_CO2, self.state.co2_ppm + dCO2)
        
        return self.state.co2_ppm


class BuildingThermalModel:
    """
    Complete building thermal model with multiple zones.
    
    Manages the thermal simulation of all zones, including inter-zone
    heat transfer (simplified) and shared HVAC resources.
    """
    
    def __init__(self, zones_config: List[Dict], initial_temp: float = 22.0):
        """
        Initialize building model.
        
        Args:
            zones_config: List of zone configuration dictionaries
            initial_temp: Initial temperature for all zones
        """
        self.zones: Dict[str, Zone] = {}
        
        for zone_cfg in zones_config:
            # Extract thermal parameters
            thermal = zone_cfg.get('thermal', {})
            config = ZoneConfig(
                name=zone_cfg['name'],
                area_m2=zone_cfg['area_m2'],
                volume_m3=zone_cfg['volume_m3'],
                occupancy_max=zone_cfg['occupancy_max'],
                lighting_baseline_watts=zone_cfg['lighting_baseline_watts'],
                plug_load_baseline_watts=zone_cfg['plug_load_baseline_watts'],
                R_wall=thermal.get('R_wall', 0.005),
                R_internal=thermal.get('R_internal', 0.01),
                C_zone=thermal.get('C_zone', 3000000),
                C_wall=thermal.get('C_wall', 1000000)
            )
            
            initial_state = ZoneState(
                temperature=initial_temp,
                wall_temperature=initial_temp - 2
            )
            
            self.zones[zone_cfg['name']] = Zone(config=config, state=initial_state)
    
    def get_zone(self, name: str) -> Optional[Zone]:
        """Get a zone by name."""
        return self.zones.get(name)
    
    def get_all_zones(self) -> List[Zone]:
        """Get all zones."""
        return list(self.zones.values())
    
    def get_zone_names(self) -> List[str]:
        """Get all zone names."""
        return list(self.zones.keys())
    
    def step(
        self,
        outdoor_temp: float,
        hvac_powers: Dict[str, float],
        internal_gains: Dict[str, float],
        dt: float
    ) -> Dict[str, float]:
        """
        Advance simulation by one time step for all zones.
        
        Args:
            outdoor_temp: Outdoor temperature (°C)
            hvac_powers: HVAC power per zone (W)
            internal_gains: Internal gains per zone (W)
            dt: Time step (seconds)
            
        Returns:
            New temperatures for each zone
        """
        new_temps = {}
        
        for name, zone in self.zones.items():
            hvac = hvac_powers.get(name, 0.0)
            gains = internal_gains.get(name, 0.0)
            new_temps[name] = zone.update_temperature(outdoor_temp, hvac, gains, dt)
        
        return new_temps
    
    def get_states(self) -> Dict[str, ZoneState]:
        """Get current states of all zones."""
        return {name: zone.state.copy() for name, zone in self.zones.items()}
    
    def set_state(self, zone_name: str, state: ZoneState) -> None:
        """Set the state of a specific zone."""
        if zone_name in self.zones:
            self.zones[zone_name].state = state
    
    def get_total_area(self) -> float:
        """Get total building area."""
        return sum(z.config.area_m2 for z in self.zones.values())
    
    def get_total_volume(self) -> float:
        """Get total building volume."""
        return sum(z.config.volume_m3 for z in self.zones.values())
