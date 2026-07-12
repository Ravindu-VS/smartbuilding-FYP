"""
HVAC System Module

Models heating, ventilation, and air conditioning systems for the building.
Includes cooling/heating capacity limits and energy consumption calculations.
"""

from dataclasses import dataclass
from typing import Dict, Tuple
from enum import Enum


class HVACMode(Enum):
    """HVAC operating mode."""
    OFF = 0
    COOLING = 1
    HEATING = 2


@dataclass
class HVACConfig:
    """HVAC system configuration."""
    cooling_capacity_watts: float  # Maximum cooling power
    heating_capacity_watts: float  # Maximum heating power
    cop_cooling: float  # Coefficient of performance for cooling
    cop_heating: float  # Coefficient of performance for heating
    setpoint_min: float  # Minimum setpoint temperature
    setpoint_max: float  # Maximum setpoint temperature
    fan_power_watts: float  # Fan power consumption


@dataclass
class HVACState:
    """Current state of HVAC for a zone."""
    setpoint: float  # Temperature setpoint (°C)
    fan_on: bool  # Fan status
    mode: HVACMode  # Current operating mode
    thermal_power: float  # Current thermal power output (W)
    electrical_power: float  # Current electrical consumption (W)


class HVACSystem:
    """
    HVAC system model.
    
    Models the heating and cooling behavior with:
    - Proportional control based on setpoint error
    - Capacity limits
    - Energy consumption based on COP
    """
    
    def __init__(self, config: Dict):
        """
        Initialize HVAC system.
        
        Args:
            config: HVAC configuration dictionary
        """
        self.config = HVACConfig(
            cooling_capacity_watts=config.get('cooling_capacity_watts', 15000),
            heating_capacity_watts=config.get('heating_capacity_watts', 12000),
            cop_cooling=config.get('cop_cooling', 3.5),
            cop_heating=config.get('cop_heating', 4.0),
            setpoint_min=config.get('setpoint_min', 18.0),
            setpoint_max=config.get('setpoint_max', 26.0),
            fan_power_watts=config.get('fan_power_watts', 200)
        )
        
        # Zone states
        self.zone_states: Dict[str, HVACState] = {}
        
        # Proportional control gain
        self.P_GAIN = 2000.0  # W per °C error
        
        # Deadband around setpoint
        self.DEADBAND = 0.5  # °C
    
    def initialize_zone(self, zone_name: str, initial_setpoint: float = 22.0) -> None:
        """
        Initialize HVAC state for a zone.
        
        Args:
            zone_name: Name of the zone
            initial_setpoint: Initial temperature setpoint
        """
        self.zone_states[zone_name] = HVACState(
            setpoint=initial_setpoint,
            fan_on=False,
            mode=HVACMode.OFF,
            thermal_power=0.0,
            electrical_power=0.0
        )
    
    def set_setpoint(self, zone_name: str, setpoint: float) -> float:
        """
        Set the temperature setpoint for a zone.
        
        Args:
            zone_name: Zone name
            setpoint: Desired setpoint (°C)
            
        Returns:
            Clamped setpoint value
        """
        setpoint = max(self.config.setpoint_min, 
                       min(self.config.setpoint_max, setpoint))
        
        if zone_name in self.zone_states:
            self.zone_states[zone_name].setpoint = setpoint
        else:
            self.initialize_zone(zone_name, setpoint)
        
        return setpoint
    
    def set_fan(self, zone_name: str, fan_on: bool) -> None:
        """Set fan state for a zone."""
        if zone_name in self.zone_states:
            self.zone_states[zone_name].fan_on = fan_on
    
    def compute_hvac_output(
        self,
        zone_name: str,
        current_temp: float,
        outdoor_temp: float
    ) -> Tuple[float, float, HVACMode]:
        """
        Compute HVAC thermal output and electrical consumption.
        
        Uses proportional control with deadband and capacity limits.
        
        Args:
            zone_name: Zone name
            current_temp: Current zone temperature (°C)
            outdoor_temp: Outdoor temperature (°C)
            
        Returns:
            Tuple of (thermal_power, electrical_power, mode)
        """
        if zone_name not in self.zone_states:
            return 0.0, 0.0, HVACMode.OFF
        
        state = self.zone_states[zone_name]
        setpoint = state.setpoint
        error = setpoint - current_temp  # Positive = need heating
        
        thermal_power = 0.0
        electrical_power = 0.0
        mode = HVACMode.OFF
        
        # Apply deadband
        if abs(error) < self.DEADBAND:
            mode = HVACMode.OFF
            thermal_power = 0.0
        elif error > 0:
            # Need heating
            mode = HVACMode.HEATING
            # Proportional control
            thermal_power = min(
                error * self.P_GAIN,
                self.config.heating_capacity_watts
            )
            # Electrical power based on COP
            electrical_power = thermal_power / self.config.cop_heating
        else:
            # Need cooling (error < 0)
            mode = HVACMode.COOLING
            # Proportional control (negative thermal power for cooling)
            thermal_power = max(
                error * self.P_GAIN,
                -self.config.cooling_capacity_watts
            )
            # Electrical power (use absolute value for COP)
            electrical_power = abs(thermal_power) / self.config.cop_cooling
        
        # Add fan power if HVAC is active or fan is forced on
        if mode != HVACMode.OFF or state.fan_on:
            electrical_power += self.config.fan_power_watts
        
        # Update state
        state.mode = mode
        state.thermal_power = thermal_power
        state.electrical_power = electrical_power
        
        return thermal_power, electrical_power, mode
    
    def step(
        self,
        zone_temps: Dict[str, float],
        outdoor_temp: float
    ) -> Dict[str, Tuple[float, float]]:
        """
        Update all zones and compute HVAC outputs.
        
        Args:
            zone_temps: Current temperatures per zone
            outdoor_temp: Outdoor temperature
            
        Returns:
            Dictionary mapping zone names to (thermal_power, electrical_power)
        """
        results = {}
        
        for zone_name, temp in zone_temps.items():
            thermal, electrical, _ = self.compute_hvac_output(
                zone_name, temp, outdoor_temp
            )
            results[zone_name] = (thermal, electrical)
        
        return results
    
    def get_state(self, zone_name: str) -> HVACState:
        """Get HVAC state for a zone."""
        return self.zone_states.get(
            zone_name,
            HVACState(22.0, False, HVACMode.OFF, 0.0, 0.0)
        )
    
    def get_total_electrical_power(self) -> float:
        """Get total electrical power consumption across all zones."""
        return sum(s.electrical_power for s in self.zone_states.values())
    
    def get_total_thermal_power(self) -> float:
        """Get total thermal power output across all zones."""
        return sum(s.thermal_power for s in self.zone_states.values())
