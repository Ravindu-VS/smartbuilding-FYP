"""
Simulation Bridge — Dual-Mode Adapter

Connects the backend integration layer to the simulation.

MODE 1: EXTERNAL (Panda3D running)
    Reads simulation state from the IPC shared file (output/.sim_state.json).
    Does NOT create its own SimulationEngine.
    Does NOT advance its own simulation clock.
    Panda3D is the sole owner of the simulation engine and time.

MODE 2: HEADLESS (Panda3D not running)
    Creates its own headless SimulationEngine instance.
    Steps the engine on each tick.
    Acts as the sole simulation source.

MODE DETECTION:
    Auto-detects which mode to use based on the presence and freshness
    of the IPC state file. If the file exists and is fresh, uses external
    mode. Otherwise falls back to headless mode. Continuously monitors
    and can switch between modes at runtime.

CONTROL ACTIONS:
    In external mode, writes ML control decisions to the IPC control file
    (output/.control_actions.json). Panda3D reads this file and applies
    the actions to its engine.
    In headless mode, applies control actions directly to the engine.
"""

import sys
import os
import logging
import math
import time
from datetime import datetime
from typing import Dict, List, Optional, Any

# Ensure project root is on path so simulation modules can be imported
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from integration.config import (
    ROOM_ID_MAP, ROOM_ID_REVERSE, ROOM_TYPE_MAP, ROOM_DISPLAY_NAMES,
    BATHROOM_OCCUPANCY_SCHEDULE, KITCHEN_OCCUPANCY_SCHEDULE,
    SIMULATION_SPEED_FACTOR, compute_humidity_ratio,
    LIGHT_ACTION_TO_SIM, HVAC_ACTION_TO_SIM,
    SHARED_STATE_STALE_TIMEOUT, RECONNECT_INTERVAL,
)
from integration.simulation_ipc import (
    SimulationStateReader, ControlActionWriter,
)

logger = logging.getLogger(__name__)


