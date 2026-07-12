"""
Simulation Engine

Core simulation loop that manages time, state updates, and coordinates all systems.
Completely independent from Panda3D rendering.

Phase 2 enhancements:
- Configurable rooms from room_config_loader
- Advanced sensor models with lag and noise
- Realistic occupancy schedules per room
- Weather simulation with cloud cover and precipitation

Phase 3 enhancements:
- 2R2C thermal circuit model with wall/zone temperatures
- Window solar gain calculations
- Inter-zone heat transfer based on room adjacency
- Thermal comfort metrics (PMV/PPD)
- Air quality indices

Phase 4 enhancements:
- Decision engine with pluggable control strategies
- Intelligent HVAC, lighting, and shading control
- ML-ready decision interface
- Decision logging for analysis
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional
import math

from simulation.room_config_loader import RoomConfigLoader
from simulation.sensor_models import AdvancedSensorModels
from simulation.occupancy_scheduler import OccupancyScheduler
from simulation.thermal_model import ThermalZone, ThermalProperties
from simulation.window_system import WindowSystem, RoomWindowConfig
from simulation.adjacency_detector import AdjacencyDetector
from simulation.inter_zone_heat_transfer import InterZoneTransferManager
from simulation.comfort_metrics import ComfortMetricsCalculator
from decisions import DecisionEngine, DecisionContext
from models import HistoricalData
from hardware import HardwareServiceFactory, ActuatorController, RoomActuators


class SimulationEngine:
    """
    Central coordinator for the smart building simulation.

    Responsibilities:
    - Manage simulation time and acceleration
    - Update environmental conditions (day/night, weather)
    - Simulate occupancy and human activity
    - Compute sensor readings
    - Execute decision logic
    - Maintain consistent state
    """

    def __init__(self, config: dict = None):
        """
        Initialize simulation engine.

        Args:
            config: Configuration dictionary
        """
        self.config = config or {}

        # Simulation time
        self.current_time = datetime.now().replace(hour=6, minute=0, second=0, microsecond=0)
        self.start_time = self.current_time
        self.elapsed_time = 0.0  # Seconds elapsed in simulation

        # Time acceleration factor
        self.speed_factor = self.config.get("speed_factor", 60.0)  # 60x = 1 min sim = 1 hour real

        # Paused state
        self.paused = False

        # Phase 2: Load room configuration
        room_loader = RoomConfigLoader(self.config)
        self.room_configs = room_loader.load_rooms()
        self.room_ids = [r.room_id for r in self.room_configs]

        # Phase 2: Initialize advanced sensor models
        self.sensor_models = AdvancedSensorModels(self.config.get("sensors", {}))

        # Phase 2: Initialize occupancy scheduler
        self.occupancy_scheduler = OccupancyScheduler(self.config.get("occupancy", {}))

        # Phase 2: Weather state tracking
        self.weather_data = {
            "cloud_cover": 0.0,
            "precipitation": 0.0,
            "wind_speed": 0.0,
            "wind_direction": 0.0,
            "solar_irradiance": 0.0,
        }

        # Smoothed weather targets (prevents jitter)
        self._weather_targets = {
            "cloud_cover": 0.2,
            "precipitation": 0.0,
            "wind_speed": 2.0,
            "wind_direction": 180.0,
        }
        self._weather_retarget_timer = 0.0  # Seconds until next target change
        self._weather_retarget_interval = 300.0  # Re-target every 5 sim-minutes

        # State tracking
        self.state = {
            "time": self.current_time.strftime("%H:%M:%S"),
            "date": self.current_time.strftime("%Y-%m-%d"),
            "speed_factor": self.speed_factor,
            "paused": self.paused,
            "rooms": {},
            "weather": self.weather_data,
        }

        # Initialize rooms
        self._init_rooms()

        # Phase 2: Historical data for charting
        self.history = {room_id: HistoricalData() for room_id in self.room_ids}

        # Phase 3: Advanced physics initialization
        self.use_advanced_physics = self.config.get("advanced_physics", True)

        if self.use_advanced_physics:
            # Initialize thermal zones (2R2C physics)
            self.thermal_zones: Dict[int, ThermalZone] = {}
            self._init_thermal_zones()

            # Initialize room adjacency detection
            self.adjacency_detector = AdjacencyDetector()
            self._setup_room_adjacencies()

            # Initialize window system for each room
            self.window_systems: Dict[int, WindowSystem] = {}
            self._setup_windows()

            # Initialize inter-zone heat transfer
            self.inter_zone_transfer = InterZoneTransferManager()
            self._setup_inter_zone_transfer()

            print("[OK] Simulation engine initialized (Advanced 2R2C Physics)")
        else:
            print("[OK] Simulation engine initialized (Simple Thermal Model)")

        # Phase 4: Initialize decision engine
        self.decision_engine = DecisionEngine(self.config.get("decisions", {}))
        self.decision_log: Dict[int, List] = {room_id: [] for room_id in self.room_ids}

        # Phase 7: Initialize hardware service
        hardware_config = self.config.get("hardware", {"type": "logging"})
        self.hardware_service = HardwareServiceFactory.create_from_config(hardware_config)
        self.hardware_service.initialize()

        # Phase 7: Initialize actuator controllers
        self.actuator_controller = ActuatorController(self.hardware_service)
        self.room_actuators: Dict[int, RoomActuators] = {}
        for room_id in self.room_ids:
            self.room_actuators[room_id] = RoomActuators(self.actuator_controller, room_id)

        print(f"  Rooms: {len(self.room_configs)}")
        print(f"  Start time: {self.current_time}")
        print(f"  Time acceleration: {self.speed_factor}x")
        if self.use_advanced_physics:
            print(f"  Physics: 2R2C thermal circuit, inter-zone transfer, comfort metrics")
        print(f"  Control Strategy: {self.decision_engine.get_strategy_name()}")
        print(f"  Hardware Service: {hardware_config.get('type', 'logging')}")

    def _init_rooms(self):
        """Initialize room states from loaded room configurations."""
        for room_config in self.room_configs:
            room_id = room_config.room_id
            self.state["rooms"][room_id] = {
                "room_id": room_id,
                "name": room_config.name,
                "zone_type": room_config.zone_type,
                "max_occupancy": room_config.max_occupancy,
                "light_on": False,
                "hvac_mode": "off",
                "hvac_setpoint": 21.0,
                "hvac_speed": 0.0,
                "shading_factor": 0.0,  # Phase 4: Window shading control
                "occupancy": 0.0,
                "temperature": 20.0,
                "humidity": 45.0,
                "light_level": 0.0,
                "energy_use": 0.0,
                "co2": 400.0,
                # Phase 3: Comfort metrics
                "temperature_wall": 20.0,  # Wall surface temperature
                "temperature_radiant": 20.0,  # Mean radiant temperature
                "operative_temperature": 20.0,  # Combined operative temperature
                "pmv": 0.0,  # Predicted Mean Vote
                "ppd": 0.0,  # Predicted Percentage Dissatisfied
                "comfort_index": 100.0,  # Overall comfort (0-100)
                # Phase 4: Decision logging
                "decision_reason": "Initializing...",
            }

    def _init_thermal_zones(self) -> None:
        """Initialize 2R2C thermal zones for each room."""
        for room_config in self.room_configs:
            dims = room_config.dimensions
            volume = dims.get("width", 6) * dims.get("depth", 6) * dims.get("height", 3)

            # Convert simple config-level thermal properties to advanced 2R2C parameters
            config_tp = room_config.thermal_properties
            advanced_tp = ThermalProperties(
                # Derive R-values from U-value: R = 1/U (simplified)
                r_wall_external=0.13,
                r_wall_internal=0.11,
                r_wall_mass=max(0.1, 1.0 / max(0.01, config_tp.u_value_w_m2k) - 0.24),
                # Map thermal_mass_j_k to wall capacitance
                c_wall=config_tp.thermal_mass_j_k * 20.0,  # Scale to wall mass
                c_zone_air=volume * 1200.0,  # Air density × specific heat × volume
                # Infiltration from config
                infiltration_ach_base=config_tp.infiltration_rate_ach,
                infiltration_wind_coeff=0.001,
                # U-values
                u_value_external=config_tp.u_value_w_m2k,
                u_value_internal=2.0,
            )

            thermal_zone = ThermalZone(
                zone_id=room_config.room_id,
                thermal_properties=advanced_tp,
                zone_volume=volume
            )
            self.thermal_zones[room_config.room_id] = thermal_zone

    def _setup_room_adjacencies(self) -> None:
        """Detect room adjacencies and set up spatial relationships."""
        # Add room bounds to detector
        for room_config in self.room_configs:
            pos = room_config.position
            dims = room_config.dimensions

            self.adjacency_detector.add_room(
                room_id=room_config.room_id,
                x_min=pos.get("x", 0),
                x_max=pos.get("x", 0) + dims.get("width", 6),
                y_min=pos.get("y", 0),
                y_max=pos.get("y", 0) + dims.get("depth", 6),
                z_min=pos.get("z", 0),
                z_max=pos.get("z", 0) + dims.get("height", 3)
            )

        # Detect all adjacencies
        adjacencies = self.adjacency_detector.detect_all_adjacencies()
        print(f"  Detected {len(adjacencies)} adjacent room pairs")

    def _setup_windows(self) -> None:
        """Initialize window systems for each room."""
        for room_config in self.room_configs:
            room_window_config = RoomWindowConfig(room_config.room_id)

            # Add standard windows if available in config
            if hasattr(room_config, 'windows') and room_config.windows:
                for window_def in room_config.windows:
                    room_window_config.add_window(
                        width=window_def.get('width', 1.0),
                        height=window_def.get('height', 1.2),
                        azimuth=window_def.get('azimuth', 180.0),
                        u_value=window_def.get('u_value', 3.0),
                        solar_transmittance=window_def.get('transmittance', 0.6),
                        frame_fraction=window_def.get('frame_fraction', 0.15),
                        shading_factor=window_def.get('shading_factor', 0.0)
                    )
            else:
                # Default: south-facing window for each room
                room_window_config.add_standard_window(count=1, azimuth=180.0)

            self.window_systems[room_config.room_id] = room_window_config.window_system

    def _setup_inter_zone_transfer(self) -> None:
        """Set up inter-zone heat transfer based on detected adjacencies."""
        adjacencies = self.adjacency_detector.get_all_adjacencies()

        for (room_id_1, room_id_2), adjacency_info in adjacencies.items():
            # Get U-value for shared wall (default to typical interior wall)
            u_value = 0.3  # W/m²K

            # Create heat flow between adjacent zones
            self.inter_zone_transfer.add_heat_flow(
                room_id_1=room_id_1,
                room_id_2=room_id_2,
                shared_area=adjacency_info.shared_area,
                u_value=u_value
            )

    def update(self, dt: float):
        """
        Update simulation state for one frame.

        Args:
            dt: Delta time since last update (in seconds), from Panda3D
        """
        if self.paused:
            return

        # Advance simulation time
        self.elapsed_time += dt * self.speed_factor
        self.current_time = self.start_time + timedelta(seconds=self.elapsed_time)

        # Update environmental conditions (sun position, outdoor weather)
        self._update_environment()

        # Update room conditions and sensors
        self._update_rooms(dt)

        # Execute decision logic
        self._update_decisions()

        # Update state dict for rendering
        self._publish_state()

    def _update_environment(self):
        """Update outdoor environmental conditions and weather."""
        # Calculate sun position based on time of day
        hour = self.current_time.hour + self.current_time.minute / 60.0

        # Sun altitude (degrees) - sine-wave model
        # Rises at ~6am (0°), peaks at ~60° at noon, sets at ~6pm (0°)
        # Negative at night for proper twilight/darkness
        sun_altitude = 60.0 * math.sin(math.radians((hour - 6.0) * 15.0))
        self.state["sun_altitude"] = max(-90, min(90, sun_altitude))

        # Sun azimuth (degrees) - east (90°) at sunrise, south (180°) at noon, west (270°) at sunset
        self.state["sun_azimuth"] = 90.0 + (hour - 6.0) * 15.0

        # Outdoor light level (lux) - depends on sun position
        sun_alt_rad = math.radians(self.state["sun_altitude"])
        if sun_alt_rad > 0:
            # During day: 0 lux at horizon, ~120k lux at zenith
            outdoor_light = 120000 * max(0, math.sin(sun_alt_rad))
        else:
            # During night: very low light
            outdoor_light = max(500, 5000 * math.sin(sun_alt_rad) + 500)  # 500-5000 lux at night

        self.state["outdoor_light"] = outdoor_light

        # Outdoor temperature (simple model)
        # Base 20°C, varies ±8°C depending on time of day
        time_factor = math.sin((hour - 6.0) * math.pi / 12.0)  # -1 to 1
        outdoor_temp = 20.0 + 8.0 * time_factor
        self.state["outdoor_temperature"] = max(5, outdoor_temp)

        # **Phase 2: Weather simulation**
        self._update_weather()

        # **Phase 2: Solar irradiance (depends on sun position and clouds)**
        if sun_alt_rad > 0:
            solar_irradiance = 1000 * max(0, math.sin(sun_alt_rad))  # W/m^2
        else:
            solar_irradiance = 0.0

        # Clouds reduce solar irradiance
        cloud_factor = 1.0 - self.weather_data.get("cloud_cover", 0.0) * 0.8
        solar_irradiance *= cloud_factor

        self.weather_data["solar_irradiance"] = solar_irradiance
        self.state["weather"]["solar_irradiance"] = solar_irradiance

    def _update_weather(self):
        """
        Update weather simulation with smooth interpolation.
        Uses target-based system to avoid per-frame jitter.
        """
        import random

        hour = self.current_time.hour + self.current_time.minute / 60.0

        # Check if we need to pick new weather targets
        self._weather_retarget_timer -= 1.0  # Approximate: called each sim step
        if self._weather_retarget_timer <= 0:
            self._weather_retarget_timer = self._weather_retarget_interval

            # Determine base conditions from time of day
            if 15 <= hour <= 17:
                base_cloud = 0.6
                base_precip = 5.0
            elif 8 <= hour <= 11:
                base_cloud = 0.4
                base_precip = 1.0
            else:
                base_cloud = 0.2
                base_precip = 0.0

            # Set new targets with some randomness
            self._weather_targets["cloud_cover"] = max(0.0, min(1.0,
                base_cloud + random.uniform(-0.15, 0.15)))
            self._weather_targets["precipitation"] = max(0.0,
                base_precip + random.uniform(-1.0, 2.0))
            self._weather_targets["wind_speed"] = max(0.0,
                2.0 + self._weather_targets["cloud_cover"] * 5.0 + random.uniform(-0.5, 0.5))
            self._weather_targets["wind_direction"] = (
                self._weather_targets["wind_direction"] + random.uniform(-10, 10)) % 360

        # Smoothly interpolate current weather toward targets
        lerp_rate = 0.02  # Smooth factor per update step
        for key in ["cloud_cover", "precipitation", "wind_speed", "wind_direction"]:
            current = self.weather_data.get(key, 0.0)
            target = self._weather_targets[key]
            self.weather_data[key] = current + (target - current) * lerp_rate

        # Clamp values
        self.weather_data["cloud_cover"] = max(0.0, min(1.0, self.weather_data["cloud_cover"]))
        self.weather_data["precipitation"] = max(0.0, self.weather_data["precipitation"])
        self.weather_data["wind_speed"] = max(0.0, self.weather_data["wind_speed"])

        # Update state dict
        self.state["weather"] = self.weather_data.copy()

    def _update_rooms(self, dt: float):
        """Update room sensor readings and conditions."""
        for room_id in self.room_ids:
            self._update_room(room_id, dt)

    def _update_room(self, room_id: int, dt: float):
        """
        Update sensor readings for a single room.
        Phase 2: Uses advanced sensor models and realistic occupancy.
        Phase 3: Uses 2R2C thermal zones, window solar gains, inter-zone transfer, comfort metrics.

        Args:
            room_id: Room identifier
            dt: Delta time (seconds)
        """
        room = self.state["rooms"][room_id]
        room_config = next(r for r in self.room_configs if r.room_id == room_id)

        # Phase 2: Get realistic occupancy from scheduler
        occupancy_fraction = self.occupancy_scheduler.get_room_occupancy(
            room_id, room_config.zone_type, self.current_time, room_config.max_occupancy
        )
        occupancy_count = int(round(occupancy_fraction * room_config.max_occupancy))
        room["occupancy"] = float(occupancy_count) # Integer count formally represented as standard float

        # Apply occupancy sensor uncertainty for realism
        occupancy_count = int(round(occupancy_fraction * room_config.max_occupancy))
        detected_count = self.sensor_models.occupancy_with_uncertainty(occupancy_count)
        room["detected_occupancy"] = detected_count

        # Get outdoor conditions
        outdoor_temp = self.state.get("outdoor_temperature", 20.0)
        wind_speed = self.weather_data.get("wind_speed", 0.0)
        solar_irradiance = self.weather_data.get("solar_irradiance", 0.0)

        if self.use_advanced_physics:
            # Phase 3: Use 2R2C thermal model
            self._update_room_advanced(room_id, room, room_config, dt,
                                       outdoor_temp, wind_speed, solar_irradiance,
                                       occupancy_fraction)
        else:
            # Phase 2: Use simple linear thermal model
            self._update_room_simple(room_id, room, room_config, dt,
                                     outdoor_temp, occupancy_fraction)

    def _update_room_simple(self, room_id: int, room: dict, room_config,
                           dt: float, outdoor_temp: float, occupancy_fraction: float) -> None:
        """
        Simple Phase 2 thermal model (linear temperature response).

        Args:
            room_id: Room identifier
            room: Room state dict
            room_config: Room configuration
            dt: Time step
            outdoor_temp: Outdoor temperature
            occupancy_fraction: Occupancy (0-1)
        """
        # Temperature depends on outdoor temp, occupancy, and light state
        base_temp = outdoor_temp + 2.0  # Building maintains slight warmth

        # Heat gains
        if room["light_on"]:
            base_temp += 1.5  # Lights generate heat
        if occupancy_fraction > 0.5:
            base_temp += 0.5  # Occupants generate heat

        # Phase 2: Use thermal properties for more realistic dynamics
        thermal_props = room_config.thermal_properties
        solar_gain = self.weather_data.get("solar_irradiance", 0.0) * thermal_props.solar_gain_factor
        base_temp += solar_gain / 1000.0  # Rough approximation

        # Slow temperature changes (room has thermal mass)
        target_temp = base_temp
        room["temperature"] += (target_temp - room["temperature"]) * 0.02

        # Phase 2: Apply sensor lag and noise
        room["temperature"] = self.sensor_models.temperature_with_lag(
            room_id, room["temperature"], dt
        )

        # Humidity depends on occupancy
        base_humidity = 45.0
        if occupancy_fraction > 0.5:
            base_humidity += 15.0  # Occupants increase humidity

        # Phase 2: Apply humidity lag
        room["humidity"] = self.sensor_models.humidity_with_lag(
            room_id, base_humidity, dt
        )

        # Light level depends on outdoor light and room light state
        outdoor_light = self.state.get("outdoor_light", 0.0)
        room_light_contribution = 500.0 if room["light_on"] else 0.0
        outdoor_contribution = outdoor_light * 0.3  # 30% of outdoor light enters

        # Cloud cover reduces outdoor light
        cloud_factor = 1.0 - self.weather_data.get("cloud_cover", 0.0) * 0.5
        outdoor_contribution *= cloud_factor

        room["light_level"] = outdoor_contribution + room_light_contribution

        # Phase 2: Apply CO2 lag (represents diffusion)
        co2_base = 400.0
        co2_occupied = 1000.0
        true_co2 = co2_base + (co2_occupied - co2_base) * occupancy_fraction
        room["co2"] = self.sensor_models.co2_with_lag(room_id, true_co2, dt)

        # Energy use depends on light and HVAC
        light_power = 20.0 if room["light_on"] else 0.0
        hvac_power = 50.0 if occupancy_fraction > 0.3 else 5.0
        room["energy_use"] = light_power + hvac_power

        # Track history for charting
        self.history[room_id].add_point(
            temperature=room["temperature"],
            occupancy=room["occupancy"],
            energy=room["energy_use"],
            humidity=room["humidity"],
            light=room["light_level"]
        )

    def _update_room_advanced(self, room_id: int, room: dict, room_config,
                             dt: float, outdoor_temp: float, wind_speed: float,
                             solar_irradiance: float, occupancy_fraction: float) -> None:
        """
        Phase 3 advanced thermal model using 2R2C circuit physics.

        Includes:
        - 2R2C thermal zone dynamics
        - Window solar gain calculations
        - Infiltration with wind dependence
        - Inter-zone heat transfer
        - Thermal comfort metrics

        Args:
            room_id: Room identifier
            room: Room state dict
            room_config: Room configuration
            dt: Time step
            outdoor_temp: Outdoor temperature
            wind_speed: Wind speed (m/s)
            solar_irradiance: Solar irradiance (W/m²)
            occupancy_fraction: Occupancy (0-1)
        """
        thermal_zone = self.thermal_zones[room_id]

        # Calculate internal heat gains (W)
        q_internal = 0.0

        # Occupant sensible heat (100 W per person)
        occupant_count = occupancy_fraction * room_config.max_occupancy
        q_internal += occupant_count * 100.0

        # Lighting heat gain (100 W per light, assuming 2 lights per room)
        if room["light_on"]:
            q_internal += 200.0

        # Apply window shading (Phase 4 decision) before solar calculation
        window_system = self.window_systems.get(room_id)
        if window_system and len(window_system.windows) > 0:
            # Update shading factor for all windows in this room
            current_shading = room.get("shading_factor", 0.0)
            for window in window_system.windows.values():
                window.update_shading(current_shading)

        # Calculate window solar gains (W)
        q_solar = 0.0
        if window_system:
            sun_alt = self.state.get("sun_altitude", 0)
            sun_azi = self.state.get("sun_azimuth", 0)
            q_solar = window_system.update_solar_gain(solar_irradiance, sun_alt, sun_azi)

        # Calculate inter-zone heat transfer to this room (W)
        current_temps = {room_id: room["temperature"] for room_id in self.room_ids}
        current_temps[room_id] = thermal_zone.state.temperature_zone
        q_inter_zone = self.inter_zone_transfer.get_flow_to_room(room_id, current_temps)

        # HVAC control (Phase 4: from decision engine)
        # Gets HVAC mode and speed from the decision engine
        hvac_mode = room.get("hvac_mode", "off")
        hvac_speed = room.get("hvac_speed", 0.0)
        hvac_setpoint = room.get("hvac_setpoint", 21.0)

        # Convert HVAC mode and speed to heat output (W)
        q_hvac = 0.0
        if hvac_mode == "heating":
            # Heating: proportional to speed (max +500 W)
            q_hvac = hvac_speed * 500.0
        elif hvac_mode == "cooling":
            # Cooling: proportional to speed (max -500 W)
            q_hvac = -hvac_speed * 500.0
        elif hvac_mode == "fan_only":
            # Fan only: minimal conditioning (10 W for circulation)
            q_hvac = 10.0
        # Mode "off" or "auto": q_hvac stays 0

        # Update 2R2C thermal zone
        thermal_zone.update(
            dt=dt,
            t_outdoor=outdoor_temp,
            q_internal=q_internal,
            q_solar=q_solar,
            q_inter_zone=q_inter_zone,
            q_hvac=q_hvac,
            wind_speed=wind_speed
        )

        # Extract temperatures from thermal zone
        room["temperature"] = thermal_zone.state.temperature_zone
        room["temperature_wall"] = thermal_zone.state.temperature_wall
        room["temperature_radiant"] = thermal_zone.state.temperature_radiant
        room["operative_temperature"] = thermal_zone.get_operative_temperature()

        # Apply sensor lag and noise to temperature
        room["temperature"] = self.sensor_models.temperature_with_lag(
            room_id, room["temperature"], dt
        )

        # Humidity depends on occupancy and temperature
        base_humidity = 45.0
        if occupancy_fraction > 0.5:
            # Occupants increase humidity
            base_humidity += 15.0
        # Temperature also affects saturation humidity (warmer = lower RH at constant absolute humidity)
        base_humidity -= (room["temperature"] - 20.0) * 0.5

        # Apply humidity lag
        room["humidity"] = self.sensor_models.humidity_with_lag(
            room_id, base_humidity, dt
        )

        # Light level depends on outdoor light and room light state
        outdoor_light = self.state.get("outdoor_light", 0.0)
        room_light_contribution = 500.0 if room["light_on"] else 0.0
        outdoor_contribution = outdoor_light * 0.3  # 30% of outdoor light enters

        # Cloud cover reduces outdoor light
        cloud_factor = 1.0 - self.weather_data.get("cloud_cover", 0.0) * 0.5
        outdoor_contribution *= cloud_factor

        room["light_level"] = self.sensor_models.light_sensor_reading(
            outdoor_contribution + room_light_contribution
        )

        # CO2 depends on occupancy
        co2_base = 400.0
        co2_occupied = 1000.0
        true_co2 = co2_base + (co2_occupied - co2_base) * occupancy_fraction
        room["co2"] = self.sensor_models.co2_with_lag(room_id, true_co2, dt)

        # Energy use calculation
        light_power = 100.0 if room["light_on"] else 0.0  # W
        hvac_power = max(0.0, abs(q_hvac))  # W (demand)
        room["energy_use"] = light_power + hvac_power

        # Calculate comfort metrics
        comfort_metrics = ComfortMetricsCalculator.calculate_all_metrics(
            t_operative=room["operative_temperature"],
            t_radiant=room["temperature_radiant"],
            humidity=room["humidity"],
            co2_ppm=int(room["co2"]),
            air_velocity=0.1,  # Assume low air velocity
            metabolic_rate=1.2 if occupancy_fraction > 0.5 else 1.0,
            clothing_level=0.7  # Mixed clothing (office)
        )

        room["pmv"] = comfort_metrics.pmv
        room["ppd"] = comfort_metrics.ppd
        room["comfort_index"] = comfort_metrics.overall_comfort_index

        # Track history for charting
        self.history[room_id].add_point(
            temperature=room["temperature"],
            occupancy=room["occupancy"],
            energy=room["energy_use"],
            humidity=room["humidity"],
            light=room["light_level"]
        )

    def _update_decisions(self):
        """
        Execute decision logic using the decision engine.
        Phase 4: Intelligent control strategies (rule-based, comfort, energy, hybrid).
        Phase 7: Send actuator commands through hardware service abstraction.
        """
        for room_id in self.room_ids:
            # Build decision context from current room state
            context = self._build_decision_context(room_id)

            # Get control decision from decision engine
            decision = self.decision_engine.make_decision(context)

            # Apply decision to room state
            room = self.state["rooms"][room_id]
            room["light_on"] = decision.light_on
            room["hvac_mode"] = decision.hvac_mode
            room["hvac_setpoint"] = decision.hvac_setpoint
            room["hvac_speed"] = decision.hvac_speed
            room["shading_factor"] = decision.shading_factor
            room["light_threshold"] = getattr(decision, "light_threshold", 400.0)
            room["decision_reason"] = decision.decision_reason

            # Phase 7: Send actuator commands through hardware service
            room_actuators = self.room_actuators[room_id]
            room_actuators.apply_decision(decision)

            # Log decision for analysis
            self.decision_log[room_id].append({
                "time": self.current_time,
                "decision": decision,
            })

    def _build_decision_context(self, room_id: int) -> DecisionContext:
        """
        Build decision context from current room state.

        Args:
            room_id: Room identifier

        Returns:
            DecisionContext for decision engine
        """
        room = self.state["rooms"][room_id]
        room_config = next(r for r in self.room_configs if r.room_id == room_id)

        return DecisionContext(
            room_id=room_id,
            zone_type=room_config.zone_type,
            temperature_zone=room["temperature"],
            temperature_wall=room["temperature_wall"],
            temperature_operative=room["operative_temperature"],
            humidity=room["humidity"],
            co2=room["co2"],
            light_level=room["light_level"],
            occupancy=room["occupancy"],
            pmv=room["pmv"],
            ppd=room["ppd"],
            comfort_index=room["comfort_index"],
            outdoor_temperature=self.state.get("outdoor_temperature", 20.0),
            solar_irradiance=self.weather_data.get("solar_irradiance", 0.0),
            wind_speed=self.weather_data.get("wind_speed", 0.0),
            light_on=room["light_on"],
            hvac_mode=room["hvac_mode"],
            hvac_setpoint=room["hvac_setpoint"],
            hvac_speed=room["hvac_speed"],
            shading_factor=room["shading_factor"],
            hour_of_day=self.current_time.hour + self.current_time.minute / 60.0,
            is_occupied=room["occupancy"] > 0,
        )

    def _publish_state(self):
        """Update the state dictionary for rendering."""
        self.state["time"] = self.current_time.strftime("%H:%M:%S")
        self.state["date"] = self.current_time.strftime("%Y-%m-%d")
        self.state["speed_factor"] = self.speed_factor
        self.state["paused"] = self.paused

    def pause(self):
        """Pause the simulation."""
        self.paused = True

    def resume(self):
        """Resume the simulation."""
        self.paused = False

    def set_speed(self, factor: float):
        """
        Set time acceleration factor.

        Args:
            factor: Acceleration factor (1.0 = normal speed, 60.0 = 60x)
        """
        self.speed_factor = max(0.1, factor)

    def get_state(self) -> Dict:
        """Get current simulation state."""
        return self.state
