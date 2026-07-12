"""
Baseline Rule Controller Module

Implements a simple rule-based controller for building systems.
Uses basic if-then rules based on occupancy and comfort targets.
"""

from dataclasses import dataclass
from typing import Dict, Tuple, Optional
from datetime import datetime


@dataclass
class ControlAction:
    """Control actions for a zone."""
    hvac_setpoint: float  # Temperature setpoint (°C)
    fan_on: bool  # Fan state
    dimming_level: float  # Lighting dimming (0-1)


@dataclass
class BaselineConfig:
    """Configuration for baseline controller."""
    comfort_setpoint: float  # Target temperature when occupied
    unoccupied_setpoint_cooling: float  # Setpoint when unoccupied (cooling mode)
    unoccupied_setpoint_heating: float  # Setpoint when unoccupied (heating mode)
    comfort_lux: float  # Target illumination when occupied


class BaselineRuleController:
    """
    Simple rule-based controller.
    
    Rules:
    - Occupied: Maintain temperature near comfort_setpoint, lights at comfort_lux
    - Unoccupied: Relax setpoints, turn off lights
    - Heating vs cooling mode based on weather (outdoor temp)
    """
    
    def __init__(self, config: Dict):
        """
        Initialize baseline controller.
        
        Args:
            config: Configuration dictionary
        """
        baseline_cfg = config.get('baseline', {})
        
        self.config = BaselineConfig(
            comfort_setpoint=baseline_cfg.get('comfort_setpoint', 23.0),
            unoccupied_setpoint_cooling=baseline_cfg.get('unoccupied_setpoint_cooling', 26.0),
            unoccupied_setpoint_heating=baseline_cfg.get('unoccupied_setpoint_heating', 18.0),
            comfort_lux=baseline_cfg.get('comfort_lux', 400.0)
        )
        
        # Track previous actions for smooth transitions
        self.previous_actions: Dict[str, ControlAction] = {}
        
        # Comfort parameters
        self.comfort_config = config.get('comfort', {})
        self.lux_target_min = self.comfort_config.get('lux_target_min', 300)
        self.lux_target_max = self.comfort_config.get('lux_target_max', 500)
    
    def _determine_mode(self, outdoor_temp: float) -> str:
        """
        Determine heating or cooling mode.
        
        Args:
            outdoor_temp: Current outdoor temperature
            
        Returns:
            'heating' or 'cooling'
        """
        # Simple threshold-based mode selection
        # Below 18°C: heating, above 22°C: cooling
        if outdoor_temp < 18.0:
            return 'heating'
        elif outdoor_temp > 22.0:
            return 'cooling'
        else:
            # Shoulder season - use setpoint comparison
            return 'cooling'  # Default to energy-saving cooling setbacks
    
    def _calculate_dimming(
        self,
        is_occupied: bool,
        daylight_lux: float
    ) -> float:
        """
        Calculate required dimming level.
        
        Implements daylight harvesting:
        - If sufficient daylight, reduce artificial lighting
        - When unoccupied, minimal lighting
        
        Args:
            is_occupied: Whether zone is occupied
            daylight_lux: Current daylight contribution
            
        Returns:
            Dimming level (0-1)
        """
        if not is_occupied:
            # Minimal lighting when unoccupied
            return 0.0
        
        target_lux = self.config.comfort_lux
        
        if daylight_lux >= target_lux:
            # Sufficient daylight
            return 0.0
        
        # Calculate needed artificial light
        needed_lux = target_lux - daylight_lux
        max_artificial_lux = self.config.comfort_lux * 1.5
        
        dimming = needed_lux / max_artificial_lux
        return max(0.0, min(1.0, dimming))
    
    def compute_action(
        self,
        zone_name: str,
        current_temp: float,
        current_lux: float,
        is_occupied: bool,
        outdoor_temp: float,
        daylight_lux: float
    ) -> ControlAction:
        """
        Compute control action for a zone.
        
        Args:
            zone_name: Zone name
            current_temp: Current zone temperature
            current_lux: Current zone illumination
            is_occupied: Whether zone is occupied
            outdoor_temp: Outdoor temperature
            daylight_lux: Current daylight level
            
        Returns:
            ControlAction with setpoint, fan, and dimming
        """
        mode = self._determine_mode(outdoor_temp)
        
        # Temperature setpoint
        if is_occupied:
            setpoint = self.config.comfort_setpoint
            fan_on = True
        else:
            if mode == 'cooling':
                setpoint = self.config.unoccupied_setpoint_cooling
            else:
                setpoint = self.config.unoccupied_setpoint_heating
            fan_on = False
        
        # Lighting dimming
        dimming = self._calculate_dimming(is_occupied, daylight_lux)
        
        action = ControlAction(
            hvac_setpoint=setpoint,
            fan_on=fan_on,
            dimming_level=dimming
        )
        
        self.previous_actions[zone_name] = action
        
        return action
    
    def compute_all_actions(
        self,
        zone_states: Dict[str, Dict],
        outdoor_temp: float,
        daylight_lux: float
    ) -> Dict[str, ControlAction]:
        """
        Compute control actions for all zones.
        
        Args:
            zone_states: Dictionary with zone state info
                Each zone: {'temperature', 'illumination', 'occupancy'}
            outdoor_temp: Outdoor temperature
            daylight_lux: Current daylight level
            
        Returns:
            Dictionary mapping zone names to ControlActions
        """
        actions = {}
        
        for zone_name, state in zone_states.items():
            action = self.compute_action(
                zone_name=zone_name,
                current_temp=state.get('temperature', 22.0),
                current_lux=state.get('illumination', 0.0),
                is_occupied=state.get('occupancy', 0) > 0,
                outdoor_temp=outdoor_temp,
                daylight_lux=daylight_lux
            )
            actions[zone_name] = action
        
        return actions
    
    def get_previous_action(self, zone_name: str) -> Optional[ControlAction]:
        """Get the previous action for a zone."""
        return self.previous_actions.get(zone_name)
    
    def reset(self) -> None:
        """Reset controller state."""
        self.previous_actions.clear()
