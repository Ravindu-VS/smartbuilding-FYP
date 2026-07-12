"""
Lighting System Module

Models artificial lighting with daylight harvesting capabilities.
Includes dimming control and energy consumption calculations.
"""

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass
class LightingConfig:
    """Lighting system configuration."""
    efficacy_lm_per_watt: float  # LED efficacy
    daylight_max_lux: float  # Maximum daylight contribution
    target_lux_occupied: float  # Target illumination when occupied
    target_lux_unoccupied: float  # Target illumination when unoccupied


@dataclass
class LightingState:
    """Current state of lighting for a zone."""
    dimming_level: float  # 0.0 to 1.0
    artificial_lux: float  # Lux from artificial lighting
    daylight_lux: float  # Lux from daylight
    total_lux: float  # Combined illumination
    power_watts: float  # Current power consumption


class LightingSystem:
    """
    Lighting system model with daylight harvesting.
    
    Features:
    - Dimming control (0-100%)
    - Daylight harvesting: reduces artificial lighting when daylight is sufficient
    - Energy calculation based on dimming level
    """
    
    def __init__(self, config: Dict):
        """
        Initialize lighting system.
        
        Args:
            config: Lighting configuration dictionary
        """
        self.config = LightingConfig(
            efficacy_lm_per_watt=config.get('efficacy_lm_per_watt', 100),
            daylight_max_lux=config.get('daylight_max_lux', 800),
            target_lux_occupied=config.get('target_lux_occupied', 400),
            target_lux_unoccupied=config.get('target_lux_unoccupied', 50)
        )
        
        # Zone states
        self.zone_states: Dict[str, LightingState] = {}
        
        # Zone baseline wattages (set per zone)
        self.zone_baseline_watts: Dict[str, float] = {}
    
    def initialize_zone(
        self,
        zone_name: str,
        baseline_watts: float,
        initial_dimming: float = 0.0
    ) -> None:
        """
        Initialize lighting state for a zone.
        
        Args:
            zone_name: Name of the zone
            baseline_watts: Maximum lighting power for the zone
            initial_dimming: Initial dimming level (0-1)
        """
        self.zone_baseline_watts[zone_name] = baseline_watts
        self.zone_states[zone_name] = LightingState(
            dimming_level=initial_dimming,
            artificial_lux=0.0,
            daylight_lux=0.0,
            total_lux=0.0,
            power_watts=0.0
        )
    
    def calculate_daylight(
        self,
        solar_irradiance: float,
        hour_of_day: float
    ) -> float:
        """
        Calculate daylight contribution based on solar conditions.
        
        Args:
            solar_irradiance: Solar irradiance (W/m²)
            hour_of_day: Current hour (0-24)
            
        Returns:
            Daylight illumination in lux
        """
        # Simple daylight model
        # Peak daylight at solar noon, zero at night
        if 6 <= hour_of_day <= 18:
            # Daylight hours
            # Sinusoidal profile peaking at noon
            import math
            daylight_factor = math.sin(math.pi * (hour_of_day - 6) / 12)
            
            # Scale by solar irradiance (normalized to typical max ~1000 W/m²)
            irradiance_factor = min(1.0, solar_irradiance / 1000.0)
            
            daylight_lux = (
                self.config.daylight_max_lux * 
                daylight_factor * 
                irradiance_factor
            )
            return max(0.0, daylight_lux)
        else:
            return 0.0
    
    def set_dimming(self, zone_name: str, dimming_level: float) -> float:
        """
        Set the dimming level for a zone.
        
        Args:
            zone_name: Zone name
            dimming_level: Desired dimming level (0-1)
            
        Returns:
            Clamped dimming value
        """
        dimming_level = max(0.0, min(1.0, dimming_level))
        
        if zone_name in self.zone_states:
            self.zone_states[zone_name].dimming_level = dimming_level
        
        return dimming_level
    
    def compute_lighting_output(
        self,
        zone_name: str,
        daylight_lux: float
    ) -> Tuple[float, float, float]:
        """
        Compute artificial lighting output and total illumination.
        
        Args:
            zone_name: Zone name
            daylight_lux: Current daylight contribution
            
        Returns:
            Tuple of (total_lux, artificial_lux, power_watts)
        """
        if zone_name not in self.zone_states:
            return daylight_lux, 0.0, 0.0
        
        state = self.zone_states[zone_name]
        baseline = self.zone_baseline_watts.get(zone_name, 0.0)
        
        # Calculate artificial lighting
        # Power is proportional to dimming level
        power = baseline * state.dimming_level
        
        # Calculate lux from artificial lighting
        # Simplified: assume efficacy and room size give a base lux
        # At full power, provide enough lux to meet occupied target
        max_artificial_lux = self.config.target_lux_occupied * 1.5  # Some headroom
        artificial_lux = max_artificial_lux * state.dimming_level
        
        # Total illumination
        total_lux = daylight_lux + artificial_lux
        
        # Update state
        state.daylight_lux = daylight_lux
        state.artificial_lux = artificial_lux
        state.total_lux = total_lux
        state.power_watts = power
        
        return total_lux, artificial_lux, power
    
    def compute_optimal_dimming(
        self,
        target_lux: float,
        daylight_lux: float
    ) -> float:
        """
        Calculate optimal dimming level for daylight harvesting.
        
        Args:
            target_lux: Desired total illumination
            daylight_lux: Current daylight contribution
            
        Returns:
            Required dimming level (0-1)
        """
        if daylight_lux >= target_lux:
            # Sufficient daylight, no artificial light needed
            return 0.0
        
        # Calculate how much artificial light is needed
        needed_lux = target_lux - daylight_lux
        max_artificial_lux = self.config.target_lux_occupied * 1.5
        
        # Dimming level to provide needed lux
        dimming = needed_lux / max_artificial_lux
        
        return max(0.0, min(1.0, dimming))
    
    def step(
        self,
        solar_irradiance: float,
        hour_of_day: float
    ) -> Dict[str, Tuple[float, float]]:
        """
        Update all zones with current daylight conditions.
        
        Args:
            solar_irradiance: Current solar irradiance (W/m²)
            hour_of_day: Current hour (0-24)
            
        Returns:
            Dictionary mapping zone names to (total_lux, power_watts)
        """
        daylight = self.calculate_daylight(solar_irradiance, hour_of_day)
        results = {}
        
        for zone_name in self.zone_states:
            total_lux, _, power = self.compute_lighting_output(
                zone_name, daylight
            )
            results[zone_name] = (total_lux, power)
        
        return results
    
    def get_state(self, zone_name: str) -> LightingState:
        """Get lighting state for a zone."""
        return self.zone_states.get(
            zone_name,
            LightingState(0.0, 0.0, 0.0, 0.0, 0.0)
        )
    
    def get_total_power(self) -> float:
        """Get total lighting power consumption."""
        return sum(s.power_watts for s in self.zone_states.values())
    
    def get_daylight_lux(self, solar_irradiance: float, hour_of_day: float) -> float:
        """Get current daylight level."""
        return self.calculate_daylight(solar_irradiance, hour_of_day)
