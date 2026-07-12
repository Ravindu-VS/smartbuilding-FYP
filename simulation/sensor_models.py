"""
Advanced Sensor Models

Realistic sensor simulation with lag, noise, and dynamic response.
Handles temperature lag, humidity response, CO2 diffusion, etc.
"""

from typing import Dict
import math


class AdvancedSensorModels:
    """
    Advanced sensor models with realistic dynamics and noise.
    """

    def __init__(self, config: Dict = None):
        """
        Initialize sensor models with configuration.

        Args:
            config: Configuration dict with sensor parameters
        """
        self.config = config or {}

        # Sensor time constants (in seconds)
        self.temp_time_constant = self.config.get("temp_time_constant", 180.0)  # 3 min
        self.humidity_time_constant = self.config.get("humidity_time_constant", 240.0)  # 4 min
        self.co2_time_constant = self.config.get("co2_time_constant", 300.0)  # 5 min

        # Sensor noise levels (standard deviation)
        self.temp_noise_std = self.config.get("temp_noise_std", 0.1)  # ±0.1°C
        self.humidity_noise_std = self.config.get("humidity_noise_std", 1.0)  # ±1%
        self.co2_noise_std = self.config.get("co2_noise_std", 5.0)  # ±5 ppm

        # Sensor bias/drift
        self.temp_bias = self.config.get("temp_bias", 0.0)
        self.humidity_bias = self.config.get("humidity_bias", 0.0)

        # State tracking for first-order lag simulation
        self.last_temperatures = {}  # room_id -> last sensor reading
        self.last_humidities = {}
        self.last_co2 = {}

    def temperature_with_lag(self, room_id: int, true_temp: float, dt: float) -> float:
        """
        Apply first-order lag to temperature reading.
        Models thermal mass of sensor and display electronics.

        Args:
            room_id: Room identifier
            true_temp: Actual room temperature
            dt: Time step (seconds)

        Returns:
            Lagged temperature reading
        """
        if room_id not in self.last_temperatures:
            self.last_temperatures[room_id] = true_temp

        # First-order lag: T_new = T_old + (T_true - T_old) * (dt / tau)
        tau = self.temp_time_constant
        factor = dt / (tau + dt)
        sensor_reading = self.last_temperatures[room_id] + factor * (true_temp - self.last_temperatures[room_id])

        # Add noise
        sensor_reading += self._gaussian_noise(self.temp_noise_std)

        # Add bias
        sensor_reading += self.temp_bias

        self.last_temperatures[room_id] = sensor_reading
        return sensor_reading

    def humidity_with_lag(self, room_id: int, true_humidity: float, dt: float) -> float:
        """
        Apply first-order lag to humidity reading.

        Args:
            room_id: Room identifier
            true_humidity: Actual room humidity (%)
            dt: Time step (seconds)

        Returns:
            Lagged humidity reading
        """
        if room_id not in self.last_humidities:
            self.last_humidities[room_id] = true_humidity

        tau = self.humidity_time_constant
        factor = dt / (tau + dt)
        sensor_reading = self.last_humidities[room_id] + factor * (true_humidity - self.last_humidities[room_id])

        # Add noise
        sensor_reading += self._gaussian_noise(self.humidity_noise_std)

        # Add bias
        sensor_reading += self.humidity_bias

        # Clamp to valid range
        sensor_reading = max(0.0, min(100.0, sensor_reading))

        self.last_humidities[room_id] = sensor_reading
        return sensor_reading

    def co2_with_lag(self, room_id: int, true_co2: float, dt: float) -> float:
        """
        Apply first-order lag to CO2 reading.
        Slower response than temperature due to diffusion.

        Args:
            room_id: Room identifier
            true_co2: Actual room CO2 (ppm)
            dt: Time step (seconds)

        Returns:
            Lagged CO2 reading
        """
        if room_id not in self.last_co2:
            self.last_co2[room_id] = true_co2

        tau = self.co2_time_constant
        factor = dt / (tau + dt)
        sensor_reading = self.last_co2[room_id] + factor * (true_co2 - self.last_co2[room_id])

        # Add noise
        sensor_reading += self._gaussian_noise(self.co2_noise_std)

        # CO2 doesn't go below 400 ppm (atmospheric baseline)
        sensor_reading = max(400.0, sensor_reading)

        self.last_co2[room_id] = sensor_reading
        return sensor_reading

    @staticmethod
    def _gaussian_noise(std_dev: float) -> float:
        """
        Generate Gaussian random noise.

        Args:
            std_dev: Standard deviation

        Returns:
            Random value from normal distribution
        """
        # Box-Muller transform for Gaussian noise
        import random
        u1 = random.random()
        u2 = random.random()
        z = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
        return z * std_dev

    def light_sensor_reading(self, true_lux: float, sensor_range: float = 100000.0) -> float:
        """
        Light sensor reading with first-order lag, noise, and saturation.

        Args:
            true_lux: Actual illuminance (lux)
            sensor_range: Maximum sensor range (lux)

        Returns:
            Simulated sensor reading with lag and noise
        """
        # Initialize tracking if needed
        if not hasattr(self, '_last_light'):
            self._last_light = true_lux

        # First-order lag (light sensors respond faster than temp sensors)
        lag_factor = 0.3  # Faster response than temperature
        self._last_light += (true_lux - self._last_light) * lag_factor

        # Add small sensor noise (±2% of reading)
        noise = self._gaussian_noise(self._last_light * 0.02)
        reading = self._last_light + noise

        # Clamp: light sensors can saturate in bright sunlight
        return max(0.0, min(reading, sensor_range))

    def occupancy_with_uncertainty(self, true_occupancy: int, false_positive_rate: float = 0.05) -> int:
        """
        Occupancy sensor reading with false positive/negative rates.

        Args:
            true_occupancy: Actual number of people
            false_positive_rate: Probability of detecting person when empty

        Returns:
            Detected occupancy count
        """
        import random

        detected = true_occupancy

        # Add false positives (detect when no one there)
        if true_occupancy == 0 and random.random() < false_positive_rate:
            detected = 1

        # Add uncertainty to detection count (±1 person)
        if true_occupancy > 0 and random.random() < 0.1:
            detected = max(0, detected + random.choice([-1, 1]))

        return detected

    def reset_state(self):
        """Reset all sensor state tracking."""
        self.last_temperatures.clear()
        self.last_humidities.clear()
        self.last_co2.clear()
