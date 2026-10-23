"""
Hardware Service Abstraction Layer

Decouples simulation and rendering from physical hardware communication.
Supports logging (current), mocking (testing), and future MQTT/REST integration.

Phase 7: Hardware Integration Foundation
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable
from enum import Enum
import time
from datetime import datetime


# ============================================================================
# ACTUATOR & SENSOR INTERFACES
# ============================================================================


class ActuatorType(Enum):
    """Types of actuators in the building."""
    LIGHT = "light"
    HVAC_HEATING = "hvac_heating"
    HVAC_COOLING = "hvac_cooling"
    HVAC_FAN = "hvac_fan"
    WINDOW_SHADING = "window_shading"


class SensorType(Enum):
    """Types of sensors in the building."""
    TEMPERATURE = "temperature"
    HUMIDITY = "humidity"
    CO2 = "co2"
    LIGHT_LEVEL = "light_level"
    OCCUPANCY = "occupancy"


@dataclass
class ActuatorCommand:
    """
    Command to send to a hardware actuator.

    Immutable representation of a control decision.
    """
    actuator_id: str  # Unique ID (e.g., "room_0_light", "room_1_hvac")
    actuator_type: ActuatorType
    room_id: int
    value: float  # 0-1 for most (light on/off, HVAC speed), varies by type
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate command."""
        if not 0.0 <= self.value <= 1.0:
            # Allow slightly outside range for floating point errors
            if 0.0 <= self.value <= 1.01 or -0.01 <= self.value <= 0.0:
                self.value = max(0.0, min(1.0, self.value))
            else:
                raise ValueError(f"Actuator value out of range: {self.value}")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/transmission."""
        return {
            "actuator_id": self.actuator_id,
            "actuator_type": self.actuator_type.value,
            "room_id": self.room_id,
            "value": self.value,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


@dataclass
class SensorReading:
    """
    Reading from a hardware sensor.

    Returned by hardware service to update simulation.
    """
    sensor_id: str
    sensor_type: SensorType
    room_id: int
    value: float
    timestamp: float = field(default_factory=time.time)
    confidence: float = 1.0  # 0-1: reliability of reading

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "sensor_id": self.sensor_id,
            "sensor_type": self.sensor_type.value,
            "room_id": self.room_id,
            "value": self.value,
            "timestamp": self.timestamp,
            "confidence": self.confidence,
        }


# ============================================================================
# HARDWARE SERVICE INTERFACE
# ============================================================================


class HardwareService(ABC):
    """
    Abstract base class for hardware communication services.

    Implementations handle the actual communication protocol
    (logging, MQTT, REST, serial, etc.)

    All actuator commands and sensor readings pass through here.
    """

    @abstractmethod
    def initialize(self):
        """Initialize hardware service (connect, authenticate, etc.)."""
        pass

    @abstractmethod
    def shutdown(self):
        """Gracefully shutdown hardware service."""
        pass

    @abstractmethod
    def send_actuator_command(self, command: ActuatorCommand) -> bool:
        """
        Send command to actuator.

        Args:
            command: ActuatorCommand to send

        Returns:
            True if successful, False if failed
        """
        pass

    @abstractmethod
    def send_actuator_commands_batch(self, commands: List[ActuatorCommand]) -> Dict[str, bool]:
        """
        Send multiple commands efficiently.

        Args:
            commands: List of ActuatorCommand

        Returns:
            Dict mapping actuator_id to success status
        """
        pass

    @abstractmethod
    def get_sensor_reading(self, sensor_id: str) -> Optional[SensorReading]:
        """
        Get latest reading from a sensor.

        Args:
            sensor_id: Sensor identifier

        Returns:
            SensorReading or None if unavailable
        """
        pass

    @abstractmethod
    def get_all_sensor_readings(self) -> Dict[str, SensorReading]:
        """
        Get all sensor readings efficiently.

        Returns:
            Dict mapping sensor_id to SensorReading
        """
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if hardware service is connected/available."""
        pass

    @abstractmethod
    def get_status(self) -> Dict[str, Any]:
        """Get service status (connected, last update, etc.)."""
        pass

    def register_sensor_callback(self, sensor_id: str, callback: Callable[[SensorReading], None]):
        """
        Register callback for sensor readings (optional, for async updates).

        Args:
            sensor_id: Sensor to monitor
            callback: Function to call when reading available
        """
        pass


