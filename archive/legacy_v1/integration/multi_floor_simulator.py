"""
Multi-Floor Headless Simulator

Creates and steps a complete 5-floor, 26-room building simulation
using the 2R2C thermal model from sim/building.py.

Generates realistic sensor data for every room based on:
- Time-of-day occupancy schedules (from building_config.py)
- 2R2C thermal dynamics (temperature, humidity, CO2)
- Weather model (outdoor temperature cycle)
- Stochastic noise for realistic sensor readings

Used by:
- StateManager (replaces the old 4-room SimulationBridge in headless mode)
- ExperimentRunner (deterministic experiments for research evaluation)
"""

import os
import sys
import math
import random
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from integration.building_config import (
    BUILDING_CONFIG, get_all_rooms, get_room_schedule,
    get_room_thermal, get_room_energy_params, THERMAL_DEFAULTS,
)

logger = logging.getLogger(__name__)


@dataclass
class RoomState:
    """Live state for a single simulated room."""
    room_id: str
    room_type: str
    floor_id: int
    display_name: str
    max_occupancy: int
    
    # Thermal state
    temperature: float = 23.0
    wall_temperature: float = 22.0
    humidity: float = 50.0
    co2_ppm: float = 400.0
    light_level: float = 0.0
    
    # Occupancy
    occupancy: int = 0
    
    # Device state (what the actuators are actually doing)
    light_on: bool = False
    hvac_mode: str = "off"
    hvac_speed: float = 0.0
    
    # Thermal params (from config)
    R_wall: float = 0.004
    R_internal: float = 0.002
    C_zone: float = 150000
    C_wall: float = 500000
    area_m2: float = 100.0
    volume_m3: float = 350.0


