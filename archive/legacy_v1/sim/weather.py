"""
Weather Generator Module

Generates synthetic weather data or loads from CSV.
Models outdoor temperature, solar irradiance, and cloud cover.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import math
import csv


@dataclass
class WeatherConfig:
    """Weather generator configuration."""
    mode: str  # 'synthetic' or 'csv'
    csv_path: str  # Path to weather CSV
    base_temp_c: float  # Annual average temperature
    daily_amplitude_c: float  # Daily temperature swing
    seasonal_amplitude_c: float  # Seasonal temperature swing
    cloud_cover_variability: float  # Cloud cover randomness


@dataclass
class WeatherState:
    """Current weather conditions."""
    outdoor_temp_c: float  # Outdoor temperature
    solar_irradiance_w_m2: float  # Solar irradiance
    cloud_cover: float  # Cloud cover (0-1)
    humidity_percent: float  # Relative humidity
    wind_speed_m_s: float  # Wind speed


class WeatherGenerator:
    """
    Weather data generator.
    
    Can operate in two modes:
    - Synthetic: Generates realistic weather using mathematical models
    - CSV: Loads weather data from a CSV file
    """
    
    # Solar constant (W/m²)
    SOLAR_CONSTANT = 1361.0
    
    # Latitude for solar calculations (default: mid-latitude ~40°N)
    LATITUDE_DEG = 40.0
    
    def __init__(self, config: Dict, random_seed: int = 42):
        """
        Initialize weather generator.
        
        Args:
            config: Configuration dictionary
            random_seed: Random seed for reproducibility
        """
        import numpy as np
        self.rng = np.random.default_rng(random_seed)
        
        self.config = WeatherConfig(
            mode=config.get('mode', 'synthetic'),
            csv_path=config.get('csv_path', ''),
            base_temp_c=config.get('base_temp_c', 15.0),
            daily_amplitude_c=config.get('daily_amplitude_c', 8.0),
            seasonal_amplitude_c=config.get('seasonal_amplitude_c', 12.0),
            cloud_cover_variability=config.get('cloud_cover_variability', 0.3)
        )
        
        # CSV data storage
        self.csv_data: List[Dict] = []
        
        # Weather persistence (for realistic day-to-day correlation)
        self.weather_trend = 0.0  # Current weather trend (-1 to 1)
        
        if self.config.mode == 'csv' and self.config.csv_path:
            self._load_csv()
    
    def _load_csv(self) -> None:
        """Load weather data from CSV file."""
        try:
            with open(self.config.csv_path, 'r') as f:
                reader = csv.DictReader(f)
                self.csv_data = list(reader)
        except FileNotFoundError:
            print(f"Warning: Weather CSV not found at {self.config.csv_path}")
            print("Falling back to synthetic weather generation.")
            self.config.mode = 'synthetic'
    
    def _day_of_year(self, timestamp: datetime) -> int:
        """Get day of year (1-365)."""
        return timestamp.timetuple().tm_yday
    
    def _solar_declination(self, day_of_year: int) -> float:
        """Calculate solar declination angle (radians)."""
        # Approximate formula
        return math.radians(23.45) * math.sin(
            2 * math.pi * (284 + day_of_year) / 365
        )
    
    def _hour_angle(self, hour: float) -> float:
        """Calculate hour angle (radians)."""
        # Solar noon at 12:00
        return math.radians(15 * (hour - 12))
    
    def _solar_altitude(
        self,
        day_of_year: int,
        hour: float
    ) -> float:
        """
        Calculate solar altitude angle.
        
        Args:
            day_of_year: Day of year (1-365)
            hour: Hour of day (0-24)
            
        Returns:
            Solar altitude in radians
        """
        lat = math.radians(self.LATITUDE_DEG)
        dec = self._solar_declination(day_of_year)
        ha = self._hour_angle(hour)
        
        sin_alt = (
            math.sin(lat) * math.sin(dec) +
            math.cos(lat) * math.cos(dec) * math.cos(ha)
        )
        
        return math.asin(max(-1, min(1, sin_alt)))
    
    def _calculate_solar_irradiance(
        self,
        day_of_year: int,
        hour: float,
        cloud_cover: float
    ) -> float:
        """
        Calculate solar irradiance on horizontal surface.
        
        Args:
            day_of_year: Day of year
            hour: Hour of day
            cloud_cover: Cloud cover fraction (0-1)
            
        Returns:
            Solar irradiance (W/m²)
        """
        altitude = self._solar_altitude(day_of_year, hour)
        
        if altitude <= 0:
            return 0.0
        
        # Clear sky irradiance (with atmospheric attenuation)
        # Simple model: I = I0 * sin(altitude) * atmospheric_factor
        atmospheric_factor = 0.7  # Accounts for atmosphere
        clear_sky = self.SOLAR_CONSTANT * math.sin(altitude) * atmospheric_factor
        
        # Apply cloud cover reduction
        cloud_factor = 1.0 - 0.75 * cloud_cover
        
        return max(0.0, clear_sky * cloud_factor)
    
    def _generate_cloud_cover(self, previous_cover: float) -> float:
        """Generate cloud cover with temporal correlation."""
        # Random walk with mean reversion
        trend = self.rng.normal(0, self.config.cloud_cover_variability)
        new_cover = previous_cover + trend
        
        # Mean reversion toward 0.5
        new_cover += 0.1 * (0.5 - new_cover)
        
        return max(0.0, min(1.0, new_cover))
    
    def _calculate_outdoor_temp(
        self,
        timestamp: datetime,
        cloud_cover: float
    ) -> float:
        """
        Calculate outdoor temperature.
        
        Combines:
        - Seasonal variation
        - Daily variation
        - Cloud cover effect
        - Random variation
        """
        day_of_year = self._day_of_year(timestamp)
        hour = timestamp.hour + timestamp.minute / 60
        
        # Seasonal component (coldest in winter, warmest in summer)
        # Offset by ~11 days for thermal lag
        seasonal_phase = 2 * math.pi * (day_of_year - 11) / 365
        seasonal = -self.config.seasonal_amplitude_c * math.cos(seasonal_phase)
        
        # Daily component (coldest at ~5am, warmest at ~3pm)
        daily_phase = 2 * math.pi * (hour - 5) / 24
        daily = -self.config.daily_amplitude_c * math.cos(daily_phase) / 2
        
        # Cloud cover effect (clouds reduce daily swing, warm nights, cool days)
        cloud_effect = 0.0
        if 6 <= hour <= 18:
            # Daytime: clouds cool
            cloud_effect = -3 * cloud_cover
        else:
            # Nighttime: clouds warm
            cloud_effect = 2 * cloud_cover
        
        # Random variation
        random_var = self.rng.normal(0, 1.5)
        
        temp = (
            self.config.base_temp_c +
            seasonal +
            daily +
            cloud_effect +
            random_var
        )
        
        return temp
    
    def get_weather(self, timestamp: datetime) -> WeatherState:
        """
        Get weather conditions for given timestamp.
        
        Args:
            timestamp: Current datetime
            
        Returns:
            WeatherState with current conditions
        """
        if self.config.mode == 'csv' and self.csv_data:
            return self._get_weather_from_csv(timestamp)
        else:
            return self._generate_synthetic_weather(timestamp)
    
    def _get_weather_from_csv(self, timestamp: datetime) -> WeatherState:
        """Get weather from CSV data."""
        # Find closest timestamp in CSV
        # This is a simplified approach - production would use proper interpolation
        
        # For now, fall back to synthetic if CSV parsing is complex
        return self._generate_synthetic_weather(timestamp)
    
    def _generate_synthetic_weather(self, timestamp: datetime) -> WeatherState:
        """Generate synthetic weather data."""
        day_of_year = self._day_of_year(timestamp)
        hour = timestamp.hour + timestamp.minute / 60
        
        # Update cloud cover with persistence
        cloud_cover = self._generate_cloud_cover(
            getattr(self, '_last_cloud_cover', 0.3)
        )
        self._last_cloud_cover = cloud_cover
        
        # Calculate other parameters
        outdoor_temp = self._calculate_outdoor_temp(timestamp, cloud_cover)
        solar_irradiance = self._calculate_solar_irradiance(
            day_of_year, hour, cloud_cover
        )
        
        # Humidity (simplified model)
        humidity = 50 + 20 * cloud_cover + self.rng.normal(0, 5)
        humidity = max(20, min(95, humidity))
        
        # Wind speed (simplified)
        wind_speed = abs(self.rng.normal(3, 2))
        
        return WeatherState(
            outdoor_temp_c=outdoor_temp,
            solar_irradiance_w_m2=solar_irradiance,
            cloud_cover=cloud_cover,
            humidity_percent=humidity,
            wind_speed_m_s=wind_speed
        )
    
    def get_season(self, timestamp: datetime) -> str:
        """Determine current season."""
        day_of_year = self._day_of_year(timestamp)
        
        if day_of_year < 80 or day_of_year >= 355:
            return 'winter'
        elif day_of_year < 172:
            return 'spring'
        elif day_of_year < 266:
            return 'summer'
        else:
            return 'fall'
    
    def is_heating_season(self, timestamp: datetime) -> bool:
        """Check if it's heating season."""
        outdoor_temp = self._calculate_outdoor_temp(
            timestamp, self._last_cloud_cover if hasattr(self, '_last_cloud_cover') else 0.3
        )
        return outdoor_temp < 15.0
