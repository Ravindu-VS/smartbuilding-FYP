"""
Optimizer Module

Multi-objective scoring and constraint handling for building control.
Evaluates energy, comfort, and control smoothness metrics.
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
import math


@dataclass
class OptimizerConfig:
    """Optimizer configuration."""
    energy_weight: float  # Weight for energy cost
    comfort_weight: float  # Weight for comfort violation
    switching_weight: float  # Weight for control switching penalty
    setpoint_change_threshold: float  # Threshold for counting setpoint changes
    dimming_change_threshold: float  # Threshold for dimming changes


@dataclass
class ComfortConfig:
    """Comfort constraint configuration."""
    temp_target_min: float
    temp_target_max: float
    lux_target_min: float
    lux_target_max: float
    temp_penalty_weight: float
    lux_penalty_weight: float


@dataclass
class ComfortMetrics:
    """Comfort violation metrics."""
    temp_violation_deg: float  # Temperature deviation (°C)
    lux_violation: float  # Illumination deviation (lux)
    comfort_score: float  # Combined comfort score (lower is better)
    is_comfortable: bool  # Whether within comfort bounds


@dataclass
class OptimizationResult:
    """Result of optimization scoring."""
    energy_cost: float
    comfort_cost: float
    switching_cost: float
    total_cost: float
    comfort_metrics: ComfortMetrics


class ObjectiveFunction:
    """
    Multi-objective function for building control optimization.
    
    Objectives:
    1. Minimize energy consumption (HVAC + lighting + plug loads)
    2. Minimize comfort violations (temperature and illumination)
    3. Minimize control switching (smooth control)
    
    Returns a weighted sum as total_cost plus individual metrics.
    """
    
    def __init__(self, config: Dict):
        """
        Initialize objective function.
        
        Args:
            config: Configuration dictionary with optimizer and comfort sections
        """
        opt_cfg = config.get('optimizer', {})
        self.opt_config = OptimizerConfig(
            energy_weight=opt_cfg.get('energy_weight', 1.0),
            comfort_weight=opt_cfg.get('comfort_weight', 5.0),
            switching_weight=opt_cfg.get('switching_weight', 0.5),
            setpoint_change_threshold=opt_cfg.get('setpoint_change_threshold', 0.5),
            dimming_change_threshold=opt_cfg.get('dimming_change_threshold', 0.1)
        )
        
        comfort_cfg = config.get('comfort', {})
        self.comfort_config = ComfortConfig(
            temp_target_min=comfort_cfg.get('temp_target_min', 22.0),
            temp_target_max=comfort_cfg.get('temp_target_max', 24.0),
            lux_target_min=comfort_cfg.get('lux_target_min', 300.0),
            lux_target_max=comfort_cfg.get('lux_target_max', 500.0),
            temp_penalty_weight=comfort_cfg.get('temp_penalty_weight', 10.0),
            lux_penalty_weight=comfort_cfg.get('lux_penalty_weight', 0.1)
        )
        
        # Track previous actions for switching penalty
        self.previous_setpoints: Dict[str, float] = {}
        self.previous_dimming: Dict[str, float] = {}
    
    def compute_comfort_metrics(
        self,
        temperature: float,
        illumination: float,
        is_occupied: bool
    ) -> ComfortMetrics:
        """
        Compute comfort metrics for a zone.
        
        Args:
            temperature: Current temperature (°C)
            illumination: Current illumination (lux)
            is_occupied: Whether zone is occupied
            
        Returns:
            ComfortMetrics with violation details
        """
        if not is_occupied:
            # No comfort violations when unoccupied
            return ComfortMetrics(
                temp_violation_deg=0.0,
                lux_violation=0.0,
                comfort_score=0.0,
                is_comfortable=True
            )
        
        # Temperature violation
        if temperature < self.comfort_config.temp_target_min:
            temp_violation = self.comfort_config.temp_target_min - temperature
        elif temperature > self.comfort_config.temp_target_max:
            temp_violation = temperature - self.comfort_config.temp_target_max
        else:
            temp_violation = 0.0
        
        # Illumination violation
        if illumination < self.comfort_config.lux_target_min:
            lux_violation = self.comfort_config.lux_target_min - illumination
        elif illumination > self.comfort_config.lux_target_max:
            lux_violation = illumination - self.comfort_config.lux_target_max
        else:
            lux_violation = 0.0
        
        # Combined comfort score
        comfort_score = (
            temp_violation * self.comfort_config.temp_penalty_weight +
            lux_violation * self.comfort_config.lux_penalty_weight
        )
        
        is_comfortable = temp_violation == 0.0 and lux_violation == 0.0
        
        return ComfortMetrics(
            temp_violation_deg=temp_violation,
            lux_violation=lux_violation,
            comfort_score=comfort_score,
            is_comfortable=is_comfortable
        )
    
    def compute_energy_cost(
        self,
        hvac_power_w: float,
        lighting_power_w: float,
        plug_power_w: float,
        dt_hours: float
    ) -> float:
        """
        Compute energy cost component.
        
        Uses energy consumption scaled to reasonable cost units.
        
        Args:
            hvac_power_w: HVAC power (watts)
            lighting_power_w: Lighting power (watts)
            plug_power_w: Plug load power (watts)
            dt_hours: Time step (hours)
            
        Returns:
            Energy cost (arbitrary units)
        """
        # Convert to kWh
        total_kwh = (hvac_power_w + lighting_power_w + plug_power_w) / 1000.0 * dt_hours
        
        # Simple linear cost (could add time-of-use rates)
        return total_kwh
    
    def compute_switching_cost(
        self,
        zone_name: str,
        setpoint: float,
        dimming: float
    ) -> float:
        """
        Compute control switching penalty.
        
        Penalizes frequent changes in control actions.
        
        Args:
            zone_name: Zone name
            setpoint: Current setpoint
            dimming: Current dimming level
            
        Returns:
            Switching cost
        """
        cost = 0.0
        
        # Setpoint switching
        prev_setpoint = self.previous_setpoints.get(zone_name)
        if prev_setpoint is not None:
            delta = abs(setpoint - prev_setpoint)
            if delta >= self.opt_config.setpoint_change_threshold:
                cost += delta * 0.5  # Scale factor
        
        # Dimming switching
        prev_dimming = self.previous_dimming.get(zone_name)
        if prev_dimming is not None:
            delta = abs(dimming - prev_dimming)
            if delta >= self.opt_config.dimming_change_threshold:
                cost += delta * 0.2  # Scale factor
        
        return cost
    
    def update_previous_actions(
        self,
        zone_name: str,
        setpoint: float,
        dimming: float
    ) -> None:
        """Update tracked previous actions."""
        self.previous_setpoints[zone_name] = setpoint
        self.previous_dimming[zone_name] = dimming
    
    def evaluate(
        self,
        zone_name: str,
        temperature: float,
        illumination: float,
        is_occupied: bool,
        hvac_power_w: float,
        lighting_power_w: float,
        plug_power_w: float,
        setpoint: float,
        dimming: float,
        dt_seconds: float
    ) -> OptimizationResult:
        """
        Evaluate the objective function for a zone.
        
        Args:
            zone_name: Zone name
            temperature: Current temperature
            illumination: Current illumination
            is_occupied: Occupancy status
            hvac_power_w: HVAC power consumption
            lighting_power_w: Lighting power consumption
            plug_power_w: Plug load power consumption
            setpoint: Current setpoint
            dimming: Current dimming level
            dt_seconds: Time step in seconds
            
        Returns:
            OptimizationResult with costs and metrics
        """
        dt_hours = dt_seconds / 3600.0
        
        # Compute individual costs
        comfort_metrics = self.compute_comfort_metrics(
            temperature, illumination, is_occupied
        )
        
        energy_cost = self.compute_energy_cost(
            hvac_power_w, lighting_power_w, plug_power_w, dt_hours
        )
        
        switching_cost = self.compute_switching_cost(
            zone_name, setpoint, dimming
        )
        
        # Weighted sum
        total_cost = (
            self.opt_config.energy_weight * energy_cost +
            self.opt_config.comfort_weight * comfort_metrics.comfort_score +
            self.opt_config.switching_weight * switching_cost
        )
        
        return OptimizationResult(
            energy_cost=energy_cost,
            comfort_cost=comfort_metrics.comfort_score,
            switching_cost=switching_cost,
            total_cost=total_cost,
            comfort_metrics=comfort_metrics
        )
    
    def evaluate_building(
        self,
        zone_results: Dict[str, OptimizationResult]
    ) -> OptimizationResult:
        """
        Aggregate zone results into building-level metrics.
        
        Args:
            zone_results: Dictionary of zone optimization results
            
        Returns:
            Aggregated OptimizationResult
        """
        total_energy = sum(r.energy_cost for r in zone_results.values())
        total_comfort = sum(r.comfort_cost for r in zone_results.values())
        total_switching = sum(r.switching_cost for r in zone_results.values())
        total_cost = sum(r.total_cost for r in zone_results.values())
        
        # Average comfort metrics
        if zone_results:
            avg_temp_violation = sum(
                r.comfort_metrics.temp_violation_deg
                for r in zone_results.values()
            ) / len(zone_results)
            avg_lux_violation = sum(
                r.comfort_metrics.lux_violation
                for r in zone_results.values()
            ) / len(zone_results)
        else:
            avg_temp_violation = 0.0
            avg_lux_violation = 0.0
        
        return OptimizationResult(
            energy_cost=total_energy,
            comfort_cost=total_comfort,
            switching_cost=total_switching,
            total_cost=total_cost,
            comfort_metrics=ComfortMetrics(
                temp_violation_deg=avg_temp_violation,
                lux_violation=avg_lux_violation,
                comfort_score=total_comfort,
                is_comfortable=total_comfort == 0.0
            )
        )
    
    def reset(self) -> None:
        """Reset previous action tracking."""
        self.previous_setpoints.clear()
        self.previous_dimming.clear()
