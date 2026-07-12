"""
Thermal Comfort and Air Quality Metrics

Implements human comfort indices used to evaluate zone conditions:
- Operative temperature (combined air + radiant)
- PMV (Predicted Mean Vote) / Fanger model
- Draught risk and local thermal discomfort
- Air quality indices (CO2, humidity)
- Overall comfort index

Phase 3: Advanced metrics for occupant comfort assessment.
"""

import math
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional


class ComfortLevel(Enum):
    """Thermal comfort classification."""
    COLD = 0
    COOL = 1
    SLIGHTLY_COOL = 2
    NEUTRAL = 3
    SLIGHTLY_WARM = 4
    WARM = 5
    HOT = 6


class AirQualityLevel(Enum):
    """Air quality classification based on CO2."""
    EXCELLENT = 0
    GOOD = 1
    FAIR = 2
    POOR = 3
    UNACCEPTABLE = 4


@dataclass
class ComfortMetrics:
    """Comfort metrics for a zone."""
    operative_temperature: float  # °C
    pmv: float  # Predicted Mean Vote (-3 to +3)
    ppd: float  # Predicted Percentage Dissatisfied (0-100%)
    draught_risk: float  # Draught risk (0-100%)
    thermal_comfort: str  # Comfort level description
    co2_level: int  # ppm
    humidity: float  # %
    air_quality: str  # Air quality level description
    overall_comfort_index: float  # 0-100
    recommendations: list  # Comfort improvement suggestions


class ThermalComfortCalculator:
    """
    Calculates thermal comfort indices using Fanger's PMV-PPD model.

    The Predicted Mean Vote (PMV) model predicts the mean thermal vote
    of a large group of people on a standard 7-point scale (-3 to +3)
    where -3 is cold and +3 is hot.

    References:
    - ISO 7730: Ergonomics of the thermal environment
    - Fanger, P.O. (1970): Thermal Comfort
    """

    # PMV model constants
    _PMV_C1 = 0.303 * math.exp(-0.036 * 75.0)  # Metabolic rate adjustment
    _PMV_C2 = 0.028  # Core temperature sensitivity

    @staticmethod
    def calculate_pmv(t_operative: float, humidity: float,
                      air_velocity: float = 0.1,
                      metabolic_rate: float = 1.0,
                      clothing_level: float = 0.5) -> float:
        """
        Calculate Predicted Mean Vote (PMV) using Fanger's model.

        Simplified version suitable for building simulation.

        Args:
            t_operative: Operative temperature (°C)
            humidity: Relative humidity (0-100%)
            air_velocity: Air velocity (m/s), default 0.1 (still air)
            metabolic_rate: Metabolic rate (met, 1.0 = seated, 1.5 = standing)
            clothing_level: Clothing insulation (clo, 0.5 = office summer, 1.0 = winter)

        Returns:
            PMV value (-3 to +3, where 0 is neutral)
        """
        # Saturation partial pressure of water vapor
        p_sat = 610.5 * math.exp((17.27 * t_operative) / (t_operative + 237.7))
        p_vap = (humidity / 100.0) * p_sat

        # Mean radiant temperature approximation (assume equal to operative temp in room)
        t_mrt = t_operative

        # Clothing factor
        f_cl = 1.0 + 1.29 * clothing_level

        # Heat production and losses (calculate first)
        M = metabolic_rate * 58.15  # Convert met to W/m²
        W = 0.0  # No work (typical office)

        # Convective heat transfer coefficient
        h_c = 5.8 + 42.2 * (air_velocity ** 0.6)

        # Evaporative heat loss (basic estimate)
        evaporative_loss = 0.0433 * (p_sat - p_vap)

        # Estimate clothing surface temperature (iterative in full model, simplified here)
        t_cl = t_operative - (M - W - evaporative_loss) / (f_cl * h_c)
        t_cl = max(0.0, min(50.0, t_cl))

        # Radiative heat loss (Stefan-Boltzmann)
        t_mrt_k = t_mrt + 273.15
        t_cl_k = t_cl + 273.15
        h_r = 4.0 * 0.95 * 5.67e-8 * ((t_cl_k ** 4 - t_mrt_k ** 4) / (t_cl_k - t_mrt_k + 1e-6))

        # Sensible heat loss
        heat_loss_sensible = (h_c + h_r) * f_cl * (t_cl - t_operative)
        heat_loss_latent = evaporative_loss * f_cl

        # PMV calculation (Fanger's equation)
        pmv = (0.303 * math.exp(-0.036 * M) + 0.028) * (M - W - heat_loss_sensible - heat_loss_latent)

        return max(-3.0, min(3.0, pmv))

    @staticmethod
    def calculate_ppd(pmv: float) -> float:
        """
        Calculate Predicted Percentage Dissatisfied (PPD) from PMV.

        PPD = 100 - 95 × exp(-0.03353 × PMV⁴ - 0.2179 × PMV²)

        Args:
            pmv: Predicted Mean Vote (-3 to +3)

        Returns:
            PPD percentage (0-100%)
        """
        ppd = 100.0 - 95.0 * math.exp(
            -0.03353 * (pmv ** 4) - 0.2179 * (pmv ** 2)
        )
        return max(0.0, min(100.0, ppd))

    @staticmethod
    def pmv_to_comfort_level(pmv: float) -> ComfortLevel:
        """
        Convert PMV to comfort level category.

        Args:
            pmv: Predicted Mean Vote (-3 to +3)

        Returns:
            ComfortLevel enum
        """
        if pmv < -2.0:
            return ComfortLevel.COLD
        elif pmv < -1.0:
            return ComfortLevel.COOL
        elif pmv < -0.5:
            return ComfortLevel.SLIGHTLY_COOL
        elif pmv < 0.5:
            return ComfortLevel.NEUTRAL
        elif pmv < 1.0:
            return ComfortLevel.SLIGHTLY_WARM
        elif pmv < 2.0:
            return ComfortLevel.WARM
        else:
            return ComfortLevel.HOT


