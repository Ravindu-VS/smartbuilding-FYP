"""
System Logger — Centralized Event Logging

Provides structured, categorized event logging for the Smart Building system.
Maintains an in-memory ring buffer of recent events accessible via API
for the dashboard's live event feed.

Writes to:  output/logs/system.log  (rotating file handler)
Exposes:    get_recent_events()  for dashboard consumption

Categories:
    SIMULATION  — start/stop/connect/disconnect
    MODEL       — ML model load/predictions
    CONTROL     — control decisions per room
    ENERGY      — energy changes and savings
    CONNECTION  — IPC connection events
    SYSTEM      — startup, shutdown, errors
"""

import os
import sys
import logging
import threading
from datetime import datetime
from typing import List, Dict, Any, Optional
from collections import deque
from logging.handlers import RotatingFileHandler

# Ensure project root is on path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from integration.config import SYSTEM_LOG_FILE, EVENT_LOG_MAX_SIZE

_logger = logging.getLogger(__name__)


class SystemLogger:
    """
    Centralized event logger for the smart building system.

    Thread-safe. Singleton pattern — use get_instance().

    Usage:
        logger = SystemLogger.get_instance()
        logger.log_control("office_1", "OCCUPIED", "Lights ON, HVAC NORMAL")
        events = logger.get_recent_events(limit=50)
    """

    _instance: Optional["SystemLogger"] = None
    _lock = threading.Lock()

    def __init__(self):
        """Initialize the system logger."""
        self._events: deque = deque(maxlen=EVENT_LOG_MAX_SIZE)
        self._event_lock = threading.Lock()
        self._event_counter = 0

        # Set up file logging
        self._setup_file_handler()

        _logger.info("✓ SystemLogger initialized")

    @classmethod
    def get_instance(cls) -> "SystemLogger":
        """Get or create the singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _setup_file_handler(self):
        """Configure rotating file handler for system.log."""
        log_path = os.path.join(PROJECT_ROOT, SYSTEM_LOG_FILE)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        # Create a dedicated logger for file output
        self._file_logger = logging.getLogger("smart_building.events")
        self._file_logger.setLevel(logging.DEBUG)

        # Avoid duplicate handlers on re-init
        if not self._file_logger.handlers:
            handler = RotatingFileHandler(
                log_path,
                maxBytes=5 * 1024 * 1024,  # 5 MB
                backupCount=3,
                encoding="utf-8",
            )
            handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                )
            )
            self._file_logger.addHandler(handler)

    # =========================================================================
    # EVENT LOGGING METHODS
    # =========================================================================

    def log_simulation(self, message: str, level: str = "INFO", sim_time: Optional[str] = None):
        """Log a simulation event (start, stop, connect, disconnect)."""
        self._add_event("SIMULATION", message, level, sim_time)

    def log_model(self, message: str, level: str = "INFO", sim_time: Optional[str] = None):
        """Log an ML model event (load, prediction summary)."""
        self._add_event("MODEL", message, level, sim_time)

    def log_control(self, room_id: str, mode: str, details: str, sim_time: Optional[str] = None):
        """Log a control decision for a room."""
        message = f"{room_id} → {mode} → {details}"
        self._add_event("CONTROL", message, "INFO", sim_time)

    def log_energy(self, message: str, level: str = "INFO", sim_time: Optional[str] = None):
        """Log an energy event (savings milestone, reset, etc.)."""
        self._add_event("ENERGY", message, level, sim_time)

    def log_connection(self, message: str, level: str = "INFO", sim_time: Optional[str] = None):
        """Log a connection event (IPC connect/disconnect/stale)."""
        self._add_event("CONNECTION", message, level, sim_time)

    def log_system(self, message: str, level: str = "INFO", sim_time: Optional[str] = None):
        """Log a system-wide event (startup, shutdown, error)."""
        self._add_event("SYSTEM", message, level, sim_time)

    # =========================================================================
    # EVENT RETRIEVAL (for Dashboard)
    # =========================================================================

    def get_recent_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get recent events for the dashboard event log panel.

        Args:
            limit: Maximum number of events to return (newest first)

        Returns:
            List of event dicts with timestamp, category, message, level
        """
        with self._event_lock:
            events = list(self._events)

        # Return newest first, up to limit
        return events[-limit:][::-1]

    def get_event_count(self) -> int:
        """Get total number of events logged."""
        return self._event_counter

    # =========================================================================
    # INTERNAL
    # =========================================================================

    def _add_event(self, event_type: str, message: str, level: str = "INFO", sim_time: Optional[str] = None):
        """Add an event to the ring buffer and write to file."""
        now = datetime.now()
        self._event_counter += 1
        
        display_time = "--:--:--"
        if sim_time and str(sim_time).lower() != "none" and str(sim_time).lower() != "null":
            if "T" in str(sim_time):
                display_time = str(sim_time).split("T")[1][:8]
            else:
                display_time = str(sim_time)

        event = {
            "id": self._event_counter,
            "sim_time": display_time,
            "real_time": now.isoformat(),
            "event_type": event_type,
            "message": message,
            "level": level,
        }

        # Add to ring buffer
        with self._event_lock:
            self._events.append(event)

        # Write to file
        time_prefix = f"[{display_time}] " if display_time != "--:--:--" else ""
        log_line = f"{time_prefix}[{event_type}] {message}"
        if level == "ERROR":
            self._file_logger.error(log_line)
        elif level == "WARNING":
            self._file_logger.warning(log_line)
        elif level == "DEBUG":
            self._file_logger.debug(log_line)
        else:
            self._file_logger.info(log_line)
