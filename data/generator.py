"""
Dataset Generator Module

Creates training/testing CSV datasets from simulation runs.
Useful for offline ML model training before hardware is available.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import csv
import os
import json


@dataclass
class DataRecord:
    """Single record in the dataset."""
    timestamp: datetime
    zone_name: str
    
    # State variables
    zone_temperature: float
    wall_temperature: float
    outdoor_temperature: float
    humidity: float
    co2_ppm: float
    illumination: float
    occupancy: int
    
    # Weather
    solar_irradiance: float
    cloud_cover: float
    
    # Control actions
    hvac_setpoint: float
    fan_on: bool
    dimming_level: float
    
    # Power consumption
    hvac_power_w: float
    lighting_power_w: float
    plug_power_w: float
    total_power_w: float
    
    # Metrics
    comfort_violation: float
    temp_violation: float
    lux_violation: float


class DatasetGenerator:
    """
    Generates CSV datasets from simulation data.
    
    Creates comprehensive datasets for:
    - ML model training (supervised learning)
    - Reinforcement learning environment
    - System identification
    - Analysis and visualization
    """
    
    def __init__(self, output_dir: str = "output/data"):
        """
        Initialize dataset generator.
        
        Args:
            output_dir: Directory for output files
        """
        self.output_dir = output_dir
        self.records: List[DataRecord] = []
        self.summary_stats: Dict[str, Any] = {}
        
        # Track cumulative metrics
        self.total_energy_kwh = 0.0
        self.comfort_violation_hours = 0.0
        self.control_switches = 0
        
        # Previous values for switch counting
        self.prev_setpoints: Dict[str, float] = {}
        self.prev_dimming: Dict[str, float] = {}
    
    def add_record(
        self,
        timestamp: datetime,
        zone_name: str,
        zone_temp: float,
        wall_temp: float,
        outdoor_temp: float,
        humidity: float,
        co2_ppm: float,
        illumination: float,
        occupancy: int,
        solar_irradiance: float,
        cloud_cover: float,
        hvac_setpoint: float,
        fan_on: bool,
        dimming_level: float,
        hvac_power_w: float,
        lighting_power_w: float,
        plug_power_w: float,
        comfort_violation: float,
        temp_violation: float,
        lux_violation: float,
        dt_hours: float
    ) -> None:
        """
        Add a data record.
        
        Args:
            timestamp: Record timestamp
            zone_name: Zone identifier
            zone_temp: Zone temperature (°C)
            wall_temp: Wall temperature (°C)
            outdoor_temp: Outdoor temperature (°C)
            humidity: Relative humidity (%)
            co2_ppm: CO2 concentration (ppm)
            illumination: Illumination level (lux)
            occupancy: Number of occupants
            solar_irradiance: Solar irradiance (W/m²)
            cloud_cover: Cloud cover fraction
            hvac_setpoint: HVAC setpoint (°C)
            fan_on: Fan status
            dimming_level: Lighting dimming (0-1)
            hvac_power_w: HVAC power (W)
            lighting_power_w: Lighting power (W)
            plug_power_w: Plug load power (W)
            comfort_violation: Total comfort violation
            temp_violation: Temperature violation (°C)
            lux_violation: Illumination violation (lux)
            dt_hours: Time step in hours
        """
        total_power = hvac_power_w + lighting_power_w + plug_power_w
        
        record = DataRecord(
            timestamp=timestamp,
            zone_name=zone_name,
            zone_temperature=zone_temp,
            wall_temperature=wall_temp,
            outdoor_temperature=outdoor_temp,
            humidity=humidity,
            co2_ppm=co2_ppm,
            illumination=illumination,
            occupancy=occupancy,
            solar_irradiance=solar_irradiance,
            cloud_cover=cloud_cover,
            hvac_setpoint=hvac_setpoint,
            fan_on=fan_on,
            dimming_level=dimming_level,
            hvac_power_w=hvac_power_w,
            lighting_power_w=lighting_power_w,
            plug_power_w=plug_power_w,
            total_power_w=total_power,
            comfort_violation=comfort_violation,
            temp_violation=temp_violation,
            lux_violation=lux_violation
        )
        
        self.records.append(record)
        
        # Update cumulative metrics
        self.total_energy_kwh += total_power / 1000.0 * dt_hours
        
        if comfort_violation > 0 and occupancy > 0:
            self.comfort_violation_hours += dt_hours
        
        # Count control switches
        self._count_switches(zone_name, hvac_setpoint, dimming_level)
    
    def _count_switches(
        self,
        zone_name: str,
        setpoint: float,
        dimming: float
    ) -> None:
        """Count control action switches."""
        if zone_name in self.prev_setpoints:
            if abs(setpoint - self.prev_setpoints[zone_name]) > 0.5:
                self.control_switches += 1
        
        if zone_name in self.prev_dimming:
            if abs(dimming - self.prev_dimming[zone_name]) > 0.1:
                self.control_switches += 1
        
        self.prev_setpoints[zone_name] = setpoint
        self.prev_dimming[zone_name] = dimming
    
    def save_csv(self, filename: str = "simulation_data.csv") -> str:
        """
        Save all records to CSV file.
        
        Args:
            filename: Output filename
            
        Returns:
            Full path to saved file
        """
        os.makedirs(self.output_dir, exist_ok=True)
        filepath = os.path.join(self.output_dir, filename)
        
        if not self.records:
            print("Warning: No records to save")
            return filepath
        
        fieldnames = [
            'timestamp', 'zone_name',
            'zone_temperature', 'wall_temperature', 'outdoor_temperature',
            'humidity', 'co2_ppm', 'illumination', 'occupancy',
            'solar_irradiance', 'cloud_cover',
            'hvac_setpoint', 'fan_on', 'dimming_level',
            'hvac_power_w', 'lighting_power_w', 'plug_power_w', 'total_power_w',
            'comfort_violation', 'temp_violation', 'lux_violation'
        ]
        
        with open(filepath, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for record in self.records:
                row = {
                    'timestamp': record.timestamp.isoformat(),
                    'zone_name': record.zone_name,
                    'zone_temperature': f"{record.zone_temperature:.2f}",
                    'wall_temperature': f"{record.wall_temperature:.2f}",
                    'outdoor_temperature': f"{record.outdoor_temperature:.2f}",
                    'humidity': f"{record.humidity:.1f}",
                    'co2_ppm': f"{record.co2_ppm:.0f}",
                    'illumination': f"{record.illumination:.1f}",
                    'occupancy': record.occupancy,
                    'solar_irradiance': f"{record.solar_irradiance:.1f}",
                    'cloud_cover': f"{record.cloud_cover:.2f}",
                    'hvac_setpoint': f"{record.hvac_setpoint:.1f}",
                    'fan_on': int(record.fan_on),
                    'dimming_level': f"{record.dimming_level:.2f}",
                    'hvac_power_w': f"{record.hvac_power_w:.1f}",
                    'lighting_power_w': f"{record.lighting_power_w:.1f}",
                    'plug_power_w': f"{record.plug_power_w:.1f}",
                    'total_power_w': f"{record.total_power_w:.1f}",
                    'comfort_violation': f"{record.comfort_violation:.3f}",
                    'temp_violation': f"{record.temp_violation:.2f}",
                    'lux_violation': f"{record.lux_violation:.1f}"
                }
                writer.writerow(row)
        
        print(f"Saved {len(self.records)} records to {filepath}")
        return filepath
    
    def get_summary(self) -> Dict:
        """
        Get summary statistics.
        
        Returns:
            Dictionary with summary metrics
        """
        if not self.records:
            return {}
        
        # Power statistics
        total_powers = [r.total_power_w for r in self.records]
        hvac_powers = [r.hvac_power_w for r in self.records]
        
        # Temperature statistics
        temps = [r.zone_temperature for r in self.records]
        
        summary = {
            'total_kwh': self.total_energy_kwh,
            'peak_kw': max(total_powers) / 1000.0 if total_powers else 0.0,
            'avg_power_kw': sum(total_powers) / len(total_powers) / 1000.0 if total_powers else 0.0,
            'comfort_violation_hours': self.comfort_violation_hours,
            'control_switch_count': self.control_switches,
            'avg_temperature': sum(temps) / len(temps) if temps else 0.0,
            'min_temperature': min(temps) if temps else 0.0,
            'max_temperature': max(temps) if temps else 0.0,
            'total_records': len(self.records),
            'hvac_energy_kwh': sum(hvac_powers) / 1000.0 * (1/60) if hvac_powers else 0.0  # Assuming 1-min steps
        }
        
        self.summary_stats = summary
        return summary
    
    def save_summary(self, filename: str = "summary_metrics.json") -> str:
        """
        Save summary statistics to JSON file.
        
        Args:
            filename: Output filename
            
        Returns:
            Full path to saved file
        """
        os.makedirs(self.output_dir, exist_ok=True)
        filepath = os.path.join(self.output_dir, filename)
        
        summary = self.get_summary()
        
        with open(filepath, 'w') as f:
            json.dump(summary, f, indent=2)
        
        print(f"Saved summary to {filepath}")
        return filepath
    
    def reset(self) -> None:
        """Reset all records and statistics."""
        self.records.clear()
        self.summary_stats.clear()
        self.total_energy_kwh = 0.0
        self.comfort_violation_hours = 0.0
        self.control_switches = 0
        self.prev_setpoints.clear()
        self.prev_dimming.clear()
    
    def get_zone_data(self, zone_name: str) -> List[DataRecord]:
        """Get records for a specific zone."""
        return [r for r in self.records if r.zone_name == zone_name]
    
    def get_time_range(self) -> Optional[tuple]:
        """Get time range of collected data."""
        if not self.records:
            return None
        
        timestamps = [r.timestamp for r in self.records]
        return (min(timestamps), max(timestamps))