class AirQualityCalculator:
    """Calculates air quality indices based on CO2 and humidity."""

    # CO2 thresholds (ppm)
    CO2_EXCELLENT = 400
    CO2_GOOD = 600
    CO2_FAIR = 1000
    CO2_POOR = 1400

    # Humidity thresholds (%)
    HUMIDITY_MIN_COMFORT = 30
    HUMIDITY_MAX_COMFORT = 60

    @staticmethod
    def co2_to_air_quality(co2_ppm: int) -> AirQualityLevel:
        """
        Classify air quality based on CO2 level.

        Args:
            co2_ppm: CO2 concentration in ppm

        Returns:
            AirQualityLevel enum
        """
        if co2_ppm <= AirQualityCalculator.CO2_EXCELLENT:
            return AirQualityLevel.EXCELLENT
        elif co2_ppm <= AirQualityCalculator.CO2_GOOD:
            return AirQualityLevel.GOOD
        elif co2_ppm <= AirQualityCalculator.CO2_FAIR:
            return AirQualityLevel.FAIR
        elif co2_ppm <= AirQualityCalculator.CO2_POOR:
            return AirQualityLevel.POOR
        else:
            return AirQualityLevel.UNACCEPTABLE

    @staticmethod
    def humidity_satisfaction(humidity: float) -> float:
        """
        Calculate satisfaction with humidity level (0-1).

        Optimal range: 30-60% RH
        Penalty increases exponentially outside this range.

        Args:
            humidity: Relative humidity (%)

        Returns:
            Satisfaction 0-1 (1.0 = optimal)
        """
        if AirQualityCalculator.HUMIDITY_MIN_COMFORT <= humidity <= AirQualityCalculator.HUMIDITY_MAX_COMFORT:
            return 1.0
        elif humidity < AirQualityCalculator.HUMIDITY_MIN_COMFORT:
            # Too dry - dissatisfaction increases as humidity drops
            deficit = AirQualityCalculator.HUMIDITY_MIN_COMFORT - humidity
            return max(0.0, 1.0 - 0.02 * deficit)
        else:
            # Too humid
            excess = humidity - AirQualityCalculator.HUMIDITY_MAX_COMFORT
            return max(0.0, 1.0 - 0.02 * excess)


class ComfortIndex:
    """
    Overall comfort index combining thermal, air quality, and environmental factors.
    """

    @staticmethod
    def calculate_overall_index(pmv: float, ppd: float, co2_ppm: int,
                                humidity: float) -> float:
        """
        Calculate overall comfort index (0-100, where 100 is ideal).

        Weighing:
        - 40% PMV/PPD (thermal comfort)
        - 30% CO2/Air quality
        - 30% Humidity

        Args:
            pmv: Predicted Mean Vote (-3 to +3)
            ppd: Predicted Percentage Dissatisfied (0-100)
            co2_ppm: CO2 concentration (ppm)
            humidity: Relative humidity (%)

        Returns:
            Overall comfort index (0-100)
        """
        # Thermal comfort score (inversely proportional to PPD)
        thermal_score = max(0.0, 100.0 - ppd)

        # Air quality score (based on CO2)
        air_quality_level = AirQualityCalculator.co2_to_air_quality(co2_ppm)
        air_quality_score = {
            AirQualityLevel.EXCELLENT: 100,
            AirQualityLevel.GOOD: 85,
            AirQualityLevel.FAIR: 70,
            AirQualityLevel.POOR: 40,
            AirQualityLevel.UNACCEPTABLE: 0
        }.get(air_quality_level, 50)

        # Humidity score
        humidity_satisfaction = AirQualityCalculator.humidity_satisfaction(humidity)
        humidity_score = humidity_satisfaction * 100.0

        # Weighted average
        overall_index = (
            0.40 * thermal_score +
            0.30 * air_quality_score +
            0.30 * humidity_score
        )

        return max(0.0, min(100.0, overall_index))