# ============================================================================
# LOGGING IMPLEMENTATION (Current)
# ============================================================================


class LoggingHardwareService(HardwareService):
    """
    Logging-based hardware service.

    Current implementation: logs all actuator commands and sensor readings.
    Useful for debugging and monitoring without physical hardware.
    """

    def __init__(self, log_file: Optional[str] = None, verbose: bool = False):
        """
        Initialize logging service.

        Args:
            log_file: Optional file path for persistent logging
            verbose: Print to console if True
        """
        self.log_file = log_file
        self.verbose = verbose
        self.command_log: List[ActuatorCommand] = []
        self.reading_log: List[SensorReading] = []
        self.is_initialized = False
        self.start_time = time.time()

        if self.log_file:
            try:
                with open(self.log_file, "w") as f:
                    f.write(f"Hardware Service Log - Started {datetime.now()}\n")
                    f.write("=" * 80 + "\n")
            except IOError as e:
                print(f"Warning: Could not create log file: {e}")

    def initialize(self):
        """Initialize logging service."""
        self.is_initialized = True
        self._log(f"[OK] LoggingHardwareService initialized")

    def shutdown(self):
        """Shutdown logging service."""
        self._log(f"Shutting down after {len(self.command_log)} commands")
        self.is_initialized = False

    def send_actuator_command(self, command: ActuatorCommand) -> bool:
        """Log actuator command."""
        self.command_log.append(command)

        message = (
            f"[{command.actuator_type.value}] {command.actuator_id}: "
            f"{command.value:.2f} (room {command.room_id})"
        )
        self._log(f"ACTUATOR: {message}")
        return True

    def send_actuator_commands_batch(self, commands: List[ActuatorCommand]) -> Dict[str, bool]:
        """Log batch of commands."""
        self._log(f"BATCH: {len(commands)} actuator commands")
        results = {}
        for cmd in commands:
            results[cmd.actuator_id] = self.send_actuator_command(cmd)
        return results

    def get_sensor_reading(self, sensor_id: str) -> Optional[SensorReading]:
        """
        Get latest reading for sensor (from log).

        Args:
            sensor_id: Sensor identifier

        Returns:
            Latest reading or None
        """
        matching = [r for r in self.reading_log if r.sensor_id == sensor_id]
        return matching[-1] if matching else None

    def get_all_sensor_readings(self) -> Dict[str, SensorReading]:
        """Get all latest sensor readings."""
        readings = {}
        sensor_ids = set(r.sensor_id for r in self.reading_log)
        for sensor_id in sensor_ids:
            reading = self.get_sensor_reading(sensor_id)
            if reading:
                readings[sensor_id] = reading
        return readings

    def is_connected(self) -> bool:
        """Always connected for logging service."""
        return self.is_initialized

    def get_status(self) -> Dict[str, Any]:
        """Get service status."""
        return {
            "type": "logging",
            "connected": self.is_initialized,
            "uptime": time.time() - self.start_time,
            "commands_logged": len(self.command_log),
            "readings_logged": len(self.reading_log),
            "log_file": self.log_file,
        }

    def _log(self, message: str):
        """Write to log file and/or console."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        formatted = f"[{timestamp}] {message}"

        if self.verbose:
            print(formatted)

        if self.log_file:
            try:
                with open(self.log_file, "a") as f:
                    f.write(formatted + "\n")
            except IOError:
                pass


# ============================================================================
# MOCKING IMPLEMENTATION (Testing)
# ============================================================================


class MockingHardwareService(HardwareService):
    """
    Mocking hardware service for testing and simulation.

    Simulates hardware responses based on command history.
    Useful for testing control logic without physical hardware.
    """

    def __init__(self, enable_randomness: bool = False):
        """
        Initialize mocking service.

        Args:
            enable_randomness: Add small random variations to readings
        """
        self.enable_randomness = enable_randomness
        self.is_initialized = False
        self.command_history: Dict[str, ActuatorCommand] = {}
        self.simulated_sensors: Dict[str, SensorReading] = {}
        self.start_time = time.time()

    def initialize(self):
        """Initialize mocking service."""
        self.is_initialized = True
        print(f"[OK] MockingHardwareService initialized (randomness: {self.enable_randomness})")

    def shutdown(self):
        """Shutdown mocking service."""
        print(f"Shutting down mock hardware ({len(self.command_history)} commands)")
        self.is_initialized = False

    def send_actuator_command(self, command: ActuatorCommand) -> bool:
        """
        Mock sending command (store internally).

        Args:
            command: ActuatorCommand

        Returns:
            True (always succeeds in mock)
        """
        self.command_history[command.actuator_id] = command
        print(f"[MOCK] {command.actuator_id} = {command.value:.2f}")
        return True

    def send_actuator_commands_batch(self, commands: List[ActuatorCommand]) -> Dict[str, bool]:
        """Mock batch command sending."""
        results = {}
        for cmd in commands:
            results[cmd.actuator_id] = self.send_actuator_command(cmd)
        return results

    def get_sensor_reading(self, sensor_id: str) -> Optional[SensorReading]:
        """Get simulated sensor reading."""
        if sensor_id in self.simulated_sensors:
            reading = self.simulated_sensors[sensor_id]

            # Add randomness if enabled
            if self.enable_randomness:
                import random
                noise = random.gauss(0, 0.01)  # Small gaussian noise
                reading.value = max(0, min(1, reading.value + noise))

            return reading
        return None

    def get_all_sensor_readings(self) -> Dict[str, SensorReading]:
        """Get all simulated sensor readings."""
        return {
            sensor_id: self.get_sensor_reading(sensor_id)
            for sensor_id in self.simulated_sensors
        }

    def is_connected(self) -> bool:
        """Always connected for mocking service."""
        return self.is_initialized

    def get_status(self) -> Dict[str, Any]:
        """Get service status."""
        return {
            "type": "mocking",
            "connected": self.is_initialized,
            "uptime": time.time() - self.start_time,
            "commands_stored": len(self.command_history),
            "sensors_simulated": len(self.simulated_sensors),
            "randomness_enabled": self.enable_randomness,
        }

    def set_sensor_reading(self, reading: SensorReading):
        """
        Manually set a sensor reading (for testing).

        Args:
            reading: SensorReading to set
        """
        self.simulated_sensors[reading.sensor_id] = reading

    def get_last_command(self, actuator_id: str) -> Optional[ActuatorCommand]:
        """Get last command sent to an actuator."""
        return self.command_history.get(actuator_id)


# ============================================================================
# HARDWARE SERVICE FACTORY
# ============================================================================


class HardwareServiceFactory:
    """Factory for creating hardware service instances."""

    @staticmethod
    def create(service_type: str = "logging", **kwargs) -> HardwareService:
        """
        Create hardware service from configuration.

        Args:
            service_type: "logging", "mocking", "mqtt", "rest"
            **kwargs: Service-specific arguments

        Returns:
            HardwareService instance
        """
        service_type = service_type.lower()

        if service_type == "logging":
            return LoggingHardwareService(
                log_file=kwargs.get("log_file"),
                verbose=kwargs.get("verbose", False),
            )

        elif service_type == "mocking":
            return MockingHardwareService(
                enable_randomness=kwargs.get("enable_randomness", False)
            )

        elif service_type == "mqtt":
            from hardware.mqtt_service import MQTTHardwareService
            return MQTTHardwareService(
                broker_address=kwargs.get("broker_address", "localhost"),
                broker_port=kwargs.get("broker_port", 1883),
                client_id=kwargs.get("client_id", "smart_building"),
                username=kwargs.get("username"),
                password=kwargs.get("password"),
                topic_prefix=kwargs.get("topic_prefix", "building/"),
            )

        elif service_type == "rest":
            from hardware.rest_service import RESTHardwareService
            return RESTHardwareService(
                base_url=kwargs.get("base_url", "http://localhost:8080"),
                api_key=kwargs.get("api_key"),
                timeout=kwargs.get("timeout", 5.0),
                verify_ssl=kwargs.get("verify_ssl", True),
            )

        else:
            raise ValueError(f"Unknown hardware service type: {service_type}")

    @staticmethod
    def create_from_config(config: dict) -> HardwareService:
        """
        Create hardware service from configuration dict.

        Args:
            config: Configuration dict with "type" and service-specific options

        Returns:
            HardwareService instance
        """
        service_type = config.get("type", "logging")
        return HardwareServiceFactory.create(service_type, **config)
