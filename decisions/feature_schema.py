"""
Feature Schema & Extraction - ML-Ready Building Control

Standardizes feature extraction for ML models.
Defines feature ranges, normalization, and schema validation.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
import numpy as np
from decisions.controller import DecisionContext


@dataclass
class FeatureDefinition:
    """Metadata for a single feature."""
    name: str
    description: str
    min_value: float
    max_value: float
    unit: str
    feature_type: str  # "temperature", "occupancy", "comfort", "environmental", "actuator", "time"


class FeatureSchema:
    """
    Standard feature schema for ML models.

    Defines all features used by decision models with ranges and types.
    Phase 6: ML-ready interface for scikit-learn / PyTorch integration.
    """

    # Feature definitions (name -> FeatureDefinition)
    FEATURES = {
        # Temperature features (4)
        "temperature_zone": FeatureDefinition(
            "temperature_zone", "Zone air temperature", 10.0, 30.0, "°C", "temperature"
        ),
        "temperature_wall": FeatureDefinition(
            "temperature_wall", "Wall surface temperature", 10.0, 30.0, "°C", "temperature"
        ),
        "temperature_operative": FeatureDefinition(
            "temperature_operative", "Operative temperature", 10.0, 30.0, "°C", "temperature"
        ),
        "outdoor_temperature": FeatureDefinition(
            "outdoor_temperature", "Outdoor temperature", -15.0, 45.0, "°C", "temperature"
        ),

        # Humidity & Air Quality (2)
        "humidity": FeatureDefinition(
            "humidity", "Relative humidity", 20.0, 80.0, "%", "air_quality"
        ),
        "co2": FeatureDefinition(
            "co2", "CO2 concentration", 400.0, 2000.0, "ppm", "air_quality"
        ),

        # Light (1)
        "light_level": FeatureDefinition(
            "light_level", "Illuminance level", 0.0, 1000.0, "lux", "environmental"
        ),

        # Occupancy (1)
        "occupancy": FeatureDefinition(
            "occupancy", "Occupancy count", 0.0, 10.0, "count", "occupancy"
        ),

        # Comfort Metrics (3)
        "pmv": FeatureDefinition(
            "pmv", "Predicted Mean Vote (thermal comfort)", -3.0, 3.0, "votes", "comfort"
        ),
        "ppd": FeatureDefinition(
            "ppd", "Predicted Percentage Dissatisfied", 0.0, 100.0, "%", "comfort"
        ),
        "comfort_index": FeatureDefinition(
            "comfort_index", "Overall comfort metric", 0.0, 100.0, "index", "comfort"
        ),

        # Environmental (2)
        "solar_irradiance": FeatureDefinition(
            "solar_irradiance", "Solar irradiance", 0.0, 1200.0, "W/m²", "environmental"
        ),
        "wind_speed": FeatureDefinition(
            "wind_speed", "Wind speed", 0.0, 20.0, "m/s", "environmental"
        ),

        # Actuator State (4)
        "light_on_current": FeatureDefinition(
            "light_on_current", "Current light state", 0.0, 1.0, "bool", "actuator"
        ),
        "hvac_speed_current": FeatureDefinition(
            "hvac_speed_current", "Current HVAC speed", 0.0, 1.0, "fraction", "actuator"
        ),
        "shading_factor_current": FeatureDefinition(
            "shading_factor_current", "Current shading factor", 0.0, 1.0, "fraction", "actuator"
        ),
        "hvac_mode_heating": FeatureDefinition(
            "hvac_mode_heating", "HVAC heating active", 0.0, 1.0, "bool", "actuator"
        ),

        # Time Context (3)
        "hour_of_day": FeatureDefinition(
            "hour_of_day", "Hour of day", 0.0, 24.0, "hours", "time"
        ),
        "is_occupied_binary": FeatureDefinition(
            "is_occupied_binary", "Binary occupancy indicator", 0.0, 1.0, "bool", "occupancy"
        ),
        "time_of_year": FeatureDefinition(
            "time_of_year", "Day of year normalized", 0.0, 1.0, "fraction", "time"
        ),
    }

    # Order of features (for consistent numpy arrays)
    FEATURE_ORDER = [
        # Temperature (4)
        "temperature_zone",
        "temperature_wall",
        "temperature_operative",
        "outdoor_temperature",
        # Humidity & Air (2)
        "humidity",
        "co2",
        # Light (1)
        "light_level",
        # Occupancy (1)
        "occupancy",
        # Comfort (3)
        "pmv",
        "ppd",
        "comfort_index",
        # Environmental (2)
        "solar_irradiance",
        "wind_speed",
        # Actuator State (4)
        "light_on_current",
        "hvac_speed_current",
        "shading_factor_current",
        "hvac_mode_heating",
        # Time (3)
        "hour_of_day",
        "is_occupied_binary",
        "time_of_year",
    ]

    @classmethod
    def get_feature_count(cls) -> int:
        """Get total number of features."""
        return len(cls.FEATURE_ORDER)

    @classmethod
    def validate_feature_value(cls, feature_name: str, value: float) -> bool:
        """Validate that a feature value is within expected range."""
        if feature_name not in cls.FEATURES:
            raise ValueError(f"Unknown feature: {feature_name}")

        feature_def = cls.FEATURES[feature_name]
        return feature_def.min_value <= value <= feature_def.max_value

    @classmethod
    def get_feature_description(cls, feature_name: str) -> str:
        """Get human-readable feature description."""
        if feature_name not in cls.FEATURES:
            return "Unknown feature"
        return f"{cls.FEATURES[feature_name].description} ({cls.FEATURES[feature_name].unit})"


class FeatureExtractor:
    """
    Extracts features from DecisionContext into standard format.

    Converts raw context into both dictionary and normalized numpy array formats
    for compatibility with different ML frameworks.
    """

    @staticmethod
    def extract_dict(context: DecisionContext) -> Dict[str, float]:
        """
        Extract features as dictionary from context.

        Args:
            context: Decision context

        Returns:
            Dictionary of feature_name -> feature_value
        """
        return {
            # Temperature
            "temperature_zone": context.temperature_zone,
            "temperature_wall": context.temperature_wall,
            "temperature_operative": context.temperature_operative,
            "outdoor_temperature": context.outdoor_temperature,
            # Humidity & Air
            "humidity": context.humidity,
            "co2": context.co2,
            # Light
            "light_level": context.light_level,
            # Occupancy
            "occupancy": context.occupancy,
            # Comfort
            "pmv": context.pmv,
            "ppd": context.ppd,
            "comfort_index": context.comfort_index,
            # Environmental
            "solar_irradiance": context.solar_irradiance,
            "wind_speed": context.wind_speed,
            # Actuator State
            "light_on_current": float(context.light_on),
            "hvac_speed_current": context.hvac_speed,
            "shading_factor_current": context.shading_factor,
            "hvac_mode_heating": 1.0 if context.hvac_mode == "heating" else 0.0,
            # Time
            "hour_of_day": context.hour_of_day,
            "is_occupied_binary": float(context.is_occupied),
            "time_of_year": 0.5,  # Placeholder (would need full datetime)
        }

    @staticmethod
    def extract_array(context: DecisionContext) -> np.ndarray:
        """
        Extract features as normalized numpy array.

        Args:
            context: Decision context

        Returns:
            Normalized numpy array (0-1 range) with shape (feature_count,)
        """
        features_dict = FeatureExtractor.extract_dict(context)
        feature_array = np.zeros(FeatureSchema.get_feature_count())

        for i, feature_name in enumerate(FeatureSchema.FEATURE_ORDER):
            feature_def = FeatureSchema.FEATURES[feature_name]
            raw_value = features_dict[feature_name]

            # Normalize to 0-1 range
            normalized = (raw_value - feature_def.min_value) / (
                feature_def.max_value - feature_def.min_value
            )
            feature_array[i] = np.clip(normalized, 0.0, 1.0)

        return feature_array

    @staticmethod
    def extract_batch(contexts: List[DecisionContext]) -> np.ndarray:
        """
        Extract features from multiple contexts as batch.

        Args:
            contexts: List of decision contexts

        Returns:
            Normalized numpy array with shape (batch_size, feature_count)
        """
        return np.array([FeatureExtractor.extract_array(ctx) for ctx in contexts])

    @staticmethod
    def denormalize(normalized_value: float, feature_name: str) -> float:
        """
        Convert normalized value (0-1) back to original range.

        Args:
            normalized_value: Normalized feature value (0-1)
            feature_name: Name of feature

        Returns:
            Denormalized value in original range
        """
        if feature_name not in FeatureSchema.FEATURES:
            raise ValueError(f"Unknown feature: {feature_name}")

        feature_def = FeatureSchema.FEATURES[feature_name]
        raw_value = (
            normalized_value * (feature_def.max_value - feature_def.min_value)
            + feature_def.min_value
        )
        return raw_value
