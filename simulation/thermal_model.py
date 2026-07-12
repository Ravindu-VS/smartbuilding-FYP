"""
Advanced Thermal Modeling (2R2C Circuit)

Implements second-order (2R2C) thermal dynamics for realistic building physics.
Models heat transfer through walls, infiltration, and internal gains.
"""

import math
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class ZoneThermalState:
    """
    Thermal state variables for a zone using 2R2C model.

    The model splits thermal mass between:
    - T_wall: Wall surface/structure temperature
    - T_zone: Air temperature (more responsive)
    """
    zone_id: int
    temperature_zone: float = 20.0      # Zone air temperature (°C)
    temperature_wall: float = 20.0      # Wall surface temperature (°C)
    temperature_radiant: float = 20.0   # Mean radiant temperature (°C)

    # Time constants (seconds)
    tau_wall: float = 3600.0  # Wall thermal time constant (~1 hour)
    tau_zone: float = 300.0   # Air thermal time constant (~5 min)


@dataclass
class ThermalProperties:
    """Enhanced thermal properties for advanced modeling."""
    # Resistances (K/W) - describe heat flow resistance
    r_wall_external: float = 0.13  # Exterior surface resistance
    r_wall_internal: float = 0.11  # Interior surface resistance
    r_wall_mass: float = 0.5       # Through wall structure

    # Capacitances (J/K) - describe thermal mass
    c_wall: float = 1000000.0  # Wall thermal mass (~1 ton material)
    c_zone_air: float = 150000.0  # Zone air mass (~50 m³ air at 1.2 kg/m³)

    # Infiltration
    infiltration_ach_base: float = 0.5  # Base air changes per hour
    infiltration_wind_coeff: float = 0.001  # Wind dependence

    # Surface properties
    u_value_external: float = 0.3  # Overall U-value (W/m²K)
    u_value_internal: float = 2.0  # Internal wall U-value (higher)

    @property
    def r_total_external(self) -> float:
        """Total resistance from outdoor to zone."""
        return self.r_wall_external + self.r_wall_mass + self.r_wall_internal

    @property
    def r_wall_to_zone(self) -> float:
        """Resistance from wall to zone air."""
        return self.r_wall_internal


