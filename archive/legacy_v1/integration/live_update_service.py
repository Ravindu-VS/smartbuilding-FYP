"""
Live Update Service

Background service that orchestrates the real-time simulation loop.
On each tick:
  1. Steps the simulation forward (or reads from IPC in external mode)
  2. Reads sensor data from all rooms
  3. Passes data through ML inference → control → energy pipeline
  4. Updates the central state manager
  5. Writes control actions back to IPC file for Panda3D (external mode)

Runs in a background thread so the Flask API remains responsive.

Reconnection Logic:
  If simulation becomes unavailable, the service continues running.
  It periodically attempts to reconnect (via SimulationBridge auto-detect).
  Dashboard shows "waiting" or "stale" state during disconnection.
  When simulation returns, data flow resumes automatically.
"""

import sys
import os
import csv
import logging
import threading
import time
from datetime import datetime
from typing import Optional, Dict, Any

# Ensure project root is on path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from integration.config import DEFAULT_UPDATE_INTERVAL, LOG_DIR, RECONNECT_INTERVAL
from integration.simulation_bridge import SimulationBridge
from integration.state_manager import StateManager

logger = logging.getLogger(__name__)


class LiveUpdateService:
    """
    Background service for real-time simulation → dashboard updates.

    Supports:
    - External mode (Panda3D running): reads IPC, no stepping
    - Headless mode (no Panda3D): steps own engine
    - Disconnected mode: waits for simulation, keeps backend alive
    - Automatic reconnection when simulation appears/reappears

    Usage:
        service = LiveUpdateService()
        service.start()
        # ... Flask API runs, dashboard polls ...
        service.stop()
    """

    def __init__(
        self,
        state_manager: Optional[StateManager] = None,
        simulation_bridge: Optional[SimulationBridge] = None,
        update_interval: float = DEFAULT_UPDATE_INTERVAL,
        enable_csv_logging: bool = True,
    ):
        """
        Initialize the live update service.

        Args:
            state_manager: StateManager instance (created if None)
            simulation_bridge: SimulationBridge instance (created if None)
            update_interval: Seconds between updates (default: 2.0)
            enable_csv_logging: Write state snapshots to CSV files
        """
        self._update_interval = update_interval
        self._enable_csv_logging = enable_csv_logging

        # Create components if not provided
        self._state_manager = state_manager or StateManager()
        self._bridge = simulation_bridge or SimulationBridge()

        # Wire closed-loop feedback: ML decisions → simulation engine
        self._state_manager.set_bridge(self._bridge)

        # Thread management
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._paused = False

        # CSV logging
        self._csv_writer = None
        self._csv_file = None
        if self._enable_csv_logging:
            self._init_csv_logger()

        # Initialize metrics tracking and analytics
        try:
            from integration.metrics_tracker import MetricsTracker
            from integration.advanced_analytics import AdvancedAnalytics
            from integration.database_persistence import DatabasePersistence

            self._metrics_tracker = MetricsTracker()
            self._analytics = AdvancedAnalytics()
            self._database = DatabasePersistence()
            logger.info("[OK] Metrics, analytics, and database persistence enabled")
        except Exception as e:
            logger.warning(f"Optional monitoring modules not available: {e}")
            self._metrics_tracker = None
            self._analytics = None
            self._database = None

        # Tick counter
        self._tick_count = 0

        # Connection state tracking
        self._was_connected = False
        self._disconnect_logged = False

        logger.info(
            f"[OK] LiveUpdateService initialized (interval={update_interval}s, "
            f"csv_logging={enable_csv_logging}, bridge_mode={self._bridge.mode})"
        )

    @property
    def state_manager(self) -> StateManager:
        """Access the state manager."""
        return self._state_manager

    @property
    def bridge(self) -> SimulationBridge:
        """Access the simulation bridge."""
        return self._bridge

    def _init_csv_logger(self):
        """Initialize CSV file for logging state snapshots."""
        try:
            os.makedirs(os.path.join(PROJECT_ROOT, LOG_DIR), exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            csv_path = os.path.join(
                PROJECT_ROOT, LOG_DIR, f"integration_log_{timestamp}.csv"
            )
            self._csv_file = open(csv_path, "w", newline="", encoding="utf-8")
            self._csv_writer = csv.writer(self._csv_file)

            # Write header
            self._csv_writer.writerow([
                "timestamp", "room_id", "room_type",
                "temperature", "humidity", "light", "co2", "humidity_ratio",
                "true_occupancy", "predicted_occupancy", "occupancy_probability",
                "control_mode", "light_action", "hvac_action",
                "power_watts", "cumulative_energy_wh",
            ])
            logger.info(f"  CSV logging to: {csv_path}")
        except Exception as e:
            logger.warning(f"CSV logging init failed: {e}")
            self._csv_writer = None

    def start(self):
        """Start the background update loop."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("LiveUpdateService already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="LiveUpdateService"
        )
        self._thread.start()
        self._state_manager.set_simulation_active(True)
        logger.info("[>] LiveUpdateService started")

    def stop(self):
        """Stop the background update loop."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._state_manager.set_simulation_active(False)

        # Close CSV file
        if self._csv_file:
            self._csv_file.close()
            self._csv_file = None

        logger.info("■ LiveUpdateService stopped")

    def pause(self):
        """Pause the simulation (updates stop)."""
        self._paused = True
        self._bridge.pause()
        logger.info("[||] LiveUpdateService paused")

    def resume(self):
        """Resume the simulation."""
        self._paused = False
        self._bridge.resume()
        logger.info("[>] LiveUpdateService resumed")

    def is_running(self) -> bool:
        """Check if the service is running."""
        return self._thread is not None and self._thread.is_alive()

    def is_paused(self) -> bool:
        """Check if the simulation is paused."""
        return self._paused

    def set_update_interval(self, interval: float):
        """Set the update interval in seconds."""
        self._update_interval = max(0.5, min(10.0, interval))
        logger.info(f"Update interval set to {self._update_interval}s")

    def get_update_interval(self) -> float:
        """Get current update interval."""
        return self._update_interval

    def _run_loop(self):
        """Main update loop (runs in background thread)."""
        logger.info("Update loop started")

        while not self._stop_event.is_set():
            loop_start = time.time()

            if not self._paused:
                try:
                    self._tick()
                except Exception as e:
                    logger.error(f"Tick error: {e}", exc_info=True)

            # Sleep for remaining interval time
            elapsed = time.time() - loop_start
            sleep_time = max(0.0, self._update_interval - elapsed)
            self._stop_event.wait(sleep_time)

        logger.info("Update loop exited")

    def _tick(self):
        """
        Execute one update cycle:
        1. Step simulation (or check IPC in external mode)
        2. Read room states
        3. Process through ML pipeline
        4. Write control actions back to IPC
        5. Log to CSV
        """
        self._tick_count += 1

        # 1. Step the simulation forward (handles mode internally)
        self._bridge.step(dt=self._update_interval)

        # 2. Check connection status and update state manager
        connected = self._bridge.is_connected()
        bridge_mode = self._bridge.mode

        if connected and not self._was_connected:
            # Just connected/reconnected
            logger.info(
                f"✓ Simulation connected (mode={bridge_mode}, tick={self._tick_count})"
            )
            self._disconnect_logged = False

        if not connected and self._was_connected:
            # Just disconnected
            logger.warning(
                f"✗ Simulation disconnected (mode={bridge_mode}, tick={self._tick_count})"
            )

        self._was_connected = connected

        # Update state manager with simulation connection status
        if connected:
            # 3. Read all room states from simulation
            raw_rooms = self._bridge.get_all_room_states()

            if not raw_rooms:
                # Connected but no data (shouldn't happen)
                self._state_manager.set_simulation_status(
                    active=True, connected=False, sim_time=None
                )
                return

            # Get sim time from the bridge (Panda3D clock in external mode)
            sim_time = self._bridge.get_simulation_time()

            # Update simulation status before processing rooms
            self._state_manager.set_simulation_status(
                active=True, connected=True, sim_time=sim_time,
                speed_factor=RECONNECT_INTERVAL,
            )

            # 4. Process through ML → control → energy pipeline
            self._state_manager.process_room_states(raw_rooms, sim_time=sim_time, dt=self._update_interval)

            # 5. Write control actions back to IPC for Panda3D (external mode)
            self._write_control_actions_to_ipc()

            # 6. Log to CSV if enabled
            if self._csv_writer:
                self._log_to_csv()

            # Periodic status log (every 30 ticks)
            if self._tick_count % 30 == 0:
                summary = self._state_manager.get_system_summary()
                logger.info(
                    f"Tick #{self._tick_count} | "
                    f"Mode: {bridge_mode} | "
                    f"Rooms: {summary['total_rooms']} | "
                    f"Occupied: {summary['occupied_rooms']} | "
                    f"Power: {summary['total_power_watts']:.0f}W | "
                    f"SimTime: {sim_time}"
                )
        else:
            # Not connected: update state manager to reflect waiting state
            self._state_manager.set_simulation_status(
                active=False, connected=False, sim_time=None
            )

            # Log waiting periodically (every 15 ticks = ~30 seconds)
            if not self._disconnect_logged or self._tick_count % 15 == 0:
                logger.info(
                    f"Tick #{self._tick_count} | Waiting for simulation "
                    f"(mode={bridge_mode}, checking every {RECONNECT_INTERVAL}s)"
                )
                self._disconnect_logged = True

    def _write_control_actions_to_ipc(self):
        """
        After ML inference and control decisions, write the per-room
        control actions to the IPC file for Panda3D to read.

        This is the Backend → Simulation direction of the two-way IPC.
        """
        if self._bridge.mode != "external":
            return  # Only write IPC in external mode

        try:
            current_state = self._state_manager.get_current_state()
            rooms = current_state.get("rooms", [])
            if not rooms:
                return

            room_actions: Dict[str, Dict[str, Any]] = {}
            for room in rooms:
                room_id = room.get("room_id")
                control = room.get("control", {})
                if room_id and control:
                    room_actions[room_id] = {
                        "control_mode": control.get("control_mode", "EMPTY"),
                        "light_action": control.get("light_action", "OFF"),
                        "hvac_action": control.get("hvac_action", "ECO"),
                        "energy_mode": control.get("energy_mode", "MAXIMUM_SAVINGS"),
                    }

            if room_actions:
                self._bridge.write_control_actions(room_actions)

        except Exception as e:
            logger.warning(f"Failed to write control actions to IPC: {e}")

    def _log_to_csv(self):
        """Write current state snapshot to CSV."""
        if self._csv_writer is None:
            return

        try:
            state = self._state_manager.get_current_state()
            for room in state.get("rooms", []):
                sensors = room.get("sensors", {})
                ai = room.get("ai", {})
                control = room.get("control", {})
                energy = room.get("energy", {})
                gt = room.get("ground_truth", {})

                self._csv_writer.writerow([
                    room.get("timestamp", ""),
                    room.get("room_id", ""),
                    room.get("room_type", ""),
                    sensors.get("Temperature", ""),
                    sensors.get("Humidity", ""),
                    sensors.get("Light", ""),
                    sensors.get("CO2", ""),
                    sensors.get("HumidityRatio", ""),
                    gt.get("true_occupancy", ""),
                    ai.get("predicted_occupancy", ""),
                    ai.get("occupancy_probability", ""),
                    control.get("control_mode", ""),
                    control.get("light_action", ""),
                    control.get("hvac_action", ""),
                    energy.get("estimated_power_watts", ""),
                    energy.get("cumulative_energy_wh", ""),
                ])

            # Flush periodically
            if self._tick_count % 10 == 0 and self._csv_file:
                self._csv_file.flush()

        except Exception as e:
            logger.warning(f"CSV logging error: {e}")
