"""
Plug Loads Generator Module

Models miscellaneous electrical loads from equipment, computers, etc.
Includes occupancy-dependent and baseline components.
"""

from dataclasses import dataclass
from typing import Dict
from datetime import datetime
import numpy as np


@dataclass
class PlugLoadConfig:
    """Plug load configuration for a zone."""
    baseline_watts: float  # Baseline (always-on) power
    occupancy_dependent_watts: float  # Additional power per occupant
    random_variability: float  # Random variation factor (0-1)


class PlugLoadGenerator:
    """
    Plug load generator.
    
    Models:
    - Baseline loads (servers, always-on equipment)
    - Occupancy-dependent loads (computers, monitors)
    - Random variation for realism
    """
    
    def __init__(self, random_seed: int = 42):
        """
        Initialize plug load generator.
        
        Args:
            random_seed: Random seed for reproducibility
        """
        self.rng = np.random.default_rng(random_seed)
        self.zone_configs: Dict[str, PlugLoadConfig] = {}
        
        # Current power per zone
        self.zone_power: Dict[str, float] = {}
    
    def initialize_zone(
        self,
        zone_name: str,
        baseline_watts: float,
        variability: float = 0.1
    ) -> None:
        """
        Initialize plug load configuration for a zone.
        
        Args:
            zone_name: Zone name
            baseline_watts: Baseline power consumption
            variability: Random variation factor
        """
        # Assume 60% is always-on, 40% is occupancy-dependent
        # Per-occupant power ~60W (computer + monitor)
        self.zone_configs[zone_name] = PlugLoadConfig(
            baseline_watts=baseline_watts * 0.4,  # Always-on portion
            occupancy_dependent_watts=60.0,  # Per occupant
            random_variability=variability
        )
        
        self.zone_power[zone_name] = baseline_watts * 0.4
    
    def compute_plug_load(
        self,
        zone_name: str,
        occupancy: int,
        hour_of_day: float
    ) -> float:
        """
        Compute plug load power for a zone.
        
        Args:
            zone_name: Zone name
            occupancy: Current occupancy count
            hour_of_day: Current hour (0-24)
            
        Returns:
            Power consumption in watts
        """
        if zone_name not in self.zone_configs:
            return 0.0
        
        config = self.zone_configs[zone_name]
        
        # Baseline load (always present)
        baseline = config.baseline_watts
        
        # Occupancy-dependent load
        occupancy_load = occupancy * config.occupancy_dependent_watts
        
        # Time-dependent factor for baseline
        # Lower at night, slightly higher during day
        if 6 <= hour_of_day <= 22:
            time_factor = 1.0
        else:
            time_factor = 0.6  # Reduced at night
        
        # Random variation
        noise = 1.0 + self.rng.normal(0, config.random_variability)
        noise = max(0.7, min(1.3, noise))
        
        total_power = (baseline * time_factor + occupancy_load) * noise
        
        self.zone_power[zone_name] = max(0.0, total_power)
        return self.zone_power[zone_name]
    
    def compute_all_loads(
        self,
        occupancies: Dict[str, int],
        hour_of_day: float
    ) -> Dict[str, float]:
        """
        Compute plug loads for all zones.
        
        Args:
            occupancies: Occupancy per zone
            hour_of_day: Current hour
            
        Returns:
            Dictionary mapping zone names to power (watts)
        """
        return {
            zone_name: self.compute_plug_load(zone_name, occ, hour_of_day)
            for zone_name, occ in occupancies.items()
        }
    
    def get_total_power(self) -> float:
        """Get total plug load power."""
        return sum(self.zone_power.values())
    
    def get_zone_power(self, zone_name: str) -> float:
        """Get plug load power for a zone."""
        return self.zone_power.get(zone_name, 0.0)
