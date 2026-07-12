"""
Actuator Models - Hardware Interface Definitions

Defines physical actuators (lights, HVAC, shading) and their control interfaces.
Separates actuator control from simulation and rendering logic.

Phase 7: Hardware Integration Foundation
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, List, Any
from enum import Enum

from hardware.service import ActuatorCommand, ActuatorType, HardwareService


class HVACMode(Enum):
    """HVAC operating modes."""
    OFF = "off"
    HEATING = "heating"
    COOLING = "cooling"
    FAN_ONLY = "fan_only"
    AUTO = "auto"


@dataclass
class ActuatorState:
    """Current state of an actuator."""
    actuator_id: str
    actuator_type: ActuatorType
    room_id: int
    value: float  # Current value (0-1)
    last_command_time: float = 0.0
    is_responding: bool = True  # Hardware responding/available
    metadata: Dict[str, Any] = field(default_factory=dict)


class ActuatorController:
    """
    Base class for controlling specific actuator types.

    Converts high-level control decisions into actuator commands.
    """

    def __init__(self, hardware_service: HardwareService):
        """
        Initialize actuator controller.

        Args:
            hardware_service: HardwareService for communication
        """
        self.hardware_service = hardware_service
        self.states: Dict[str, ActuatorState] = {}

    def register_actuator(
        self, actuator_id: str, actuator_type: ActuatorType, room_id: int
    ):
        """
        Register an actuator for control.

        Args:
            actuator_id: Unique actuator ID
            actuator_type: Type of actuator
            room_id: Room this actuator controls
        """
        self.states[actuator_id] = ActuatorState(
            actuator_id=actuator_id,
            actuator_type=actuator_type,
            room_id=room_id,
            value=0.0,
        )

    def send_command(self, actuator_id: str, value: float) -> bool:
        """
        Send command to actuator.

        Args:
            actuator_id: Target actuator
            value: Control value (0-1)

        Returns:
            True if successful
        """
        if actuator_id not in self.states:
            print(f"Warning: Unknown actuator {actuator_id}")
            return False

        state = self.states[actuator_id]
        command = ActuatorCommand(
            actuator_id=actuator_id,
            actuator_type=state.actuator_type,
            room_id=state.room_id,
            value=value,
        )

        success = self.hardware_service.send_actuator_command(command)

        if success:
            state.value = value
            import time
            state.last_command_time = time.time()

        return success

    def send_commands_batch(self, commands: Dict[str, float]) -> Dict[str, bool]:
        """
        Send multiple commands efficiently.

        Args:
            commands: Dict mapping actuator_id to value

        Returns:
            Dict mapping actuator_id to success status
        """
        actuator_commands = []

        for actuator_id, value in commands.items():
            if actuator_id not in self.states:
                continue

            state = self.states[actuator_id]
            actuator_commands.append(
                ActuatorCommand(
                    actuator_id=actuator_id,
                    actuator_type=state.actuator_type,
                    room_id=state.room_id,
                    value=value,
                )
            )

        results = self.hardware_service.send_actuator_commands_batch(actuator_commands)

        # Update local state for successful commands
        for actuator_id, success in results.items():
            if success and actuator_id in self.states:
                self.states[actuator_id].value = commands[actuator_id]
                import time
                self.states[actuator_id].last_command_time = time.time()

        return results

    def get_actuator_state(self, actuator_id: str) -> Optional[ActuatorState]:
        """Get current state of an actuator."""
        return self.states.get(actuator_id)

    def get_all_states(self) -> Dict[str, ActuatorState]:
        """Get all actuator states."""
        return self.states.copy()


class LightActuator:
    """
    Control interface for light actuators.

    Command format: 0 = OFF, 1 = ON (or 0-1 for dimmable lights)
    """

    def __init__(self, controller: ActuatorController, actuator_id: str, room_id: int):
        """
        Initialize light actuator.

        Args:
            controller: ActuatorController instance
            actuator_id: Unique ID for this light
            room_id: Room this light is in
        """
        self.controller = controller
        self.actuator_id = actuator_id
        self.room_id = room_id
        controller.register_actuator(actuator_id, ActuatorType.LIGHT, room_id)

    def set_on(self) -> bool:
        """Turn light on."""
        return self.controller.send_command(self.actuator_id, 1.0)

    def set_off(self) -> bool:
        """Turn light off."""
        return self.controller.send_command(self.actuator_id, 0.0)

    def set_brightness(self, brightness: float) -> bool:
        """
        Set light brightness (0-1).

        Args:
            brightness: 0 = off, 1 = full brightness

        Returns:
            True if successful
        """
        return self.controller.send_command(self.actuator_id, brightness)

    def is_on(self) -> bool:
        """Check if light is on."""
        state = self.controller.get_actuator_state(self.actuator_id)
        return state.value > 0.5 if state else False


class HVACActuator:
    """
    Control interface for HVAC systems.

    Command format:
    - value 0 = OFF
    - value 0-1 = Speed (0.5 = 50% compressor/fan speed)
    Mode controlled via metadata
    """

    def __init__(self, controller: ActuatorController, actuator_id: str, room_id: int):
        """
        Initialize HVAC actuator.

        Args:
            controller: ActuatorController instance
            actuator_id: Unique ID (e.g., "room_0_hvac")
            room_id: Room to control
        """
        self.controller = controller
        self.actuator_id = actuator_id
        self.room_id = room_id
        self.current_mode = HVACMode.OFF
        self.current_speed = 0.0
        controller.register_actuator(actuator_id, ActuatorType.HVAC_HEATING, room_id)

    def set_heating(self, speed: float) -> bool:
        """
        Set heating mode and speed.

        Args:
            speed: 0-1 (compressor/fan speed)

        Returns:
            True if successful
        """
        self.current_mode = HVACMode.HEATING
        self.current_speed = speed
        return self.controller.send_command(self.actuator_id, speed)

    def set_cooling(self, speed: float) -> bool:
        """
        Set cooling mode and speed.

        Args:
            speed: 0-1

        Returns:
            True if successful
        """
        self.current_mode = HVACMode.COOLING
        self.current_speed = speed
        return self.controller.send_command(self.actuator_id, speed)

    def set_fan_only(self, speed: float) -> bool:
        """
        Set fan-only circulation mode.

        Args:
            speed: 0-1

        Returns:
            True if successful
        """
        self.current_mode = HVACMode.FAN_ONLY
        self.current_speed = speed
        return self.controller.send_command(self.actuator_id, speed)

    def turn_off(self) -> bool:
        """Turn HVAC off."""
        self.current_mode = HVACMode.OFF
        self.current_speed = 0.0
        return self.controller.send_command(self.actuator_id, 0.0)

    def get_mode(self) -> HVACMode:
        """Get current HVAC mode."""
        return self.current_mode

    def get_speed(self) -> float:
        """Get current HVAC speed (0-1)."""
        return self.current_speed


class ShadingActuator:
    """
    Control interface for window shading/blinds.

    Command format:
    - 0 = fully open
    - 0.5 = 50% shaded
    - 1.0 = fully closed
    """

    def __init__(self, controller: ActuatorController, actuator_id: str, room_id: int):
        """
        Initialize shading actuator.

        Args:
            controller: ActuatorController instance
            actuator_id: Unique ID (e.g., "room_0_shading")
            room_id: Room with windows
        """
        self.controller = controller
        self.actuator_id = actuator_id
        self.room_id = room_id
        controller.register_actuator(actuator_id, ActuatorType.WINDOW_SHADING, room_id)

    def set_open(self) -> bool:
        """Open shading fully."""
        return self.controller.send_command(self.actuator_id, 0.0)

    def set_closed(self) -> bool:
        """Close shading fully."""
        return self.controller.send_command(self.actuator_id, 1.0)

    def set_position(self, position: float) -> bool:
        """
        Set shading position.

        Args:
            position: 0 = open, 1 = closed

        Returns:
            True if successful
        """
        return self.controller.send_command(self.actuator_id, position)

    def get_position(self) -> float:
        """Get current shading position (0-1)."""
        state = self.controller.get_actuator_state(self.actuator_id)
        return state.value if state else 0.0


class RoomActuators:
    """
    All actuators for a single room.

    Convenience wrapper to control all room actuators together.
    """

    def __init__(self, controller: ActuatorController, room_id: int):
        """
        Initialize room actuators.

        Args:
            controller: ActuatorController instance
            room_id: Room ID
        """
        self.controller = controller
        self.room_id = room_id

        # Create actuators for this room
        self.light = LightActuator(controller, f"room_{room_id}_light", room_id)
        self.hvac = HVACActuator(controller, f"room_{room_id}_hvac", room_id)
        self.shading = ShadingActuator(controller, f"room_{room_id}_shading", room_id)

    def apply_decision(self, decision_output):
        """
        Apply control decision to all room actuators.

        Args:
            decision_output: DecisionOutput from decision engine
        """
        commands = {}

        # Light command
        commands[self.light.actuator_id] = 1.0 if decision_output.light_on else 0.0

        # HVAC command (depends on mode)
        hvac_value = decision_output.hvac_speed
        if decision_output.hvac_mode == "off":
            hvac_value = 0.0
        commands[self.hvac.actuator_id] = hvac_value

        # Shading command
        commands[self.shading.actuator_id] = decision_output.shading_factor

        # Send all commands at once
        self.controller.send_commands_batch(commands)

        # Update local state
        if decision_output.hvac_mode == "heating":
            self.hvac.set_heating(decision_output.hvac_speed)
        elif decision_output.hvac_mode == "cooling":
            self.hvac.set_cooling(decision_output.hvac_speed)
        elif decision_output.hvac_mode == "fan_only":
            self.hvac.set_fan_only(decision_output.hvac_speed)
        else:
            self.hvac.turn_off()
