"""
Physical Output Controller for Raspberry Pi 4B
================================================

Controls physical GPIO outputs to demonstrate AI decisions
for all 26 rooms in the smart building prototype.

Supported configurations:
  1. MINIMAL: 1x RGB LED (Room 101) + 1x DC Motor Fan
  2. FLOOR_DEMO: 5x RGB LEDs (1 per floor) showing aggregate state
  3. FULL_GRID: PCA9685 PWM board driving 26 individual indicator LEDs

When not running on a Raspberry Pi, this module operates in
simulation mode and logs output states without GPIO access.
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("PhysicalOutput")


# =============================================================================
# PIN CONFIGURATION — Customize to your wiring
# =============================================================================
class PinConfig:
    """GPIO pin assignments for the Raspberry Pi 4B."""

    # Room 101 — Full actuator set (same physical hardware as ESP32 drove)
    # When using Pi directly, connect these to the Pi's GPIO header
    ROOM_101_FAN = 18        # DC Motor Fan via MOSFET (BCM 18, Pin 12)
    ROOM_101_RGB_RED = 17    # RGB LED Red (BCM 17, Pin 11)
    ROOM_101_RGB_GREEN = 27  # RGB LED Green (BCM 27, Pin 13)
    ROOM_101_RGB_BLUE = 22   # RGB LED Blue (BCM 22, Pin 15)

    # Floor indicator LEDs (1 per floor, optional)
    FLOOR_LEDS = {
        0: 5,   # Floor 0 indicator (BCM 5)
        1: 6,   # Floor 1 indicator (BCM 6)
        2: 13,  # Floor 2 indicator (BCM 13)
        3: 19,  # Floor 3 indicator (BCM 19)
        4: 26,  # Floor 4 indicator (BCM 26)
    }

    # Status LED (system heartbeat)
    STATUS_LED = 24  # BCM 24


class PhysicalOutputManager:
    """
    Manages all physical GPIO outputs for the building prototype.

    Operates in two modes:
    - Pi mode: Actual GPIO control via RPi.GPIO
    - Sim mode: Logs state changes (for development on non-Pi systems)
    """

    def __init__(self, mode: str = "MINIMAL"):
        """
        Initialize the output manager.

        Args:
            mode: "MINIMAL" | "FLOOR_DEMO" | "FULL_GRID"
        """
        self._mode = mode
        self._is_pi = False
        self._gpio = None
        self._pwm_channels: Dict[int, Any] = {}

        # Current output state for each room
        self._states: Dict[str, Dict[str, Any]] = {}

        # Aggregate floor states
        self._floor_states: Dict[int, Dict[str, Any]] = {}

        self._init_gpio()

    def _init_gpio(self):
        """Initialize GPIO if running on Raspberry Pi."""
        try:
            import RPi.GPIO as GPIO
            self._gpio = GPIO
            self._gpio.setmode(GPIO.BCM)
            self._gpio.setwarnings(False)
            self._is_pi = True

            # Setup Room 101 pins
            self._gpio.setup(PinConfig.ROOM_101_FAN, GPIO.OUT)
            self._gpio.setup(PinConfig.ROOM_101_RGB_RED, GPIO.OUT)
            self._gpio.setup(PinConfig.ROOM_101_RGB_GREEN, GPIO.OUT)
            self._gpio.setup(PinConfig.ROOM_101_RGB_BLUE, GPIO.OUT)
            self._gpio.setup(PinConfig.STATUS_LED, GPIO.OUT)

            # Default all OFF
            self._gpio.output(PinConfig.ROOM_101_FAN, GPIO.LOW)
            self._gpio.output(PinConfig.ROOM_101_RGB_RED, GPIO.LOW)
            self._gpio.output(PinConfig.ROOM_101_RGB_GREEN, GPIO.LOW)
            self._gpio.output(PinConfig.ROOM_101_RGB_BLUE, GPIO.LOW)

            # Setup floor indicator LEDs
            if self._mode in ("FLOOR_DEMO", "FULL_GRID"):
                for floor_id, pin in PinConfig.FLOOR_LEDS.items():
                    self._gpio.setup(pin, GPIO.OUT)
                    self._gpio.output(pin, GPIO.LOW)

            # Heartbeat LED ON
            self._gpio.output(PinConfig.STATUS_LED, GPIO.HIGH)

            logger.info(f"✓ GPIO initialized in {self._mode} mode")

        except (ImportError, RuntimeError):
            self._is_pi = False
            logger.info(f"ℹ GPIO simulation mode ({self._mode}) — no physical Pi detected")

    def update_room(self, room_id: str, floor_id: int, control: Dict[str, Any]):
        """
        Update the physical output for a specific room.

        Args:
            room_id: Room identifier (e.g., "f1_room_101")
            floor_id: Floor number (0-4)
            control: Control decision dict with light_action, hvac_action, control_mode
        """
        self._states[room_id] = {
            "light": control.get("light_action", "OFF"),
            "hvac": control.get("hvac_action", "ECO"),
            "mode": control.get("control_mode", "EMPTY"),
            "power": control.get("estimated_power_watts", 0),
            "floor_id": floor_id,
        }

        # Drive Room 101 physical actuators
        if room_id == "f1_room_101" and self._is_pi:
            self._drive_room_101(control)

        # Update floor aggregate
        self._update_floor_state(floor_id)

    def _drive_room_101(self, control: Dict[str, Any]):
        """Drive Room 101's physical actuators (fan + RGB LED)."""
        if not self._gpio:
            return

        # Fan control
        hvac = control.get("hvac_action", "ECO")
        if hvac in ("NORMAL", "LOW"):
            self._gpio.output(PinConfig.ROOM_101_FAN, self._gpio.HIGH)
        else:
            self._gpio.output(PinConfig.ROOM_101_FAN, self._gpio.LOW)

        # RGB LED = room lighting
        light = control.get("light_action", "OFF")
        if light == "ON":
            self._gpio.output(PinConfig.ROOM_101_RGB_RED, self._gpio.HIGH)
            self._gpio.output(PinConfig.ROOM_101_RGB_GREEN, self._gpio.HIGH)
            self._gpio.output(PinConfig.ROOM_101_RGB_BLUE, self._gpio.HIGH)
        elif light == "DIM":
            self._gpio.output(PinConfig.ROOM_101_RGB_RED, self._gpio.HIGH)
            self._gpio.output(PinConfig.ROOM_101_RGB_GREEN, self._gpio.HIGH)
            self._gpio.output(PinConfig.ROOM_101_RGB_BLUE, self._gpio.LOW)
        else:
            self._gpio.output(PinConfig.ROOM_101_RGB_RED, self._gpio.LOW)
            self._gpio.output(PinConfig.ROOM_101_RGB_GREEN, self._gpio.LOW)
            self._gpio.output(PinConfig.ROOM_101_RGB_BLUE, self._gpio.LOW)

    def _update_floor_state(self, floor_id: int):
        """Compute aggregate floor state and drive floor indicator LED."""
        floor_rooms = {
            rid: state for rid, state in self._states.items()
            if state.get("floor_id") == floor_id
        }

        if not floor_rooms:
            return

        occupied_count = sum(1 for s in floor_rooms.values() if s["mode"] == "OCCUPIED")
        total = len(floor_rooms)

        self._floor_states[floor_id] = {
            "occupied_rooms": occupied_count,
            "total_rooms": total,
            "occupancy_ratio": occupied_count / total if total > 0 else 0,
        }

        # Drive floor LED if in FLOOR_DEMO mode
        if self._is_pi and self._mode in ("FLOOR_DEMO", "FULL_GRID"):
            pin = PinConfig.FLOOR_LEDS.get(floor_id)
            if pin is not None:
                self._gpio.output(pin, self._gpio.HIGH if occupied_count > 0 else self._gpio.LOW)

    def get_all_states(self) -> Dict[str, Any]:
        """Get all current physical output states."""
        return {
            "rooms": dict(self._states),
            "floors": dict(self._floor_states),
            "mode": self._mode,
            "is_pi": self._is_pi,
        }

    def cleanup(self):
        """Clean up GPIO on shutdown."""
        if self._is_pi and self._gpio:
            self._gpio.cleanup()
            logger.info("GPIO cleaned up")
