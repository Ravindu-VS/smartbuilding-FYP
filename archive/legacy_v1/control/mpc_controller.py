"""
MPC-like Controller Module

Implements a Model Predictive Control approach using look-ahead simulation.
Evaluates candidate actions over a prediction horizon to minimize total cost.
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
from copy import deepcopy
import itertools

from .optimizer import ObjectiveFunction, OptimizationResult
from .baseline_rule_controller import ControlAction


@dataclass
class MPCConfig:
    """MPC controller configuration."""
    horizon_steps: int  # Number of look-ahead steps
    candidate_setpoints: List[float]  # Discrete setpoint candidates
    candidate_dimming: List[float]  # Discrete dimming candidates
    prediction_noise: float  # Uncertainty factor for predictions


class MPCController:
    """
    MPC-like controller with look-ahead optimization.
    
    Features:
    - Simulates building response over prediction horizon
    - Evaluates discrete action candidates
    - Selects action minimizing total cost
    - Handles constraints through penalty in objective
    """
    
    def __init__(self, config: Dict, building_model, hvac_system, lighting_system):
        """
        Initialize MPC controller.
        
        Args:
            config: Configuration dictionary
            building_model: Building thermal model instance
            hvac_system: HVAC system instance
            lighting_system: Lighting system instance
        """
        mpc_cfg = config.get('mpc', {})
        
        self.config = MPCConfig(
            horizon_steps=mpc_cfg.get('horizon_steps', 30),
            candidate_setpoints=mpc_cfg.get('candidate_setpoints', [20, 22, 23, 24, 26]),
            candidate_dimming=mpc_cfg.get('candidate_dimming', [0.0, 0.3, 0.5, 0.7, 1.0]),
            prediction_noise=mpc_cfg.get('prediction_noise', 0.1)
        )
        
        # Store references to models for simulation
        self.building_config = config.get('building', {})
        self.hvac_config = config.get('hvac', {})
        self.lighting_config = config.get('lighting', {})
        self.full_config = config
        
        # Optimizer for cost evaluation
        self.optimizer = ObjectiveFunction(config)
        
        # Previous actions
        self.previous_actions: Dict[str, ControlAction] = {}
        
        # For fast simulation, we won't clone full models
        # Instead, we use simplified prediction
    
    def _predict_temperature(
        self,
        current_temp: float,
        setpoint: float,
        outdoor_temp: float,
        occupancy: int,
        steps: int,
        dt: float
    ) -> List[float]:
        """
        Predict temperature trajectory.
        
        Uses simplified first-order model for fast prediction:
        dT/dt = -k * (T - T_target) + disturbance
        
        Args:
            current_temp: Current temperature
            setpoint: HVAC setpoint
            outdoor_temp: Outdoor temperature
            occupancy: Occupancy count
            steps: Number of prediction steps
            dt: Time step (seconds)
            
        Returns:
            List of predicted temperatures
        """
        temps = [current_temp]
        T = current_temp
        
        # Simplified thermal time constant (~1 hour)
        tau = 3600.0
        k = dt / tau
        
        # HVAC drives temperature toward setpoint
        # Outdoor temp and occupancy add disturbance
        
        for _ in range(steps):
            # Disturbance from outdoor temp
            outdoor_effect = (outdoor_temp - T) * 0.002 * dt
            
            # Heat from occupants
            occupant_effect = occupancy * 0.001 * dt
            
            # HVAC effect (strong pull toward setpoint)
            hvac_effect = (setpoint - T) * k
            
            T = T + hvac_effect + outdoor_effect + occupant_effect
            temps.append(T)
        
        return temps
    
    def _predict_lighting(
        self,
        dimming: float,
        daylight_lux: float
    ) -> float:
        """
        Predict illumination level.
        
        Args:
            dimming: Dimming level
            daylight_lux: Daylight contribution
            
        Returns:
            Total predicted illumination
        """
        max_artificial = 600.0  # Maximum artificial lux
        artificial = max_artificial * dimming
        return daylight_lux + artificial
    
    def _evaluate_candidate(
        self,
        zone_name: str,
        setpoint: float,
        dimming: float,
        current_temp: float,
        outdoor_temp: float,
        daylight_lux: float,
        occupancy: int,
        dt: float
    ) -> float:
        """
        Evaluate a candidate action over prediction horizon.
        
        Args:
            zone_name: Zone name
            setpoint: Candidate setpoint
            dimming: Candidate dimming
            current_temp: Current temperature
            outdoor_temp: Outdoor temperature
            daylight_lux: Daylight level
            occupancy: Occupancy count
            dt: Time step
            
        Returns:
            Total predicted cost over horizon
        """
        horizon = min(self.config.horizon_steps, 30)  # Limit for speed
        
        # Predict temperature trajectory
        temps = self._predict_temperature(
            current_temp, setpoint, outdoor_temp, occupancy, horizon, dt
        )
        
        # Predict illumination (assumed constant over horizon)
        illum = self._predict_lighting(dimming, daylight_lux)
        
        # Estimate power consumption
        # HVAC power estimate
        temp_error = abs(setpoint - current_temp)
        hvac_power = min(temp_error * 2000, 15000)  # Simple proportional
        
        # Lighting power
        lighting_baseline = 1000.0  # Approximate baseline
        lighting_power = lighting_baseline * dimming
        
        # Plug power (constant estimate)
        plug_power = 500.0
        
        # Compute cost over horizon
        total_cost = 0.0
        is_occupied = occupancy > 0
        
        for i, temp in enumerate(temps):
            result = self.optimizer.evaluate(
                zone_name=zone_name,
                temperature=temp,
                illumination=illum,
                is_occupied=is_occupied,
                hvac_power_w=hvac_power,
                lighting_power_w=lighting_power,
                plug_power_w=plug_power,
                setpoint=setpoint,
                dimming=dimming,
                dt_seconds=dt
            )
            
            # Discount future costs slightly
            discount = 0.98 ** i
            total_cost += result.total_cost * discount
        
        return total_cost
    
    def _get_candidate_actions(
        self,
        is_occupied: bool
    ) -> List[Tuple[float, float]]:
        """
        Get list of candidate (setpoint, dimming) pairs.
        
        Reduces candidates based on occupancy for speed.
        
        Args:
            is_occupied: Whether zone is occupied
            
        Returns:
            List of (setpoint, dimming) tuples
        """
        if is_occupied:
            # Full set of candidates
            setpoints = self.config.candidate_setpoints
            dimmings = self.config.candidate_dimming
        else:
            # Reduced set for unoccupied
            setpoints = [18.0, 26.0]  # Extreme setbacks
            dimmings = [0.0]  # Lights off
        
        return list(itertools.product(setpoints, dimmings))
    
    def compute_action(
        self,
        zone_name: str,
        current_temp: float,
        current_lux: float,
        is_occupied: bool,
        outdoor_temp: float,
        daylight_lux: float,
        occupancy: int,
        dt: float
    ) -> ControlAction:
        """
        Compute optimal control action using MPC.
        
        Args:
            zone_name: Zone name
            current_temp: Current temperature
            current_lux: Current illumination
            is_occupied: Occupancy status
            outdoor_temp: Outdoor temperature
            daylight_lux: Daylight level
            occupancy: Occupancy count
            dt: Time step (seconds)
            
        Returns:
            Optimal ControlAction
        """
        candidates = self._get_candidate_actions(is_occupied)
        
        best_cost = float('inf')
        best_action = ControlAction(
            hvac_setpoint=23.0,
            fan_on=True,
            dimming_level=0.5
        )
        
        for setpoint, dimming in candidates:
            cost = self._evaluate_candidate(
                zone_name=zone_name,
                setpoint=setpoint,
                dimming=dimming,
                current_temp=current_temp,
                outdoor_temp=outdoor_temp,
                daylight_lux=daylight_lux,
                occupancy=occupancy,
                dt=dt
            )
            
            if cost < best_cost:
                best_cost = cost
                best_action = ControlAction(
                    hvac_setpoint=setpoint,
                    fan_on=is_occupied or abs(setpoint - current_temp) > 1.0,
                    dimming_level=dimming
                )
        
        # Update optimizer's previous action tracking
        self.optimizer.update_previous_actions(
            zone_name, best_action.hvac_setpoint, best_action.dimming_level
        )
        
        self.previous_actions[zone_name] = best_action
        
        return best_action
    
    def compute_all_actions(
        self,
        zone_states: Dict[str, Dict],
        outdoor_temp: float,
        daylight_lux: float,
        dt: float
    ) -> Dict[str, ControlAction]:
        """
        Compute control actions for all zones.
        
        Args:
            zone_states: Dictionary with zone state info
            outdoor_temp: Outdoor temperature
            daylight_lux: Current daylight level
            dt: Time step (seconds)
            
        Returns:
            Dictionary mapping zone names to ControlActions
        """
        actions = {}
        
        for zone_name, state in zone_states.items():
            occupancy = state.get('occupancy', 0)
            action = self.compute_action(
                zone_name=zone_name,
                current_temp=state.get('temperature', 22.0),
                current_lux=state.get('illumination', 0.0),
                is_occupied=occupancy > 0,
                outdoor_temp=outdoor_temp,
                daylight_lux=daylight_lux,
                occupancy=occupancy,
                dt=dt
            )
            actions[zone_name] = action
        
        return actions
    
    def get_previous_action(self, zone_name: str) -> Optional[ControlAction]:
        """Get the previous action for a zone."""
        return self.previous_actions.get(zone_name)
    
    def reset(self) -> None:
        """Reset controller state."""
        self.previous_actions.clear()
        self.optimizer.reset()
