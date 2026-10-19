import os
import sys
import numpy as np
import yaml
from datetime import datetime, timedelta
from typing import Dict, Optional, Any
from dataclasses import dataclass

# Ensure project root is on path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from control.baseline_rule_controller import ControlAction
from stable_baselines3 import PPO

class PPOController:
    """
    PPO Controller Adapter that loads the trained RL policy
    and converts predictions into ControlActions matching the simulator expectations.
    """
    
    def __init__(self, config: Dict, model_path: str = "models/ppo_building_controller.zip"):
        self.config = config
        
        # Load zone names and order from config
        self.zone_names = [zone["name"] for zone in config["building"]["zones"]]
        self.num_zones = len(self.zone_names)
        
        # Initialize internal simulation clock for hour of day estimation
        self.start_date_str = config["simulation"].get("start_date", "2024-01-15")
        self.dt = config["simulation"].get("time_step_seconds", 60)
        self.current_time = datetime.strptime(self.start_date_str, "%Y-%m-%d")
        
        # Load trained PPO model
        # If model is not trained yet, we will fallback to baseline controller rules
        self.model = None
        self.model_path = model_path
        if os.path.exists(self.model_path) or os.path.exists(self.model_path.replace(".zip", "")):
            try:
                self.model = PPO.load(self.model_path)
                print(f"[OK] PPO Controller loaded policy weights from {self.model_path}")
            except Exception as e:
                print(f"[Warning] Failed to load PPO weights: {e}. Falling back to baseline heuristics.")
        else:
            print(f"[Warning] PPO model weights file {self.model_path} not found. Running with fallback baseline.")
            
        # Fallback controller configuration
        from control.baseline_rule_controller import BaselineRuleController
        self.fallback_controller = BaselineRuleController(config)
        self.previous_actions = {}

    def compute_all_actions(
        self,
        zone_states: Dict[str, Dict],
        outdoor_temp: float,
        daylight_lux: float,
        dt_seconds: Optional[float] = None
    ) -> Dict[str, ControlAction]:
        """
        Compute control actions for all zones using PPO model, with fallback to baseline rules.
        """
        # If model not available, run fallback rules
        if self.model is None:
            return self.fallback_controller.compute_all_actions(zone_states, outdoor_temp, daylight_lux)
            
        # 1. Reconstruct observation vector
        hour_of_day = self.current_time.hour + self.current_time.minute / 60.0
        
        obs_list = []
        for zone_name in self.zone_names:
            state = zone_states[zone_name]
            obs_list.append(state.get('temperature', 22.0))
            obs_list.append(state.get('illumination', 0.0))
            obs_list.append(float(state.get('occupancy', 0)))
            
        obs_list.append(outdoor_temp)
        obs_list.append(daylight_lux)
        obs_list.append(hour_of_day)
        
        obs_array = np.array(obs_list, dtype=np.float32)
        
        # 2. Query PPO model
        try:
            action, _ = self.model.predict(obs_array, deterministic=True)
        except Exception as e:
            print(f"Error predicting action with PPO: {e}. Falling back to baseline.")
            return self.fallback_controller.compute_all_actions(zone_states, outdoor_temp, daylight_lux)
            
        # 3. Rescale actions to control outputs
        actions = {}
        for i, zone_name in enumerate(self.zone_names):
            raw_hvac_act = action[i * 2]
            raw_light_act = action[i * 2 + 1]
            
            # Rescale HVAC: [-1, 1] -> [18.0, 26.0]
            hvac_setpoint = 18.0 + (raw_hvac_act + 1.0) * 4.0
            # Rescale Dimming: [-1, 1] -> [0.0, 1.0]
            dimming_level = (raw_light_act + 1.0) / 2.0
            
            # Fan is turned ON if there is occupancy in the zone
            is_occupied = zone_states[zone_name].get('occupancy', 0) > 0
            
            control_action = ControlAction(
                hvac_setpoint=float(hvac_setpoint),
                fan_on=bool(is_occupied),
                dimming_level=float(dimming_level)
            )
            actions[zone_name] = control_action
            self.previous_actions[zone_name] = control_action
            
        # 4. Advance internal clock
        step_dt = dt_seconds if dt_seconds is not None else self.dt
        self.current_time += timedelta(seconds=step_dt)
        
        return actions

    def reset(self) -> None:
        """Reset internal controller state."""
        self.current_time = datetime.strptime(self.start_date_str, "%Y-%m-%d")
        self.previous_actions.clear()
        self.fallback_controller.reset()