class SimulationBridge:
    """
    Dual-mode adapter: External IPC (Panda3D) or Headless engine.

    IMPORTANT ARCHITECTURAL ROLE:
    - In EXTERNAL mode: Panda3D = Physical Source, Bridge = Reader
    - In HEADLESS mode: Bridge owns the SimulationEngine
    - StateManager = Backend's Authoritative Source (receives from bridge)
    - API = Exposes StateManager (never calls bridge directly)
    - Dashboard = Reads from API (never bypasses backend)

    Usage:
        bridge = SimulationBridge()
        # bridge auto-detects mode
        rooms = bridge.get_all_room_states()
        sim_time = bridge.get_simulation_time()
    """

    def __init__(self, config: dict = None):
        """
        Initialize the simulation bridge.

        Args:
            config: Optional config overrides.
        """
        self._config = config or {}
        self._mode = "initializing"  # "external", "headless", "disconnected"

        # Headless engine (only created if no external sim)
        self._engine = None
        self._running = False

        # External IPC (for reading Panda3D state)
        self._state_reader = SimulationStateReader(
            project_root=PROJECT_ROOT,
            stale_timeout=SHARED_STATE_STALE_TIMEOUT,
        )

        # Control action writer (for sending ML decisions to Panda3D)
        self._control_writer = ControlActionWriter(project_root=PROJECT_ROOT)

        # Connection tracking
        self._connection_failed = False
        self._last_error = None
        self._last_reconnect_attempt = 0.0

        # Cached state from last read
        self._cached_rooms: List[Dict[str, Any]] = []
        self._cached_sim_time: str = ""
        self._cached_engine_state: Optional[dict] = None

        # Auto-detect mode
        self._detect_mode()

        logger.info(f"✓ SimulationBridge initialized (mode={self._mode})")

    def _detect_mode(self):
        """
        Auto-detect whether an external Panda3D simulation is running
        by checking the IPC state file.
        """
        # Check if external simulation state file exists and is fresh
        data = self._state_reader.read_state()
        if data is not None and not self._state_reader.is_stale():
            self._mode = "external"
            self._running = True
            self._connection_failed = False
            logger.info("  Mode: EXTERNAL (Panda3D detected via IPC)")
            logger.info(f"  Reading from: {self._state_reader.filepath}")
            return

        # No external simulation — try headless fallback
        logger.info("  No external simulation detected, trying headless mode...")
        try:
            self._init_headless_engine()
            self._mode = "headless"
            self._running = True
            self._connection_failed = False
            logger.info("  Mode: HEADLESS (own SimulationEngine)")
        except Exception as e:
            logger.warning(f"  Headless engine init failed: {e}")
            self._mode = "disconnected"
            self._running = False
            self._connection_failed = True
            self._last_error = str(e)
            logger.info("  Mode: DISCONNECTED (waiting for simulation)")

    def _init_headless_engine(self):
        """Create a headless SimulationEngine instance."""
        from simulation.engine import SimulationEngine

        engine_config = {
            "speed_factor": self._config.get(
                "speed_factor", SIMULATION_SPEED_FACTOR
            ),
            "advanced_physics": self._config.get("advanced_physics", True),
            "sensors": self._config.get("sensors", {}),
            "occupancy": self._config.get("occupancy", {}),
            "decisions": self._config.get("decisions", {}),
            "hardware": {"type": "logging"},
        }

        self._engine = SimulationEngine(engine_config)
        self._inject_custom_schedules()
        logger.info(
            f"  SimulationEngine created with {len(self._engine.room_ids)} rooms"
        )

    def _inject_custom_schedules(self):
        """Inject custom occupancy schedules for bathroom and kitchen."""
        if self._engine is None:
            return
        scheduler = self._engine.occupancy_scheduler
        if "bathroom" not in scheduler.zone_schedules:
            scheduler.zone_schedules["bathroom"] = BATHROOM_OCCUPANCY_SCHEDULE
        if "kitchen" not in scheduler.zone_schedules:
            scheduler.zone_schedules["kitchen"] = KITCHEN_OCCUPANCY_SCHEDULE

    # =========================================================================
    # CORE API: Step + Read
    # =========================================================================

    def step(self, dt: float = 2.0):
        """
        Advance the simulation by dt seconds.

        In EXTERNAL mode: Does nothing (Panda3D owns the clock).
        In HEADLESS mode: Steps the engine forward.
        In DISCONNECTED mode: Attempts reconnection.
        """
        if self._mode == "external":
            # Panda3D advances the clock. We just check for IPC freshness.
            self._check_external_connection()
            return

        if self._mode == "headless":
            if self._engine is not None:
                try:
                    self._engine.update(dt)
                except Exception as e:
                    logger.error(f"Headless simulation step failed: {e}")
                    self._connection_failed = True
                    self._last_error = str(e)
            return

        # Disconnected mode: try to reconnect periodically
        now = time.time()
        if (now - self._last_reconnect_attempt) > RECONNECT_INTERVAL:
            self._last_reconnect_attempt = now
            self._attempt_reconnect()

    def _check_external_connection(self):
        """
        Check if the external Panda3D simulation is still alive.
        If the IPC state file becomes stale, switch to disconnected mode.
        """
        data = self._state_reader.read_state()
        if data is None or self._state_reader.is_stale():
            age = self._state_reader.get_age_seconds()
            if age > SHARED_STATE_STALE_TIMEOUT:
                if self._mode == "external":
                    logger.warning(
                        f"External simulation lost (state file stale: {age:.1f}s). "
                        f"Switching to disconnected mode."
                    )
                    self._mode = "disconnected"
                    self._running = False
                    self._connection_failed = True
                    self._last_error = "External simulation disconnected"

    def _attempt_reconnect(self):
        """Try to reconnect to either external or headless simulation."""
        logger.debug("Attempting reconnection...")

        # First check if external simulation came back
        data = self._state_reader.read_state()
        if data is not None and not self._state_reader.is_stale():
            logger.info("✓ External simulation reconnected (IPC file is fresh)")
            self._mode = "external"
            self._running = True
            self._connection_failed = False
            self._last_error = None
            return

        # Try headless fallback
        if self._engine is None:
            try:
                self._init_headless_engine()
                self._mode = "headless"
                self._running = True
                self._connection_failed = False
                self._last_error = None
                logger.info("✓ Headless simulation started as fallback")
            except Exception as e:
                logger.debug(f"Headless fallback still unavailable: {e}")

    def get_all_room_states(self) -> List[Dict[str, Any]]:
        """
        Read all room states from the current simulation source.

        In EXTERNAL mode: reads from IPC state file.
        In HEADLESS mode: reads from own engine.

        Returns:
            List of standardized room state dicts. Empty if disconnected.
        """
        if self._mode == "external":
            return self._get_rooms_from_ipc()
        elif self._mode == "headless":
            return self._get_rooms_from_engine()
        else:
            return []  # Disconnected

    def _get_rooms_from_ipc(self) -> List[Dict[str, Any]]:
        """Read room states from the external IPC state file."""
        data = self._state_reader.read_state()
        if data is None:
            return []

        engine_state = data.get("engine_state", {})
        if not engine_state:
            return []

        # Cache the full engine state for sim time extraction
        self._cached_engine_state = engine_state

        rooms_data = []
        for int_id, room_state in engine_state.get("rooms", {}).items():
            try:
                # The IPC file may have int keys as strings
                int_id_num = int(int_id)
                mapped = self._map_room_state(int_id_num, room_state, engine_state)
                rooms_data.append(mapped)
            except Exception as e:
                logger.warning(f"Failed to map IPC room {int_id}: {e}")
                continue

        self._cached_rooms = rooms_data
        return rooms_data

    def _get_rooms_from_engine(self) -> List[Dict[str, Any]]:
        """Read room states from the headless engine (same as original)."""
        if self._engine is None:
            return []

        try:
            engine_state = self._engine.get_state()
        except Exception as e:
            logger.error(f"Failed to get engine state: {e}")
            self._connection_failed = True
            self._last_error = str(e)
            return []

        self._cached_engine_state = engine_state

        rooms_data = []
        for int_id, room_state in engine_state.get("rooms", {}).items():
            try:
                mapped = self._map_room_state(int_id, room_state, engine_state)
                rooms_data.append(mapped)
            except Exception as e:
                logger.warning(f"Failed to map room {int_id}: {e}")
                continue

        self._cached_rooms = rooms_data
        return rooms_data

    def _map_room_state(
        self, int_id: int, room: dict, engine_state: dict
    ) -> Dict[str, Any]:
        """
        Map a single room's engine state to the integration schema.
        """
        string_id = ROOM_ID_MAP.get(int_id, f"room_{int_id}")
        zone_type = room.get("zone_type", "office")
        mapped_type = ROOM_TYPE_MAP.get(zone_type, zone_type)
        display_name = ROOM_DISPLAY_NAMES.get(string_id, room.get("name", string_id))

        temperature = round(room.get("temperature", 20.0), 2)
        humidity = round(room.get("humidity", 45.0), 2)
        light = round(room.get("light_level", 0.0), 1)
        co2 = round(room.get("co2", 400.0), 1)
        humidity_ratio = compute_humidity_ratio(temperature, humidity)

        occupancy_count = room.get("occupancy", 0.0)
        true_occupancy = 1 if occupancy_count > 0 else 0

        timestamp = f"{engine_state.get('date', '')}T{engine_state.get('time', '')}"

        return {
            "room_id": string_id,
            "room_type": mapped_type,
            "display_name": display_name,
            "int_id": int_id,
            "timestamp": timestamp,
            "sensors": {
                "Temperature": temperature,
                "Humidity": humidity,
                "Light": light,
                "CO2": co2,
                "HumidityRatio": humidity_ratio,
            },
            "ground_truth": {
                "true_occupancy": true_occupancy,
                "occupancy_count": int(occupancy_count),
            },
            "ai": {},
            "control": {},
            "energy": {},
            "device_state": {
                "light_on": room.get("light_on", False),
                "hvac_mode": room.get("hvac_mode", "off"),
                "hvac_setpoint": room.get("hvac_setpoint", 21.0),
                "hvac_speed": round(room.get("hvac_speed", 0.0), 2),
            },
        }

    # =========================================================================
    # CONTROL ACTIONS: Backend → Simulation
    # =========================================================================

    def apply_control_actions(self, room_id: str, control: Dict[str, Any]):
        """
        Apply ML controller decisions to the simulation.

        In EXTERNAL mode: Collected and batch-written via write_control_actions().
        In HEADLESS mode: Applied directly to the engine.
        """
        if self._mode == "headless" and self._engine is not None:
            self._apply_control_to_engine(room_id, control)
        # In external mode, actions are batched and written via write_control_actions()

    def _apply_control_to_engine(self, room_id: str, control: Dict[str, Any]):
        """Apply control directly to the headless engine."""
        int_id = ROOM_ID_REVERSE.get(room_id)
        if int_id is None:
            return

        room = self._engine.state.get("rooms", {}).get(int_id)
        if room is None:
            return

        try:
            light_action = control.get("light_action", "OFF")
            room["light_on"] = LIGHT_ACTION_TO_SIM.get(light_action, False)

            hvac_action = control.get("hvac_action", "ECO")
            hvac_sim = HVAC_ACTION_TO_SIM.get(
                hvac_action, {"hvac_mode": "off", "hvac_speed": 0.0}
            )
            room["hvac_mode"] = hvac_sim["hvac_mode"]
            room["hvac_speed"] = hvac_sim["hvac_speed"]
        except Exception as e:
            logger.warning(f"Failed to apply control to room {room_id}: {e}")

    def write_control_actions(self, room_actions: Dict[str, Dict[str, Any]]):
        """
        Write all ML control actions to the IPC file for Panda3D.

        In EXTERNAL mode: Writes to the control actions IPC file.
        In HEADLESS mode: No-op (actions already applied directly).

        Args:
            room_actions: Dict mapping room_id to control action dict.
        """
        if self._mode == "external":
            self._control_writer.write_actions(room_actions)

    # =========================================================================
    # SIMULATION TIME
    # =========================================================================

    def get_simulation_time(self) -> str:
        """
        Get current simulation time as ISO string.

        In EXTERNAL mode: reads from cached IPC data (Panda3D's clock).
        In HEADLESS mode: reads from own engine.
        NEVER generates its own clock in external mode.
        """
        if self._mode == "external" and self._cached_engine_state:
            state = self._cached_engine_state
            return f"{state.get('date', '')}T{state.get('time', '')}"

        if self._mode == "headless" and self._engine is not None:
            state = self._engine.get_state()
            return f"{state.get('date', '')}T{state.get('time', '')}"

        return ""  # Disconnected — no time to report

    # =========================================================================
    # CONNECTION STATUS
    # =========================================================================

    def is_running(self) -> bool:
        """Check if simulation is active (any mode)."""
        return self._running and not self._connection_failed

    def is_connected(self) -> bool:
        """Check if simulation bridge is connected to a simulation source."""
        if self._mode == "external":
            return not self._state_reader.is_stale()
        elif self._mode == "headless":
            return self._engine is not None and not self._connection_failed
        return False

    def get_connection_status(self) -> Dict[str, Any]:
        """Get detailed connection status."""
        return {
            "connected": self.is_connected(),
            "running": self._running,
            "mode": self._mode,
            "error": self._last_error,
            "engine_type": {
                "external": "Panda3D (IPC)",
                "headless": "SimulationEngine (headless)",
                "disconnected": "Waiting for simulation",
            }.get(self._mode, "Unknown"),
        }

    def reconnect(self) -> bool:
        """Attempt to reconnect to simulation."""
        self._attempt_reconnect()
        return self.is_connected()

    # =========================================================================
    # HEADLESS-MODE CONTROLS (no-op in external mode)
    # =========================================================================

    def pause(self):
        if self._mode == "headless" and self._engine:
            self._engine.pause()
            logger.info("Simulation paused (headless)")

    def resume(self):
        if self._mode == "headless" and self._engine:
            self._engine.resume()
            logger.info("Simulation resumed (headless)")

    def is_paused(self) -> bool:
        if self._mode == "headless" and self._engine:
            return self._engine.paused
        return False

    def set_speed(self, factor: float):
        if self._mode == "headless" and self._engine:
            self._engine.set_speed(factor)
            logger.info(f"Simulation speed set to {factor}x")

    def get_weather(self) -> dict:
        if self._cached_engine_state:
            return self._cached_engine_state.get("weather", {})
        if self._engine:
            return self._engine.get_state().get("weather", {})
        return {}

    @property
    def mode(self) -> str:
        """Current bridge mode: 'external', 'headless', or 'disconnected'."""
        return self._mode