class MultiFloorSimulator:
    """
    Headless multi-floor building simulator.
    
    Steps all 26 rooms through a 2R2C thermal model each tick.
    Generates stochastic occupancy based on schedules.
    """
    
    def __init__(self, speed_factor: float = 360.0, seed: int = 42):
        """
        Initialize the simulator.
        
        Args:
            speed_factor: Simulation speed multiplier.
                          60.0 = 1 real second = 1 sim minute.
            seed: Random seed for reproducibility.
        """
        self._speed_factor = speed_factor
        self._rng = random.Random(seed)
        
        # Simulation clock (seconds since midnight)
        self._sim_seconds = 6 * 3600  # Start at 06:00
        self._day_count = 0
        
        # Build room states from config
        self._rooms: Dict[str, RoomState] = {}
        self._init_rooms()
        
        # Outdoor weather state
        self._outdoor_temp = 28.0  # Sri Lankan tropical default
        self._outdoor_humidity = 75.0
        
        logger.info(f"MultiFloorSimulator initialized: {len(self._rooms)} rooms, speed={speed_factor}x")
    
    def _init_rooms(self):
        """Create RoomState objects for all rooms from building config."""
        for room_info in get_all_rooms():
            room_type = room_info["type"]
            thermal = get_room_thermal(room_type)
            
            state = RoomState(
                room_id=room_info["room_id"],
                room_type=room_type,
                floor_id=room_info["floor_id"],
                display_name=room_info["name"],
                max_occupancy=room_info["max_occupancy"],
                temperature=22.0 + self._rng.uniform(-1, 1),
                wall_temperature=21.0 + self._rng.uniform(-0.5, 0.5),
                humidity=50.0 + self._rng.uniform(-5, 5),
                co2_ppm=400.0 + self._rng.uniform(0, 50),
                R_wall=thermal["R_wall"],
                R_internal=thermal["R_internal"],
                C_zone=thermal["C_zone"],
                C_wall=thermal["C_wall"],
                area_m2=room_info.get("area_m2", 100),
                volume_m3=room_info.get("volume_m3", 350),
            )
            self._rooms[room_info["room_id"]] = state
    
    @property
    def simulation_time_str(self) -> str:
        """Get current simulation time as HH:MM:SS string."""
        total_secs = int(self._sim_seconds) % 86400
        h = total_secs // 3600
        m = (total_secs % 3600) // 60
        s = total_secs % 60
        return f"{h:02d}:{m:02d}:{s:02d}"
    
    @property
    def sim_hour(self) -> float:
        """Get current simulation hour as float (e.g. 14.5 = 2:30 PM)."""
        return (self._sim_seconds % 86400) / 3600.0
    
    def step(self, dt_real: float = 2.0):
        """
        Advance the simulation by one tick.
        
        Args:
            dt_real: Real-time seconds elapsed since last step.
        """
        # Advance simulation clock
        dt_sim = dt_real * self._speed_factor  # seconds of sim time
        self._sim_seconds += dt_sim
        
        # Check for day rollover
        if self._sim_seconds >= 86400:
            self._sim_seconds %= 86400
            self._day_count += 1
        
        hour = self.sim_hour
        
        # Update outdoor weather
        self._update_weather(hour)
        
        # Update each room
        for room in self._rooms.values():
            self._step_room(room, hour, dt_sim)
    
    def step_deterministic(self, dt_sim_seconds: float):
        """
        Advance simulation by exact sim-time seconds (for experiments).
        No speed_factor multiplication — caller provides exact sim delta.
        """
        self._sim_seconds += dt_sim_seconds
        if self._sim_seconds >= 86400:
            self._sim_seconds %= 86400
            self._day_count += 1
        
        hour = self.sim_hour
        self._update_weather(hour)
        
        for room in self._rooms.values():
            self._step_room(room, hour, dt_sim_seconds)
    
    def _update_weather(self, hour: float):
        """Update outdoor temperature using a sinusoidal model for tropical climate."""
        # Sri Lankan tropical: ~24°C min at 5am, ~33°C max at 2pm
        base_temp = 28.5
        amplitude = 4.5
        phase = (hour - 14.0) * math.pi / 12.0  # Peak at 14:00
        self._outdoor_temp = base_temp - amplitude * math.cos(phase)
        
        # Humidity: inverse of temperature
        self._outdoor_humidity = 80 - (self._outdoor_temp - 24) * 3
    
    def _step_room(self, room: RoomState, hour: float, dt_sim: float):
        """Step a single room through its thermal and occupancy dynamics."""
        # 1. Generate stochastic occupancy from schedule
        schedule = get_room_schedule(room.room_type)
        hour_idx = int(hour) % 24
        base_prob = schedule[hour_idx]
        
        # Interpolate between hours
        next_idx = (hour_idx + 1) % 24
        frac = hour - int(hour)
        interp_prob = base_prob * (1 - frac) + schedule[next_idx] * frac
        
        # Stochastic occupancy
        expected_occ = interp_prob * room.max_occupancy
        room.occupancy = max(0, min(room.max_occupancy,
            int(expected_occ + self._rng.gauss(0, max(1, expected_occ * 0.3)))))
        
        # 2. Light level (based on time and occupancy)
        solar = max(0, math.sin((hour - 6) * math.pi / 12)) * 800 if 6 < hour < 18 else 0
        artificial = 400 if room.light_on else 0
        room.light_level = solar * 0.3 + artificial + self._rng.uniform(-10, 10)
        
        # 3. Temperature (2R2C thermal model)
        T_zone = room.temperature
        T_wall = room.wall_temperature
        T_out = self._outdoor_temp
        
        # Internal heat gains
        Q_occupants = room.occupancy * 100.0  # 100W per person
        Q_equipment = 50.0 if room.light_on else 10.0
        Q_internal = Q_occupants + Q_equipment
        
        # HVAC power
        if room.hvac_mode == "heating":
            Q_hvac = 2000 * room.hvac_speed
        elif room.hvac_mode == "cooling":
            Q_hvac = -3000 * room.hvac_speed
        elif room.hvac_mode == "fan_only":
            Q_hvac = -500 * room.hvac_speed
        else:
            Q_hvac = 0
        
        # 2R2C equations
        Q_wall_out = (T_out - T_wall) / room.R_wall
        Q_wall_zone = (T_zone - T_wall) / room.R_internal
        
        dT_wall = (Q_wall_out - Q_wall_zone) / room.C_wall * dt_sim
        T_wall_new = T_wall + dT_wall
        
        Q_zone_net = -Q_wall_zone + Q_hvac + Q_internal
        dT_zone = Q_zone_net / room.C_zone * dt_sim
        T_zone_new = T_zone + dT_zone
        
        room.wall_temperature = T_wall_new
        room.temperature = max(15, min(40, T_zone_new))
        
        # 4. Humidity
        moisture_gen = room.occupancy * 0.05  # g/s per person
        ventilation_removal = 0.001 * (room.humidity - self._outdoor_humidity)
        room.humidity = max(30, min(90,
            room.humidity + (moisture_gen - ventilation_removal) * dt_sim / 60.0
            + self._rng.uniform(-0.2, 0.2)))
        
        # 5. CO2
        OUTDOOR_CO2 = 400.0
        co2_gen = room.occupancy * 0.005 * 1e6 / (room.volume_m3 * 1000)
        ventilation_ach = 0.5 if room.hvac_mode != "off" else 0.15
        co2_removal = (ventilation_ach / 3600) * (room.co2_ppm - OUTDOOR_CO2)
        room.co2_ppm = max(OUTDOOR_CO2, min(2000,
            room.co2_ppm + (co2_gen - co2_removal) * dt_sim
            + self._rng.uniform(-2, 2)))
            
    def get_state(self) -> Dict[str, Any]:
        """Return engine state, used for clock syncing."""
        hour = int((self._sim_seconds // 3600) % 24)
        minute = int((self._sim_seconds % 3600) // 60)
        return {
            "date": f"Day {self._day_count}",
            "time": f"{hour:02d}:{minute:02d}:00"
        }
    
    def get_all_room_states(self) -> List[Dict[str, Any]]:
        """
        Get all room states in the format expected by StateManager.process_room_states().
        
        Returns a list of dicts compatible with the existing pipeline.
        """
        states = []
        for room in self._rooms.values():
            # Compute humidity ratio
            humidity_ratio = self._compute_humidity_ratio(room.temperature, room.humidity)
            
            states.append({
                "room_id": room.room_id,
                "room_type": room.room_type,
                "floor_id": room.floor_id,
                "display_name": room.display_name,
                "sensors": {
                    "Temperature": round(room.temperature, 2),
                    "Humidity": round(room.humidity, 2),
                    "Light": round(room.light_level, 1),
                    "CO2": round(room.co2_ppm, 1),
                    "HumidityRatio": round(humidity_ratio, 6),
                },
                "ground_truth": {
                    "true_occupancy": room.occupancy,
                    "max_occupancy": room.max_occupancy,
                },
                "device_state": {
                    "light_on": room.light_on,
                    "hvac_mode": room.hvac_mode,
                    "hvac_speed": room.hvac_speed,
                },
            })
        return states
    
    def apply_control(self, room_id: str, light_on: bool, hvac_mode: str, hvac_speed: float = 0.5):
        """Apply control actions to a specific room."""
        if room_id in self._rooms:
            room = self._rooms[room_id]
            room.light_on = light_on
            room.hvac_mode = hvac_mode
            room.hvac_speed = hvac_speed
    
    def get_outdoor_conditions(self) -> Dict[str, float]:
        """Get current outdoor weather."""
        return {
            "temperature": round(self._outdoor_temp, 1),
            "humidity": round(self._outdoor_humidity, 1),
        }
    
    def reset(self, seed: int = 42):
        """Reset the simulator to initial state."""
        self._rng = random.Random(seed)
        self._sim_seconds = 6 * 3600
        self._day_count = 0
        self._rooms.clear()
        self._init_rooms()
    
    @staticmethod
    def _compute_humidity_ratio(temp_c: float, rh_pct: float) -> float:
        """Compute humidity ratio from temperature and relative humidity."""
        a, b = 17.27, 237.7
        p_sat = 610.78 * math.exp((a * temp_c) / (b + temp_c))
        rh_frac = max(0, min(1, rh_pct / 100))
        p_w = rh_frac * p_sat
        denom = 101325 - p_w
        if denom <= 0:
            return 0.01
        return 0.622 * p_w / denom
