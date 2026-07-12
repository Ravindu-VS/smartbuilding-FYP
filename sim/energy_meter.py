"""
Energy Meter Module

Tracks and calculates energy consumption over time.
Provides cumulative and instantaneous power/energy metrics.
"""

from dataclasses import dataclass, field
from typing import Dict, List
from datetime import datetime


@dataclass
class EnergyRecord:
    """Single energy measurement record."""
    timestamp: datetime
    hvac_power_w: float
    lighting_power_w: float
    plug_power_w: float
    total_power_w: float
    
    @property
    def total_power_kw(self) -> float:
        return self.total_power_w / 1000.0


@dataclass
class ZoneEnergyMetrics:
    """Energy metrics for a single zone."""
    total_hvac_kwh: float = 0.0
    total_lighting_kwh: float = 0.0
    total_plug_kwh: float = 0.0
    peak_hvac_kw: float = 0.0
    peak_lighting_kw: float = 0.0
    peak_plug_kw: float = 0.0
    
    @property
    def total_kwh(self) -> float:
        return self.total_hvac_kwh + self.total_lighting_kwh + self.total_plug_kwh
    
    @property
    def peak_kw(self) -> float:
        return self.peak_hvac_kw + self.peak_lighting_kw + self.peak_plug_kw


@dataclass
class BuildingEnergyMetrics:
    """Aggregated energy metrics for the building."""
    total_hvac_kwh: float = 0.0
    total_lighting_kwh: float = 0.0
    total_plug_kwh: float = 0.0
    peak_total_kw: float = 0.0
    peak_hvac_kw: float = 0.0
    peak_lighting_kw: float = 0.0
    peak_plug_kw: float = 0.0
    zone_metrics: Dict[str, ZoneEnergyMetrics] = field(default_factory=dict)
    
    @property
    def total_kwh(self) -> float:
        return self.total_hvac_kwh + self.total_lighting_kwh + self.total_plug_kwh


