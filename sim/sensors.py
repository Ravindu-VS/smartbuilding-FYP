"""
Sensor Simulator Module

Adds realistic sensor noise and sampling behavior to simulation data.
Models various sensor imperfections.
"""

from dataclasses import dataclass
from typing import Dict, Any
import numpy as np


@dataclass
class SensorConfig:
    """Configuration for a sensor type."""
    noise_std: float  # Standard deviation of noise
    sampling_rate_seconds: int  # Sampling rate
    bias: float = 0.0  # Constant bias
    drift_rate: float = 0.0  # Drift rate per hour


@dataclass
class OccupancySensorConfig:
    """Configuration for occupancy sensors."""
    false_positive_rate: float  # Probability of detecting when unoccupied
    false_negative_rate: float  # Probability of missing detection when occupied


class SensorSimulator:
    """
    Simulates sensor behavior with noise and artifacts.
    
    Features:
    - Gaussian noise for continuous sensors
    - Sampling rate simulation
    - Sensor bias and drift
    - Occupancy sensor false positives/negatives
    """
    
    def __init__(self, config: Dict, random_seed: int = 42):
        """
        Initialize sensor simulator.
        
        Args:
            config: Configuration dictionary
            random_seed: Random seed for reproducibility
        """
        self.rng = np.random.default_rng(random_seed)
        
        # Temperature sensor config
        temp_config = config.get('temperature', {})
        self.temp_sensor = SensorConfig(
            noise_std=temp_config.get('noise_std', 0.2),
            sampling_rate_seconds=temp_config.get('sampling_rate_seconds', 60)
        )
        
        # Illumination sensor config
        lux_config = config.get('illumination', {})
        self.lux_sensor = SensorConfig(
            noise_std=lux_config.get('noise_std', 10.0),
            sampling_rate_seconds=lux_config.get('sampling_rate_seconds', 60)
        )
        
        # Occupancy sensor config
        occ_config = config.get('occupancy', {})
        self.occ_sensor = OccupancySensorConfig(
            false_positive_rate=occ_config.get('false_positive_rate', 0.02),
            false_negative_rate=occ_config.get('false_negative_rate', 0.05)
        )
        
        # Track last sampled values
        self.last_sample_time: Dict[str, float] = {}
        self.last_values: Dict[str, Any] = {}
    
    def add_temperature_noise(self, true_temp: float) -> float:
        """
        Add noise to temperature measurement.
        
        Args:
            true_temp: True temperature value
            
        Returns:
            Noisy temperature reading
        """
        noise = self.rng.normal(0, self.temp_sensor.noise_std)
        return true_temp + noise
    
    def add_illumination_noise(self, true_lux: float) -> float:
        """
        Add noise to illumination measurement.
        
        Args:
            true_lux: True illumination value
            
        Returns:
            Noisy illumination reading
        """
        noise = self.rng.normal(0, self.lux_sensor.noise_std)
        return max(0.0, true_lux + noise)
    
    def add_occupancy_noise(self, true_occupancy: int) -> int:
        """
        Apply occupancy sensor errors.
        
        Args:
            true_occupancy: True occupancy count
            
        Returns:
            Sensed occupancy (binary: 0 or 1 for simplicity)
        """
        is_occupied = true_occupancy > 0
        
        if is_occupied:
            # May miss detection
            if self.rng.random() < self.occ_sensor.false_negative_rate:
                return 0
            return 1
        else:
            # May have false detection
            if self.rng.random() < self.occ_sensor.false_positive_rate:
                return 1
            return 0
    
    def sample_sensors(
        self,
        zone_name: str,
        true_temp: float,
        true_lux: float,
        true_occupancy: int,
        current_time: float
    ) -> Dict[str, float]:
        """
        Sample all sensors for a zone with proper timing.
        
        Args:
            zone_name: Zone identifier
            true_temp: True temperature
            true_lux: True illumination
            true_occupancy: True occupancy
            current_time: Current simulation time (seconds)
            
        Returns:
            Dictionary with sensor readings
        """
        key = f"{zone_name}_sample"
        
        # Check if enough time has passed since last sample
        last_time = self.last_sample_time.get(key, -999999)
        
        # Use temperature sampling rate as reference
        if current_time - last_time >= self.temp_sensor.sampling_rate_seconds:
            # Take new samples
            readings = {
                'temperature': self.add_temperature_noise(true_temp),
                'illumination': self.add_illumination_noise(true_lux),
                'occupancy': self.add_occupancy_noise(true_occupancy)
            }
            
            self.last_sample_time[key] = current_time
            self.last_values[key] = readings
            
            return readings
        else:
            # Return last sampled values
            return self.last_values.get(key, {
                'temperature': true_temp,
                'illumination': true_lux,
                'occupancy': true_occupancy
            })
    
    def add_humidity_noise(self, true_humidity: float) -> float:
        """
        Add noise to humidity measurement.
        
        Args:
            true_humidity: True humidity value
            
        Returns:
            Noisy humidity reading
        """
        noise = self.rng.normal(0, 2.0)  # ±2% typical
        return max(0.0, min(100.0, true_humidity + noise))
    
    def add_co2_noise(self, true_co2: float) -> float:
        """
        Add noise to CO2 measurement.
        
        Args:
            true_co2: True CO2 value (ppm)
            
        Returns:
            Noisy CO2 reading
        """
        noise = self.rng.normal(0, 30.0)  # ±30 ppm typical
        return max(0.0, true_co2 + noise)
    
    def add_power_noise(self, true_power: float) -> float:
        """
        Add noise to power measurement.
        
        Args:
            true_power: True power value (watts)
            
        Returns:
            Noisy power reading
        """
        # Power meters typically have ~1-2% accuracy
        relative_noise = self.rng.normal(0, 0.015)
        return max(0.0, true_power * (1 + relative_noise))
