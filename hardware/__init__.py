"""
Hardware Service Module

Abstraction layer for hardware communication and control.

Separates simulation logic from physical device control, enabling:
- Current: Logging and mocking (testing without hardware)
- Future: MQTT, REST, serial, or custom protocols

Phase 7: Hardware Integration Foundation
"""

from hardware.service import (
    HardwareService,
    LoggingHardwareService,
    MockingHardwareService,
    HardwareServiceFactory,
    ActuatorCommand,
    ActuatorType,
    SensorReading,
    SensorType,
)

from hardware.actuators import (
    ActuatorController,
    LightActuator,
    HVACActuator,
    ShadingActuator,
    RoomActuators,
    ActuatorState,
    HVACMode,
)

__all__ = [
    # Service
    "HardwareService",
    "LoggingHardwareService",
    "MockingHardwareService",
    "HardwareServiceFactory",
    # Data
    "ActuatorCommand",
    "ActuatorType",
    "SensorReading",
    "SensorType",
    # Controllers
    "ActuatorController",
    "LightActuator",
    "HVACActuator",
    "ShadingActuator",
    "RoomActuators",
    "ActuatorState",
    "HVACMode",
]
