"""
Simulation IPC — Two-Way Inter-Process Communication

Provides shared-file communication between the Panda3D 3D simulation
and the backend integration layer.

Direction 1 (Sim → Backend):
    Panda3D writes raw simulation state → output/.sim_state.json
    Backend reads simulation state for ML inference + control

Direction 2 (Backend → Sim):
    Backend writes control actions → output/.control_actions.json
    Panda3D reads control actions and applies to simulation engine

Design:
- Atomic file writes (write to .tmp, then os.replace) for crash safety
- frame_id / sim_tick / written_at timestamps in every file
- Stale timeout detection on both directions
- Thread-safe reads/writes
"""

import os
import json
import time
import logging
import threading
from typing import Dict, Any, Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)

# Default paths (overridden by config)
_DEFAULT_STATE_PATH = os.path.join("output", ".sim_state.json")
_DEFAULT_CONTROL_PATH = os.path.join("output", ".control_actions.json")
_DEFAULT_STALE_TIMEOUT = 5.0  # seconds


# =============================================================================
# ATOMIC FILE UTILITIES
# =============================================================================

def _atomic_write_json(filepath: str, data: dict) -> bool:
    """
    Atomically write JSON data to a file (write to .tmp then rename).

    Args:
        filepath: Target file path
        data: Dictionary to serialize as JSON

    Returns:
        True if successful, False otherwise
    """
    tmp_path = filepath + ".tmp"
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))  # Compact for speed
        os.replace(tmp_path, filepath)  # Atomic on same filesystem
        return True
    except Exception as e:
        logger.warning(f"Atomic write failed for {filepath}: {e}")
        # Clean up tmp file if it exists
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        return False


def _read_json_safe(filepath: str) -> Optional[dict]:
    """
    Safely read a JSON file, handling partial writes and corruption.

    Args:
        filepath: Path to JSON file

    Returns:
        Parsed dict or None if read failed
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, IOError) as e:
        logger.debug(f"JSON read error for {filepath}: {e}")
        return None


# =============================================================================
# DIRECTION 1: Simulation → Backend (Sim State)
# =============================================================================

class SimulationStateWriter:
    """
    Used by Panda3D to write raw simulation state to the shared file.

    The Panda3D app calls write_state() every frame (or at a configured interval)
    with the full simulation engine state. This becomes the single source of truth
    for the backend.

    Usage (in Panda3D app.py):
        writer = SimulationStateWriter()
        # In _update_frame:
        writer.write_state(self.simulation_engine.get_state())
    """

    def __init__(self, filepath: str = None, project_root: str = None):
        """
        Args:
            filepath: Path to the state file (default from config)
            project_root: Project root directory for relative paths
        """
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if filepath is None:
            filepath = os.path.join(project_root, _DEFAULT_STATE_PATH)
        self._filepath = filepath
        self._frame_id = 0
        self._lock = threading.Lock()
        logger.info(f"SimulationStateWriter: {self._filepath}")

    def write_state(self, engine_state: dict) -> bool:
        """
        Write the current simulation engine state to the shared file.

        Wraps the raw engine state with IPC metadata (frame_id, written_at).

        Args:
            engine_state: The dict from SimulationEngine.get_state()

        Returns:
            True if write succeeded
        """
        with self._lock:
            self._frame_id += 1
            ipc_payload = {
                "ipc_version": 1,
                "frame_id": self._frame_id,
                "written_at": time.time(),
                "written_at_iso": datetime.now().isoformat(),
                "engine_state": engine_state,
            }
            return _atomic_write_json(self._filepath, ipc_payload)

    @property
    def filepath(self) -> str:
        return self._filepath

    @property
    def frame_id(self) -> int:
        return self._frame_id


class SimulationStateReader:
    """
    Used by the backend's SimulationBridge to read simulation state.

    Detects stale data (file not updated within timeout), handles
    file-not-found (simulation not started yet), and tracks frame_id
    to avoid re-processing the same state.

    Usage (in SimulationBridge):
        reader = SimulationStateReader()
        data = reader.read_state()
        if data and not reader.is_stale():
            process(data['engine_state'])
    """

    def __init__(self, filepath: str = None, project_root: str = None,
                 stale_timeout: float = _DEFAULT_STALE_TIMEOUT):
        """
        Args:
            filepath: Path to the state file
            project_root: Project root directory
            stale_timeout: Seconds before data is considered stale
        """
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if filepath is None:
            filepath = os.path.join(project_root, _DEFAULT_STATE_PATH)
        self._filepath = filepath
        self._stale_timeout = stale_timeout
        self._last_frame_id = 0
        self._last_data: Optional[dict] = None
        self._last_read_time: float = 0.0

    def read_state(self) -> Optional[dict]:
        """
        Read the latest simulation state from the shared file.

        Returns:
            IPC payload dict with frame_id, written_at, engine_state.
            None if file doesn't exist or is unreadable.
        """
        data = _read_json_safe(self._filepath)
        if data is not None:
            self._last_data = data
            self._last_read_time = time.time()
        return data

    def has_new_frame(self) -> bool:
        """Check if there's a new frame since last read."""
        data = self.read_state()
        if data is None:
            return False
        frame_id = data.get("frame_id", 0)
        if frame_id > self._last_frame_id:
            self._last_frame_id = frame_id
            return True
        return False

    def is_stale(self) -> bool:
        """
        Check if the state data is stale (not updated recently).

        Returns:
            True if data is stale or unavailable
        """
        if self._last_data is None:
            return True
        written_at = self._last_data.get("written_at", 0)
        age = time.time() - written_at
        return age > self._stale_timeout

    def is_available(self) -> bool:
        """Check if the shared state file exists."""
        return os.path.exists(self._filepath)

    def get_age_seconds(self) -> float:
        """Get age of the last data in seconds."""
        if self._last_data is None:
            return float("inf")
        written_at = self._last_data.get("written_at", 0)
        return time.time() - written_at

    @property
    def filepath(self) -> str:
        return self._filepath

    @property
    def last_frame_id(self) -> int:
        return self._last_frame_id


