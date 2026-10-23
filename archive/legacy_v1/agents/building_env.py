import os
import sys
import numpy as np
import yaml
import gymnasium as gym
from gymnasium import spaces
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple, Optional

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Import simulation components
from sim.building import BuildingThermalModel
from sim.hvac import HVACSystem
from sim.lighting import LightingSystem
from sim.occupancy import OccupancyGenerator
from sim.weather import WeatherGenerator
from sim.loads import PlugLoadGenerator
from sim.sensors import SensorSimulator
from sim.energy_meter import EnergyMeter
from control.optimizer import ObjectiveFunction

class BuildingEnv(gym.Env):
    """
    Custom Gymnasium Environment wrapping the Smart Building Simulator.
    Allows training of a PPO agent to control HVAC setpoints and Lighting dimming levels.
    """
    metadata = {"render_modes": ["human"]}

    def __init__(self, config_path: str = "config.yaml", max_steps_per_episode: int = 1440):
        super(BuildingEnv, self).__init__()
        
        # Load configuration
        with open(config_path, "r") as f:
            self.config = yaml.safe_load(f)
            
        self.max_steps_per_episode = max_steps_per_episode
        self.dt = self.config["simulation"].get("time_step_seconds", 60)
        self.start_date_str = self.config["simulation"].get("start_date", "2024-01-15")
        
        # Initialize simulation components
        self._setup_components()
        
        self.zones = self.building.get_all_zones()
        self.num_zones = len(self.zones)
        self.zone_names = [zone.name for zone in self.zones]
        
        # Action Space: [HVAC Setpoint, Dimming Level] for each zone
        # We normalize actions to [-1, 1] for stable RL training
        self.action_space = spaces.Box(
            low=-1.0,
            high=1.0,
            shape=(self.num_zones * 2,),
            dtype=np.float32
        )
        
        # Observation Space:
        # For each zone: [Indoor Temp, Illumination, Occupancy] -> size: num_zones * 3
        # Global: [Outdoor Temp, Daylight Lux, Hour of Day] -> size: 3
        # Total size: num_zones * 3 + 3
        self.observation_space = spaces.Box(
            low=np.array([-20.0, 0.0, 0.0] * self.num_zones + [-20.0, 0.0, 0.0], dtype=np.float32),
            high=np.array([60.0, 1000.0, 50.0] * self.num_zones + [60.0, 1000.0, 24.0], dtype=np.float32),
            dtype=np.float32
        )
        
        self.step_count = 0
        self.current_time = datetime.strptime(self.start_date_str, "%Y-%m-%d")

    def _setup_components(self):
        """Helper to instantiate simulation engine components."""
        random_seed = self.config["simulation"].get("random_seed", 42)
        
        self.building = BuildingThermalModel(
            zones_config=self.config["building"]["zones"],
            initial_temp=22.0
        )
        
        self.hvac = HVACSystem(self.config["hvac"])
        for zone_name in self.building.get_zone_names():
            self.hvac.initialize_zone(zone_name, initial_setpoint=22.0)
            
        self.lighting = LightingSystem(self.config["lighting"])
        for zone in self.building.get_all_zones():
            self.lighting.initialize_zone(
                zone.name,
                baseline_watts=zone.config.lighting_baseline_watts
            )
            
        self.occupancy_gen = OccupancyGenerator(self.config["occupancy"], random_seed)
        for zone in self.building.get_all_zones():
            if "meeting" in zone.name.lower():
                zone_type = "meeting"
            elif "corridor" in zone.name.lower():
                zone_type = "corridor"
            else:
                zone_type = "office"
            self.occupancy_gen.initialize_zone(
                zone.name,
                max_occupancy=zone.config.occupancy_max,
                zone_type=zone_type
            )
            
        self.weather = WeatherGenerator(self.config["weather"], random_seed + 1)
        self.plug_loads = PlugLoadGenerator(random_seed + 2)
        for zone in self.building.get_all_zones():
            self.plug_loads.initialize_zone(
                zone.name,
                baseline_watts=zone.config.plug_load_baseline_watts
            )
            
        self.sensors = SensorSimulator(self.config["sensors"], random_seed + 3)
        self.energy_meter = EnergyMeter()
        for zone_name in self.building.get_zone_names():
            self.energy_meter.initialize_zone(zone_name)
            
        self.optimizer = ObjectiveFunction(self.config)

    def reset(self, seed: Optional[int] = None, options: Optional[Dict] = None) -> Tuple[np.ndarray, Dict]:
        super().reset(seed=seed)
        
        # Reset simulator state
        self.step_count = 0
        self.current_time = datetime.strptime(self.start_date_str, "%Y-%m-%d")
        
        # Re-setup simulation components for a fresh run
        self._setup_components()
        
        # Pre-generate schedules for the episode duration
        duration_days = int(np.ceil(self.max_steps_per_episode * self.dt / (24 * 3600)))
        for zone in self.building.get_all_zones():
            if "meeting" in zone.name.lower():
                self.occupancy_gen.generate_meeting_schedule(zone.name, self.current_time, duration_days)
                
        # Get initial observation
        obs = self._get_observation()
        info = {"message": "Environment reset successfully"}
        
        return obs, info

    def step(self, action: np.ndarray) -> Tuple[np.ndarray, float, bool, bool, Dict]:
        self.step_count += 1
        
        day_index = self.step_count * self.dt // (24 * 3600)
        hour_of_day = self.current_time.hour + self.current_time.minute / 60.0
        
        # 1. Fetch outdoor environment metrics
        weather_state = self.weather.get_weather(self.current_time)
        outdoor_temp = weather_state.outdoor_temp_c
        solar_irradiance = weather_state.solar_irradiance_w_m2
        daylight_lux = self.lighting.get_daylight_lux(solar_irradiance, hour_of_day)
        
        # 2. Fetch occupancy states
        occupancies = self.occupancy_gen.get_all_occupancies(self.current_time, day_index)
        
        # 3. Apply Actions (rescale action array from [-1, 1] to target ranges)
        hvac_powers = {}
        lighting_powers = {}
        plug_powers = {}
        internal_gains = {}
        thermal_powers = {}
        
        total_episode_cost = 0.0
        
        for i, zone in enumerate(self.zones):
            zone_name = zone.name
            
            # Extract and rescale actions
            raw_hvac_act = action[i * 2]
            raw_light_act = action[i * 2 + 1]
            
            # Rescale HVAC: [-1, 1] -> [18.0, 26.0]
            hvac_setpoint = 18.0 + (raw_hvac_act + 1.0) * 4.0
            # Rescale Dimming: [-1, 1] -> [0.0, 1.0]
            dimming_level = (raw_light_act + 1.0) / 2.0
            
            occupancy = occupancies.get(zone_name, 0)
            
            # Apply HVAC control
            self.hvac.set_setpoint(zone_name, hvac_setpoint)
            self.hvac.set_fan(zone_name, True if occupancy > 0 else False)
            thermal, electrical, _ = self.hvac.compute_hvac_output(
                zone_name, zone.state.temperature, outdoor_temp
            )
            hvac_powers[zone_name] = electrical
            thermal_powers[zone_name] = thermal
            
            # Apply Lighting control
            self.lighting.set_dimming(zone_name, dimming_level)
            total_lux, _, light_power = self.lighting.compute_lighting_output(
                zone_name, daylight_lux
            )
            lighting_powers[zone_name] = light_power
            zone.state.illumination = total_lux
            
            # Compute Plug loads
            plug_power = self.plug_loads.compute_plug_load(zone_name, occupancy, hour_of_day)
            plug_powers[zone_name] = plug_power
            
            # Compute heat gains
            gains = zone.compute_heat_gains(occupancy, plug_power, light_power, solar_irradiance)
            internal_gains[zone_name] = gains
            
            # Update state occupancy
            zone.state.occupancy = occupancy
            
            # Evaluate objective cost (cost is positive, lower is better)
            opt_result = self.optimizer.evaluate(
                zone_name=zone_name,
                temperature=zone.state.temperature,
                illumination=zone.state.illumination,
                is_occupied=(occupancy > 0),
                hvac_power_w=electrical,
                lighting_power_w=light_power,
                plug_power_w=plug_power,
                setpoint=hvac_setpoint,
                dimming=dimming_level,
                dt_seconds=self.dt
            )
            total_episode_cost += opt_result.total_cost
            self.optimizer.update_previous_actions(zone_name, hvac_setpoint, dimming_level)
            
        # 4. Advance Thermal model
        self.building.step(outdoor_temp, thermal_powers, internal_gains, self.dt)
        
        # 5. Advance Energy meter
        self.energy_meter.update(self.current_time, hvac_powers, lighting_powers, plug_powers, self.dt)
        
        # 6. Advance simulation time
        self.current_time += timedelta(seconds=self.dt)
        
        # Next observation
        obs = self._get_observation()
        
        # Reward is negative total cost
        reward = float(-total_episode_cost)
        
        # Check termination / truncation
        terminated = False
        truncated = self.step_count >= self.max_steps_per_episode
        
        info = {
            "step_cost": total_episode_cost,
            "step_energy_kwh": (sum(hvac_powers.values()) + sum(lighting_powers.values())) / 1000.0 * (self.dt / 3600.0)
        }
        
        return obs, reward, terminated, truncated, info

    def _get_observation(self) -> np.ndarray:
        obs_list = []
        # Per-zone state
        for zone in self.zones:
            obs_list.append(zone.state.temperature)
            obs_list.append(zone.state.illumination)
            obs_list.append(float(zone.state.occupancy))
            
        # Global environment state
        weather_state = self.weather.get_weather(self.current_time)
        solar_irradiance = weather_state.solar_irradiance_w_m2
        hour_of_day = self.current_time.hour + self.current_time.minute / 60.0
        daylight_lux = self.lighting.get_daylight_lux(solar_irradiance, hour_of_day)
        
        obs_list.append(weather_state.outdoor_temp_c)
        obs_list.append(daylight_lux)
        obs_list.append(hour_of_day)
        
        return np.array(obs_list, dtype=np.float32)

    def render(self):
        pass

    def close(self):
        pass