class ThermalZone:
    """
    Thermal zone implementing 2R2C circuit model.

    Models heat transfer:
    - T_outdoor → [R_ext] → T_wall → [R_int] → T_zone
    -                │                    │
    -              [C_wall]            [C_zone]

    With heat gains:
    - Q_internal (occupancy, equipment, lighting)
    - Q_solar (solar through windows)
    - Q_inter_zone (heat from adjacent zones)
    - Q_hvac (HVAC system)
    """

    def __init__(self, zone_id: int, thermal_properties: ThermalProperties,
                 zone_volume: float = 108.0):  # m³ (6×6×3 typical room)
        """
        Initialize thermal zone.

        Args:
            zone_id: Zone identifier
            thermal_properties: ThermalProperties dataclass
            zone_volume: Zone volume in cubic meters
        """
        self.zone_id = zone_id
        self.properties = thermal_properties
        self.volume = zone_volume

        # State variables
        self.state = ZoneThermalState(zone_id=zone_id)

        # Derived time constants
        self._calculate_time_constants()

    def _calculate_time_constants(self):
        """Calculate thermal time constants from RC values."""
        # τ = R × C (seconds)
        self.state.tau_wall = self.properties.r_wall_mass * self.properties.c_wall
        self.state.tau_zone = self.properties.r_wall_to_zone * self.properties.c_zone_air

    def update(self, dt: float, t_outdoor: float, q_internal: float = 0.0,
               q_solar: float = 0.0, q_inter_zone: float = 0.0, q_hvac: float = 0.0,
               wind_speed: float = 0.0):
        """
        Update zone temperature using 2R2C dynamics.

        Args:
            dt: Time step (seconds)
            t_outdoor: Outdoor air temperature (°C)
            q_internal: Internal gains (W) - occupancy, equipment, lighting
            q_solar: Solar gain through windows (W)
            q_inter_zone: Heat transfer from adjacent zones (W)
            q_hvac: HVAC heating/cooling (W)
            wind_speed: Wind speed (m/s) - affects infiltration
        """
        # Current state
        t_wall = self.state.temperature_wall
        t_zone = self.state.temperature_zone

        # Calculate infiltration rate (ACH)
        ach = self._calculate_infiltration(t_zone, t_outdoor, wind_speed)

        # Calculate infiltration heat loss
        q_infiltration = self._calculate_infiltration_heat_loss(
            ach, t_zone, t_outdoor
        )

        # Wall surface dynamics
        # dT_wall/dt = (1/C_wall) × [(T_outdoor - T_wall)/R_ext + (T_zone - T_wall)/R_int]
        r_ext_total = self.properties.r_wall_external + self.properties.r_wall_mass
        dt_wall_dt = (1.0 / self.properties.c_wall) * (
            (t_outdoor - t_wall) / r_ext_total +
            (t_zone - t_wall) / self.properties.r_wall_to_zone
        )

        # Zone air dynamics
        # dT_zone/dt = (1/C_zone) × [(T_wall - T_zone)/R_int + Q_gains - Q_losses]
        dt_zone_dt = (1.0 / self.properties.c_zone_air) * (
            (t_wall - t_zone) / self.properties.r_wall_to_zone +
            q_internal + q_solar + q_inter_zone + q_hvac - q_infiltration
        )

        # Euler integration: x(t+dt) = x(t) + dx/dt × dt
        self.state.temperature_wall += dt_wall_dt * dt
        self.state.temperature_zone += dt_zone_dt * dt

        # Update radiant temperature (approximate as zone + offset due to solar)
        solar_fraction = q_solar / max(1.0, q_solar + q_internal + abs(q_hvac))
        solar_offset = solar_fraction * 2.0  # Solar increases radiant temp more
        self.state.temperature_radiant = self.state.temperature_zone + solar_offset

    def _calculate_infiltration(self, t_zone: float, t_outdoor: float,
                               wind_speed: float) -> float:
        """
        Calculate infiltration rate (ACH) using stack effect and wind.

        Args:
            t_zone: Zone temperature (°C)
            t_outdoor: Outdoor temperature (°C)
            wind_speed: Wind speed (m/s)

        Returns:
            Air changes per hour (ACH)
        """
        # Stack effect: increases with temperature difference
        delta_t = abs(t_zone - t_outdoor)
        ach_stack = self.properties.infiltration_ach_base * (delta_t / 20.0)

        # Wind effect: ACH_wind = A × v^n where n ≈ 0.65
        ach_wind = self.properties.infiltration_wind_coeff * (wind_speed ** 0.65)

        # Total infiltration (both effects)
        ach = ach_stack + ach_wind

        return max(0.0, ach)  # Can't be negative

    def _calculate_infiltration_heat_loss(self, ach: float, t_zone: float,
                                         t_outdoor: float) -> float:
        """
        Calculate sensible heat loss due to infiltration.

        Q = ACH × V × ρ × c_p × ΔT / 3600

        Args:
            ach: Air changes per hour
            t_zone: Zone temperature (°C)
            t_outdoor: Outdoor temperature (°C)

        Returns:
            Heat loss (W) - positive means cooling effect
        """
        # Air properties at standard conditions
        rho = 1.2  # Air density (kg/m³) at ~20°C
        c_p = 1005.0  # Specific heat (J/kg·K)

        # Convert ACH to volume flow (m³/s)
        volume_flow = (ach * self.volume) / 3600.0  # m³/s

        # Heat loss = flow × density × specific_heat × ΔT
        delta_t = t_zone - t_outdoor
        q_infiltration = volume_flow * rho * c_p * delta_t

        return max(0.0, q_infiltration)  # Positive = cooling

    def get_operative_temperature(self) -> float:
        """
        Get operative temperature (combination of air and radiant temps).

        For low air velocities: T_op ≈ 0.5 × T_air + 0.5 × T_radiant
        """
        return 0.5 * self.state.temperature_zone + 0.5 * self.state.temperature_radiant

    def reset_history(self):
        """Reset state to initial conditions."""
        self.state.temperature_zone = 20.0
        self.state.temperature_wall = 20.0
        self.state.temperature_radiant = 20.0