class ComfortMetricsCalculator:
    """
    Complete comfort metrics for a zone.

    Combines thermal, air quality, and environmental assessments.
    """

    @staticmethod
    def calculate_all_metrics(t_operative: float, t_radiant: float,
                             humidity: float, co2_ppm: int,
                             air_velocity: float = 0.1,
                             metabolic_rate: float = 1.0,
                             clothing_level: float = 0.5) -> ComfortMetrics:
        """
        Calculate comprehensive comfort metrics for a zone.

        Args:
            t_operative: Operative temperature (°C)
            t_radiant: Mean radiant temperature (°C)
            humidity: Relative humidity (0-100%)
            co2_ppm: CO2 concentration (ppm)
            air_velocity: Air velocity (m/s)
            metabolic_rate: Metabolic rate (met)
            clothing_level: Clothing insulation (clo)

        Returns:
            ComfortMetrics dataclass
        """
        # Thermal comfort
        pmv = ThermalComfortCalculator.calculate_pmv(
            t_operative, humidity, air_velocity, metabolic_rate, clothing_level
        )
        ppd = ThermalComfortCalculator.calculate_ppd(pmv)
        comfort_level = ThermalComfortCalculator.pmv_to_comfort_level(pmv)

        # Air quality
        air_quality_level = AirQualityCalculator.co2_to_air_quality(co2_ppm)

        # Overall index
        overall_index = ComfortIndex.calculate_overall_index(
            pmv, ppd, co2_ppm, humidity
        )

        # Recommendations
        recommendations = ComfortMetricsCalculator._generate_recommendations(
            pmv, ppd, co2_ppm, humidity, comfort_level
        )

        return ComfortMetrics(
            operative_temperature=t_operative,
            pmv=pmv,
            ppd=ppd,
            draught_risk=ComfortMetricsCalculator._estimate_draught_risk(air_velocity, t_operative),
            thermal_comfort=comfort_level.name,
            co2_level=co2_ppm,
            humidity=humidity,
            air_quality=air_quality_level.name,
            overall_comfort_index=overall_index,
            recommendations=recommendations
        )

    @staticmethod
    def _estimate_draught_risk(air_velocity: float, operative_temp: float) -> float:
        """
        Estimate draught risk based on air velocity and temperature.

        Higher risk with higher velocities and lower temperatures.

        Args:
            air_velocity: Air velocity (m/s)
            operative_temp: Operative temperature (°C)

        Returns:
            Draught risk (0-100%)
        """
        if operative_temp > 23:
            base_risk = 0.0
        elif operative_temp > 20:
            base_risk = (23.0 - operative_temp) * 10.0
        else:
            base_risk = 30.0

        # Velocity effect (nonlinear)
        velocity_factor = (air_velocity ** 1.5) * 100.0

        draught_risk = base_risk + velocity_factor
        return max(0.0, min(100.0, draught_risk))

    @staticmethod
    def _generate_recommendations(pmv: float, ppd: float, co2_ppm: int,
                                 humidity: float, comfort_level: ComfortLevel) -> list:
        """
        Generate comfort improvement recommendations.

        Args:
            pmv: Predicted Mean Vote
            ppd: Predicted Percentage Dissatisfied
            co2_ppm: CO2 level
            humidity: Humidity level
            comfort_level: Thermal comfort level

        Returns:
            List of recommendations
        """
        recommendations = []

        # Thermal recommendations
        if comfort_level in [ComfortLevel.COLD, ComfortLevel.COOL]:
            recommendations.append("Temperature is too cold - increase heating")
        elif comfort_level in [ComfortLevel.WARM, ComfortLevel.HOT]:
            recommendations.append("Temperature is too warm - increase cooling/ventilation")

        # CO2 recommendations
        if co2_ppm > AirQualityCalculator.CO2_POOR:
            recommendations.append("CO2 level very high - increase ventilation immediately")
        elif co2_ppm > AirQualityCalculator.CO2_FAIR:
            recommendations.append("CO2 level elevated - open windows or increase fresh air supply")

        # Humidity recommendations
        if humidity < AirQualityCalculator.HUMIDITY_MIN_COMFORT:
            recommendations.append("Air is too dry - increase humidity")
        elif humidity > AirQualityCalculator.HUMIDITY_MAX_COMFORT:
            recommendations.append("Air is too humid - increase dehumidification/ventilation")

        # PPD recommendations
        if ppd > 20:
            recommendations.append("More than 20% of occupants dissatisfied - adjust conditions")

        return recommendations if recommendations else ["Conditions are acceptable"]