# =============================================================================
# DIRECTION 2: Backend → Simulation (Control Actions)
# =============================================================================

class ControlActionWriter:
    """
    Used by the backend to write ML controller decisions back to Panda3D.

    After the backend runs ML inference and control logic, it writes the
    per-room control actions to a shared file. The Panda3D app reads these
    and applies them to its simulation engine.

    Usage (in LiveUpdateService or StateManager):
        writer = ControlActionWriter()
        writer.write_actions({
            "office_1": {"light_action": "ON", "hvac_action": "NORMAL", ...},
            "kitchen_1": {"light_action": "DIM", "hvac_action": "LOW", ...},
        })
    """

    def __init__(self, filepath: str = None, project_root: str = None):
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if filepath is None:
            filepath = os.path.join(project_root, _DEFAULT_CONTROL_PATH)
        self._filepath = filepath
        self._tick_id = 0
        self._lock = threading.Lock()
        logger.info(f"ControlActionWriter: {self._filepath}")

    def write_actions(self, room_actions: Dict[str, Dict[str, Any]]) -> bool:
        """
        Write control actions for all rooms to the shared file.

        Args:
            room_actions: Dict mapping room_id to control action dict.
                Each control action should contain:
                - control_mode: "EMPTY" | "STANDBY" | "OCCUPIED"
                - light_action: "OFF" | "DIM" | "ON"
                - hvac_action: "ECO" | "OFF" | "LOW" | "NORMAL"
                - energy_mode: str

        Returns:
            True if write succeeded
        """
        with self._lock:
            self._tick_id += 1
            ipc_payload = {
                "ipc_version": 1,
                "tick_id": self._tick_id,
                "written_at": time.time(),
                "written_at_iso": datetime.now().isoformat(),
                "room_actions": room_actions,
            }
            return _atomic_write_json(self._filepath, ipc_payload)

    @property
    def filepath(self) -> str:
        return self._filepath


class ControlActionReader:
    """
    Used by Panda3D to read ML controller decisions from the backend.

    The 3D app reads this file periodically and applies the control actions
    to its simulation engine (light_on, hvac_mode, hvac_speed).

    Usage (in Panda3D app.py):
        reader = ControlActionReader()
        actions = reader.read_actions()
        if actions:
            for room_id, action in actions.items():
                apply_to_engine(room_id, action)
    """

    def __init__(self, filepath: str = None, project_root: str = None,
                 stale_timeout: float = _DEFAULT_STALE_TIMEOUT):
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if filepath is None:
            filepath = os.path.join(project_root, _DEFAULT_CONTROL_PATH)
        self._filepath = filepath
        self._stale_timeout = stale_timeout
        self._last_tick_id = 0
        self._last_data: Optional[dict] = None

    def read_actions(self) -> Optional[Dict[str, Dict[str, Any]]]:
        """
        Read the latest control actions from the shared file.

        Returns:
            Dict mapping room_id to control action dict, or None if unavailable.
        """
        data = _read_json_safe(self._filepath)
        if data is None:
            return None
        self._last_data = data
        return data.get("room_actions")

    def has_new_actions(self) -> bool:
        """Check if there are new actions since last read."""
        data = _read_json_safe(self._filepath)
        if data is None:
            return False
        tick_id = data.get("tick_id", 0)
        if tick_id > self._last_tick_id:
            self._last_tick_id = tick_id
            self._last_data = data
            return True
        return False

    def is_stale(self) -> bool:
        """Check if actions data is stale."""
        if self._last_data is None:
            return True
        written_at = self._last_data.get("written_at", 0)
        return (time.time() - written_at) > self._stale_timeout

    def is_available(self) -> bool:
        """Check if the control file exists."""
        return os.path.exists(self._filepath)

    @property
    def filepath(self) -> str:
        return self._filepath


# =============================================================================
# CLEANUP UTILITY
# =============================================================================

def cleanup_ipc_files(project_root: str = None):
    """
    Remove IPC files on shutdown.

    Args:
        project_root: Project root directory
    """
    if project_root is None:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    for filename in [_DEFAULT_STATE_PATH, _DEFAULT_CONTROL_PATH]:
        filepath = os.path.join(project_root, filename)
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.info(f"Cleaned up IPC file: {filepath}")
        except OSError as e:
            logger.warning(f"Failed to clean up {filepath}: {e}")

    # Also clean .tmp files
    for filename in [_DEFAULT_STATE_PATH + ".tmp", _DEFAULT_CONTROL_PATH + ".tmp"]:
        filepath = os.path.join(project_root, filename)
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except OSError:
            pass