class EnergyMeter:
    """
    Energy metering and tracking system.
    
    Features:
    - Cumulative energy calculation
    - Peak power tracking
    - Per-zone breakdown
    - Historical data storage
    """
    
    def __init__(self):
        """Initialize energy meter."""
        self.zone_metrics: Dict[str, ZoneEnergyMetrics] = {}
        self.building_metrics = BuildingEnergyMetrics()
        
        # Historical records (for plotting/analysis)
        self.records: List[EnergyRecord] = []
        
        # Current power values
        self.current_hvac_power: Dict[str, float] = {}
        self.current_lighting_power: Dict[str, float] = {}
        self.current_plug_power: Dict[str, float] = {}
        
        # Last update time for energy integration
        self.last_update_time: float = 0.0
    
    def initialize_zone(self, zone_name: str) -> None:
        """
        Initialize metering for a zone.
        
        Args:
            zone_name: Zone name
        """
        self.zone_metrics[zone_name] = ZoneEnergyMetrics()
        self.current_hvac_power[zone_name] = 0.0
        self.current_lighting_power[zone_name] = 0.0
        self.current_plug_power[zone_name] = 0.0
    
    def update(
        self,
        timestamp: datetime,
        hvac_powers: Dict[str, float],
        lighting_powers: Dict[str, float],
        plug_powers: Dict[str, float],
        dt_seconds: float
    ) -> EnergyRecord:
        """
        Update energy meter with current power values.
        
        Args:
            timestamp: Current timestamp
            hvac_powers: HVAC power per zone (watts)
            lighting_powers: Lighting power per zone (watts)
            plug_powers: Plug load power per zone (watts)
            dt_seconds: Time step (seconds)
            
        Returns:
            Current energy record
        """
        dt_hours = dt_seconds / 3600.0
        
        total_hvac = 0.0
        total_lighting = 0.0
        total_plug = 0.0
        
        for zone_name in self.zone_metrics:
            hvac = hvac_powers.get(zone_name, 0.0)
            lighting = lighting_powers.get(zone_name, 0.0)
            plug = plug_powers.get(zone_name, 0.0)
            
            # Update current powers
            self.current_hvac_power[zone_name] = hvac
            self.current_lighting_power[zone_name] = lighting
            self.current_plug_power[zone_name] = plug
            
            # Integrate energy (power * time)
            zone_metrics = self.zone_metrics[zone_name]
            zone_metrics.total_hvac_kwh += (hvac / 1000.0) * dt_hours
            zone_metrics.total_lighting_kwh += (lighting / 1000.0) * dt_hours
            zone_metrics.total_plug_kwh += (plug / 1000.0) * dt_hours
            
            # Update peaks
            zone_metrics.peak_hvac_kw = max(
                zone_metrics.peak_hvac_kw, hvac / 1000.0
            )
            zone_metrics.peak_lighting_kw = max(
                zone_metrics.peak_lighting_kw, lighting / 1000.0
            )
            zone_metrics.peak_plug_kw = max(
                zone_metrics.peak_plug_kw, plug / 1000.0
            )
            
            # Aggregate totals
            total_hvac += hvac
            total_lighting += lighting
            total_plug += plug
        
        # Update building metrics
        self.building_metrics.total_hvac_kwh += (total_hvac / 1000.0) * dt_hours
        self.building_metrics.total_lighting_kwh += (total_lighting / 1000.0) * dt_hours
        self.building_metrics.total_plug_kwh += (total_plug / 1000.0) * dt_hours
        
        total_power = total_hvac + total_lighting + total_plug
        
        self.building_metrics.peak_total_kw = max(
            self.building_metrics.peak_total_kw, total_power / 1000.0
        )
        self.building_metrics.peak_hvac_kw = max(
            self.building_metrics.peak_hvac_kw, total_hvac / 1000.0
        )
        self.building_metrics.peak_lighting_kw = max(
            self.building_metrics.peak_lighting_kw, total_lighting / 1000.0
        )
        self.building_metrics.peak_plug_kw = max(
            self.building_metrics.peak_plug_kw, total_plug / 1000.0
        )
        
        # Create record
        record = EnergyRecord(
            timestamp=timestamp,
            hvac_power_w=total_hvac,
            lighting_power_w=total_lighting,
            plug_power_w=total_plug,
            total_power_w=total_power
        )
        
        self.records.append(record)
        
        return record
    
    def get_current_total_power(self) -> float:
        """Get current total power consumption (watts)."""
        hvac = sum(self.current_hvac_power.values())
        lighting = sum(self.current_lighting_power.values())
        plug = sum(self.current_plug_power.values())
        return hvac + lighting + plug
    
    def get_zone_current_power(self, zone_name: str) -> float:
        """Get current total power for a zone (watts)."""
        hvac = self.current_hvac_power.get(zone_name, 0.0)
        lighting = self.current_lighting_power.get(zone_name, 0.0)
        plug = self.current_plug_power.get(zone_name, 0.0)
        return hvac + lighting + plug
    
    def get_summary(self) -> Dict:
        """
        Get summary of energy consumption.
        
        Returns:
            Dictionary with summary metrics
        """
        return {
            'total_kwh': self.building_metrics.total_kwh,
            'hvac_kwh': self.building_metrics.total_hvac_kwh,
            'lighting_kwh': self.building_metrics.total_lighting_kwh,
            'plug_kwh': self.building_metrics.total_plug_kwh,
            'peak_kw': self.building_metrics.peak_total_kw,
            'peak_hvac_kw': self.building_metrics.peak_hvac_kw,
            'peak_lighting_kw': self.building_metrics.peak_lighting_kw,
            'peak_plug_kw': self.building_metrics.peak_plug_kw,
            'zone_breakdown': {
                name: {
                    'total_kwh': m.total_kwh,
                    'hvac_kwh': m.total_hvac_kwh,
                    'lighting_kwh': m.total_lighting_kwh,
                    'plug_kwh': m.total_plug_kwh
                }
                for name, m in self.zone_metrics.items()
            }
        }
    
    def reset(self) -> None:
        """Reset all meters."""
        for zone in self.zone_metrics.values():
            zone.total_hvac_kwh = 0.0
            zone.total_lighting_kwh = 0.0
            zone.total_plug_kwh = 0.0
            zone.peak_hvac_kw = 0.0
            zone.peak_lighting_kw = 0.0
            zone.peak_plug_kw = 0.0
        
        self.building_metrics = BuildingEnergyMetrics()
        self.records.clear()
